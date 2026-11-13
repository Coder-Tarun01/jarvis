import { useEffect, useId, useRef } from "react";

import { MARK_VIEWBOX, MarkPaths } from "./IntiMark.jsx";

const THEME = {
  idle: { a: "34 211 238", b: "139 92 246", glow: 0.42, label: "STANDBY", sub: "systems nominal" },
  listening: { a: "103 232 249", b: "34 211 238", glow: 0.85, label: "LISTENING", sub: "capturing audio" },
  thinking: { a: "139 92 246", b: "34 211 238", glow: 0.72, label: "PROCESSING", sub: "reasoning" },
  speaking: { a: "34 211 238", b: "167 139 250", glow: 0.95, label: "TRANSMITTING", sub: "voice output" },
};

const TICKS = Array.from({ length: 60 }, (_, index) => index);
const BARS = Array.from({ length: 64 }, (_, index) => index);
const SPIN_ORIGIN = { transformBox: "view-box", transformOrigin: "120px 120px" };

/* Living core: bloom, breathing sphere, layered rings, orbiting nodes, a
   mic-reactive halo when listening and a radiating waveform when speaking.
   All motion is transform/opacity only and is neutralised by the global
   prefers-reduced-motion rule. */
export default function Orb({
  state = "idle",
  size = 220,
  micLevelRef,
  onClick,
  showLabel = true,
  compact = false,
  className = "",
}) {
  const theme = THEME[state] || THEME.idle;
  const rootRef = useRef(null);
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const interactive = typeof onClick === "function";
  const listening = state === "listening";
  const thinking = state === "thinking";
  const speaking = state === "speaking";

  /* Mic level -> CSS variable, driven imperatively to avoid React renders. */
  useEffect(() => {
    const node = rootRef.current;
    if (!node) return undefined;
    if (!listening || !micLevelRef) {
      node.style.setProperty("--mic", "0");
      return undefined;
    }
    let frame = 0;
    let smoothed = 0;
    const tick = () => {
      const raw = micLevelRef.current || 0;
      smoothed = smoothed * 0.7 + raw * 0.3;
      node.style.setProperty("--mic", smoothed.toFixed(3));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      node.style.setProperty("--mic", "0");
    };
  }, [listening, micLevelRef]);

  const Tag = interactive ? "button" : "div";

  return (
    <div
      ref={rootRef}
      className={`relative flex select-none flex-col items-center ${className}`}
      style={{ width: size, "--orb-a": theme.a, "--orb-b": theme.b, "--orb-glow": theme.glow }}
    >
      <Tag
        type={interactive ? "button" : undefined}
        onClick={onClick}
        aria-label={interactive ? `JARVIS ${theme.label} — toggle microphone` : `JARVIS ${theme.label}`}
        className="group relative block rounded-full outline-none"
        style={{ width: size, height: size }}
      >
        <div
          className="pointer-events-none absolute inset-[10%] rounded-full blur-2xl transition-opacity duration-700"
          style={{
            background:
              "radial-gradient(circle, rgb(var(--orb-a) / 0.55) 0%, rgb(var(--orb-b) / 0.28) 45%, transparent 72%)",
            opacity: "var(--orb-glow)",
          }}
        />

        <svg viewBox="0 0 240 240" className="relative h-full w-full overflow-visible" role="presentation">
          <defs>
            <radialGradient id={`core-${uid}`} cx="36%" cy="30%" r="78%">
              <stop offset="0%" style={{ stopColor: "rgb(var(--orb-a))", stopOpacity: 0.98 }} />
              <stop offset="52%" style={{ stopColor: "rgb(var(--orb-b))", stopOpacity: 0.9 }} />
              <stop offset="100%" style={{ stopColor: "#04060f", stopOpacity: 0.96 }} />
            </radialGradient>
            <radialGradient id={`halo-${uid}`} cx="50%" cy="50%" r="50%">
              <stop offset="55%" style={{ stopColor: "rgb(var(--orb-a))", stopOpacity: 0 }} />
              <stop offset="86%" style={{ stopColor: "rgb(var(--orb-a))", stopOpacity: 0.26 }} />
              <stop offset="100%" style={{ stopColor: "rgb(var(--orb-b))", stopOpacity: 0 }} />
            </radialGradient>
            <linearGradient id={`arc-${uid}`} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" style={{ stopColor: "rgb(var(--orb-a))", stopOpacity: 0.95 }} />
              <stop offset="100%" style={{ stopColor: "rgb(var(--orb-b))", stopOpacity: 0.12 }} />
            </linearGradient>
          </defs>

          <circle cx="120" cy="120" r="104" fill={`url(#halo-${uid})`} />

          {listening && (
            <g className="pointer-events-none">
              {[0, 1].map((index) => (
                <circle
                  key={index}
                  cx="120"
                  cy="120"
                  r="78"
                  fill="none"
                  strokeWidth="1.2"
                  className="animate-ripple"
                  style={{
                    stroke: "rgb(var(--orb-a) / 0.7)",
                    transformBox: "view-box",
                    transformOrigin: "120px 120px",
                    animationDelay: `${index * 1.35}s`,
                  }}
                />
              ))}
            </g>
          )}

          {speaking && (
            <g className="pointer-events-none">
              {[0, 1, 2].map((index) => (
                <circle
                  key={index}
                  cx="120"
                  cy="120"
                  r="66"
                  fill="none"
                  strokeWidth="1"
                  className="animate-ripple"
                  style={{
                    stroke: "rgb(var(--orb-a) / 0.55)",
                    transformBox: "view-box",
                    transformOrigin: "120px 120px",
                    animationDelay: `${index * 0.75}s`,
                    animationDuration: "2.4s",
                  }}
                />
              ))}
            </g>
          )}

          <circle cx="120" cy="120" r="112" fill="none" strokeWidth="1" style={{ stroke: "rgb(255 255 255 / 0.07)" }} />

          <g className="animate-spin-slow" style={SPIN_ORIGIN}>
            <circle cx="120" cy="120" r="104" fill="none" strokeWidth="1" strokeDasharray="1 7" style={{ stroke: "rgb(var(--orb-a) / 0.55)" }} />
          </g>

          <g className="animate-spin-rev" style={SPIN_ORIGIN}>
            {TICKS.map((tick) => {
              const major = tick % 5 === 0;
              return (
                <line
                  key={tick}
                  x1="120"
                  y1={major ? 8 : 11}
                  x2="120"
                  y2="15"
                  strokeWidth={major ? 1.6 : 0.8}
                  transform={`rotate(${tick * 6} 120 120)`}
                  style={{ stroke: major ? "rgb(var(--orb-a) / 0.55)" : "rgb(255 255 255 / 0.16)" }}
                />
              );
            })}
          </g>
        </svg>

        <svg viewBox="0 0 240 240" className="pointer-events-none absolute inset-0 h-full w-full" role="presentation">
          <g className={thinking ? "animate-spin-fast" : "animate-spin-med"} style={SPIN_ORIGIN}>
            <circle
              cx="120"
              cy="120"
              r="88"
              fill="none"
              strokeWidth={thinking ? 5 : 3}
              strokeDasharray={thinking ? "10 6" : "26 12"}
              style={{
                stroke: `url(#arc-${uid})`,
                opacity: thinking ? 0.95 : 0.6,
                transition: "opacity 400ms ease, stroke-width 400ms ease",
              }}
            />
          </g>

          <g className="animate-spin-rev" style={SPIN_ORIGIN}>
            <circle
              cx="120"
              cy="120"
              r="80"
              fill="none"
              strokeWidth="1.6"
              strokeDasharray="52 200"
              strokeLinecap="round"
              style={{ stroke: "rgb(var(--orb-a) / 0.75)" }}
            />
            <circle
              cx="120"
              cy="120"
              r="80"
              fill="none"
              strokeWidth="1.6"
              strokeDasharray="22 230"
              strokeDashoffset="-96"
              strokeLinecap="round"
              style={{ stroke: "rgb(var(--orb-b) / 0.6)" }}
            />
          </g>

          <g className="animate-spin-med" style={SPIN_ORIGIN}>
            <circle cx="120" cy="20" r="2.6" style={{ fill: "rgb(var(--orb-a))" }} />
            <circle cx="120" cy="220" r="1.6" style={{ fill: "rgb(var(--orb-b) / 0.8)" }} />
          </g>
          <g className="animate-spin-slow" style={SPIN_ORIGIN}>
            <circle cx="16" cy="120" r="1.8" style={{ fill: "rgb(var(--orb-a) / 0.9)" }} />
          </g>

          {speaking && (
            <g>
              {BARS.map((bar) => {
                const angle = (bar * 360) / BARS.length;
                const strong = bar % 4 === 0;
                return (
                  <g key={bar} transform={`rotate(${angle} 120 120)`}>
                    <rect
                      x="119"
                      y={strong ? 44 : 47}
                      width="2"
                      height={strong ? 14 : 9}
                      rx="1"
                      style={{
                        fill: strong ? "rgb(var(--orb-a))" : "rgb(var(--orb-b) / 0.85)",
                        transformBox: "fill-box",
                        transformOrigin: "50% 100%",
                        animation: `wave ${strong ? 0.9 : 1.25}s ease-in-out infinite`,
                        animationDelay: `${(bar % 8) * 0.07}s`,
                      }}
                    />
                  </g>
                );
              })}
            </g>
          )}

          <g
            style={{
              transformBox: "view-box",
              transformOrigin: "120px 120px",
              transform: "scale(calc(1 + var(--mic) * 0.09))",
              transition: "transform 90ms linear",
            }}
          >
            <circle cx="120" cy="120" r="56" fill="#04060f" opacity="0.88" />
            <circle cx="120" cy="120" r="56" fill={`url(#core-${uid})`} opacity="0.42" />
            <circle
              cx="120"
              cy="120"
              r="56"
              fill="none"
              strokeWidth="1.2"
              style={{ stroke: "rgb(var(--orb-a) / 0.55)" }}
            />
            {/* the INTI mark is the core of the orb */}
            <svg
              x="87"
              y="89"
              width="66"
              height="62"
              viewBox={MARK_VIEWBOX}
              overflow="visible"
              role="presentation"
              style={{ filter: "drop-shadow(0 0 7px rgb(var(--orb-a) / 0.55))" }}
            >
              <MarkPaths />
            </svg>
          </g>

          <circle
            cx="120"
            cy="120"
            r="60"
            fill="none"
            strokeWidth="0.8"
            className="animate-breathe"
            style={{
              stroke: "rgb(var(--orb-a) / 0.5)",
              transformBox: "view-box",
              transformOrigin: "120px 120px",
            }}
          />
        </svg>
      </Tag>

      {showLabel && (
        <div className={`flex flex-col items-center ${compact ? "mt-1 gap-0.5" : "mt-2.5 gap-1"}`}>
          <div className="flex items-center gap-2">
            <span
              className="h-1 w-1 animate-blink rounded-full"
              style={{ background: "rgb(var(--orb-a))", boxShadow: "0 0 10px rgb(var(--orb-a))" }}
            />
            <span
              className="font-hud text-[10px] font-semibold uppercase tracking-[0.42em]"
              style={{ color: "rgb(var(--orb-a))" }}
            >
              {theme.label}
            </span>
          </div>
          {!compact && (
            <span className="font-mono text-[9px] uppercase tracking-[0.3em] text-muted/70">
              {theme.sub}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
