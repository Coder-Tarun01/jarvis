/* UI-only snapshot kept in sessionStorage.
   Populated from the /api/health response the login screen already fetches, so the
   HUD can show tool count without adding any new network calls. */

const KEY = "jarvis_hud_snapshot";

export function saveSnapshot(snapshot) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(snapshot));
  } catch {
    /* storage may be disabled */
  }
}

export function readSnapshot() {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return typeof parsed === "object" && parsed ? parsed : null;
  } catch {
    return null;
  }
}

export function clearSnapshot() {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
