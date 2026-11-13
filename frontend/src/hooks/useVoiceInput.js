import { useCallback, useEffect, useRef, useState } from "react";

import { apiBase } from "../lib/api.js";

const SpeechRecognition =
  typeof window !== "undefined" ? window.SpeechRecognition || window.webkitSpeechRecognition : null;

/**
 * Microphone input.
 * provider "browser" -> Web Speech API (Chrome/Edge; streams interim results)
 * provider "whisper" -> MediaRecorder + POST /api/speech/transcribe
 *
 * `start({ continuous, silenceMs })` keeps one session open and submits the whole
 * utterance once the speaker pauses. The wake word uses that mode so
 * "Hey Jarvis …" and the request that follows can be two separate breaths.
 */
export function useVoiceInput({ provider = "browser", token, onTranscript, onError }) {
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef(null);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const bufferRef = useRef("");
  const silenceRef = useRef(0);
  const emittedRef = useRef(false);
  const callbacks = useRef({});

  callbacks.current = { onTranscript, onError };

  const browserSupported = Boolean(SpeechRecognition);
  const recorderSupported =
    typeof navigator !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    typeof MediaRecorder !== "undefined";
  const supported = provider === "whisper" ? recorderSupported : browserSupported;

  const clearSilence = useCallback(() => {
    window.clearTimeout(silenceRef.current);
    silenceRef.current = 0;
  }, []);

  /** Hand the buffered utterance over exactly once. */
  const flush = useCallback(() => {
    clearSilence();
    if (emittedRef.current) return;
    const text = bufferRef.current.trim();
    bufferRef.current = "";
    if (!text) return;
    emittedRef.current = true;
    callbacks.current.onTranscript?.(text);
  }, [clearSilence]);

  const startBrowser = useCallback(
    (options = {}) => {
      if (!SpeechRecognition) {
        callbacks.current.onError?.(
          "This browser has no Web Speech API. Use Chrome/Edge, or set STT_PROVIDER=whisper.",
        );
        return;
      }

      const continuous = Boolean(options.continuous);
      const silenceMs = Math.max(700, Number(options.silenceMs) || 1800);
      const noSpeechMs = Math.max(2000, Number(options.noSpeechMs) || 8000);

      /* Chrome allows a single session per page — drop whatever is open. */
      try {
        recognitionRef.current?.abort();
      } catch {
        /* ignore */
      }
      recognitionRef.current = null;
      clearSilence();
      bufferRef.current = "";
      emittedRef.current = false;

      try {
        const recognition = new SpeechRecognition();
        recognition.lang = "en-US";
        recognition.continuous = continuous;
        recognition.interimResults = true;
        recognition.maxAlternatives = 1;

        /* Close the session if the speaker stops (or never starts) talking. */
        const armStop = (ms) => {
          clearSilence();
          silenceRef.current = window.setTimeout(() => {
            try {
              recognition.stop();
            } catch {
              /* ignore */
            }
          }, ms);
        };

        recognition.onstart = () => {
          setListening(true);
          if (continuous) armStop(noSpeechMs);
        };

        recognition.onresult = (event) => {
          let finalText = "";
          for (let i = event.resultIndex; i < event.results.length; i += 1) {
            const result = event.results[i];
            if (result.isFinal) finalText += result[0].transcript;
          }
          finalText = finalText.trim();
          if (!finalText) return;

          if (!continuous) {
            callbacks.current.onTranscript?.(finalText);
            return;
          }

          // Wake-triggered capture: collect the sentence, submit on a pause.
          bufferRef.current = `${bufferRef.current} ${finalText}`.trim();
          armStop(silenceMs);
        };

        recognition.onerror = (event) => {
          setListening(false);
          if (event.error === "no-speech" || event.error === "aborted") return;
          callbacks.current.onError?.(
            event.error === "not-allowed"
              ? "Microphone permission denied."
              : `Speech recognition error: ${event.error}`,
          );
        };

        recognition.onend = () => {
          if (recognitionRef.current === recognition) recognitionRef.current = null;
          setListening(false);
          if (continuous) flush();
        };

        recognitionRef.current = recognition;
        recognition.start();
      } catch (error) {
        recognitionRef.current = null;
        setListening(false);
        callbacks.current.onError?.(String(error));
      }
    },
    [clearSilence, flush],
  );

  const startWhisper = useCallback(async () => {
    if (!recorderSupported) {
      callbacks.current.onError?.("This browser cannot record audio. Set STT_PROVIDER=browser.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };

      recorder.onstop = async () => {
        setListening(false);
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        if (blob.size < 1200) return;

        try {
          const form = new FormData();
          form.append("file", blob, "speech.webm");
          const response = await fetch(`${apiBase()}/api/speech/transcribe`, {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
            body: form,
          });
          if (!response.ok) throw new Error(await response.text());
          const data = await response.json();
          if (data.text) callbacks.current.onTranscript?.(data.text);
        } catch (error) {
          callbacks.current.onError?.(`Transcription failed: ${error.message}`);
        }
      };

      recorder.start();
      recorderRef.current = recorder;
      setListening(true);
    } catch (error) {
      setListening(false);
      callbacks.current.onError?.(`Microphone unavailable: ${error.message}`);
    }
  }, [recorderSupported, token]);

  const start = useCallback(
    (options = {}) => {
      if (provider === "whisper") {
        startWhisper();
      } else {
        startBrowser(options);
      }
    },
    [provider, startWhisper, startBrowser],
  );

  const stop = useCallback(() => {
    clearSilence();
    if (provider === "whisper") {
      recorderRef.current?.stop();
      recorderRef.current = null;
      setListening(false);
      return;
    }
    const current = recognitionRef.current;
    recognitionRef.current = null;
    try {
      current?.stop();
    } catch {
      /* ignore */
    }
    setListening(false);
    // `onend` flushes whatever was buffered; nothing to do if it already did.
  }, [provider, clearSilence]);

  useEffect(
    () => () => {
      window.clearTimeout(silenceRef.current);
      recognitionRef.current?.abort?.();
      recorderRef.current?.stop?.();
    },
    [],
  );

  return { supported, listening, start, stop, browserSupported };
}
