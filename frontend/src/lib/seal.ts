// Seal geometry, taken from docs/design/praman_seal.svg (200 × 200 viewBox).
// The ring text is one glyph per character at a fixed angle around the centre, so the spacing
// never depends on font metrics (a textPath let "PRAMAN" run into the end of "CHECK").

export const SEAL_VIEWBOX = 200;
export const SEAL_CENTRE = 100;

export const SEAL_OUTER = { r: 90, stroke: 5.3 } as const;
export const SEAL_INNER = { r: 56.9, stroke: 3.3 } as const;

/** Ring glyphs: baseline y before rotation, font size, and each character's angle in degrees. */
export const SEAL_RING_Y = 34.4;
export const SEAL_RING_SIZE = 18;
export const SEAL_RING_TEXT = "PRAMAN · PROOF CHECK · ";

export const SEAL_GLYPHS: readonly { ch: string; angle: number }[] = [
  { ch: "P", angle: 254.07 },
  { ch: "R", angle: 272.2 },
  { ch: "A", angle: 290.34 },
  { ch: "M", angle: 308.48 },
  { ch: "A", angle: 326.61 },
  { ch: "N", angle: 344.75 },
  { ch: "·", angle: 8.78 },
  { ch: "P", angle: 32.81 },
  { ch: "R", angle: 50.94 },
  { ch: "O", angle: 69.08 },
  { ch: "O", angle: 87.22 },
  { ch: "F", angle: 105.35 },
  { ch: "C", angle: 133.46 },
  { ch: "H", angle: 151.6 },
  { ch: "E", angle: 169.74 },
  { ch: "C", angle: 187.87 },
  { ch: "K", angle: 206.01 },
  { ch: "·", angle: 230.04 },
];

/** Centre mark "प्र": font size; dy lifts the baseline so the glyph sits on the centre. */
export const SEAL_MARK = { text: "प्र", size: 58, dy: "0.36em" } as const;
