"""Run inspector (FR-13.1): one self-contained HTML page per checked draft.

Each sentence is coloured by its worst verdict. Hovering (or tapping) a
sentence shows its claims, each claim's verdict and the checker's reason,
and the text of every passage it cites. Planted errors carry a tag with
their class and, on selection, the original wording beside the corrupted
one. No external files or network: the page opens anywhere.
"""

from __future__ import annotations

import html
from collections import defaultdict
from collections.abc import Mapping, Sequence

from tcv.schemas import Claim, Draft, Passage, SeededDraft, Verdict, VerdictKind

_SEVERITY = {  # worst first → colour class
    VerdictKind.CONTRADICTED: "bad", VerdictKind.COUNTEREXAMPLE_FOUND: "bad",
    VerdictKind.INTERNALLY_INCONSISTENT: "bad", VerdictKind.UNSUPPORTED: "bad", VerdictKind.MISATTRIBUTED: "bad",
    VerdictKind.PARTIALLY_SUPPORTED: "bad", VerdictKind.OVERCLAIM: "warn", VerdictKind.UNCERTAIN: "warn",
    VerdictKind.ERROR: "err", VerdictKind.INFERENCE_RETAINED: "info", VerdictKind.EXEMPT: "info",
    VerdictKind.SUPPORTED: "ok",
}
_RANK = ["bad", "warn", "err", "info", "ok"]

_CSS = """
:root{--bg:#fbfbf9;--fg:#1d1d1b;--muted:#6b6b66;--panel:#ffffff;--line:#e4e2dc;
--ok:#1f7a4d;--ok-bg:#e6f4ec;--bad:#b3261e;--bad-bg:#fbe7e5;--warn:#8a5a00;--warn-bg:#fdf1d8;
--info:#3d5a80;--info-bg:#e8eef6;--err:#5f5f5f;--err-bg:#ececec;--tag:#5b3fa8;--tag-bg:#eee8fb}
@media (prefers-color-scheme: dark){:root{--bg:#161615;--fg:#ecebe6;--muted:#a3a29b;--panel:#1f1f1d;--line:#34332f;
--ok:#7fd1a4;--ok-bg:#15301f;--bad:#f1948c;--bad-bg:#3a1a17;--warn:#f0c46a;--warn-bg:#352a12;
--info:#9db8dd;--info-bg:#1b2533;--err:#b8b8b8;--err-bg:#2a2a2a;--tag:#c3b1f2;--tag-bg:#2a2340}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}
header{padding:20px 16px 8px;max-width:1200px;margin:auto}h1{font-size:1.25rem;margin:0 0 4px}
.meta{color:var(--muted);font-size:.875rem}.legend{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;font-size:.8rem}
.legend span{padding:2px 8px;border-radius:999px}
main{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,420px);gap:24px;max-width:1200px;margin:auto;padding:8px 16px 40px}
@media (max-width:860px){main{grid-template-columns:1fr}#panel{position:static!important;max-height:none!important}}
h2{font-size:1.05rem;margin:22px 0 6px}
.s{cursor:pointer;border-radius:4px;padding:1px 2px;border-bottom:2px solid transparent}
.s:hover,.s.sel{outline:2px solid var(--fg);outline-offset:1px}
.ok{background:var(--ok-bg);border-color:var(--ok)}.bad{background:var(--bad-bg);border-color:var(--bad)}
.warn{background:var(--warn-bg);border-color:var(--warn)}.info{background:var(--info-bg);border-color:var(--info)}
.err{background:var(--err-bg);border-color:var(--err);border-style:dashed}.none{border-color:var(--line)}
.tag{font-size:.7rem;font-weight:600;color:var(--tag);background:var(--tag-bg);border-radius:4px;padding:0 4px;margin-left:3px;vertical-align:1px}
#panel{position:sticky;top:12px;align-self:start;max-height:calc(100vh - 24px);overflow:auto;background:var(--panel);
border:1px solid var(--line);border-radius:10px;padding:14px 16px;font-size:.9rem}
#panel .hint{color:var(--muted)}.claim{border-top:1px solid var(--line);padding:8px 0}
.k{font-weight:600;font-size:.8rem;padding:1px 6px;border-radius:4px}
.why{color:var(--muted);margin:2px 0 0}.psg{background:var(--bg);border:1px solid var(--line);border-radius:6px;
padding:6px 8px;margin:6px 0;font-size:.82rem;white-space:pre-wrap}.cid{font-family:ui-monospace,monospace;font-size:.78rem;color:var(--muted)}
.planted{background:var(--tag-bg);border-radius:6px;padding:8px;margin-bottom:8px}.planted b{color:var(--tag)}
del{color:var(--bad)}ins{color:var(--ok);text-decoration:none}
"""

_JS = """
const panel=document.getElementById('panel');let sel=null;
function show(el){const t=document.getElementById('d-'+el.dataset.id);panel.innerHTML=t?t.innerHTML:'';}
document.querySelectorAll('.s').forEach(el=>{
 el.addEventListener('mouseenter',()=>{if(!sel)show(el)});
 el.addEventListener('click',()=>{if(sel)sel.classList.remove('sel');if(sel===el){sel=null;return}
  sel=el;el.classList.add('sel');show(el)});});
"""


def _e(x: str) -> str:
    return html.escape(x, quote=True)


def render(title: str, draft: Draft, claims: Sequence[Claim], verdicts: Sequence[Verdict],
           passages: Mapping[str, Passage], subtitle: str = "", planted: SeededDraft | None = None) -> str:
    verdict_of = {v.claim_id: v for v in verdicts}
    claims_of: dict[str, list[Claim]] = defaultdict(list)
    for c in claims:
        claims_of[c.sentence_id].append(c)
    planted_of: dict[str, list] = defaultdict(list)
    for e in (planted.errors if planted else ()):
        for sid in e.sentence_ids:
            planted_of[sid].append(e)

    counts: dict[str, int] = defaultdict(int)
    for v in verdicts:
        counts[v.kind.value] += 1

    body, details = [], []
    for sec in draft.sections:
        sents = [s for s in draft.sentences if s.section == sec]
        if not sents:
            continue
        body.append(f"<h2>{_e(sec)}</h2><p>")
        for s in sents:
            kinds = [verdict_of[c.claim_id].kind for c in claims_of[s.sentence_id] if c.claim_id in verdict_of]
            cls = min((_SEVERITY[k] for k in kinds), key=_RANK.index, default="none")
            tags = "".join(f'<span class="tag">{_e(e.error_class.value)}</span>' for e in planted_of[s.sentence_id])
            body.append(f'<span class="s {cls}" data-id="{_e(s.sentence_id)}">{_e(s.text)}</span>{tags} ')

            d = [f'<div class="cid">{_e(s.sentence_id)} · {_e(s.section)}</div>']
            for e in planted_of[s.sentence_id]:
                d.append(f'<div class="planted"><b>Planted {_e(e.error_class.value)}</b> · counts as caught if: '
                         f'{_e(", ".join(k.value for k in e.expected_verdicts))}'
                         + (f'<div><del>{_e(e.original)}</del></div>' if e.original else "")
                         + f'<div><ins>{_e(e.corrupted)}</ins></div></div>')
            if not claims_of[s.sentence_id]:
                d.append('<p class="hint">No claims recorded for this sentence.</p>')
            for c in claims_of[s.sentence_id]:
                v = verdict_of.get(c.claim_id)
                kind = v.kind if v else None
                badge = (f'<span class="k {_SEVERITY[kind]}">{_e(kind.value)}</span>' if kind
                         else '<span class="k none">not checked</span>')
                conf = f" · confidence {v.confidence:.2f}" if v and v.confidence is not None else ""
                d.append(f'<div class="claim">{badge} <span class="cid">{_e(c.claim_id)} · '
                         f'{_e(c.ctype.value if c.ctype else "—")} · {_e(c.modality.value)}{conf}</span>'
                         f'<div>{_e(c.text)}</div>'
                         + (f'<p class="why">{_e(v.rationale)}</p>' if v else ""))
                for cid in c.citations:
                    p = passages.get(cid)
                    d.append(f'<div class="psg"><span class="cid">{_e(cid)}</span>\n'
                             f'{_e(p.chunk.text if p else "(passage not in the evidence pool)")}</div>')
                d.append("</div>")
            if not s.citations:
                d.append('<p class="hint">This sentence cites nothing.</p>')
            details.append(f'<template id="d-{_e(s.sentence_id)}">{"".join(d)}</template>')
        body.append("</p>")

    legend = "".join(f'<span class="{c}">{_e(label)}</span>' for c, label in
                     [("ok", "supported"), ("bad", "failing"), ("warn", "overclaim / abstained"),
                      ("info", "exempt / inference"), ("err", "check failed")])
    summary = " · ".join(f"{k} {n}" for k, n in sorted(counts.items()))
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(title)}</title>'
            f'<style>{_CSS}</style></head><body><header><h1>{_e(title)}</h1>'
            f'<div class="meta">{_e(subtitle)}</div><div class="meta">{_e(summary)}</div>'
            f'<div class="legend">{legend}</div></header><main><article>{"".join(body)}</article>'
            f'<aside id="panel"><p class="hint">Hover or tap a sentence to see its claims, verdicts and the '
            f'passages it cites. Tap again to unpin.</p></aside></main>{"".join(details)}'
            f'<script>{_JS}</script></body></html>')
