// The Exhibit (DESIGN §4.2, left column): the product page as evidence. Title, masked store,
// photo well with READ ticks, and the description with every claim highlighted in place.

import { Fragment } from "react";
import { Check } from "lucide-react";
import type { Claim } from "../lib/events";
import { assetUrl } from "../lib/api";
import { photosRead, type CaseState } from "../lib/reducer";
import { findRanges, photoOfClaim, segments, VERDICT_KEY } from "../lib/view";
import { useCaseUi } from "./caseUi";
import { Img } from "./Img";

export function Exhibit({ state }: { state: CaseState }) {
  const { listing } = state;
  const ui = useCaseUi();
  const read = photosRead(state);
  const scanned = state.photoReads[0] ? lastReadPhoto(state) : null;
  const shown = ui.photo ?? scanned ?? listing?.photos[0]?.index ?? null;
  const shownPhoto = listing?.photos.find((p) => p.index === shown) ?? null;

  const claims = state.claims.filter((c) => !c.derived_from && c.location !== "n/a");
  const textClaims = claims.filter((c) => photoOfClaim(c) === null && c.location !== "tag");
  const titleRanges = listing ? findRanges(listing.title, textClaims) : [];
  const placedInTitle = new Set(titleRanges.map((r) => r.claimId));
  const bodyRanges = listing ? findRanges(listing.body_text, textClaims.filter((c) => !placedInTitle.has(c.id))) : [];
  const placed = new Set([...placedInTitle, ...bodyRanges.map((r) => r.claimId)]);
  const photoClaims = groupByPhoto(claims.filter((c) => photoOfClaim(c) !== null));
  const elsewhere = claims.filter((c) => photoOfClaim(c) === null && !placed.has(c.id));

  if (!listing) {
    return (
      <aside className="col exhibit" aria-label="Exhibit">
        <span className="label">Exhibit · product page</span>
        <div className="skeleton" aria-hidden="true">
          <i style={{ width: "80%" }} />
          <i style={{ width: "55%" }} />
          <i style={{ width: "92%" }} />
          <i style={{ width: "70%" }} />
        </div>
        <p className="muted">Opening the product page…</p>
      </aside>
    );
  }

  // A photo the agent has read is asked for again: before that the server sends a blurred copy,
  // because the brand printed on the pack isn't known yet.
  const photoSrc = (p: { url: string; index: number }): string =>
    assetUrl(p.url) + (read.has(p.index) && p.url.startsWith("/api/") ? "?read=1" : "");

  return (
    <aside className="col exhibit" aria-label="Exhibit: product page">
      <span className="label">Exhibit · product page</span>
      <h1 className="ex-title">
        <Highlighted text={listing.title} ranges={titleRanges} state={state} />
      </h1>
      {listing.store && <div className="store">{listing.store}</div>}

      {shownPhoto && (
        <figure className="well">
          <Img
            src={photoSrc(shownPhoto)}
            alt={`Product photo ${shownPhoto.index}${read.has(shownPhoto.index) ? ", read by the agent" : ""}`}
          />
          <figcaption className="well-cap mono">
            PHOTO {shownPhoto.index} / {listing.photos.length}
            {read.has(shownPhoto.index) && <span className="read-tag">READ</span>}
          </figcaption>
        </figure>
      )}
      {listing.photos.length > 1 && (
        <div className="thumbs" role="group" aria-label="Photos">
          {listing.photos.map((p) => (
            <button
              key={p.index}
              type="button"
              className={`thumb${p.index === shown ? " on" : ""}${read.has(p.index) ? " read" : ""}`}
              onClick={() => ui.setPhoto(p.index)}
              aria-label={`Show photo ${p.index}${read.has(p.index) ? " (read)" : ""}`}
              aria-pressed={p.index === shown}
            >
              <Img src={photoSrc(p)} alt="" loading="lazy" />
              {read.has(p.index) && (
                <span className="tick" aria-hidden="true">
                  <Check size={14} strokeWidth={2.5} />
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      <div className="desc">
        <span className="label">Description</span>
        {paragraphs(listing.body_text, bodyRanges).map((para, i) => (
          <p key={i}>
            <Highlighted text={listing.body_text} ranges={para.ranges} state={state} from={para.start} to={para.end} />
          </p>
        ))}
      </div>

      {photoClaims.map(([photo, cs]) => (
        <div className="boxtext" key={photo}>
          <button type="button" className="label linkish" onClick={() => ui.setPhoto(photo)}>
            On the pack · photo {photo}
          </button>
          <p>
            {cs.map((c, i) => (
              <Fragment key={c.id}>
                {i > 0 && <span className="sep"> · </span>}“<Mark claim={c} state={state} text={c.quote.trim()} />”
              </Fragment>
            ))}
          </p>
        </div>
      ))}
      {elsewhere.length > 0 && (
        <div className="boxtext">
          <span className="label">Elsewhere on the page</span>
          <p>
            {elsewhere.map((c, i) => (
              <Fragment key={c.id}>
                {i > 0 && <span className="sep"> · </span>}
                <span className="loc mono">{c.location.toUpperCase()}</span> “<Mark claim={c} state={state} text={c.quote.trim()} />”
              </Fragment>
            ))}
          </p>
        </div>
      )}
    </aside>
  );
}

function lastReadPhoto(state: CaseState): number | null {
  // The photo whose print turned into evidence, else the first one read.
  const fromEvidence = [...state.evidence].reverse().find((e) => e.photo_index != null)?.photo_index;
  if (fromEvidence != null) return fromEvidence;
  return state.photoReads.at(-1)?.photos[0]?.index ?? null;
}

function groupByPhoto(claims: Claim[]): [number, Claim[]][] {
  const m = new Map<number, Claim[]>();
  for (const c of claims) {
    const n = photoOfClaim(c);
    if (n === null) continue;
    m.set(n, [...(m.get(n) ?? []), c]);
  }
  return [...m.entries()].sort((a, b) => a[0] - b[0]);
}

interface Para {
  start: number;
  end: number;
  ranges: ReturnType<typeof findRanges>;
}

/** Split on blank lines; keep each paragraph's slice of the ranges (a range never spans two). */
function paragraphs(text: string, ranges: ReturnType<typeof findRanges>): Para[] {
  const out: Para[] = [];
  const re = /\n\s*\n/g;
  let at = 0;
  let m: RegExpExecArray | null;
  const push = (start: number, end: number) => {
    if (text.slice(start, end).trim()) {
      out.push({ start, end, ranges: ranges.filter((r) => r.start >= start && r.end <= end) });
    }
  };
  while ((m = re.exec(text))) {
    push(at, m.index);
    at = m.index + m[0].length;
  }
  push(at, text.length);
  return out;
}

function Highlighted({
  text,
  ranges,
  state,
  from = 0,
  to = text.length,
}: {
  text: string;
  ranges: ReturnType<typeof findRanges>;
  state: CaseState;
  from?: number;
  to?: number;
}) {
  const slice = text.slice(from, to);
  const local = ranges.map((r) => ({ ...r, start: r.start - from, end: r.end - from }));
  const claims = new Map(state.claims.map((c) => [c.id, c] as const));
  return (
    <>
      {segments(slice, local).map((seg, i) => {
        const c = seg.claimId ? claims.get(seg.claimId) : undefined;
        if (!c) return <Lines key={i} text={seg.text} />;
        // Trailing spaces and line breaks stay outside the highlight, so the claim ID sits
        // right after the last highlighted word
        const core = seg.text.replace(/\s+$/, "");
        const trail = seg.text.slice(core.length);
        return (
          <Fragment key={i}>
            <Mark claim={c} state={state} text={core} />
            {trail && <Lines text={trail} />}
          </Fragment>
        );
      })}
    </>
  );
}

function Lines({ text }: { text: string }) {
  const parts = text.split("\n");
  return (
    <>
      {parts.map((p, i) => (
        <Fragment key={i}>
          {i > 0 && <br />}
          {p}
        </Fragment>
      ))}
    </>
  );
}

/** A highlighted claim with its ID as a superscript glued to the last word (never wraps alone). */
function Mark({ claim, state, text }: { claim: Claim; state: CaseState; text: string }) {
  const ui = useCaseUi();
  const v = state.verdicts[claim.id];
  const key = v ? VERDICT_KEY[v.label] : "pending";
  const lit = ui.focus?.kind === "claim" && ui.focus.id === claim.id;
  const head = text.replace(/\S+$/, "");
  const tail = text.slice(head.length);
  return (
    <mark
      className={`hl hl-${key}${lit ? " lit" : ""}`}
      onMouseEnter={() => ui.setFocus({ kind: "claim", id: claim.id })}
      onMouseLeave={() => ui.setFocus(null)}
      title={v ? `${claim.id}: ${v.label}` : `${claim.id}: not decided yet`}
    >
      {head && <Lines text={head} />}
      <span className="hl-tail">
        {tail}
        <sup>{claim.id}</sup>
      </span>
    </mark>
  );
}
