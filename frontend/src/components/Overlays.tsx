// The Scan (DESIGN §5.1) and the Ledger (DESIGN §5.2), played over the board when a photo_read
// or registry_lookup event arrives. Each closes the moment its first evidence card lands, so the
// crop (or the matched row) visibly becomes that card. Instant speed skips them; reduced motion
// shows them as a short fade with everything already in place.

import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { AnimatePresence, motion } from "motion/react";
import { assetUrl } from "../lib/api";
import type { Box, PhotoItem, PramanEvent } from "../lib/events";
import type { CaseState, LedgerMoment, ScanMoment } from "../lib/reducer";
import { ledgerDate, scanPhotoIndex } from "../lib/view";
import { useApp } from "../AppContext";
import { PhotoCrop, cropLayoutId, cropRegion } from "./PhotoCrop";
import { Img } from "./Img";

export function CaseOverlays({ state, upcoming }: { state: CaseState; upcoming: readonly PramanEvent[] }) {
  const { speed } = useApp();
  const after = (seq: number) => state.evidence.some((e) => (state.evidenceSeq[e.id] ?? 0) > seq);
  const scan = state.scan && !after(state.scan.seq) ? state.scan : null;
  const ledger = state.ledger && !after(state.ledger.seq) ? state.ledger : null;
  if (speed === "instant") return null;
  return (
    <AnimatePresence>
      {scan && <Scan key={`scan-${scan.seq}`} moment={scan} state={state} upcoming={upcoming} />}
      {ledger && <Ledger key={`ledger-${ledger.seq}`} moment={ledger} />}
    </AnimatePresence>
  );
}

// ---------------------------------------------------------------------------
// The Scan

const KIND_RANK: Record<PhotoItem["kind"], number> = { code: 0, certificate: 1, composition: 2, label: 3, claim: 4, other: 5 };
const MAX_ITEMS = 7;

/** The region of the photo holding the print, padded, with a readable aspect (0.75–1.9). */
export function regionOfInterest(boxes: readonly Box[], aspect: number): Box {
  if (boxes.length === 0) return [0, 0, 1000, 1000];
  let y0 = Math.min(...boxes.map((b) => b[0])) - 60;
  let x0 = Math.min(...boxes.map((b) => b[1])) - 60;
  let y1 = Math.max(...boxes.map((b) => b[2])) + 60;
  let x1 = Math.max(...boxes.map((b) => b[3])) + 60;
  const grow = (lo: number, hi: number, size: number): [number, number] => {
    const extra = size - (hi - lo);
    if (extra <= 0) return [lo, hi];
    let a = lo - extra / 2;
    let b = hi + extra / 2;
    if (a < 0) [a, b] = [0, b - a];
    if (b > 1000) [a, b] = [Math.max(0, a - (b - 1000)), 1000];
    return [a, b];
  };
  [y0, y1] = grow(Math.max(0, y0), Math.min(1000, y1), 260);
  [x0, x1] = grow(Math.max(0, x0), Math.min(1000, x1), 260);
  const ratio = ((x1 - x0) * aspect) / (y1 - y0);
  if (ratio > 1.9) [y0, y1] = grow(y0, y1, ((x1 - x0) * aspect) / 1.9);
  if (ratio < 0.75) [x0, x1] = grow(x0, x1, ((y1 - y0) * 0.75) / aspect);
  return [y0, x0, y1, x1];
}
const CHARS_PER_S = 40;

/** A QR code the core found on the photo (sent as a "code" item, text "QR code: <domain>"). */
function isQrItem(it: PhotoItem): boolean {
  return it.kind === "code" && /^QR code\b/.test(it.text);
}

function Scan({ moment, state, upcoming }: { moment: ScanMoment; state: CaseState; upcoming: readonly PramanEvent[] }) {
  const { reducedMotion, timeScale } = useApp();
  const t = timeScale;

  // Which boxes become evidence: look ahead at the evidence events still queued.
  const leads = useMemo(() => {
    const out: { photo: number; box: Box }[] = [];
    for (const e of upcoming) {
      if (e.type === "evidence" && e.data.photo_index != null && e.data.crop_box) {
        out.push({ photo: e.data.photo_index, box: e.data.crop_box });
      }
      if (e.type === "step" && e.data.phase !== "act") break;
    }
    return out;
  }, [upcoming]);

  const index = scanPhotoIndex(moment.read.photos, leads[0]?.photo);
  const read = moment.read.photos.find((p) => p.index === index);
  const photo = state.listing?.photos.find((p) => p.index === index);
  const aspect = photo?.width && photo?.height ? photo.width / photo.height : 1;

  const items = useMemo(() => {
    const boxed = (read?.items ?? []).filter((it): it is PhotoItem & { box_2d: Box } => it.box_2d !== null);
    // QR codes on the pack (W4) are always shown and boxed; then the most proof-like print
    const qrs = boxed.filter(isQrItem);
    const rest = boxed.filter((it) => !isQrItem(it));
    const ranked = rest.sort((a, b) => KIND_RANK[a.kind] - KIND_RANK[b.kind] || a.box_2d[0] - b.box_2d[0]);
    const chosen = [...qrs, ...ranked].slice(0, MAX_ITEMS);
    return chosen.sort((a, b) => a.box_2d[0] - b.box_2d[0]);
  }, [read]);

  const leadBoxes: Box[] = leads.filter((l) => l.photo === index).map((l) => l.box);
  const qrBoxes: Box[] = items.filter(isQrItem).map((it) => it.box_2d);
  const bracketBoxes: Box[] = [
    ...(leadBoxes.length
      ? leadBoxes
      : items.filter((it) => it.kind === "code" || it.kind === "certificate" || it.kind === "composition").map((it) => it.box_2d)),
    ...qrBoxes.filter((q) => !leadBoxes.some((l) => l.join(",") === q.join(","))),
  ];
  const lift = leadBoxes[0];
  const roi = regionOfInterest([...items.map((it) => it.box_2d), ...bracketBoxes], aspect);
  const rw = roi[3] - roi[1];
  const rh = roi[2] - roi[0];
  const roiAspect = (rw * aspect) / rh;
  /** a box in photo units (0–1000) → percentages of the region shown */
  const place = (b: Box) => ({
    top: `${((b[0] - roi[0]) / rh) * 100}%`,
    left: `${((b[1] - roi[1]) / rw) * 100}%`,
    height: `${((b[2] - b[0]) / rh) * 100}%`,
    width: `${((b[3] - b[1]) / rw) * 100}%`,
  });
  const passAtBox = (b: Box) => passAt(((b[0] - roi[0]) / rh) * 1000);

  const IN = 0.32 * t;
  const SWEEP = 1.4 * t;
  const passAt = (y: number) => (reducedMotion ? 0 : IN + (SWEEP * y) / 1000);
  const others = moment.read.photos.filter((p) => p.index !== index).length;

  if (!read || !photo) return null;
  return (
    <motion.div
      className="overlay scan"
      role="status"
      aria-label={`Reading photo ${index}`}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: (reducedMotion ? 0.12 : 0.18) * t }}
    >
      <div className="scan-head label">
        Reading photo {index}
        {others > 0 ? ` · and ${others} more` : ""} · {items.length} printed items
      </div>
      <div className="scan-body">
        <motion.div
          className="scan-photo"
          style={{ aspectRatio: `${roiAspect}`, width: `min(100%, calc((100vh - 250px) * ${roiAspect.toFixed(3)}))` }}
          initial={reducedMotion ? false : { scale: 0.55, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: IN, ease: "easeOut" }}
        >
          <Img
            src={assetUrl(photo.url)}
            alt={`Photo ${index}`}
            draggable={false}
            style={{
              width: `${(1000 / rw) * 100}%`,
              height: `${(1000 / rh) * 100}%`,
              left: `${(-roi[1] / rw) * 100}%`,
              top: `${(-roi[0] / rh) * 100}%`,
            }}
          />
          {items.map((it, i) => (
            <motion.span
              key={i}
              className="scan-box"
              style={place(it.box_2d)}
              initial={reducedMotion ? false : { opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: passAtBox(it.box_2d), duration: 0.12 * t }}
            />
          ))}
          {!reducedMotion && (
            <motion.div
              className="scanline"
              initial={{ top: "0%" }}
              animate={{ top: "100%" }}
              transition={{ delay: IN, duration: SWEEP, ease: "linear" }}
            />
          )}
          {items.length === 0 && (
            <motion.div className="scan-glow" initial={{ opacity: 0 }} animate={{ opacity: [0, 1, 0.6] }} transition={{ delay: IN, duration: SWEEP }} />
          )}
          {bracketBoxes.map((b, i) => (
            <Brackets key={i} style={place(b)} delay={passAtBox([b[2], b[1], b[2], b[3]]) + 0.08 * t} reduced={reducedMotion} />
          ))}
          {lift && (
            <motion.div
              className="scan-lift"
              style={(({ top, left, width }) => ({ top, left, width }))(place(cropRegion(lift, aspect)))}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: reducedMotion ? 0 : passAtBox([lift[2], 0, lift[2], 0]) + 0.45 * t, duration: 0.01 }}
            >
              <PhotoCrop
                bare
                src={assetUrl(photo.url)}
                box={lift}
                width={photo.width}
                height={photo.height}
                alt=""
                layoutId={reducedMotion ? undefined : cropLayoutId(index ?? 0, lift)}
              />
            </motion.div>
          )}
        </motion.div>
        <ol className="scan-text mono" aria-label="Printed text read from the photo">
          {items.map((it, i) => (
            <li key={i} className={`k-${it.kind}`}>
              <span className="scan-kind">{it.kind.toUpperCase()}</span>
              <Typed text={clip(it.text)} delay={passAtBox(it.box_2d)} cps={CHARS_PER_S / Math.max(t, 0.01)} instant={reducedMotion} />
            </li>
          ))}
        </ol>
      </div>
    </motion.div>
  );
}

const clip = (s: string) => {
  const one = s.replace(/\s+/g, " ").trim();
  return one.length > 64 ? `${one.slice(0, 62)}…` : one;
};

/** Four corners fly in from the photo's edges and lock onto the box (spring 260/24). */
function Brackets({ style, delay, reduced }: { style: CSSProperties; delay: number; reduced: boolean }) {
  const corners = [
    { cls: "tl", from: { x: -60, y: -60 } },
    { cls: "tr", from: { x: 60, y: -60 } },
    { cls: "bl", from: { x: -60, y: 60 } },
    { cls: "br", from: { x: 60, y: 60 } },
  ];
  return (
    <span className="scan-brackets" style={style} aria-hidden="true">
      {corners.map((c) => (
        <motion.i
          key={c.cls}
          className={c.cls}
          initial={reduced ? false : { ...c.from, opacity: 0 }}
          animate={{ x: 0, y: 0, opacity: 1 }}
          transition={{ delay, type: "spring", stiffness: 260, damping: 24 }}
        />
      ))}
      {!reduced && (
        <motion.b
          className="lock-flash"
          initial={{ opacity: 0 }}
          animate={{ opacity: [0, 0.9, 0] }}
          transition={{ delay: delay + 0.42, duration: 0.05 }}
        />
      )}
    </span>
  );
}

/** Text typed out at a steady rate once the scan line reaches it. */
function Typed({ text, delay, cps, instant }: { text: string; delay: number; cps: number; instant: boolean }) {
  const [n, setN] = useState(instant ? text.length : 0);
  useEffect(() => {
    if (instant) {
      setN(text.length);
      return;
    }
    let raf = 0;
    const start = performance.now() + delay * 1000;
    const tick = (now: number) => {
      const k = Math.max(0, Math.min(text.length, Math.floor(((now - start) / 1000) * cps)));
      setN(k);
      if (k < text.length) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [text, delay, cps, instant]);
  return (
    <span className="typed">
      <span>{text.slice(0, n)}</span>
      <span className="sr-only">{text}</span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// The Ledger

const LEDGER_ROW_H = 30;

function Ledger({ moment }: { moment: LedgerMoment }) {
  const { reducedMotion, timeScale } = useApp();
  const t = timeScale;
  const { lookup } = moment;
  const match = lookup.match;
  // Rows the lookup ran past. We don't have the list itself, so they are shown redacted;
  // the count is the real `rows_scanned`.
  const filler = Math.max(0, Math.min(36, lookup.rows_scanned - (match ? 1 : 0)));
  const rows = filler + (match ? 1 : 0);
  const visible = 6;
  const travel = Math.max(0, rows - visible + (match ? 2 : 0)) * LEDGER_ROW_H;
  const SCROLL = 0.9 * t;

  return (
    <motion.div
      className="overlay ledger-panel"
      role="status"
      aria-label={match ? `CPCB list: ${match.name} found` : `CPCB list: no match for ${lookup.query}`}
      initial={reducedMotion ? { opacity: 0 } : { x: 40, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: (reducedMotion ? 0.12 : 0.2) * t, ease: "easeOut" }}
    >
      <div className="ledger-head mono">
        CPCB CERTIFIED LIST · {ledgerDate(lookup.list_date)} · {lookup.rows_scanned} {lookup.rows_scanned === 1 ? "ROW" : "ROWS"}
      </div>
      <div className="ledger-query mono">Looking up {lookup.query}</div>
      <div className="ledger-window" style={{ height: Math.min(rows, visible) * LEDGER_ROW_H + 8 }}>
        <motion.div
          className="ledger-rows"
          initial={reducedMotion ? false : { y: 0 }}
          animate={{ y: -travel }}
          transition={{ duration: SCROLL, ease: [0.16, 1, 0.3, 1], delay: 0.15 * t }}
        >
          {Array.from({ length: filler }, (_, i) => (
            <div key={i} className="lrow redacted" aria-hidden="true">
              <span />
              <i style={{ width: `${45 + ((i * 37) % 40)}%` }} />
            </div>
          ))}
          {match && (
            <motion.div className="lrow hit row" layoutId={reducedMotion ? undefined : `reg:${moment.lookup.seq}`}>
              <motion.b
                className="sweep"
                initial={reducedMotion ? false : { scaleX: 0 }}
                animate={{ scaleX: 1 }}
                transition={{ delay: (reducedMotion ? 0 : 0.15 * t) + SCROLL, duration: 0.3 * t, ease: "easeOut" }}
              />
              <span>S.No. {match.s_no}</span>
              <span>
                {match.name}
                <small>{[match.state, match.table === 2 ? "not certified" : "certified"].filter(Boolean).join(" · ")}</small>
              </span>
              <motion.span
                className="score"
                initial={reducedMotion ? false : { opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.15 * t + SCROLL + 0.2 * t }}
              >
                {lookup.score.toFixed(2)}
              </motion.span>
            </motion.div>
          )}
        </motion.div>
      </div>
      {!match && (
        <motion.p className="ledger-miss" initial={reducedMotion ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: SCROLL }}>
          No match for {lookup.query}
        </motion.p>
      )}
      {match && <div className="ledger-foot mono">NAME MATCH {lookup.score.toFixed(2)}</div>}
    </motion.div>
  );
}
