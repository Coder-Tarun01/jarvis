import { useState } from "react";

const STATUS = {
  running: { label: "EXECUTING", tone: "holo" },
  ok: { label: "COMPLETE", tone: "ok" },
  error: { label: "FAILED", tone: "alarm" },
};

function Spinner() {
  return (
    <span className="relative flex h-3.5 w-3.5 items-center justify-center">
      <span className="absolute inset-0 animate-spin-fast rounded-full border border-holo/30 border-t-holo" />
      <span className="h-1 w-1 rounded-full bg-holo" />
    </span>
  );
}

/**
 * Tool results arrive as (sometimes truncated) JSON. Show something a human can
 * scan instead of a wall of braces — purely presentational.
 */
function prettySummary(summary) {
  if (!summary) return "";
  const text = String(summary).trim();
  if (!text.startsWith("{") && !text.startsWith("[")) {
    return text.replace(/\s+/g, " ");
  }
  const friendly = (data) => {
    if (Array.isArray(data)) return `${data.length} item${data.length === 1 ? "" : "s"}`;
    if (data && typeof data === "object") {
      for (const key of ["human", "text", "message", "summary", "answer", "result", "ok"]) {
        const value = data[key];
        if (["string", "number", "boolean"].includes(typeof value)) return String(value);
      }
      const keys = Object.keys(data);
      return keys.length ? `${keys.length} fields · ${keys.slice(0, 3).join(", ")}` : "done";
    }
    return String(data);
  };
  try {
    return friendly(JSON.parse(text));
  } catch {
    // The server may have clipped a long payload mid-string — dredge a key out.
    const match = text.match(/"(?:human|text|message|summary|answer|result)"\s*:\s*"([^"]+)"/);
    if (match) return match[1];
    return text.replace(/^[{[]\s*/, "").replace(/[\]}]\s*$/, "").replace(/\s+/g, " ").slice(0, 120);
  }
}

export default function ToolModule({ tool }) {
  const [open, setOpen] = useState(false);
  const status = STATUS[tool.status] || STATUS.running;
  const color = `rgb(var(--${status.tone}))`;

  return (
    <div
      className="glass-quiet mb-1.5 overflow-hidden !rounded-xl"
      style={{ borderColor: `rgb(var(--${status.tone}) / 0.28)` }}
    >
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left transition-colors hover:bg-white/[0.03]"
      >
        <span className="flex h-3.5 w-3.5 items-center justify-center">
          {tool.status === "running" ? (
            <Spinner />
          ) : (
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{ background: color, boxShadow: `0 0 8px ${color}` }}
            />
          )}
        </span>

        <span className="font-mono text-[10.5px] tracking-[0.04em] text-ink/85">{tool.name}</span>

        <span
          className="font-hud text-[8px] font-semibold uppercase tracking-[0.26em]"
          style={{ color }}
        >
          {status.label}
        </span>

        {tool.summary && !open ? (
          <span className="min-w-0 flex-1 truncate font-mono text-[9.5px] text-muted/60">
            {prettySummary(tool.summary)}
          </span>
        ) : (
          <span className="flex-1" />
        )}

        <svg
          viewBox="0 0 24 24"
          className={`h-3 w-3 shrink-0 text-muted/70 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className="border-t border-edge/40 px-2.5 py-2">
          <div className="hud-label mb-1 text-[8px] tracking-[0.3em]">arguments</div>
          <pre className="max-h-40 overflow-auto rounded-lg border border-edge/50 bg-void/70 p-2 font-mono text-[10px] leading-relaxed text-holo/80">
            {JSON.stringify(tool.input ?? {}, null, 2)}
          </pre>
          {tool.summary && (
            <>
              <div className="hud-label mb-1 mt-2 text-[8px] tracking-[0.3em]">result</div>
              <p className="rounded-lg border border-edge/50 bg-void/60 p-2 font-mono text-[10px] leading-relaxed text-ink/70">
                {tool.summary}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
