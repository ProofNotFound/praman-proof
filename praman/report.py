"""Report export (FR-11): Markdown and HTML with claims, verdicts, evidence, rules, rewrites,
the approver, the CPCB list date and the disclaimer (PRD §8). Anonymised when the mode is on."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from praman import anonymise, provenance, store
from praman.config import CPCB_LIST_DATE_TEXT
from praman.events import load_events
from praman.models import VerdictLabel
from praman.rules import get_rule, load_rules

ORDER = [v.value for v in VerdictLabel]
SOURCE_LABEL = {
    "text": "Page text",
    "photo": "Photo",
    "registry": "CPCB registry",
    "link": "Linked page",
    "consistency": "Consistency check",
    "web": "Material check (web search)",
}


def _date(iso: str | None) -> str:
    if not iso:
        return ""
    d = datetime.fromisoformat(iso)
    return d.strftime("%-d %b %Y")


def _datetime(iso: str | None) -> str:
    if not iso:
        return ""
    d = datetime.fromisoformat(iso)
    return d.strftime("%-d %b %Y, %H:%M UTC")


def disclaimer(listing_date: str) -> str:
    return (
        "Decision support, not legal advice. Based on what is visible on the listing on "
        f"{listing_date}. CPCB list dated {CPCB_LIST_DATE_TEXT}."
    )


def report_data(run_id: str) -> dict[str, Any] | None:
    run = store.get_run(run_id)
    if not run:
        return None
    listing = store.run_listing_model(run)
    claims = store.claims(run_id)
    evidence = store.evidence(run_id)
    verdicts = store.verdicts(run_id)
    history = store.reviews(run_id)
    latest = {r["claim_id"]: r for r in history}
    rules = load_rules()
    counts: dict[str, int] = {}
    for v in verdicts.values():
        label = latest[v.claim_id]["label"] if v.claim_id in latest else v.label.value
        counts[label] = counts.get(label, 0) + 1
    items = []
    for c in claims:
        v = verdicts.get(c.id)
        items.append(
            {
                "claim": c.model_dump(),
                "verdict": v.model_dump(mode="json") if v else None,
                "review": latest.get(c.id),
                "evidence": [e.model_dump() for e in evidence if v and e.id in v.evidence_ids],
                "rules": [
                    get_rule(r).chip() | {"citation_url": get_rule(r).citation_url}
                    for r in (v.rule_ids if v else c.rule_ids)
                    if r in rules
                ],
            }
        )
    data = {
        "run": store.public_run(run),
        "listing": {
            "id": listing.id if listing else run["listing_id"],
            "title": listing.title if listing else "",
            "store": listing.store if listing else None,
            "fetched_at": listing.fetched_at.isoformat() if listing else None,
        },
        "counts": {k: counts[k] for k in ORDER if k in counts},
        "quota_reached": _quota_reached(run_id),
        "items": items,
        "reviews": history,
        "steps": len(store.steps(run_id)),
        "disclaimer": disclaimer(
            _date(listing.fetched_at.isoformat()) if listing else _date(run["started_at"])
        ),
    }
    return {**anonymise.maybe_mask(data), "audit": store.audit(run_id)}


QUOTA_LINE = "Model quota reached: claims not yet checked are marked Needs review."


def _quota_reached(run_id: str) -> bool:
    fin = [e for e in load_events(run_id) if e["type"] == "run_finished"]
    return bool(fin and fin[-1]["data"].get("quota_reached"))


def final_label(it: dict[str, Any]) -> str:
    """The reviewer's verdict when there is one, else the agent's."""
    if it.get("review"):
        return it["review"]["label"]
    return it["verdict"]["label"] if it["verdict"] else "Undecided"


def review_line(r: dict[str, Any]) -> str:
    who = f"{r['reviewer']}, {_datetime(r['at'])}"
    if r["decision"] == "agree":
        return f"Reviewer agreed ({who})."
    return (
        f"Reviewer changed the verdict from {r['ai_label']} to {r['label']}: {r['reason']} ({who})."
    )


def decision_log(d: dict[str, Any]) -> list[str]:
    """The audit trail in time order: the agent's run, each reviewer decision, the approval."""
    run = d["run"]
    out = [
        f"{_datetime(run['started_at'])} · Agent · checked the page: {d.get('steps', 0)} steps, "
        f"{run['llm_calls']} model calls, ₹{(run['est_cost_inr'] or 0):.2f}"
    ]
    out += [
        f"{_datetime(r['at'])} · {r['reviewer']} · {r['claim_id']}: {review_line(r)}"
        for r in d.get("reviews", [])
    ]
    if run.get("approved_by"):
        out.append(f"{_datetime(run['approved_at'])} · {run['approved_by']} · approved the report")
    return out


def audit_lines(d: dict[str, Any]) -> list[str]:
    """What the run was checked with, and whether the record still matches its signature."""
    a = d.get("audit") or {}
    out = [provenance.line(a.get("provenance"))]
    n = a.get("reviews", 0)
    if n:
        state = (
            "each one linked to the one before, chain intact"
            if a.get("reviews_intact")
            else "chain broken or partly unrecorded: compare with an exported copy"
        )
        out.append(f"Review record: {n} {'decision' if n == 1 else 'decisions'}, {state}.")
    if a.get("fingerprint"):
        ok = a.get("fingerprint_matches")
        out.append(
            f"Report fingerprint (SHA-256): {a['fingerprint']}"
            + (" · matches the stored record." if ok else " · does NOT match the stored record.")
        )
    return out


def to_markdown(d: dict[str, Any]) -> str:
    run, lst = d["run"], d["listing"]
    lines = [
        f"# Proof report: case {lst['id']}",
        "",
        f"**Listing:** {lst['title']}" + (f" ({lst['store']})" if lst.get("store") else ""),
        f"**Checked:** {_datetime(run['started_at'])} · mode {run['mode']} · model answers "
        f"{run['llm_mode']}",
        "",
        "**Summary:** " + " · ".join(f"{k}: {n}" for k, n in d["counts"].items()),
        "",
    ]
    if d.get("quota_reached"):
        lines += [QUOTA_LINE, ""]
    for it in d["items"]:
        c, v = it["claim"], it["verdict"]
        label = final_label(it)
        lines += [
            f"## {c['id']} · {label}",
            "",
            f"> “{c['quote']}”",
            "",
            f"{c['type']} claim · scope: {c['scope']} · found in: {c['location']}",
            "",
        ]
        if v:
            lines.append(f"**Why:** {v['reason']}")
            if v.get("missing"):
                lines.append(f"\n**What would change it:** {v['missing']}")
            if v.get("sources_searched"):
                lines.append(f"\n**Searched:** {', '.join(v['sources_searched'])}")
            if it.get("review"):
                lines.append(f"\n**Human review:** {review_line(it['review'])}")
            lines.append("")
        if it["evidence"]:
            lines.append("**Evidence**")
            lines.append("")
            for e in it["evidence"]:
                src = SOURCE_LABEL.get(e["source"], e["source"])
                if e.get("photo_index"):
                    src += f" {e['photo_index']}"
                lines.append(f"- {e['id']} · {src} · {e['covers_claim']}: {e['detail']}")
                if e.get("note"):
                    lines.append(f"  - {e['note']}")
            lines.append("")
        if it["rules"]:
            lines.append("**Rules**")
            lines.append("")
            for r in it["rules"]:
                cite = f" ({r['citation_url']})" if r.get("citation_url") else ""
                lines.append(f"- {r['id']} {r['name']}. {r['source']}, {r['clause']}.{cite}")
            lines.append("")
        if v and v.get("rewrite"):
            lines += [f"**Suggested wording:** {v['rewrite']}", ""]
    lines += [
        "---",
        "",
        f"Reviewed and approved by **{run['approved_by']}** on {_datetime(run['approved_at'])}."
        if run.get("approved_by")
        else "Not approved yet.",
        "",
        f"Model calls: {run['llm_calls']} · tokens: {run['tokens_in']} in, {run['tokens_out']} "
        f"out · estimated cost: ₹{(run['est_cost_inr'] or 0):.2f}",
        "",
        "## Decision log",
        "",
        *[f"- {line}" for line in decision_log(d)],
        "",
        "## Audit",
        "",
        *[f"- {line}" for line in audit_lines(d)],
        "",
        f"*{d['disclaimer']}*",
        "",
    ]
    return "\n".join(lines)


STYLE = """
body{background:#F3EFE6;color:#1C1B17;font:16px/1.5 'IBM Plex Sans',system-ui,sans-serif;margin:0}
main{background:#FBF9F4;max-width:760px;margin:24px auto;padding:40px 48px;
box-shadow:0 1px 0 #D6CFBF,0 12px 24px -16px #1C1B1726}
h1{font:600 30px/1.2 Fraunces,Georgia,serif;margin:0 0 8px}
h2{font:600 20px/1.3 Fraunces,Georgia,serif;margin:32px 0 8px;border-top:1.5px solid #B9B09C;padding-top:16px}
.meta,.small{color:#4A473F;font-size:14px}.mono{font-family:'IBM Plex Mono',ui-monospace,monospace}
blockquote{font:italic 20px/1.4 Fraunces,Georgia,serif;margin:8px 0}
.stamp{display:inline-block;border:3px double currentColor;padding:2px 10px;font:600 14px 'IBM Plex Mono',monospace;
letter-spacing:.12em;text-transform:uppercase;transform:rotate(-3deg);margin-left:8px}
.Backed{color:#1F7A4D}.Partly{color:#A86A12}.Not{color:#5F5B51}.Contradicted{color:#B3261E}
.Needs{color:#2457A6}.None{color:#A39E92}
ul{padding-left:20px}li{margin:4px 0}.disclaimer{margin-top:32px;font-size:14px;color:#4A473F}
@page{size:A4;margin:16mm}@media print{body{background:#fff}main{box-shadow:none;margin:0}}
"""


def _stamp_class(label: str) -> str:
    return {"Not a claim": "None"}.get(label, label.split()[0])


def to_html(d: dict[str, Any]) -> str:
    e = html.escape
    run, lst = d["run"], d["listing"]
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        f"<title>Proof report · case {e(lst['id'])}</title><style>{STYLE}</style></head><body><main>",
        f"<h1>प्रमाण · Proof report</h1><p class='meta'>Case {e(lst['id'])} · {e(lst['title'])}"
        + (f" · {e(lst['store'])}" if lst.get("store") else "")
        + f"<br>Checked {e(_datetime(run['started_at']))} · mode {e(run['mode'])} · "
        f"model answers {e(run['llm_mode'])}</p>",
        "<p>"
        + " ".join(
            f"<span class='stamp {_stamp_class(k)}'>{e(k)} · {n}</span>"
            for k, n in d["counts"].items()
        )
        + "</p>",
    ]
    if d.get("quota_reached"):
        parts.append(f"<p class='small'>{e(QUOTA_LINE)}</p>")
    for it in d["items"]:
        c, v = it["claim"], it["verdict"]
        label = final_label(it)
        parts.append(
            f"<h2>{e(c['id'])} <span class='stamp {_stamp_class(label)}'>{e(label)}</span></h2>"
            f"<blockquote>“{e(c['quote'])}”</blockquote>"
            f"<p class='small mono'>{e(c['type'])} · scope {e(c['scope'])} · {e(c['location'])}</p>"
        )
        if v:
            parts.append(f"<p>{e(v['reason'])}</p>")
            if v.get("missing"):
                parts.append(f"<p class='small'>{e(v['missing'])}</p>")
        if it.get("review"):
            parts.append(f"<p><strong>Human review:</strong> {e(review_line(it['review']))}</p>")
        if it["evidence"]:
            parts.append("<ul>")
            for ev in it["evidence"]:
                src = SOURCE_LABEL.get(ev["source"], ev["source"])
                if ev.get("photo_index"):
                    src += f" {ev['photo_index']}"
                note = f"<br><span class='small'>{e(ev['note'])}</span>" if ev.get("note") else ""
                parts.append(
                    f"<li><span class='mono'>{e(ev['id'])} · {e(src)} · {e(ev['covers_claim'])}</span>"
                    f" {e(ev['detail'])}{note}</li>"
                )
            parts.append("</ul>")
        if it["rules"]:
            parts.append(
                "<p class='small'>"
                + "<br>".join(
                    f"<span class='mono'>{e(r['id'])}</span> {e(r['name'])}. {e(r['source'])}, "
                    f"{e(r['clause'])}."
                    for r in it["rules"]
                )
                + "</p>"
            )
        if v and v.get("rewrite"):
            parts.append(f"<p><strong>Suggested wording:</strong> {e(v['rewrite'])}</p>")
    approved = (
        f"Reviewed and approved by <strong>{e(run['approved_by'])}</strong> on "
        f"{e(_datetime(run['approved_at']))}."
        if run.get("approved_by")
        else "Not approved yet."
    )
    parts += [
        f"<h2>Approval</h2><p>{approved}</p>",
        f"<p class='small mono'>Model calls {run['llm_calls']} · tokens {run['tokens_in']} in, "
        f"{run['tokens_out']} out · estimated cost ₹{(run['est_cost_inr'] or 0):.2f}</p>",
        "<h2>Decision log</h2><ul class='small'>"
        + "".join(f"<li>{e(line)}</li>" for line in decision_log(d))
        + "</ul>",
        "<h2>Audit</h2><ul class='small mono'>"
        + "".join(f"<li>{e(line)}</li>" for line in audit_lines(d))
        + "</ul>",
        f"<p class='disclaimer'>{e(d['disclaimer'])}</p>",
        "</main></body></html>",
    ]
    return "".join(parts)
