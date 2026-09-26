"""Fetch approved candidate papers from arXiv (decision D-3).

Two steps, both conservative:

  * ``check``: look every candidate up in the arXiv API and compare the
    title we wrote down with the title arXiv returns. Several IDs in the
    candidate list were quoted from memory; a wrong ID silently puts the
    wrong paper in the corpus, so nothing is downloaded on a mismatch.
  * ``fetch``: refuses to run until every candidate carries a team
    decision (keep/drop). Kept papers are downloaded at a *pinned* arXiv
    version (``2305.19118v4``, not the floating latest), and a new corpus
    config listing the seed papers plus the kept ones is written.

Network access goes through an injectable ``get`` function so the whole
module is testable offline.
"""

from __future__ import annotations

import difflib
import re
import shutil
import subprocess
import time
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from .sources import CorpusConfig, SourceEntry

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_PDF = "https://arxiv.org/pdf/{id}"
USER_AGENT = "tcv-corpus-fetch/0.1 (NSUT B.Tech project; research use)"
TITLE_MATCH_MIN = 0.90
POLITE_DELAY_S = 3.0  # arXiv asks automated clients for one request every ~3 s

_ATOM = {"a": "http://www.w3.org/2005/Atom"}

Get = Callable[[str], bytes]


class FetchError(RuntimeError):
    pass


def http_get(url: str, timeout: float = 120.0) -> bytes:
    """GET via curl with an honest User-Agent.

    arXiv's front end answers 406 to Python's own HTTP stack (urllib,
    http.client, httpx) at the TLS level whatever the headers, while curl is
    served normally — observed 2026-09-26. curl ships with macOS and Linux.
    """
    if shutil.which("curl") is None:
        raise FetchError("curl is required for fetching from arXiv")
    r = subprocess.run(["curl", "--silent", "--show-error", "--fail", "--location", "--max-time", str(int(timeout)),
                        "--retry", "3", "--retry-delay", "10", "--user-agent", USER_AGENT, url],
                       capture_output=True)
    if r.returncode != 0:
        raise FetchError(f"GET {url} failed: {r.stderr.decode(errors='replace').strip()[:300]}")
    return r.stdout


# ---------------------------------------------------------------- candidates


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    arxiv: str
    title: str
    year: int | None = None
    priority: Literal["core", "optional"]
    verify: bool = False
    decision: Literal["keep", "drop"] | None = None


def load_candidates(path: str | Path) -> list[Candidate]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    cands = [Candidate.model_validate(c) for c in raw["candidates"]]
    ids = [c.arxiv for c in cands]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"duplicate arXiv id(s) in candidates: {dupes}")
    return cands


# ---------------------------------------------------------------- arXiv lookup


@dataclass(frozen=True)
class ArxivRecord:
    arxiv_id: str  # without version, e.g. "2305.19118"
    version: str  # latest version at lookup time, e.g. "v4" — the one we pin
    title: str
    year: int
    first_author_surname: str

    @property
    def versioned_id(self) -> str:
        return f"{self.arxiv_id}{self.version}"


_ABS_ID = re.compile(r"arxiv\.org/abs/(?P<id>[^v]+)(?P<ver>v\d+)$")


def parse_atom(xml: bytes) -> dict[str, ArxivRecord]:
    """Records keyed by unversioned arXiv id. Error entries (unknown ids) are skipped."""
    root = ET.fromstring(xml)
    out: dict[str, ArxivRecord] = {}
    for e in root.findall("a:entry", _ATOM):
        m = _ABS_ID.search((e.findtext("a:id", "", _ATOM) or "").strip())
        if not m:
            continue  # the API reports a bad id as an entry titled "Error"
        authors = [a.findtext("a:name", "", _ATOM) for a in e.findall("a:author", _ATOM)]
        out[m["id"]] = ArxivRecord(
            arxiv_id=m["id"],
            version=m["ver"],
            title=" ".join((e.findtext("a:title", "", _ATOM) or "").split()),
            year=int((e.findtext("a:published", "", _ATOM) or "0000")[:4]),
            first_author_surname=(authors[0].split()[-1] if authors and authors[0].split() else "anon"),
        )
    return out


def lookup(ids: Iterable[str], get: Get = http_get, batch: int = 50,
           sleep: Callable[[float], None] = time.sleep) -> dict[str, ArxivRecord]:
    ids = list(ids)
    out: dict[str, ArxivRecord] = {}
    for n, start in enumerate(range(0, len(ids), batch)):
        if n:
            sleep(POLITE_DELAY_S)
        chunk = ids[start:start + batch]
        q = urllib.parse.urlencode({"id_list": ",".join(chunk), "max_results": len(chunk)})
        out.update(parse_atom(get(f"{ARXIV_API}?{q}")))
    return out


# ---------------------------------------------------------------- checking


def _norm_title(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def title_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm_title(a), _norm_title(b)).ratio()


@dataclass(frozen=True)
class CheckResult:
    candidate: Candidate
    record: ArxivRecord | None
    similarity: float

    @property
    def status(self) -> Literal["ok", "title_mismatch", "not_found"]:
        if self.record is None:
            return "not_found"
        return "ok" if self.similarity >= TITLE_MATCH_MIN else "title_mismatch"


def check(candidates: list[Candidate], records: dict[str, ArxivRecord]) -> list[CheckResult]:
    results = []
    for c in candidates:
        r = records.get(c.arxiv)
        results.append(CheckResult(c, r, title_similarity(c.title, r.title) if r else 0.0))
    return results


# ---------------------------------------------------------------- fetching


class FetchRefused(RuntimeError):
    pass


def _slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "anon"


def doc_id_for(record: ArxivRecord, taken: set[str]) -> str:
    """Readable slug like the seed papers ("du-2023"), made unique with b, c, …"""
    base = f"{_slug(record.first_author_surname)}-{record.year}"
    if base not in taken:
        return base
    for suffix in "bcdefghijklmnopqrstuvwxyz":
        if f"{base}{suffix}" not in taken:
            return f"{base}{suffix}"
    raise ValueError(f"too many documents with id {base}")


def plan_fetch(candidates: list[Candidate], results: list[CheckResult], seed: CorpusConfig
               ) -> list[tuple[Candidate, ArxivRecord, SourceEntry]]:
    """Validate decisions and checks; return (candidate, record, corpus entry) per kept paper."""
    undecided = [c.arxiv for c in candidates if c.decision is None]
    if undecided:
        raise FetchRefused(f"{len(undecided)} candidate(s) have no decision (keep/drop), e.g. {undecided[:5]}")
    by_id = {r.candidate.arxiv: r for r in results}
    bad = [r for c in candidates if c.decision == "keep" for r in [by_id[c.arxiv]] if r.status != "ok"]
    if bad:
        lines = [f"{r.candidate.arxiv}: {r.status}"
                 + (f" (arXiv says {r.record.title!r})" if r.record else "") for r in bad]
        raise FetchRefused("kept candidates failed the arXiv check — fix the id or drop them:\n  "
                           + "\n  ".join(lines))
    seeded = {d.source.split(":", 1)[1].split("v")[0] for d in seed.documents if d.source.startswith("arxiv:")}
    taken = {d.doc_id for d in seed.documents}
    plan = []
    for c in candidates:
        if c.decision != "keep" or c.arxiv in seeded:
            continue
        rec = by_id[c.arxiv].record
        assert rec is not None
        doc_id = doc_id_for(rec, taken)
        taken.add(doc_id)
        plan.append((c, rec, SourceEntry(doc_id=doc_id, title=rec.title, filename=f"{doc_id}.pdf",
                                         source=f"arxiv:{rec.versioned_id}", year=rec.year)))
    return plan


def download(entries: list[SourceEntry], papers_dir: str | Path, get: Get = http_get,
             sleep: Callable[[float], None] = time.sleep, log: Callable[[str], None] = print) -> None:
    papers = Path(papers_dir)
    papers.mkdir(parents=True, exist_ok=True)
    fetched = 0
    for e in entries:
        path = papers / e.filename
        if path.exists():
            log(f"  have {e.filename}")
            continue
        if fetched:
            sleep(POLITE_DELAY_S)
        data = get(ARXIV_PDF.format(id=e.source.removeprefix("arxiv:")))
        if not data.startswith(b"%PDF"):
            raise FetchRefused(f"{e.source} did not return a PDF")
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        fetched += 1
        log(f"  got  {e.filename} ({len(data) // 1024} KiB) ← {e.source}")


def write_corpus_config(seed: CorpusConfig, new: list[SourceEntry], version: str, path: str | Path) -> CorpusConfig:
    cfg = CorpusConfig.model_validate({**seed.model_dump(), "version": version,
                                       "documents": [*seed.model_dump()["documents"],
                                                     *(e.model_dump() for e in new)]})
    header = (f"# Corpus {version}: the {len(seed.documents)} seed papers plus {len(new)} approved candidates\n"
              f"# (decision D-3). Written by `tcv fetch`; arXiv versions are pinned.\n"
              f"# Ingest with: uv run tcv ingest --config {Path(path).as_posix()}\n\n")
    body = yaml.safe_dump(cfg.model_dump(exclude_none=True), sort_keys=False, allow_unicode=True, width=120)
    Path(path).write_text(header + body, encoding="utf-8")
    return cfg
