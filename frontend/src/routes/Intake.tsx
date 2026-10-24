// Intake (DESIGN §4.1): the hero, the URL box and four case folders. The URL box works in every
// mode: live checks go to the server; without one, a demo listing's URL opens its recorded case.

import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { ArrowRight } from "lucide-react";
import { useApp, useOpenCase, type DemoCase } from "../AppContext";
import { ApiError, canCheckNewPages, fileCaseId, getAccessCode, loadRecording, loadUrlKeys, setAccessCode, startRun } from "../lib/api";
import { matchDemoUrl, parseProductUrl } from "../lib/urls";
import type { VerdictLabel } from "../lib/events";
import { reduceAll } from "../lib/reducer";
import { TopBar } from "../components/TopBar";
import { FooterLine } from "../components/Seal";
import { Teaser, type TeaserItem } from "../components/Teaser";
import { Img } from "../components/Img";
import { AccessCode } from "../components/AccessCode";

const PRIORITY: VerdictLabel[] = ["Backed", "Contradicted", "Partly backed", "Needs review", "Not backed", "Not a claim"];

export function IntakeRoute() {
  const { backend, demoCases, present, notice, setNotice } = useApp();
  const openCase = useOpenCase();
  const navigate = useNavigate();
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [teaser, setTeaser] = useState<TeaserItem[]>([]);
  // The answer to the last submit: one plain line, plus case files to open when that helps.
  const [urlMsg, setUrlMsg] = useState<{ text: string; cases: string[] } | null>(null);
  // The access code box stays hidden until a check needs it (or someone asks for it)
  const [askCode, setAskCode] = useState(false);
  // bumped when a code is refused, so the box starts empty again
  const [codeTry, setCodeTry] = useState(0);

  const live = canCheckNewPages(backend);
  const needsCode = backend?.kind === "live" && backend.health.needs_access_code === true;
  const urlNote = !backend
    ? "Checking for the Praman server…"
    : backend.kind === "recording"
      ? "No Praman server here: a demo listing's URL opens its recorded case; other pages need the server."
      : live
        ? null
        : `The server is in ${backend.health.llm_mode} mode: a demo listing's URL opens its case; new pages need live mode.`;
  const allCases = demoCases.map((c) => c.listingId);

  // The teaser: one decided claim per demo case, from the bundled recordings (real results).
  useEffect(() => {
    let alive = true;
    Promise.all(
      demoCases.map((c) =>
        loadRecording(c.listingId, "agent")
          .then((rec) => {
            const s = reduceAll(rec.events);
            for (const label of PRIORITY) {
              const claim = s.claims.find((cl) => s.verdicts[cl.id]?.label === label);
              if (claim) return { listingId: c.listingId, quote: claim.quote, label };
            }
            return null;
          })
          .catch(() => null),
      ),
    ).then((items) => alive && setTeaser(items.filter((x): x is TeaserItem => x !== null)));
    return () => {
      alive = false;
    };
  }, [demoCases]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy || !backend) return;
    const parsed = parseProductUrl(url);
    if (!parsed.ok) {
      setUrlMsg({ text: parsed.error, cases: [] });
      return;
    }
    setBusy(true);
    setUrlMsg(null);
    // Reading a new page means downloading its photos: say so, so the wait doesn't look like a freeze
    const slow = setTimeout(() => setUrlMsg({ text: "Fetching the page and its photos. This can take up to a minute.", cases: [] }), 4000);
    try {
      if (backend.kind === "recording") {
        const ids = await matchDemoUrl(parsed, await loadUrlKeys());
        const only = ids.length === 1 ? ids[0] : undefined;
        if (only) {
          navigate(`/case/${fileCaseId(only, "agent")}`);
        } else if (ids.length > 1) {
          setUrlMsg({ text: "That store has more than one case file. Pick one:", cases: ids });
        } else {
          setUrlMsg({
            text: "Live checks need the Praman server, which isn't running here. The case files play recorded checks:",
            cases: allCases,
          });
        }
        return;
      }
      const runId = await startRun({ url: parsed.url, mode: "agent" });
      navigate(`/case/${encodeURIComponent(runId)}`);
    } catch (err) {
      const text = err instanceof Error ? err.message : "Couldn't start the check.";
      if (err instanceof ApiError && err.status === 401) {
        const tried = getAccessCode() !== "";
        if (tried) {
          setAccessCode("");
          setCodeTry((n) => n + 1);
        }
        setAskCode(true);
        setUrlMsg({
          text: tried
            ? "That access code didn't work. Check it (it changes each time the server restarts), enter it above and press Run again."
            : "This page isn't one of the case files, so checking it live needs the access code. Enter it above and press Run again.",
          cases: [],
        });
        return;
      }
      setUrlMsg({ text, cases: err instanceof ApiError && err.status === 409 ? allCases : [] });
    } finally {
      clearTimeout(slow);
      setBusy(false);
    }
  };

  return (
    <div className="screen intake-screen">
      <TopBar
        quiet
        crumb={<b>CASES</b>}
        actions={
          <>
            <Link className="btn" to="/scan">
              Store scan
            </Link>
            <Link className="btn" to="/eval">
              Evaluation
            </Link>
            <Link className="btn" to="/impact">
              Impact
            </Link>
            <Link className="btn" to="/rules">
              Rule packs
            </Link>
          </>
        }
      />
      <main className="intake">
        <section className="intake-main">
          <h1 className="hero">Every green claim needs proof.</h1>
          <p className="lede">
            Praman reads the product page, the pack photos and the government registry, and shows what's proven, what isn't, and what
            conflicts.
          </p>

          {notice && backend?.kind === "live" && (
            <div className="notice" role="status">
              {notice}
              <button type="button" className="linkish" onClick={() => setNotice(null)} aria-label="Dismiss">
                Dismiss
              </button>
            </div>
          )}

          {!present && (
            <form className="url-form" onSubmit={submit}>
              <label htmlFor="url" className="label">
                Paste a product page URL
              </label>
              <div className="url-row">
                <input
                  id="url"
                  type="text"
                  inputMode="url"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="https://store.example/products/…"
                  value={url}
                  onChange={(e) => {
                    setUrl(e.target.value);
                    if (urlMsg) setUrlMsg(null);
                  }}
                  aria-describedby={urlMsg ? "url-msg" : urlNote ? "url-note" : undefined}
                />
                <button type="submit" className="btn solid" disabled={busy || !backend}>
                  {busy ? "Starting…" : "Run"} <ArrowRight size={16} strokeWidth={1.5} aria-hidden="true" />
                </button>
              </div>
              {needsCode && live && askCode && <AccessCode key={codeTry} id="access-code" autoFocus />}
              {urlMsg ? (
                <div id="url-msg" className="url-msg" role="status">
                  <p>{urlMsg.text}</p>
                  {urlMsg.cases.length > 0 && (
                    <div className="row-gap">
                      {urlMsg.cases.map((id) => (
                        <button key={id} type="button" className="btn" onClick={() => void openCase(id)}>
                          Open case {id}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                urlNote && (
                  <p id="url-note" className="note">
                    {urlNote}
                  </p>
                )
              )}
              <p className="note scan-link">
                <Link to="/scan">Or scan a whole store</Link>: its product pages ranked by how much their green claims need checking.
                {needsCode && live && !askCode && (
                  <>
                    {" "}
                    <button type="button" className="linkish" onClick={() => setAskCode(true)}>
                      Have an access code?
                    </button>
                  </>
                )}
              </p>
            </form>
          )}

          <h2 className="label folders-title">Or open a case file</h2>
          <div className="folders">
            {demoCases.length === 0 &&
              [0, 1, 2, 3].map((i) => (
                <div key={i} className="folder skeleton-folder" aria-hidden="true">
                  <span className="tab" />
                </div>
              ))}
            {demoCases.map((c, i) => (
              <Folder key={c.listingId} c={c} n={i + 1} onOpen={() => openCase(c.listingId)} />
            ))}
          </div>
        </section>
        <aside className="intake-side" aria-label="What a check looks like">
          <Teaser items={teaser} />
        </aside>
      </main>
      <footer className="foot">
        <FooterLine />
        <span className="keys">
          <kbd>1</kbd>–<kbd>4</kbd> open a case · <kbd>P</kbd> present · <kbd>?</kbd> keys
        </span>
      </footer>
    </div>
  );
}

function Folder({ c, n, onOpen }: { c: DemoCase; n: number; onOpen: () => void }) {
  return (
    <button type="button" className="folder" onClick={onOpen} aria-label={`Open case ${c.listingId}: ${c.title} (key ${n})`}>
      <span className="tab mono">CASE {c.listingId}</span>
      <span className="folder-body">
        <Img src={c.thumb} alt="" loading="lazy" />
        <span className="folder-text">
          <span className="folder-title">{c.title}</span>
          <span className="folder-meta mono">
            {c.claimCount != null ? `${c.claimCount} ${c.claimCount === 1 ? "CLAIM" : "CLAIMS"}` : "CASE FILE"}
            <kbd>{n}</kbd>
          </span>
        </span>
      </span>
    </button>
  );
}
