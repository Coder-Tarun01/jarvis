import ToolModule from "./ToolModule.jsx";

function AssistantGlyph() {
  return (
    <span className="relative flex h-7 w-7 items-center justify-center">
      <span className="absolute inset-0 rounded-full border border-holo/35 bg-holo/[0.06]" />
      <span className="absolute inset-0 animate-spin-slow rounded-full border border-dashed border-holo/25" />
      <span className="h-2 w-2 rounded-full bg-holo shadow-[0_0_10px_rgba(34,211,238,0.9)]" />
    </span>
  );
}

function UserGlyph() {
  return (
    <span className="relative flex h-7 w-7 items-center justify-center">
      <span className="absolute inset-0 rounded-full border border-pulse/35 bg-pulse/[0.08]" />
      <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 text-pulse/80" fill="none" stroke="currentColor" strokeWidth="1.9">
        <circle cx="12" cy="8.5" r="3.2" />
        <path d="M5.5 19.5a6.5 6.5 0 0 1 13 0" strokeLinecap="round" />
      </svg>
    </span>
  );
}

export default function MessageBubble({ message }) {
  const isUser = message.role === "user";
  const tools = message.tools || [];
  const hasBody = Boolean(message.text) || message.streaming || tools.length > 0;

  if (!hasBody) return null;

  return (
    <article
      className={`message-in flex w-full gap-2.5 sm:gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}
      aria-label={isUser ? "Your message" : "JARVIS message"}
    >
      <div className="mt-1 shrink-0">{isUser ? <UserGlyph /> : <AssistantGlyph />}</div>

      <div className={`flex min-w-0 max-w-[min(720px,88%)] flex-col ${isUser ? "items-end" : "items-start"}`}>
        <div className={`mb-1 flex items-center gap-2 px-0.5 ${isUser ? "flex-row-reverse" : ""}`}>
          <span className="hud-label text-[8px] tracking-[0.34em]">{isUser ? "operator" : "jarvis"}</span>
          {message.streaming && (
            <span className="flex items-center gap-1 font-mono text-[8px] uppercase tracking-[0.28em] text-holo/80">
              <span className="h-1 w-1 animate-blink rounded-full bg-holo" />
              streaming
            </span>
          )}
        </div>

        {tools.length > 0 && (
          <div className="mb-1.5 w-full">
            {tools.map((tool, index) => (
              <ToolModule key={tool.id || `${tool.name}-${index}`} tool={tool} />
            ))}
          </div>
        )}

        <div
          className={[
            "relative w-fit max-w-full px-3.5 py-2.5 backdrop-blur-sm",
            isUser
              ? "rounded-2xl rounded-tr-md border border-pulse/30 bg-pulse/[0.09] text-ink/90"
              : "rounded-2xl rounded-tl-md border border-edge/60 border-l-2 border-l-holo/70 bg-panel/45 text-ink/90",
          ].join(" ")}
        >
          {message.text ? (
            <p className="whitespace-pre-wrap break-words text-[14px] leading-[1.65] sm:text-[14.5px]">
              {message.text}
              {message.streaming && <span className="stream-caret" aria-hidden="true" />}
            </p>
          ) : (
            <span className="flex items-center gap-1.5 py-0.5" aria-label="JARVIS is thinking">
              {[0, 1, 2].map((dot) => (
                <span
                  key={dot}
                  className="h-1.5 w-1.5 animate-blink rounded-full bg-holo/80"
                  style={{ animationDelay: `${dot * 0.18}s`, animationDuration: "1.1s" }}
                />
              ))}
            </span>
          )}
        </div>
      </div>
    </article>
  );
}
