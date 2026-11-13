import { useCallback, useEffect, useRef, useState } from "react";

import { apiBase } from "../lib/api.js";

/**
 * Text to speech.
 * provider "browser"     -> SpeechSynthesis (free, offline, instant)
 * provider "elevenlabs"  -> POST /api/speech/speak (falls back to the browser)
 */
export function useSpeech({ provider = "browser", token }) {
  const [speaking, setSpeaking] = useState(false);
  const audioRef = useRef(null);
  const voicesRef = useRef([]);
  const supported = typeof window !== "undefined" && "speechSynthesis" in window;

  useEffect(() => {
    if (!supported) return undefined;
    const load = () => {
      voicesRef.current = window.speechSynthesis.getVoices();
    };
    load();
    window.speechSynthesis.addEventListener?.("voiceschanged", load);
    return () => window.speechSynthesis.removeEventListener?.("voiceschanged", load);
  }, [supported]);

  const cancel = useCallback(() => {
    if (supported) window.speechSynthesis.cancel();
    if (audioRef.current) {
      try {
        audioRef.current.pause();
        URL.revokeObjectURL(audioRef.current.src);
      } catch {
        /* ignore */
      }
      audioRef.current = null;
    }
    setSpeaking(false);
  }, [supported]);

  const speakWithBrowser = useCallback(
    (text) => {
      if (!supported || !text) return;
      const utterance = new window.SpeechSynthesisUtterance(text.slice(0, 1500));
      const voices = voicesRef.current.length ? voicesRef.current : window.speechSynthesis.getVoices();
      const preferred =
        voices.find((voice) => /en-GB/i.test(voice.lang) && /daniel|male|google uk english male/i.test(voice.name)) ||
        voices.find((voice) => /en-GB/i.test(voice.lang)) ||
        voices.find((voice) => voice.lang?.toLowerCase().startsWith("en"));
      if (preferred) utterance.voice = preferred;
      utterance.rate = 1.03;
      utterance.pitch = 0.9;
      utterance.onstart = () => setSpeaking(true);
      utterance.onend = () => setSpeaking(false);
      utterance.onerror = () => setSpeaking(false);
      window.speechSynthesis.speak(utterance);
    },
    [supported],
  );

  const speak = useCallback(
    async (rawText) => {
      const text = (rawText || "")
        .replace(/```[\s\S]*?```/g, " (code block) ")
        .replace(/[*_#`>]/g, "")
        .replace(/\s+/g, " ")
        .trim();
      if (!text) return;

      cancel();

      if (provider !== "elevenlabs" || !token) {
        speakWithBrowser(text);
        return;
      }

      try {
        const response = await fetch(`${apiBase()}/api/speech/speak`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ text: text.slice(0, 2500) }),
        });
        if (!response.ok) throw new Error(await response.text());

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        audioRef.current = audio;
        audio.onplay = () => setSpeaking(true);
        audio.onended = () => {
          setSpeaking(false);
          URL.revokeObjectURL(url);
        };
        audio.onerror = () => setSpeaking(false);
        await audio.play();
      } catch (error) {
        console.warn("ElevenLabs TTS failed — using the browser voice instead", error);
        speakWithBrowser(text);
      }
    },
    [provider, token, cancel, speakWithBrowser],
  );

  return { speak, cancel, speaking, supported };
}
