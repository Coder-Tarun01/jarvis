import { useCallback, useEffect, useRef, useState } from "react";

import Backdrop from "../components/Backdrop.jsx";
import Orb from "../components/Orb.jsx";
import { useReducedMotion } from "../hooks/useHudEnvironment.js";
import { api } from "../lib/api.js";
import { saveSnapshot } from "../lib/hudState.js";

const BOOT_LINE = "INITIALIZING J.A.R.V.I.S";
const BOOT_LOG = [
  "core lattice ....... online",
  "memory archive ..... indexed",
  "secure channel ..... required",
];

function Corners() {
  const base = "pointer-events-none absolute h-3 w-3 border-holo/50";
  return (
    <>
      <span className={`${base} left-0 top-0 border-l border-t`} />
      <span className={`${base} right-0 top-0 border-r border-t`} />
      <span className={`${base} bottom-0 left-0 border-b border-l`} />
      <span className={`${base} bottom-0 right-0 border-b border-r`} />
    </>
  );
}

export default function Login({ onLogin }) {
  const reduced = useReducedMotion();
  const [typed, setTyped] = useState(reduced ? BOOT_LINE : "");
  const [phase, setPhase] = useState(reduced ? 3 : 0);
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [shake, setShake] = useState(false);
  const inputRef = useRef(null);

  /* Boot typewriter — text only, no layout-affecting animation. */
  useEffect(() => {
    if (reduced) {
      setTyped(BOOT_LINE);
      setPhase(3);
      return undefined;
    }
    let index = 0;
    const timers = [];
    const id = window.setInterval(() => {
      index += 1;
      setTyped(BOOT_LINE.slice(0, index));
      if (index >= BOOT_LINE.length) {
        window.clearInterval(id);
        timers.push(window.setTimeout(() => setPhase(1), 160));
        timers.push(window.setTimeout(() => setPhase(2), 520));
        timers.push(window.setTimeout(() => setPhase(3), 880));
      }
    }, 46);
    return () => {
      window.clearInterval(id);
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [reduced]);

  useEffect(() => {
    if (phase >= 3) inputRef.current?.focus({ preventScroll: true });
  }, [phase]);

  const fail = useCallback((message) => {
    setError(message);
    setShake(true);
    window.setTimeout(() => setShake(false), 460);
  }, []);

  const submit = async (event) => {
    event.preventDefault();
    const candidate = value.trim();
    if (!candidate) {
      fail("Paste the token from your .env (JARVIS_AUTH_TOKEN).");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const health = await api("/api/health", { token: candidate });
      saveSnapshot({
        toolCount: health?.tool_count ?? null,
        model: health?.model ?? null,
        provider: health?.provider ?? null,
      });
      onLogin(candidate);
    } catch (err) {
      fail(
        /401|invalid|missing/i.test(err.message)
          ? "Access denied — check JARVIS_AUTH_TOKEN in your .env."
          : `Link failure: ${err.message}`,
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative flex h-full items-center justify-center overflow-hidden px-4 py-6">
      <Backdrop />

      <div className="relative z-10 flex w-full max-w-md flex-col items-center sm:max-w-lg">
        <div className="scale-[0.78] sm:scale-100">
          <Orb state={busy ? "thinking" : "idle"} size={210} showLabel={false} />
        </div>

        <div className="-mt-1 text-center">
          <h1 className="font-display text-[26px] font-bold tracking-[0.54em] text-ink text-glow sm:text-[32px]">
            INTI
          </h1>
          <div className="mx-auto mt-2 h-px w-48 bg-gradient-to-r from-transparent via-holo/70 to-transparent" />
          <p className="mt-2 font-mono text-[9px] uppercase tracking-[0.42em] text-muted/70 sm:text-[10px]">
            tarun sai kumar
          </p>
          <p className="mt-3 font-mono text-[10px] uppercase tracking-[0.34em] text-holo/80 sm:text-[11px]">
            {typed}
            {phase < 1 && <span className="ml-0.5 inline-block h-3 w-[6px] animate-caret bg-holo align-middle" />}
          </p>
        </div>

        {/* boot log — revealed line by line */}
        <div className="mt-3 h-[60px] w-full max-w-[340px] space-y-1">
          {BOOT_LOG.map((line, index) => (
            <p
              key={line}
              className={`font-mono text-[10px] leading-5 tracking-[0.14em] text-muted/55 transition-opacity duration-500 ${
                phase >= 1 && index < 3 ? "opacity-100" : "opacity-0"
              }`}
              style={{ transitionDelay: `${index * 120}ms` }}
            >
              <span className="text-ok/70">›</span> {line}
            </p>
          ))}
        </div>

        {/* token panel */}
        <div
          className={`relative mt-5 w-full transition-all duration-500 ease-hud ${
            phase >= 2 ? "translate-y-0 opacity-100" : "translate-y-3 opacity-0"
          } ${shake ? "animate-shake" : ""}`}
          aria-hidden={phase < 2}
        >
          <form
            onSubmit={submit}
            className="glass relative overflow-hidden p-4 sm:p-6"
            style={{ borderColor: "rgb(var(--holo) / 0.25)" }}
          >
            <Corners />
            <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-holo/70 to-transparent" />

            <div className="flex items-center justify-between">
              <span className="hud-label text-[10px] tracking-[0.34em] text-holo/80">access credential</span>
              <span className="flex items-center gap-1.5">
                <span
                  className={`h-1 w-1 animate-blink rounded-full ${value ? "bg-ok" : "bg-warn"}`}
                />
                <span
                  className={`font-mono text-[8px] uppercase tracking-[0.28em] ${
                    value ? "text-ok/80" : "text-warn/80"
                  }`}
                >
                  {value ? "ready" : "locked"}
                </span>
              </span>
            </div>

            <label htmlFor="token" className="sr-only">
              JARVIS access token
            </label>
            <div className="relative mt-2">
              <svg
                viewBox="0 0 24 24"
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted/60"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.7"
              >
                <rect x="4.5" y="10" width="15" height="9.5" rx="2" />
                <path d="M8 10V7.5a4 4 0 0 1 8 0V10" strokeLinecap="round" />
              </svg>
              <input
                ref={inputRef}
                id="token"
                type="password"
                value={value}
                onChange={(event) => setValue(event.target.value)}
                placeholder="enter access token"
                autoComplete="current-password"
                disabled={phase < 3 || busy}
                tabIndex={phase >= 3 ? 0 : -1}
                className="field py-3 pl-10 font-mono text-[13px] tracking-[0.1em]"
              />
            </div>

            {error ? (
              <p role="alert" className="mt-2 flex items-start gap-1.5 text-[11px] leading-snug text-alarm">
                <span className="mt-[3px] h-1 w-1 shrink-0 rounded-full bg-alarm" />
                {error}
              </p>
            ) : (
              <p className="mt-2 text-[10px] leading-snug text-muted/55">
                Token lives in <span className="font-mono text-muted/80">.env</span> · stored locally only.
              </p>
            )}

            <button
              type="submit"
              disabled={phase < 3 || busy}
              tabIndex={phase >= 3 ? 0 : -1}
              className="hud-btn hud-btn-primary group mt-5 w-full py-3"
            >
              {busy ? (
                <>
                  <span className="h-3 w-3 animate-spin-fast rounded-full border border-holo/40 border-t-holo" />
                  authenticating
                </>
              ) : (
                <>
                  enter system
                  <svg
                    viewBox="0 0 24 24"
                    className="h-3.5 w-3.5 transition-transform duration-300 group-hover:translate-x-1"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <path d="M5 12h13M13 6.5 18.5 12 13 17.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </>
              )}
            </button>
          </form>

          <p className="mt-3 text-center font-mono text-[8.5px] uppercase tracking-[0.28em] text-muted/40">
            single-user deployment · local network only
          </p>
        </div>
      </div>
    </div>
  );
}
