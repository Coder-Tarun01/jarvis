import { useCallback, useEffect, useRef, useState } from "react";

const SpeechRecognition =
  typeof window !== "undefined" ? window.SpeechRecognition || window.webkitSpeechRecognition : null;

const RESTART_DELAY_MS = 600;

/* "hey jarvis, what's the weather" -> phrase plus the command that followed it. */
const WAKE_PATTERNS = [
  /\b(?:hey|hi|hello|ok|okay|yo)\s+jarvis\b/i,
  /\bjarvis\b/i,
];

/** Split a heard phrase into the wake word and whatever came after it. */
export function splitWakePhrase(text) {
  const value = (text || "").trim();
  for (const pattern of WAKE_PATTERNS) {
    const match = pattern.exec(value);
    if (!match) continue;
    const rest = value
      .slice(match.index + match[0].length)
      .replace(/^[\s,.!?;:—–-]+/, "")
      .trim();
    return { hit: true, rest };
  }
  return { hit: false, rest: "" };
}

/**
 * Always-on "Hey Jarvis" detection.
 *
 * The browser's own recogniser is cheap, but it owns the microphone: only one
 * SpeechRecognition session may run per page. Detection therefore *releases* the
 * slot (`stop()`) and the caller opens the command capture; `resume()` re-arms it
 * once that capture is finished. Without that hand-off the always-on session keeps
 * the device and the command recogniser gets nothing — the wake word "fires" but
 * the mic appears dead.
 *
 * `paused` (e.g. while the command capture runs) tears the session down and brings
 * it back when it flips false, so the two never overlap.
 */
export function useWakeWord({ enabled = false, onWake, paused = false }) {
  const [active, setActive] = useState(false);
  const recognitionRef = useRef(null);
  const restartRef = useRef(0);
  const startRef = useRef(null);
  const suppressedRef = useRef(false);
  const pausedRef = useRef(paused);
  const enabledRef = useRef(enabled);
  const wakeRef = useRef(onWake);

  pausedRef.current = paused;
  enabledRef.current = enabled;
  wakeRef.current = onWake;

  const supported = Boolean(SpeechRecognition);

  /** Stop listening and hand the microphone back to whoever asked for it. */
  const stop = useCallback(() => {
    suppressedRef.current = true;
    window.clearTimeout(restartRef.current);
    restartRef.current = 0;
    const current = recognitionRef.current;
    recognitionRef.current = null;
    try {
      current?.abort();
    } catch {
      /* already gone */
    }
    setActive(false);
  }, []);

  /** Re-arm after the command capture; safe to call repeatedly. */
  const resume = useCallback(() => {
    suppressedRef.current = false;
    if (!enabledRef.current || pausedRef.current) return;
    if (recognitionRef.current) return;
    startRef.current?.();
  }, []);

  useEffect(() => {
    if (!enabled || !supported) {
      setActive(false);
      return undefined;
    }

    let stopped = false;
    let pendingTimer = 0;
    let fired = false;

    const fire = (rest) => {
      if (fired || stopped || suppressedRef.current) return;
      fired = true;
      window.clearTimeout(pendingTimer);
      pendingTimer = 0;
      // Hand the microphone over *before* the caller starts capturing.
      stop();
      wakeRef.current?.(rest);
    };

    const listen = () => {
      if (stopped || suppressedRef.current || pausedRef.current || recognitionRef.current) return;

      // fresh session: allow exactly one trigger
      fired = false;
      window.clearTimeout(pendingTimer);
      pendingTimer = 0;

      const recognition = new SpeechRecognition();
      recognition.lang = "en-US";
      recognition.continuous = true;
      recognition.interimResults = true;

      recognition.onstart = () => {
        if (!stopped) setActive(true);
      };

      recognition.onerror = () => {
        if (recognitionRef.current === recognition) recognitionRef.current = null;
        if (!stopped) setActive(false);
      };

      recognition.onend = () => {
        if (recognitionRef.current === recognition) recognitionRef.current = null;
        window.clearTimeout(pendingTimer);
        pendingTimer = 0;
        if (stopped || suppressedRef.current) {
          if (!stopped) setActive(false);
          return;
        }
        setActive(false);
        window.clearTimeout(restartRef.current);
        restartRef.current = window.setTimeout(() => {
          if (!stopped && !suppressedRef.current && !pausedRef.current) listen();
        }, RESTART_DELAY_MS);
      };

      recognition.onresult = (event) => {
        if (fired || pausedRef.current || suppressedRef.current) return;
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const result = event.results[i];
          const heard = result[0]?.transcript || "";
          const { hit, rest } = splitWakePhrase(heard);
          if (!hit) continue;

          // A final transcript is authoritative: "hey jarvis, what's the weather"
          // arrives complete, so nothing gets truncated.
          if (result.isFinal) {
            fire(rest);
            return;
          }

          // Interim: wait for the final so the command is not cut in half, but
          // do not wait forever — "hey jarvis" alone usually ends a phrase.
          window.clearTimeout(pendingTimer);
          pendingTimer = window.setTimeout(() => fire(rest), rest ? 700 : 900);
        }
      };

      recognitionRef.current = recognition;
      try {
        recognition.start();
      } catch {
        recognitionRef.current = null;
      }
    };

    startRef.current = listen;
    suppressedRef.current = false;
    listen();

    return () => {
      stopped = true;
      startRef.current = null;
      window.clearTimeout(pendingTimer);
      pendingTimer = 0;
      window.clearTimeout(restartRef.current);
      restartRef.current = 0;
      const current = recognitionRef.current;
      recognitionRef.current = null;
      try {
        current?.abort();
      } catch {
        /* ignore */
      }
      setActive(false);
    };
  }, [enabled, supported, paused, stop]);

  return { supported, active, stop, resume };
}
