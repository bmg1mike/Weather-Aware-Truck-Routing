import type { CSSProperties } from 'react';

const paths = {
  arrow: 'M4 12h16m-6-6 6 6-6 6',
  chevron: 'm9 5 7 7-7 7',
  check: 'm5 12 4 4L19 6',
  clock: 'M12 8v4l3 2m6-2a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
  compass: 'm16 8-3 5-5 3 3-5 5-3ZM12 3v2m0 14v2M3 12h2m14 0h2',
  globe: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM3 12h18M12 3c5 5 5 13 0 18-5-5-5-13 0-18Z',
  layers: 'm12 3 10 5-10 5L2 8l10-5ZM2 12l10 5 10-5M2 16l10 5 10-5',
  location: 'M12 21s7-6 7-12a7 7 0 1 0-14 0c0 6 7 12 7 12Zm0-9a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z',
  pause: 'M9 5v14M15 5v14',
  play: 'm9 5 10 7-10 7V5Z',
  route: 'M6 6h10a4 4 0 0 1 0 8H8a4 4 0 0 0 0 8M6 3v6M3 6h6M8 19v3',
  shield: 'm12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Zm-4 9 3 3 5-6',
  swap: 'M7 3v16m-4-4 4 4 4-4M17 21V5m-4 4 4-4 4 4',
  truck: 'M3 6h11v12H3V6Zm11 5h4l3 4v3h-7M6 18v2m12-2v2M3 11h11',
  weather: 'M4 16a4 4 0 0 1 0-8 5 5 0 0 1 9-2 5 5 0 1 1 4 10H4Zm2 4h1m4 0h1m4 0h1',
} as const;

export function Icon({
  name,
  size = 20,
  style,
}: {
  name: keyof typeof paths;
  size?: number;
  style?: CSSProperties;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={style}
    >
      <path d={paths[name]} />
    </svg>
  );
}
