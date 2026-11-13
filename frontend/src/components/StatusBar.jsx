import IntiMark from "./IntiMark.jsx";
import { useClock } from "../hooks/useHudEnvironment.js";

function Pulse({ tone = "holo", label }) {
  const color = `rgb(var(--${tone}))`;
  return (
    <span className="inline-flex items-center gap-2">
      <span className="relative flex h-2 w-2 items-center justify-center">
        <span className="absolute h-2 w-2 animate-ripple rounded-full" style={{ background: color, opacity: 0.5 }} />
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: color, boxShadow: `0 0 10px ${color}` }} />
      </span>
      {label ? <span className="hud-label text-[9px] tracking-[0.3em]">{label}</span> : null}
    </span>
  );
}

export default function StatusBar({
  state,
  connected,
  model,
  toolCount,
  whatsappMode,
  llmConfigured,
  micActive,
  micSupported,
  muted,
  wakeEnabled,
  wakeArmed,
  wakeSupported,
  onToggleWake,
  onToggleMute,
  onOpenMenu,
  onToggleSidebar,
  onRequestAlerts,
  sidebarOpen,
}) {
  const now = useClock();
  const time = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  const seconds = String(now.getSeconds()).padStart(2, "0");
  const date = now
    .toLocaleDateString([], { weekday: "short", day: "2-digit", month: "short" })
    .toUpperCase();

  return (
    <header className="relative z-20 shrink-0 border-b border-edge/50 bg-void/55 backdrop-blur-xl">
      <div className="flex h-14 items-center gap-3 px-3 sm:px-4">
        <button type="button" onClick={onOpenMenu} className="hud-icon lg:hidden" aria-label="Open navigation">
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />
          </svg>
        </button>

        <button
          type="button"
          onClick={onToggleSidebar}
          className={`hud-icon hidden lg:inline-flex ${sidebarOpen ? "border-holo/50 text-holo" : ""}`}
          aria-label={sidebarOpen ? "Hide conversations" : "Show conversations"}
          aria-expanded={sidebarOpen}
          title={sidebarOpen ? "Hide conversations" : "Show conversations"}
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.8">
            <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" />
            <path d="M9.5 4.5v15" />
          </svg>
        </button>

        <div className="flex min-w-0 items-center gap-2.5">
          <IntiMark size={21} glow className="hidden sm:block" />
          <div className="relative">
            <span className="font-display text-[15px] font-bold tracking-[0.34em] text-ink text-glow sm:text-[17px]">
              JARVIS
            </span>
            <span className="absolute -bottom-1 left-0 h-px w-full bg-gradient-to-r from-holo/80 via-pulse/50 to-transparent" />
          </div>
          <span className="chip hide-sm">v1.0</span>
          <div className="hide-sm hidden items-center gap-2 md:flex">
            <span className="h-3 w-px bg-edge" />
            <Pulse tone={connected ? "ok" : "alarm"} label={connected ? "link up" : "offline"} />
          </div>
        </div>

        <div className="hide-sm ml-2 hidden items-center gap-2 md:flex">
          <span className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted">{date}</span>
          <span className="font-mono text-[13px] font-medium tabular-nums text-ink/90">
            {time}
            <span className="text-holo/70">:{seconds}</span>
          </span>
        </div>

        <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
          <span className="chip hide-sm border-holo/25 text-holo/90" title="Active model">
            <span className="h-1 w-1 rounded-full bg-holo" />
            <span className="max-w-[130px] truncate normal-case tracking-[0.12em]">{model || "no model"}</span>
          </span>

          <span className="chip hide-sm" title="Registered tools">
            {toolCount ? `${toolCount} tools` : "— tools"}
          </span>

          {whatsappMode && whatsappMode !== "off" ? (
            <span
              className="chip hide-sm"
              title={
                whatsappMode === "cloud"
                  ? "WhatsApp sends go out through the Cloud API"
                  : "WhatsApp opens a pre-filled chat for you to send"
              }
            >
              WA {whatsappMode === "cloud" ? "cloud" : "link"}
            </span>
          ) : null}

          <span
            className={`chip ${micActive ? "border-holo/60 text-holo" : micSupported ? "" : "opacity-50"}`}
            title={micSupported ? "Microphone state" : "Microphone unsupported in this browser"}
          >
            <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="1.9">
              <path d="M12 4a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V7a3 3 0 0 1 3-3Z" />
              <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5" strokeLinecap="round" />
            </svg>
            {micActive ? "live" : micSupported ? "ready" : "n/a"}
          </span>

          <button
            type="button"
            onClick={onRequestAlerts}
            className="hud-icon hide-sm"
            title="Enable desktop alerts for reminders"
            aria-label="Enable desktop alerts"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="1.7">
              <path d="M6.5 9.5a5.5 5.5 0 0 1 11 0c0 4 1.5 5.5 1.5 5.5H5s1.5-1.5 1.5-5.5Z" strokeLinejoin="round" />
              <path d="M10.5 18.5a1.8 1.8 0 0 0 3 0" strokeLinecap="round" />
            </svg>
          </button>

          <button
            type="button"
            onClick={onToggleWake}
            disabled={!wakeSupported}
            title={
              !wakeSupported
                ? "Wake word needs Chrome or Edge"
                : wakeEnabled
                  ? wakeArmed
                    ? "Wake word armed — say “Hey Jarvis”"
                    : "Wake word starting…"
                  : "Toggle the Hey Jarvis wake word"
            }
            aria-pressed={wakeEnabled}
            className={`hud-btn hud-btn-sm hide-sm ${wakeEnabled ? "border-holo/60 text-holo" : ""}`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                wakeEnabled && wakeArmed
                  ? "animate-blink bg-holo"
                  : wakeEnabled
                    ? "bg-warn"
                    : "bg-muted/40"
              }`}
            />
            wake {wakeEnabled ? "on" : "off"}
          </button>

          <button
            type="button"
            onClick={onToggleMute}
            title={muted ? "Unmute spoken replies" : "Mute spoken replies"}
            aria-pressed={!muted}
            className={`hud-btn hud-btn-sm ${muted ? "" : "border-holo/40 text-holo"}`}
          >
            {muted ? "muted" : "voice"}
          </button>

          <span
            className="relative flex h-7 w-7 items-center justify-center rounded-full border border-edge/80"
            title={llmConfigured === false ? "LLM key missing" : `Connection ${connected ? "online" : "offline"}`}
          >
            <span
              className={`h-2 w-2 rounded-full ${connected ? "bg-ok" : "bg-alarm"}`}
              style={{ boxShadow: `0 0 12px rgb(var(--${connected ? "ok" : "alarm"}))` }}
            />
            {connected ? <span className="absolute inset-0 animate-ripple rounded-full border border-ok/40" /> : null}
          </span>
        </div>
      </div>

      <div className="hidden h-6 items-center gap-3 border-y border-edge/30 bg-void/30 px-4 sm:flex">
        <span className="hud-label text-[8px] tracking-[0.34em] text-holo/85">{state}</span>
        <span className="h-px flex-1 bg-gradient-to-r from-holo/25 via-pulse/15 to-transparent" />
        <span className="font-mono text-[8px] uppercase tracking-[0.28em] text-muted/60">
          {llmConfigured === false ? "llm key missing" : "secure channel"}
        </span>
      </div>
    </header>
  );
}
