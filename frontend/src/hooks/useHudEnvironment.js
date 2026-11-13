import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Decorative microphone level for the orb and the composer waveform.
 *
 * Returns a ref (not state) so 60fps updates never trigger a React render: the
 * consumers write it into a CSS variable inside their own rAF loop.
 * Failures are swallowed — the visuals simply fall back to CSS animation.
 */
export function useMicLevel(active, { reduced = false } = {}) {
  const levelRef = useRef(0);

  useEffect(() => {
    if (!active || reduced) {
      levelRef.current = 0;
      return undefined;
    }

    let cancelled = false;
    let stream = null;
    let context = null;
    let frame = 0;

    const teardown = () => {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      try {
        stream?.getTracks().forEach((track) => track.stop());
      } catch {
        /* ignore */
      }
      stream = null;
      try {
        context?.close();
      } catch {
        /* ignore */
      }
      context = null;
      levelRef.current = 0;
    };

    const start = async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) return;
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (cancelled) {
          teardown();
          return;
        }
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) {
          teardown();
          return;
        }
        context = new AudioContextClass();
        if (context.state === "suspended") {
          try {
            await context.resume();
          } catch {
            /* ignore */
          }
        }
        const source = context.createMediaStreamSource(stream);
        const analyser = context.createAnalyser();
        analyser.fftSize = 1024;
        analyser.smoothingTimeConstant = 0.72;
        source.connect(analyser);

        const buffer = new Uint8Array(analyser.frequencyBinCount);
        const loop = () => {
          analyser.getByteFrequencyData(buffer);
          // Speech band only (skip DC + hiss), RMS for a perceptual level.
          let sum = 0;
          const end = Math.min(buffer.length, 120);
          for (let i = 3; i < end; i += 1) {
            const value = buffer[i] / 255;
            sum += value * value;
          }
          const rms = Math.sqrt(sum / Math.max(1, end - 3));
          const target = Math.min(1, rms * 3.4);
          const current = levelRef.current;
          levelRef.current = current * 0.68 + target * 0.32;
          frame = requestAnimationFrame(loop);
        };
        loop();
      } catch {
        teardown();
      }
    };

    start();

    return () => {
      cancelled = true;
      teardown();
    };
  }, [active, reduced]);

  return levelRef;
}

/** Live clock, ticking on the second. */
export function useClock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  return now;
}

/** Tracks the OS "reduce motion" preference at runtime. */
export function useReducedMotion() {
  const [reduced, setReduced] = useState(
    () =>
      typeof window !== "undefined" &&
      Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches),
  );

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => setReduced(query.matches);
    query.addEventListener?.("change", onChange);
    return () => query.removeEventListener?.("change", onChange);
  }, []);

  return reduced;
}

/** Toggles the mic from the keyboard (bound by the assistant shell). */
export function useHotkey(enabled, onTrigger) {
  const ref = useRef(onTrigger);
  ref.current = onTrigger;

  const handler = useCallback((event) => {
    if (!enabled) return;
    if (event.code !== "Space" || event.repeat) return;
    const target = event.target;
    const typing =
      target instanceof HTMLElement &&
      (target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable);
    if (typing) return;
    event.preventDefault();
    ref.current?.();
  }, [enabled]);

  useEffect(() => {
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handler]);
}
