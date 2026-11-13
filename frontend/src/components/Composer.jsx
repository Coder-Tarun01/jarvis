import { useEffect, useRef, useState } from "react";

function MicWave({ levelRef, active }) {
  const stripRef = useRef(null);

  useEffect(() => {
    const node = stripRef.current;
    if (!node || !active || !levelRef) return undefined;
    let frame = 0;
    const tick = () => {
      node.style.setProperty("--lvl", (levelRef.current || 0).toFixed(3));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [active, levelRef]);

  return (
    <div
      ref={stripRef}
      className="flex h-8 w-14 items-center justify-center gap-[3px] overflow-hidden"
      style={{ "--lvl": 0 }}
      aria-hidden="true"
    >
      {[1.05, 1.5, 0.85, 1.3, 0.95].map((factor, index) => (
        <span
          key={index}
          className="h-6 w-[3px] rounded-full bg-holo/80"
          style={{
            transform: `scaleY(calc(0.12 + var(--lvl) * ${factor}))`,
            transformOrigin: "center",
            transition: "transform 80ms linear",
            boxShadow: "0 0 8px rgba(34,211,238,0.5)",
          }}
        />
      ))}
    </div>
  );
}

export default function Composer({
  onSend,
  onStop,
  busy,
  listening,
  onMicToggle,
  micSupported,
  micLevelRef,
  placeholder = "Ask JARVIS anything…",
}) {
  const [value, setValue] = useState("");
  const textareaRef = useRef(null);

  useEffect(() => {
    const node = textareaRef.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 152)}px`;
  }, [value]);

  const submit = () => {
    const text = value.trim();
    if (!text || busy) return;
    onSend(text);
    setValue("");
  };

  return (
    <div className="relative shrink-0 px-3 pb-3 pt-1.5 sm:px-5 sm:pb-4">
      <div className="mx-auto w-full max-w-3xl">
        <div className="glass group flex items-end gap-2 rounded-2xl p-1.5 transition-shadow duration-300 focus-within:shadow-holoLg">
          <button
            type="button"
            onClick={onMicToggle}
            disabled={!micSupported || busy}
            aria-pressed={listening}
            aria-label={listening ? "Stop listening" : "Start listening"}
            title={
              micSupported
                ? listening
                  ? "Stop listening"
                  : "Push to talk (space)"
                : "Speech recognition is unavailable in this browser"
            }
            className={`relative flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border transition-all duration-300 ${
              listening
                ? "border-holo/70 bg-holo/15 text-holo shadow-[0_0_28px_-6px_rgba(34,211,238,0.8)]"
                : "border-edge/90 bg-void/50 text-muted hover:border-holo/50 hover:text-holo"
            } disabled:cursor-not-allowed disabled:opacity-40`}
          >
            {listening && (
              <>
                <span className="absolute inset-0 animate-ripple rounded-xl border border-holo/50" />
                <span
                  className="absolute inset-0 animate-ripple rounded-xl border border-holo/30"
                  style={{ animationDelay: "1.2s" }}
                />
              </>
            )}
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M12 4a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V7a3 3 0 0 1 3-3Z" />
              <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5" strokeLinecap="round" />
            </svg>
          </button>

          {listening && <MicWave levelRef={micLevelRef} active={listening} />}

          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder={listening ? "Listening…" : placeholder}
            aria-label="Message JARVIS"
            className="max-h-40 min-h-[44px] flex-1 resize-none bg-transparent px-1.5 py-2.5 text-[14px] leading-relaxed text-ink placeholder:text-muted/55 focus:outline-none"
          />

          {busy ? (
            <button
              type="button"
              onClick={onStop}
              className="hud-btn hud-btn-danger h-12 shrink-0 !rounded-xl"
              title="Interrupt the current response"
            >
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor">
                <rect x="6.5" y="6.5" width="11" height="11" rx="2" />
              </svg>
              stop
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!value.trim()}
              className="hud-btn hud-btn-primary h-12 shrink-0 !rounded-xl px-3.5"
              title="Send (enter)"
            >
              <span className="hidden sm:inline">send</span>
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.9">
                <path d="m4.5 12 15-7-5.5 15-3-6.5-6.5-1.5Z" strokeLinejoin="round" />
              </svg>
            </button>
          )}
        </div>

        <div className="mt-1.5 flex items-center justify-between px-1">
          <div className="flex items-center gap-2.5">
            <span className="flex items-center gap-1">
              <kbd className="keycap">space</kbd>
              <span className="hud-label text-[8px] tracking-[0.24em] text-muted/70">talk</span>
            </span>
            <span className="hide-sm flex items-center gap-1">
              <kbd className="keycap">enter</kbd>
              <span className="hud-label text-[8px] tracking-[0.24em] text-muted/70">send</span>
            </span>
            <span className="hide-sm flex items-center gap-1">
              <kbd className="keycap">shift</kbd>
              <kbd className="keycap">enter</kbd>
              <span className="hud-label text-[8px] tracking-[0.24em] text-muted/70">line</span>
            </span>
          </div>
          <span
            className={`hud-label flex items-center gap-1.5 text-[8px] tracking-[0.28em] ${
              busy ? "text-holo/80" : listening ? "text-ok/80" : "text-muted/60"
            }`}
          >
            <span
              className={`h-1 w-1 rounded-full ${busy ? "animate-blink bg-holo" : listening ? "bg-ok" : "bg-muted/60"}`}
            />
            {busy ? "processing" : listening ? "listening" : "ready"}
          </span>
        </div>
      </div>
    </div>
  );
}
