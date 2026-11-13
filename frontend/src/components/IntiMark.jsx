/* INTI monogram — two columns, a raked top beam and the blue accent sliver.
   This is the app's symbol: it replaces the old JARVIS glyph in the orb core,
   the header, the archive sidebar, the login lockup and the favicon.
   Geometry lives in a 128 × 120 box so it can be dropped into any SVG. */

export const MARK_VIEWBOX = "0 0 128 120";
export const MARK_RATIO = 128 / 120;

const BAR = "#F5F8FF";
const ACCENT = "#1477F8";

/* Raw shapes — usable inside another <svg> (the orb embeds it in its own). */
export function MarkPaths({ bar = BAR, accent = ACCENT }) {
  return (
    <g>
      <rect x="0" y="0" width="15.5" height="120" fill={bar} />
      <polygon points="26,0 122,0 106,20 26,20" fill={bar} />
      <polygon points="68,24 104,24 90,45 54,45" fill={accent} />
      <rect x="44" y="41" width="15.5" height="79" fill={bar} />
    </g>
  );
}

export default function IntiMark({
  size = 24,
  className = "",
  glow = false,
  title = "INTI",
}) {
  return (
    <svg
      viewBox={MARK_VIEWBOX}
      width={Math.round(size * MARK_RATIO)}
      height={size}
      role="img"
      aria-label={title}
      className={`shrink-0 ${className}`}
      style={glow ? { filter: "drop-shadow(0 0 8px rgba(20, 119, 248, 0.5))" } : undefined}
    >
      <MarkPaths />
    </svg>
  );
}
