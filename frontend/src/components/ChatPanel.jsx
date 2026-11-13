import { useEffect, useRef } from "react";

import Composer from "./Composer.jsx";
import MessageBubble from "./MessageBubble.jsx";
import Orb from "./Orb.jsx";

const SUGGESTIONS = [
  "What time is it right now, and what's on my plate today?",
  "Remind me to call the dentist tomorrow at 9:30",
  "Search the web for the latest on fusion energy",
  "Remember that I'm allergic to peanuts",
  "Add 'review the deck' to my todos",
];

function Telemetry({ label, value, tone = "holo" }) {
  return (
    <div className="flex flex-col">
      <span className="hud-label text-[7.5px] tracking-[0.3em] text-muted/70">{label}</span>
      <span className={`font-mono text-[10px] ${tone === "pulse" ? "text-pulse/90" : "text-holo/90"}`}>
        {value}
      </span>
    </div>
  );
}

function EmptyState({ onPick }) {
  return (
    <div className="mx-auto flex w-full max-w-xl flex-col items-center gap-4 py-2 text-center">
      <div className="flex items-center gap-2">
        <span className="h-px w-8 bg-gradient-to-r from-transparent to-holo/60" />
        <span className="hud-label text-[9px] tracking-[0.42em] text-holo/80">awaiting instruction</span>
        <span className="h-px w-8 bg-gradient-to-l from-transparent to-holo/60" />
      </div>
      <p className="max-w-md text-[12.5px] leading-relaxed text-muted/80">
        Speak or type. Your archive, memory and tools are standing by.
      </p>
      <div className="mt-1 grid w-full grid-cols-1 gap-1.5 sm:grid-cols-2">
        {SUGGESTIONS.map((suggestion, index) => (
          <button
            key={suggestion}
            type="button"
            onClick={() => onPick(suggestion)}
            className="group flex items-center gap-2 rounded-xl border border-edge/60 bg-panel/40 px-3 py-2 text-left text-[12px] leading-snug text-ink/80 transition-colors duration-200 hover:border-holo/40 hover:bg-holo/[0.06] hover:text-ink"
          >
            <span className="font-mono text-[8px] text-muted/50 group-hover:text-holo/70">
              {String(index + 1).padStart(2, "0")}
            </span>
            <span className="min-w-0 flex-1">{suggestion}</span>
            <svg
              viewBox="0 0 24 24"
              className="h-3 w-3 shrink-0 -translate-x-1 text-holo/0 transition-all duration-200 group-hover:translate-x-0 group-hover:text-holo/80"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="m9 6 6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        ))}
      </div>
    </div>
  );
}

export default function ChatPanel({
  messages,
  busy,
  onSend,
  onStop,
  listening,
  onMicToggle,
  micSupported,
  micLevelRef,
  orbState,
  orbOnClick,
  model,
  sttProvider,
  ttsProvider,
  googleEnabled,
  historyCount,
}) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  return (
    <section className="relative flex min-h-0 min-w-0 flex-1 flex-col">
      {/* ---------------------------------------------------------- orb stage */}
      <div className="relative flex shrink-0 items-center justify-center pb-0.5 pt-1 sm:pt-2">
        <div className="pointer-events-none absolute left-4 top-1/2 hidden -translate-y-1/2 space-y-2 xl:block">
          <Telemetry label="stt" value={(sttProvider || "browser").toUpperCase()} />
          <Telemetry label="tts" value={(ttsProvider || "browser").toUpperCase()} tone="pulse" />
        </div>

        <div className="pointer-events-none absolute right-6 top-1/2 hidden -translate-y-1/2 items-end space-y-2 pr-1 text-right xl:flex xl:flex-col">
          <Telemetry label="model" value={model || "—"} />
          <Telemetry label="archive" value={`${historyCount ?? 0} thread${historyCount === 1 ? "" : "s"}`} />
          <Telemetry label="google" value={googleEnabled ? "linked" : "off"} tone="pulse" />
        </div>

        <div className="orb-stage relative flex h-[152px] w-full items-center justify-center sm:h-[200px] xl:h-[232px]">
          <div className="origin-center scale-[0.64] sm:scale-[0.88] xl:scale-100">
            <Orb
              state={orbState}
              size={200}
              micLevelRef={micLevelRef}
              onClick={orbOnClick}
              showLabel
              compact
            />
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------------ messages */}
      <div className="scroll-fade relative min-h-0 flex-1 overflow-y-auto px-3 pb-1 pt-3 sm:px-6 sm:pt-5">
        <div className="mx-auto my-auto flex w-full max-w-3xl flex-col gap-4 py-2" aria-live="polite">
          {messages.length === 0 ? (
            <EmptyState onPick={onSend} />
          ) : (
            messages.map((message) => <MessageBubble key={message.id} message={message} />)
          )}
          <div ref={bottomRef} className="h-1" />
        </div>
      </div>

      <Composer
        onSend={onSend}
        onStop={onStop}
        busy={busy}
        listening={listening}
        onMicToggle={onMicToggle}
        micSupported={micSupported}
        micLevelRef={micLevelRef}
      />
    </section>
  );
}
