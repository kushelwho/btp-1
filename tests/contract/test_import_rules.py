"""The architectural import rules are enforced, not just declared.

A contract that passes on an empty package proves nothing, so each rule is
also shown to *fail* when a violation is planted in a throwaway copy of the
source tree. The real tree is never modified.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# The console script, not `python -m importlinter.cli` — that module has no __main__
# and silently exits 0 without linting anything.
LINT = [str(Path(sys.executable).parent / "lint-imports"), "--config", str(ROOT / "pyproject.toml"), "--no-cache"]


def _lint(src_root: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(src_root)}
    return subprocess.run(LINT, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)


@pytest.fixture
def tree(tmp_path):
    shutil.copytree(ROOT / "src" / "tcv", tmp_path / "tcv", ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path


def _plant(tree: Path, module: str, code: str) -> None:
    path = tree / Path(*module.split(".")).with_suffix(".py")
    path.parent.mkdir(parents=True, exist_ok=True)
    for parent in path.relative_to(tree).parents:
        init = tree / parent / "__init__.py"
        if parent != Path(".") and not init.exists():
            init.write_text("")
    path.write_text(code)


def test_real_tree_keeps_every_contract(tree):
    r = _lint(tree)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Contracts: 4 kept, 0 broken" in r.stdout, "linter did not actually run"


@pytest.mark.parametrize(
    "module, code, broken",
    [
        ("tcv.checker.operators.count", "import tcv.llm.gateway\n", "pure code"),
        ("tcv.checker.operators.count", "import anthropic\n", "pure code"),
        ("tcv.checker.verify_t1", "from tcv.retrieval import search\n", "Only the Researcher"),
        ("tcv.orchestrator.loop", "import tcv.retrieval.index\n", "Only the Researcher"),
        ("tcv.agents.planner", "import anthropic\n", "Only the gateway"),
        ("tcv.agents.planner", "from google import genai\n", "Only the gateway"),
        ("tcv.checker.operators.count", "from google.genai import types\n", "pure code"),
        ("tcv.schemas.bad", "import tcv.corpus.chunk\n", "Schemas depend on nothing"),
    ],
)
def test_planted_violation_is_caught(tree, module, code, broken):
    _plant(tree, module, code)
    r = _lint(tree)
    assert r.returncode != 0, f"violation in {module} was not caught"
    assert "BROKEN" in r.stdout and broken in r.stdout, r.stdout


def test_researcher_is_allowed_to_use_retrieval(tree):
    _plant(tree, "tcv.agents.researcher", "from tcv.retrieval.search import HybridSearcher\n")
    r = _lint(tree)
    assert r.returncode == 0, r.stdout
