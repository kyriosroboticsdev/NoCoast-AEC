// The tekt logo (three buildings over the wordmark), drawn inline from the traced artwork so the navy
// parts follow the theme: navy on light, near-white on the dark night-sky background. The blue and
// orange stay the brand colours in both. Standalone SVGs are in public/brand/.
import { ICON, LOCKUP, WORDMARK } from "./logoPaths";

const BLUE = "#8bc6e3";
const ORANGE = "#f3880d";

/** Horizontal lockup: the building mark, then "tekt". `height` is the mark's height in px. */
export function Logo({ height = 26 }: { height?: number }) {
  const wordW = WORDMARK.width * LOCKUP.wordScale;
  const wordH = WORDMARK.height * LOCKUP.wordScale;
  const width = ICON.width + LOCKUP.gap + wordW;
  return (
    <svg className="logo" height={height} viewBox={`0 0 ${width} ${ICON.height}`} role="img" aria-label="tekt">
      <g fillRule="evenodd">
        <path fill={BLUE} d={ICON.blue} />
        <path fill={ORANGE} d={ICON.orange} />
        <path fill="var(--logo-ink)" d={ICON.ink} />
        <path fill="var(--logo-ink)" d={WORDMARK.ink}
          transform={`translate(${ICON.width + LOCKUP.gap} ${ICON.height - wordH}) scale(${LOCKUP.wordScale})`} />
      </g>
    </svg>
  );
}
