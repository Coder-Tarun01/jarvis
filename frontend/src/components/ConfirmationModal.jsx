import { useEffect, useRef, useState } from "react";

function Panel({ request, onApprove, onDeny }) {
  const total = Math.max(5, Math.round(request.timeout || 60));
  const [remaining, setRemaining] = useState(total);
  const denyRef = useRef(null);

  useEffect(() => {
    setRemaining(total);
    const id = window.setInterval(() => {
      setRemaining((prev) => (prev <= 1 ? 0 : prev - 1));
    }, 1000);
    return () => window.clearInterval(id);
  }, [total, request.id]);

  useEffect(() => {
    denyRef.current?.focus({ preventScroll: true });
  }, []);

  useEffect(() => {
    const handler = (event) => {
      if (event.key === "Escape") onDeny();
      if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) onApprove();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onApprove, onDeny]);

  const progress = Math.max(0, Math.min(1, remaining / total));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Dismiss"
        onClick={onDeny}
        className="absolute inset-0 cursor-default bg-void/80 backdrop-blur-md"
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="authz-title"
        className="glass relative z-10 w-full max-w-lg animate-fade-up overflow-hidden !rounded-2xl"
        style={{ borderColor: "rgb(var(--warn) / 0.45)", boxShadow: "0 0 90px -30px rgb(var(--warn) / 0.55)" }}
      >
        <div
          className="pointer-events-none absolute inset-x-0 top-0 h-px"
          style={{ background: "linear-gradient(90deg, transparent, rgb(var(--warn)), transparent)" }}
        />
        <div
          className="pointer-events-none absolute -right-16 -top-16 h-40 w-40 rounded-full blur-3xl"
          style={{ background: "radial-gradient(circle, rgb(var(--warn) / 0.28), transparent 70%)" }}
        />

        <div className="relative p-5 sm:p-6">
          <div className="flex items-start gap-3">
            <span className="relative mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-warn/40 bg-warn/10">
              <span className="absolute inset-0 animate-ripple rounded-xl border border-warn/30" />
              <svg viewBox="0 0 24 24" className="h-5 w-5 text-warn" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M12 4.5 21 19.5H3L12 4.5Z" strokeLinejoin="round" />
                <path d="M12 10v4.2M12 17.2v.2" strokeLinecap="round" />
              </svg>
            </span>

            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-3">
                <h2 id="authz-title" className="font-display text-[12px] font-bold uppercase tracking-[0.3em] text-warn">
                  Authorization required
                </h2>
                <span className="shrink-0 font-mono text-[11px] tabular-nums text-warn/80">
                  {String(Math.floor(remaining / 60)).padStart(2, "0")}:
                  {String(remaining % 60).padStart(2, "0")}
                </span>
              </div>
              <p className="mt-1 text-[12.5px] leading-relaxed text-muted">
                {request.hint || "This action has effects outside JARVIS."}
              </p>
            </div>
          </div>

          <div className="mt-4 rounded-xl border border-edge/60 bg-void/60 p-3">
            <div className="flex items-center justify-between gap-3">
              <span className="hud-label text-[8px] tracking-[0.3em] text-muted/70">tool</span>
              <span className="font-mono text-[11px] text-warn">{request.name}</span>
            </div>
            <div className="my-2 h-px bg-edge/50" />
            <pre className="max-h-44 overflow-auto whitespace-pre-wrap break-words font-mono text-[10.5px] leading-relaxed text-ink/75">
              {JSON.stringify(request.input || {}, null, 2)}
            </pre>
          </div>

          <div className="mt-3 h-1 overflow-hidden rounded-full bg-edge/40">
            <div
              className="h-full origin-left rounded-full"
              style={{
                background: "linear-gradient(90deg, rgb(var(--warn) / 0.5), rgb(var(--warn)))",
                transform: `scaleX(${progress})`,
                transition: "transform 1s linear",
              }}
            />
          </div>

          <p className="mt-3 text-[11px] leading-relaxed text-muted/80">
            Approving lets JARVIS act outside the app. Denying tells it to stand down. Times out automatically.
          </p>

          <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button
              ref={denyRef}
              type="button"
              onClick={onDeny}
              className="hud-btn focus-visible:outline-warn/70 sm:min-w-[110px]"
            >
              deny
            </button>
            <button
              type="button"
              onClick={onApprove}
              className="hud-btn hud-btn-warn focus-visible:outline-warn/70 sm:min-w-[130px]"
              title="Approve (ctrl/cmd + enter)"
            >
              approve
              <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2.2">
                <path d="m5 12.5 4.5 4.5L19 7.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>

          <div className="mt-3 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 sm:justify-end">
            <kbd className="keycap">ctrl</kbd>
            <kbd className="keycap">enter</kbd>
            <span className="hud-label text-[8px] tracking-[0.24em] text-muted/60">approve</span>
            <span className="mx-1 h-2 w-px bg-edge" />
            <kbd className="keycap">esc</kbd>
            <span className="hud-label text-[8px] tracking-[0.24em] text-muted/60">deny</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ConfirmationModal({ request, onApprove, onDeny }) {
  if (!request) return null;
  return <Panel request={request} onApprove={onApprove} onDeny={onDeny} />;
}
