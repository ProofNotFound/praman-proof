// Evidence cards (DESIGN §4.2): text quote, photo crop, registry row, conflict, certificate scope.

import { forwardRef, type CSSProperties } from "react";
import { motion } from "motion/react";
import { assetUrl } from "../lib/api";
import type { CaseState } from "../lib/reducer";
import { COVER_VAR, ledgerDate, type EvidenceCardModel } from "../lib/view";
import { PhotoCrop, cropLayoutId } from "./PhotoCrop";
import { useApp } from "../AppContext";

const KIND_LABEL: Record<string, string> = {
  code: "CODE",
  certificate: "MARK",
  composition: "COMPOSITION",
  label: "LABEL",
  claim: "PRINT",
  other: "PRINT",
};

const SOURCE_LABEL: Record<string, string> = {
  link: "Linked page",
  web: "Material check · web search",
};

export function idsLabel(ids: readonly string[]): string {
  if (ids.length <= 2) return ids.join(" · ");
  return `${ids[0]} +${ids.length - 1}`;
}

interface Props {
  card: EvidenceCardModel;
  state: CaseState;
  fresh: boolean;
  dim: boolean;
  lit: boolean;
  onFocus: (on: boolean) => void;
  compact?: boolean;
}

export const EvidenceCard = forwardRef<HTMLElement, Props>(function EvidenceCard(
  { card, state, fresh, dim, lit, onFocus, compact = false },
  ref,
) {
  const { motionOK, timeScale } = useApp();
  const style = { ["--cov" as string]: COVER_VAR[card.covers] } as CSSProperties;
  const cls = `card ev cov-${card.covers} ev-${card.kind}${dim ? " dim" : ""}${lit ? " lit" : ""}${compact ? " compact" : ""}`;
  const animate = fresh && motionOK;
  return (
    <motion.article
      ref={ref}
      className={cls}
      style={style}
      data-card={card.key}
      tabIndex={0}
      aria-label={`Evidence ${card.ids.join(", ")}: ${ariaText(card)}`}
      onMouseEnter={() => onFocus(true)}
      onMouseLeave={() => onFocus(false)}
      onFocus={() => onFocus(true)}
      onBlur={() => onFocus(false)}
      initial={animate ? { opacity: 0, y: 8 } : false}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22 * timeScale, ease: "easeOut" }}
    >
      <span className="label ev-label">{header(card)}</span>
      <Body card={card} state={state} compact={compact} lift={animate} />
      {!compact && card.first.note && <p className="ev-note">{card.first.note}</p>}
    </motion.article>
  );
});

function header(card: EvidenceCardModel): string {
  const ids = idsLabel(card.ids);
  switch (card.kind) {
    case "photo":
      return `${ids} · Photo ${card.photoIndex ?? "?"} · ${KIND_LABEL[card.itemKind ?? "other"]}`;
    case "certificate":
      return `${ids} · Certificate scope`;
    case "registry":
      return `${ids} · CPCB list · ${card.registry ? ledgerDate(card.registry.list_date) : "26 OCT 2023"}`;
    case "qr":
      return `${ids} · QR code · Photo ${card.photoIndex ?? "?"}`;
    case "conflict":
      return `${ids} · Conflict check`;
    default:
      return `${ids} · ${SOURCE_LABEL[card.first.source] ?? "Page text"}`;
  }
}

function ariaText(card: EvidenceCardModel): string {
  switch (card.kind) {
    case "conflict":
      return `“${card.conflict?.a}” conflicts with “${card.conflict?.b}”`;
    default:
      return card.first.detail;
  }
}

function Body({ card, state, compact, lift }: { card: EvidenceCardModel; state: CaseState; compact: boolean; lift: boolean }) {
  const photo = card.photoIndex != null ? state.listing?.photos.find((p) => p.index === card.photoIndex) : undefined;
  const layoutId = lift && card.photoIndex != null && card.box ? cropLayoutId(card.photoIndex, card.box) : undefined;
  switch (card.kind) {
    case "photo":
      return (
        <>
          {photo && card.box && !compact && (
            <PhotoCrop
              src={assetUrl(photo.url)}
              box={card.box}
              width={photo.width}
              height={photo.height}
              tone={COVER_VAR[card.covers]}
              alt={`Crop of photo ${card.photoIndex}`}
              maxHeight={150}
              layoutId={layoutId}
            />
          )}
          <div className="code">{card.printed}</div>
        </>
      );
    case "certificate": {
      const claim = state.claims.find((c) => c.id === card.links[0]?.claimId);
      return (
        <>
          <div className="cert">
            {photo && card.box && !compact && (
              <PhotoCrop
                src={assetUrl(photo.url)}
                box={card.box}
                width={photo.width}
                height={photo.height}
                tone={COVER_VAR[card.covers]}
                alt={`Crop of photo ${card.photoIndex}`}
                maxHeight={110}
                layoutId={layoutId}
              />
            )}
            <div className="cert-name">{card.first.certifier ?? card.printed}</div>
          </div>
          <dl className="scope mono">
            <dt>Covers</dt>
            <dd className="scope-has">{card.first.cert_scope}</dd>
            <dt>Claim needs</dt>
            <dd>{claim?.scope === "part" ? "part" : "product"}</dd>
          </dl>
        </>
      );
    }
    case "qr": {
      const q = card.qr;
      return (
        <>
          {photo && card.box && !compact && (
            <PhotoCrop
              src={assetUrl(photo.url)}
              box={card.box}
              width={photo.width}
              height={photo.height}
              tone={COVER_VAR[card.covers]}
              alt={`QR code on photo ${card.photoIndex}`}
              maxHeight={110}
              layoutId={layoutId}
            />
          )}
          <div className="code">
            → {q?.domain}
            {q?.path ?? ""}
          </div>
          <span className={`qr-status mono${q?.followed ? " opened" : ""}`}>
            {q?.followed ? "Opened · the store's own site" : "Not followed · another site"}
          </span>
        </>
      );
    }
    case "registry": {
      const r = card.registry;
      const m = r?.match;
      return (
        <div className="ledger">
          {m ? (
            <motion.div className="row hit" layoutId={lift && r ? `reg:${r.seq}` : undefined}>
              <span>S.No. {m.s_no}</span>
              <span>
                {m.name}
                <small>
                  {[m.state, m.table === 2 ? "not certified" : m.table === 1 ? "certified" : m.type].filter(Boolean).join(" · ")}
                </small>
              </span>
              <span title="name match">{r.score.toFixed(2)}</span>
            </motion.div>
          ) : (
            <div className="row miss">
              <span>—</span>
              <span>{card.first.detail}</span>
              <span />
            </div>
          )}
          {r && <div className="ledger-q mono">for {r.query}</div>}
        </div>
      );
    }
    case "conflict": {
      const c = card.conflict;
      if (!c) return <p className="ev-quote">{card.first.detail}</p>;
      const rule = card.ruleId ? state.rules[card.ruleId] : undefined;
      return (
        <>
          <div className="vs">
            <div className="side">
              <q>{c.a}</q>
              <small>{c.aTag}</small>
            </div>
            <span className="ne" aria-label="conflicts with">
              ≠
            </span>
            <div className="side">
              <q>{c.b}</q>
              <small>{c.bTag}</small>
            </div>
          </div>
          {rule && !compact && (
            <div className="vs-rule mono">
              {rule.id} · {rule.name}
            </div>
          )}
        </>
      );
    }
    default:
      return (
        <>
          <q className="ev-quote">{card.quote ?? card.first.detail}</q>
          <span className="loc-tag mono">{card.location ?? "PAGE"}</span>
        </>
      );
  }
}
