// The tekt logo, drawn inline so it follows the theme: a tile holding a monoline "t" whose crossbar is
// an orange beam, and the "tekt" wordmark with the same beams. Standalone files are in public/brand/.

export function Logo({ height = 24 }: { height?: number }) {
  const line = { fill: "none", strokeWidth: 8, strokeLinecap: "round", strokeLinejoin: "round" } as const;
  const t = (x: number) => (
    <>
      <path d={`M${x + 10} 8 V44 Q${x + 10} 56 ${x + 22} 56`} stroke="var(--text)" {...line} />
      <path d={`M${x + 2} 22 H${x + 24}`} stroke="var(--beam)" {...line} />
    </>
  );
  return (
    <svg className="logo" height={height} viewBox="0 0 232 64" role="img" aria-label="tekt">
      <LogoMarkPaths />
      <g transform="translate(80 0)">
        {t(0)}
        <path d="M36 39 H68 A16 16 0 1 0 63.6 50" stroke="var(--text)" {...line} />
        <path d="M84 4 V56 M104 24 L84 42 M92 35 L106 56" stroke="var(--text)" {...line} />
        {t(112)}
      </g>
    </svg>
  );
}

function LogoMarkPaths() {
  return (
    <>
      <rect width="64" height="64" rx="15" fill="var(--brand)" />
      <path d="M28 12 V43 Q28 52 37 52 H42" fill="none" stroke="var(--brand-ink)" strokeWidth="7.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M14 25 H50" fill="none" stroke="var(--beam)" strokeWidth="7.5" strokeLinecap="round" />
    </>
  );
}
