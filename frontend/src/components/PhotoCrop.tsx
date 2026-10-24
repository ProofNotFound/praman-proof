// A region of a pack photo, cut out with bracket corners (DESIGN §4.2 "Photo crop").
// Uses a positioned <img> rather than a CSS background so it also prints.

import type { CSSProperties } from "react";
import { motion } from "motion/react";
import type { Box } from "../lib/events";
import { Img } from "./Img";

/** Grow the box so the crop is never thinner than 1 : maxAspect, then pad it. */
export const cropLayoutId = (photo: number, box: Box): string => `crop:${photo}:${box.join(",")}`;

export function cropRegion(box: Box, photoAspect: number, maxAspect = 4.2): Box {
  let [y0, x0, y1, x1] = box;
  const padX = 14;
  const padY = 18;
  y0 -= padY;
  y1 += padY;
  x0 -= padX;
  x1 += padX;
  const wPx = (x1 - x0) * photoAspect;
  const hPx = y1 - y0;
  if (wPx / hPx > maxAspect) {
    const grow = (wPx / maxAspect - hPx) / 2;
    y0 -= grow;
    y1 += grow;
  }
  const clamp = (v: number) => Math.max(0, Math.min(1000, v));
  return [clamp(y0), clamp(x0), clamp(y1), clamp(x1)];
}

export function PhotoCrop({
  src,
  box,
  width,
  height,
  tone = "var(--accent)",
  alt,
  maxHeight,
  layoutId,
  bare = false,
}: {
  src: string;
  box: Box;
  width?: number | null;
  height?: number | null;
  tone?: string;
  alt: string;
  maxHeight?: number;
  /** shared with the Scan overlay's crop, so the crop lifts out of the photo into the card */
  layoutId?: string;
  /** no padded wrapper (inside the Scan overlay) */
  bare?: boolean;
}) {
  const aspect = width && height ? width / height : 1;
  const r = cropRegion(box, aspect);
  const [y0, x0, y1, x1] = r;
  const bw = Math.max(1, x1 - x0);
  const bh = Math.max(1, y1 - y0);
  const frame: CSSProperties = { aspectRatio: `${bw * aspect} / ${bh}`, maxHeight };
  const img: CSSProperties = {
    width: `${(1000 / bw) * 100}%`,
    height: `${(1000 / bh) * 100}%`,
    left: `${(-x0 / bw) * 100}%`,
    top: `${(-y0 / bh) * 100}%`,
  };
  // the original box inside the padded crop, for the bracket corners
  const inner: CSSProperties = {
    left: `${((box[1] - x0) / bw) * 100}%`,
    top: `${((box[0] - y0) / bh) * 100}%`,
    width: `${((box[3] - box[1]) / bw) * 100}%`,
    height: `${((box[2] - box[0]) / bh) * 100}%`,
    ["--tone" as string]: tone,
  };
  const body = (
    <motion.div className="crop-frame" style={frame} layoutId={layoutId}>
      <Img src={src} alt={alt} style={img} draggable={false} />
      <span className="brackets" style={inner} aria-hidden="true">
        <i />
        <i />
        <i />
        <i />
      </span>
    </motion.div>
  );
  return bare ? body : <div className="crop">{body}</div>;
}
