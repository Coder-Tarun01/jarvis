const TONE = {
  info: { tone: "holo", glyph: "i", label: "system" },
  memory: { tone: "pulse", glyph: "◆", label: "memory" },
  warn: { tone: "warn", glyph: "!", label: "alert" },
  error: { tone: "alarm", glyph: "×", label: "error" },
};

export default function Toasts({ items, onDismiss }) {
  if (!items.length) return null;

  return (
    <div className="pointer-events-none fixed bottom-24 right-3 z-40 flex w-[min(360px,92vw)] flex-col gap-2 sm:bottom-28 sm:right-5">
      {items.map((item) => {
        const style = TONE[item.kind] || TONE.info;
        const color = `rgb(var(--${style.tone}))`;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onDismiss(item.id)}
            className="toast-in glass pointer-events-auto flex w-full items-start gap-2.5 overflow-hidden rounded-xl px-3 py-2.5 text-left transition-transform duration-200 hover:-translate-y-0.5"
            style={{ borderColor: `rgb(var(--${style.tone}) / 0.32)` }}
          >
            <span
              className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border font-mono text-[10px]"
              style={{ borderColor: `rgb(var(--${style.tone}) / 0.4)`, color, background: `rgb(var(--${style.tone}) / 0.1)` }}
            >
              {style.glyph}
            </span>
            <span className="min-w-0 flex-1">
              <span
                className="block font-hud text-[8px] font-semibold uppercase tracking-[0.32em]"
                style={{ color }}
              >
                {style.label}
              </span>
              <span className="mt-0.5 block text-[11.5px] leading-snug text-ink/85">{item.text}</span>
            </span>
            <svg
              viewBox="0 0 24 24"
              className="mt-0.5 h-3 w-3 shrink-0 text-muted/50"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M6 6l12 12M18 6 6 18" strokeLinecap="round" />
            </svg>
          </button>
        );
      })}
    </div>
  );
}
