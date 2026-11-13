import { useCallback, useEffect, useRef, useState } from "react";

import { api, wsUrl } from "../lib/api.js";

const uid = () => Math.random().toString(36).slice(2, 10);

const DEFAULT_CONFIG = {
  model: "",
  llm_configured: true,
  stt_provider: "browser",
  tts_provider: "browser",
  google_enabled: false,
  whatsapp_mode: "off",
};

/**
 * Owns the WebSocket, the message list and the orb state machine.
 * All wiring is event-driven: the server is the single source of truth.
 */
export function useJarvis({ token, onAssistantDone, onReminder, onNotice, onConversationCreated }) {
  const [messages, setMessages] = useState([]);
  const [state, setState] = useState("idle");
  const [connected, setConnected] = useState(false);
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  const [confirmation, setConfirmation] = useState(null);
  const [conversationId, setConversationId] = useState(null);

  const socketRef = useRef(null);
  const retryRef = useRef(null);
  const closedRef = useRef(false);
  const streamIdRef = useRef(null);
  const conversationIdRef = useRef(null);
  const connectRef = useRef(() => {});
  const callbacks = useRef({});

  callbacks.current = { onAssistantDone, onReminder, onNotice, onConversationCreated };

  const updateAssistant = useCallback((updater) => {
    const id = streamIdRef.current;
    if (!id) return;
    setMessages((prev) => prev.map((message) => (message.id === id ? updater(message) : message)));
  }, []);

  const handleEvent = useCallback(
    (event) => {
      const notify = callbacks.current.onNotice;
      switch (event.type) {
        case "hello":
          setConfig((prev) => ({ ...prev, ...event }));
          break;
        case "state":
          setState(event.state || "idle");
          break;
        case "token":
          updateAssistant((message) => ({ ...message, text: message.text + (event.text || "") }));
          break;
        case "tool_call":
          updateAssistant((message) => ({
            ...message,
            tools: [
              ...(message.tools || []),
              { id: event.id, name: event.name, input: event.input, status: "running" },
            ],
          }));
          break;
        case "tool_result":
          updateAssistant((message) => ({
            ...message,
            tools: (message.tools || []).map((tool) =>
              tool.id === event.id
                ? { ...tool, status: event.ok ? "ok" : "error", summary: event.summary }
                : tool,
            ),
          }));
          break;
        case "confirmation_request":
          setConfirmation({
            id: event.id,
            name: event.name,
            input: event.input,
            hint: event.hint,
            timeout: event.timeout,
          });
          break;
        case "confirmation_timeout":
          setConfirmation(null);
          notify?.({ kind: "warn", text: "No answer in time — the action was cancelled." });
          break;
        case "client_action":
          if (event.action === "open_url" && event.url) {
            window.open(event.url, "_blank", "noopener,noreferrer");
          }
          break;
        case "assistant_done": {
          const id = streamIdRef.current;
          if (id) {
            setMessages((prev) =>
              prev.map((message) =>
                message.id === id
                  ? { ...message, text: event.text || message.text, streaming: false }
                  : message,
              ),
            );
          }
          if (event.conversation_id) {
            conversationIdRef.current = event.conversation_id;
            setConversationId(event.conversation_id);
          }
          setState("idle");
          callbacks.current.onAssistantDone?.(event);
          break;
        }
        case "conversation_created":
          if (event.conversation) {
            conversationIdRef.current = event.conversation.id;
            setConversationId(event.conversation.id);
            callbacks.current.onConversationCreated?.(event.conversation);
          }
          break;
        case "memory_added":
          notify?.({
            kind: "memory",
            text: `Remembered: ${(event.facts || []).join(" · ")}`,
          });
          break;
        case "reminder_scheduled":
          notify?.({ kind: "info", text: `Scheduled: ${event.text} — ${event.due_human}` });
          break;
        case "reminder":
          callbacks.current.onReminder?.(event);
          break;
        case "warning":
          notify?.({ kind: "warn", text: event.message });
          break;
        case "error":
          notify?.({ kind: "error", text: event.message });
          setState("idle");
          updateAssistant((message) => ({ ...message, streaming: false }));
          break;
        case "stopped":
          setState("idle");
          updateAssistant((message) => ({ ...message, streaming: false }));
          break;
        default:
          break;
      }
    },
    [updateAssistant],
  );

  const connect = useCallback(() => {
    if (!token) return;
    const existing = socketRef.current;
    if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const socket = new WebSocket(wsUrl(token));
    socketRef.current = socket;

    socket.onopen = () => {
      setConnected(true);
      if (retryRef.current) {
        clearTimeout(retryRef.current);
        retryRef.current = null;
      }
    };

    socket.onclose = () => {
      setConnected(false);
      if (closedRef.current) return;
      retryRef.current = setTimeout(() => connectRef.current(), 2500);
    };

    socket.onerror = () => setConnected(false);

    socket.onmessage = (raw) => {
      try {
        handleEvent(JSON.parse(raw.data));
      } catch (error) {
        console.warn("JARVIS: unreadable event", error);
      }
    };
  }, [token, handleEvent]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    closedRef.current = false;
    connect();
    return () => {
      closedRef.current = true;
      if (retryRef.current) clearTimeout(retryRef.current);
      retryRef.current = null;
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [connect]);

  const send = useCallback((rawText) => {
    const text = (rawText || "").trim();
    if (!text) return false;

    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      callbacks.current.onNotice?.({ kind: "error", text: "Not connected to the JARVIS backend." });
      return false;
    }

    const assistantId = uid();
    streamIdRef.current = assistantId;
    setMessages((prev) => [
      ...prev,
      { id: uid(), role: "user", text, tools: [], streaming: false },
      { id: assistantId, role: "assistant", text: "", tools: [], streaming: true },
    ]);
    setState("thinking");
    socket.send(
      JSON.stringify({
        type: "user_message",
        text,
        conversation_id: conversationIdRef.current,
      }),
    );
    return true;
  }, []);

  const stop = useCallback(() => {
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "stop" }));
    }
    setState("idle");
    updateAssistant((message) => ({ ...message, streaming: false }));
  }, [updateAssistant]);

  const respondToConfirmation = useCallback(
    (approved) => {
      if (!confirmation) return;
      const socket = socketRef.current;
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(
          JSON.stringify({ type: "confirm", id: confirmation.id, approved: Boolean(approved) }),
        );
      }
      setConfirmation(null);
      if (approved) setState("thinking");
    },
    [confirmation],
  );

  const newConversation = useCallback(() => {
    conversationIdRef.current = null;
    streamIdRef.current = null;
    setConversationId(null);
    setMessages([]);
    setConfirmation(null);
    setState("idle");
  }, []);

  const openConversation = useCallback(async (id) => {
    const data = await api(`/api/conversations/${id}`);
    conversationIdRef.current = id;
    streamIdRef.current = null;
    setConversationId(id);
    setConfirmation(null);
    setState("idle");
    setMessages(
      (data.messages || [])
        .filter((message) => message.role === "user" || message.role === "assistant")
        .map((message) => ({
          id: `srv-${message.id}`,
          role: message.role,
          text: message.content,
          tools: [],
          streaming: false,
        })),
    );
  }, []);

  return {
    messages,
    state,
    setState,
    connected,
    config,
    confirmation,
    conversationId,
    send,
    stop,
    respondToConfirmation,
    newConversation,
    openConversation,
  };
}
