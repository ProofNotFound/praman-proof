// The Stamp (DESIGN §5.4): a double-bordered, ink-textured verdict mark that lands with a slight
// overshoot. "Not a claim" is outline-only. Readable as text for screen readers.

import { motion } from "motion/react";
import type { VerdictLabel } from "../lib/events";
import { VERDICT_KEY } from "../lib/view";
import { useApp } from "../AppContext";

export function Stamp({
  label,
  animate = false,
  size = "md",
  className = "",
  ownPace = false,
}: {
  label: VerdictLabel;
  animate?: boolean;
  size?: "sm" | "md" | "lg";
  className?: string;
  /** animate at normal speed whatever the case player's speed (the home-page teaser) */
  ownPace?: boolean;
}) {
  const app = useApp();
  const motionOK = ownPace ? !app.reducedMotion : app.motionOK;
  const timeScale = ownPace ? 1 : app.timeScale;
  const key = VERDICT_KEY[label];
  const cls = `stamp stamp-${size} v-${key}${key === "none" ? " outline" : ""} ${className}`;
  if (!animate || !motionOK) {
    return (
      <span className={cls} role="img" aria-label={`Verdict: ${label}`}>
        {label.toUpperCase()}
      </span>
    );
  }
  return (
    <motion.span
      className={cls}
      role="img"
      aria-label={`Verdict: ${label}`}
      initial={{ opacity: 0, scale: 1.6, rotate: -8 }}
      animate={{ opacity: 0.94, scale: 1, rotate: -3 }}
      transition={{ duration: 0.26 * timeScale, ease: [0.2, 0.9, 0.3, 1.2] }}
    >
      {label.toUpperCase()}
    </motion.span>
  );
}
