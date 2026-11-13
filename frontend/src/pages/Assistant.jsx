import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import Backdrop from "../components/Backdrop.jsx";
import ChatPanel from "../components/ChatPanel.jsx";
import ConfirmationModal from "../components/ConfirmationModal.jsx";
import Sidebar from "../components/Sidebar.jsx";
import StatusBar from "../components/StatusBar.jsx";
import Toasts from "../components/Toasts.jsx";
import {
  useHotkey,
  useMicLevel,
  useReducedMotion,
} from "../hooks/useHudEnvironment.js";
import { useJarvis } from "../hooks/useJarvis.js";
import { useSpeech } from "../hooks/useSpeech.js";
import { useVoiceInput } from "../hooks/useVoiceInput.js";
import { useWakeWord } from "../hooks/useWakeWord.js";
import { api } from "../lib/api.js";
import { readSnapshot } from "../lib/hudState.js";

export default function Assistant({ token, onLogout }) {
  const [conversations, setConversations] = useState([]);
  const [query, setQuery] = useState("");
  const [toasts, setToasts] = useState([]);
  const [muted, setMuted] = useState(false);
  const [wakeEnabled, setWakeEnabled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [ttsProvider, setTtsProvider] = useState("browser");
  const [sttProvider, setSttProvider] = useState("browser");

  const snapshot = useMemo(() => readSnapshot(), []);
  const reducedMotion = useReducedMotion();

  const mutedRef = useRef(muted);
  mutedRef.current = muted;

  /* The archive starts closed; while it is off-canvas it must not be tabbable. */
  const sidebarRef = useRef(null);
  useEffect(() => {
    const node = sidebarRef.current;
    if (!node) return;
    if (sidebarOpen) node.removeAttribute("inert");
    else node.setAttribute("inert", "");
  }, [sidebarOpen]);

  const pushToast = useCallback((toast) => {
    const id = Math.random().toString(36).slice(2, 9);
    setToasts((prev) => [...prev.slice(-3), { id, kind: toast.kind || "info", text: toast.text }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((item) => item.id !== id));
    }, 8000);
  }, []);

  const { speak, cancel: cancelSpeech, speaking } = useSpeech({ provider: ttsProvider, token });

  const refreshConversations = useCallback(async () => {
    try {
      const suffix = query.trim() ? `?q=${encodeURIComponent(query.trim())}` : "";
      const data = await api(`/api/conversations${suffix}`, { token });
      setConversations(Array.isArray(data) ? data : []);
    } catch (error) {
      console.warn("conversation list failed", error);
    }
  }, [query, token]);

  const handleAssistantDone = useCallback(
    (event) => {
      if (!mutedRef.current && event?.text) speak(event.text);
      refreshConversations();
    },
    [speak, refreshConversations],
  );

  const handleReminder = useCallback(
    (event) => {
      const text = event.kind === "timer" ? `Timer done: ${event.text}` : event.text;
      pushToast({ kind: "warn", text: `⏰ ${text}` });
      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        try {
          new Notification("JARVIS", { body: text });
        } catch {
          /* some browsers require a service worker */
        }
      }
      if (!mutedRef.current) speak(text);
    },
    [pushToast, speak],
  );

  const jarvis = useJarvis({
    token,
    onAssistantDone: handleAssistantDone,
    onReminder: handleReminder,
    onNotice: pushToast,
    onConversationCreated: () => refreshConversations(),
  });

  const { send, setState: setOrbState, stop } = jarvis;

  useEffect(() => {
    if (jarvis.config.tts_provider && jarvis.config.tts_provider !== ttsProvider) {
      setTtsProvider(jarvis.config.tts_provider);
    }
    if (jarvis.config.stt_provider && jarvis.config.stt_provider !== sttProvider) {
      setSttProvider(jarvis.config.stt_provider);
    }
  }, [jarvis.config, ttsProvider, sttProvider]);

  useEffect(() => {
    refreshConversations();
  }, [refreshConversations]);

  const handleTranscript = useCallback(
    (text) => {
      setOrbState("idle");
      if (text) send(text);
    },
    [send, setOrbState],
  );

  const voice = useVoiceInput({
    provider: sttProvider,
    token,
    onTranscript: handleTranscript,
    onError: (text) => pushToast({ kind: "error", text }),
  });

  const micLevelRef = useMicLevel(voice.listening, { reduced: reducedMotion });

  /* The wake-word session and the command capture can never run at the same
     time: Chrome allows one recogniser per page. So starting the mic stops the
     wake word first, and the wake word is re-armed once capture is over. */
  const wakeApiRef = useRef({ stop: () => {}, resume: () => {} });

  const startListening = useCallback(
    (options) => {
      cancelSpeech();
      wakeApiRef.current.stop();
      setOrbState("listening");
      // Give the wake session a beat to release the device before we open ours.
      window.setTimeout(() => voice.start(options), 160);
    },
    [cancelSpeech, setOrbState, voice],
  );

  const toggleMic = useCallback(() => {
    if (voice.listening) {
      voice.stop();
      setOrbState("idle");
    } else {
      startListening();
    }
  }, [voice, setOrbState, startListening]);

  const wake = useWakeWord({
    enabled: wakeEnabled,
    paused: voice.listening,
    onWake: (rest) => {
      const command = (rest || "").trim();
      if (command.length > 1) {
        /* "hey jarvis, what's the weather" — the request arrived with the wake
           word, so answer it instead of opening the mic again. */
        setOrbState("idle");
        pushToast({ kind: "info", text: command });
        send(command);
        window.setTimeout(() => wakeApiRef.current.resume(), 400);
        return;
      }
      pushToast({ kind: "info", text: "Wake word detected — listening." });
      // Continuous capture: the request can follow in a second breath and is
      // submitted once the speaker pauses.
      startListening({ continuous: true, silenceMs: 1800 });
    },
  });

  wakeApiRef.current = { stop: wake.stop, resume: wake.resume };

  /* Re-arm the wake word whenever a capture finishes (or never started). */
  useEffect(() => {
    if (voice.listening) return undefined;
    const id = window.setTimeout(() => wakeApiRef.current.resume(), 500);
    return () => window.clearTimeout(id);
  }, [voice.listening]);

  const toggleWake = useCallback(() => {
    if (!wake.supported) {
      pushToast({ kind: "warn", text: "The wake word needs Chrome or Edge (Web Speech API)." });
      return;
    }
    setWakeEnabled((prev) => !prev);
  }, [wake.supported, pushToast]);

  const toggleMute = useCallback(() => {
    setMuted((prev) => {
      if (!prev) cancelSpeech();
      return !prev;
    });
  }, [cancelSpeech]);

  const handleSend = useCallback(
    (text) => {
      cancelSpeech();
      send(text);
    },
    [cancelSpeech, send],
  );

  const handleStop = useCallback(() => {
    cancelSpeech();
    stop();
  }, [cancelSpeech, stop]);

  const handleNew = useCallback(() => {
    cancelSpeech();
    jarvis.newConversation();
    setMenuOpen(false);
  }, [cancelSpeech, jarvis]);

  const handleSelect = useCallback(
    async (id) => {
      cancelSpeech();
      setMenuOpen(false);
      try {
        await jarvis.openConversation(id);
      } catch (error) {
        pushToast({ kind: "error", text: error.message });
      }
    },
    [cancelSpeech, jarvis, pushToast],
  );

  const handleDelete = useCallback(
    async (id) => {
      try {
        await api(`/api/conversations/${id}`, { method: "DELETE", token });
        if (jarvis.conversationId === id) jarvis.newConversation();
        refreshConversations();
      } catch (error) {
        pushToast({ kind: "error", text: error.message });
      }
    },
    [token, jarvis, refreshConversations, pushToast],
  );

  const requestNotifications = useCallback(async () => {
    if (typeof Notification === "undefined") {
      pushToast({ kind: "warn", text: "This browser has no desktop notifications." });
      return;
    }
    const permission = await Notification.requestPermission();
    pushToast({
      kind: permission === "granted" ? "info" : "warn",
      text: `Desktop alerts: ${permission}`,
    });
  }, [pushToast]);

  const orbState = useMemo(() => {
    if (voice.listening) return "listening";
    if (jarvis.confirmation || jarvis.state === "thinking") return "thinking";
    if (speaking) return "speaking";
    return "idle";
  }, [voice.listening, jarvis.confirmation, jarvis.state, speaking]);

  const busy = jarvis.state === "thinking";

  /* Space toggles push-to-talk (ignored while typing or while authorising). */
  useHotkey(!busy && !jarvis.confirmation && voice.supported, toggleMic);

  const sidebarProps = {
    conversations,
    activeId: jarvis.conversationId,
    onSelect: handleSelect,
    onNew: handleNew,
    onDelete: handleDelete,
    query,
    onQueryChange: setQuery,
    onLogout,
    connected: jarvis.connected,
  };

  return (
    <div className="relative flex h-full flex-col overflow-hidden">
      <Backdrop />

      <div className="relative z-10 flex h-full min-h-0 flex-col">
        <StatusBar
          state={orbState}
          connected={jarvis.connected}
          model={jarvis.config.model || snapshot?.model}
          toolCount={snapshot?.toolCount}
          whatsappMode={jarvis.config.whatsapp_mode}
          llmConfigured={jarvis.config.llm_configured}
          micActive={voice.listening}
          micSupported={voice.supported}
          muted={muted}
          wakeEnabled={wakeEnabled}
          wakeArmed={wake.active}
          wakeSupported={wake.supported}
          onToggleWake={toggleWake}
          onToggleMute={toggleMute}
          onOpenMenu={() => setMenuOpen(true)}
          onToggleSidebar={() => setSidebarOpen((prev) => !prev)}
          onRequestAlerts={requestNotifications}
          sidebarOpen={sidebarOpen}
        />

        <div className="flex min-h-0 flex-1">
          <div
            ref={sidebarRef}
            className={`hidden shrink-0 overflow-hidden transition-[width] duration-300 ease-hud lg:block ${
              sidebarOpen ? "w-[290px]" : "w-0"
            }`}
          >
            <Sidebar {...sidebarProps} className="h-full" />
          </div>

          <main className="relative flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="sweep-border flex min-h-0 flex-1 flex-col">
              <ChatPanel
                messages={jarvis.messages}
                busy={busy}
                onSend={handleSend}
                onStop={handleStop}
                listening={voice.listening}
                onMicToggle={toggleMic}
                micSupported={voice.supported}
                micLevelRef={micLevelRef}
                orbState={orbState}
                orbOnClick={voice.supported ? toggleMic : undefined}
                model={jarvis.config.model || snapshot?.model}
                sttProvider={sttProvider}
                ttsProvider={ttsProvider}
                googleEnabled={Boolean(jarvis.config.google_enabled)}
                historyCount={conversations.length}
              />
            </div>
          </main>
        </div>
      </div>

      {menuOpen && (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => setMenuOpen(false)}
            className="absolute inset-0 bg-void/80 backdrop-blur-sm"
          />
          <div className="relative h-full animate-fade-up">
            <Sidebar {...sidebarProps} className="flex h-full" />
          </div>
        </div>
      )}

      <ConfirmationModal
        request={jarvis.confirmation}
        onApprove={() => jarvis.respondToConfirmation(true)}
        onDeny={() => jarvis.respondToConfirmation(false)}
      />

      <Toasts
        items={toasts}
        onDismiss={(id) => setToasts((prev) => prev.filter((item) => item.id !== id))}
      />
    </div>
  );
}
