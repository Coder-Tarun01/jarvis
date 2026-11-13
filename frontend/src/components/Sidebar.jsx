import IntiMark from "./IntiMark.jsx";

function formatWhen(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  return date.toDateString() === now.toDateString()
    ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString([], { month: "short", day: "numeric" });
}

export default function Sidebar({
  conversations = [],
  activeId,
  onSelect,
  onNew,
  onDelete,
  query,
  onQueryChange,
  onLogout,
  connected,
  className = "",
  collapsed = false,
}) {
  return (
    <aside
      className={`relative z-30 flex h-full shrink-0 flex-col overflow-hidden border-r border-edge/50 bg-void/35 backdrop-blur-xl transition-[width] duration-300 ease-hud ${
        collapsed ? "w-[78px]" : "w-[290px]"
      } ${className}`}
    >
      <div className="pointer-events-none absolute inset-y-0 right-0 w-px bg-gradient-to-b from-holo/30 via-transparent to-pulse/30" />

      <div className={`flex items-center gap-2.5 px-3 pb-2 pt-3 ${collapsed ? "justify-center" : ""}`}>
        <span className="relative flex h-7 w-7 shrink-0 items-center justify-center">
          <span className="absolute inset-0 rounded-[7px] border border-holo/40 bg-holo/[0.06]" />
          <IntiMark size={15} glow className="relative" />
        </span>
        {!collapsed && (
          <div className="min-w-0">
            <div className="font-display text-[11px] font-bold tracking-[0.3em] text-ink/90">ARCHIVE</div>
            <div className="hud-label text-[8px] tracking-[0.3em] text-muted/70">
              {conversations.length} threads logged
            </div>
          </div>
        )}
      </div>

      <div className={`px-3 ${collapsed ? "pt-1" : "pt-2"}`}>
        <button
          type="button"
          onClick={onNew}
          title="New conversation"
          className={`hud-btn hud-btn-primary w-full ${collapsed ? "h-10 justify-center px-0" : "justify-start"}`}
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 5v14M5 12h14" strokeLinecap="round" />
          </svg>
          {!collapsed && <span>new thread</span>}
        </button>
      </div>

      <div className={`mt-3 ${collapsed ? "px-2" : "px-3"}`}>
        {collapsed ? (
          <div className="mx-auto h-8 w-8 rounded-lg border border-edge/70 bg-void/50" />
        ) : (
          <div className="relative">
            <svg
              viewBox="0 0 24 24"
              className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted/70"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.9"
            >
              <circle cx="11" cy="11" r="6.5" />
              <path d="m16 16 4 4" strokeLinecap="round" />
            </svg>
            <input
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="search archive"
              aria-label="Search conversations"
              className="field pl-9 text-[13px]"
            />
          </div>
        )}
      </div>

      <div className={`scroll-fade mt-3 flex-1 overflow-y-auto ${collapsed ? "px-2" : "px-2.5"} pb-3`}>
        {conversations.length === 0 && !collapsed && (
          <div className="mx-auto mt-6 max-w-[190px] text-center">
            <p className="hud-label text-[9px] leading-5 tracking-[0.26em] text-muted/60">no records</p>
            <p className="mt-1 text-[11px] leading-5 text-muted/50">
              Your conversations will be indexed here.
            </p>
          </div>
        )}

        {conversations.map((conversation, index) => {
          const active = conversation.id === activeId;
          const ordinal = String(index + 1).padStart(2, "0");
          return (
            <div
              key={conversation.id}
              className={`group relative mb-1 flex items-center rounded-xl border transition-colors duration-200 ${
                active
                  ? "border-holo/40 bg-holo/[0.07]"
                  : "border-transparent hover:border-edge/80 hover:bg-panel/40"
              } ${collapsed ? "justify-center px-1 py-2" : "px-1.5 py-2"}`}
            >
              {active && (
                <span className="absolute left-0 top-1/2 h-6 w-[2px] -translate-y-1/2 rounded-full bg-holo shadow-[0_0_12px_rgba(34,211,238,0.9)]" />
              )}
              <button
                type="button"
                onClick={() => onSelect(conversation.id)}
                title={conversation.title}
                className={`flex min-w-0 flex-1 items-center gap-2 text-left ${collapsed ? "justify-center" : ""}`}
              >
                <span
                  className={`font-mono text-[9px] tabular-nums ${
                    active ? "text-holo" : "text-muted/50 group-hover:text-holo/70"
                  }`}
                >
                  {ordinal}
                </span>
                {!collapsed && (
                  <span className="min-w-0 flex-1">
                    <span
                      className={`block truncate text-[12.5px] leading-tight ${
                        active ? "text-ink" : "text-ink/75 group-hover:text-ink/90"
                      }`}
                    >
                      {conversation.title}
                    </span>
                    <span className="mt-0.5 block truncate font-mono text-[9px] uppercase tracking-[0.16em] text-muted/60">
                      {conversation.message_count} msg · {formatWhen(conversation.updated_at)}
                    </span>
                  </span>
                )}
              </button>
              {!collapsed && (
                <button
                  type="button"
                  title="Delete conversation"
                  aria-label={`Delete ${conversation.title}`}
                  onClick={() => onDelete(conversation.id)}
                  className="hud-icon h-6 w-6 shrink-0 opacity-0 transition-opacity duration-200 hover:!text-alarm group-hover:opacity-100"
                >
                  <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M6 6l12 12M18 6 6 18" strokeLinecap="round" />
                  </svg>
                </button>
              )}
            </div>
          );
        })}
      </div>

      <div className="border-t border-edge/40 px-3 py-2.5">
        <div className={`flex items-center ${collapsed ? "justify-center" : "justify-between"} gap-2`}>
          <span className="flex items-center gap-1.5" title={connected ? "WebSocket connected" : "Reconnecting"}>
            <span
              className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-ok" : "bg-alarm"}`}
              style={{ boxShadow: `0 0 8px rgb(var(--${connected ? "ok" : "alarm"}))` }}
            />
            {!collapsed && (
              <span className="hud-label text-[8px] tracking-[0.28em]">{connected ? "linked" : "no link"}</span>
            )}
          </span>
          {!collapsed && (
            <button
              type="button"
              onClick={onLogout}
              className="hud-btn hud-btn-sm hud-btn-danger"
              title="Sign out of this session"
            >
              sign out
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}
