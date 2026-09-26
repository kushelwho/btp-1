"""Versioned prompt templates.

Prompts are files, never string literals in code, so a prompt change shows up
in a diff and its version is recorded with every call.

    prompts/<name>/v<N>.md

    <<<system>>>
    Stable instructions. Anything placed here is cacheable across calls.
    <<<user>>>
    Per-call content with ${placeholders}.

Placeholders use ``${name}`` (string.Template), so literal JSON braces in a
prompt need no escaping. A missing variable is an error, not a blank.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_REF = re.compile(r"^(?P<name>[a-z0-9_/]+)@(?P<version>\d+)$")
_SPLIT = re.compile(r"^<<<(system|user)>>>\s*$", re.M)


class PromptError(ValueError):
    pass


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    system: str
    user: str
    sha256: str

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"

    def placeholders(self) -> set[str]:
        names = set()
        for tpl in (self.system, self.user):
            for m in Template.pattern.finditer(tpl):
                if m.group("named") or m.group("braced"):
                    names.add(m.group("named") or m.group("braced"))
        return names

    def render(self, variables: dict[str, str]) -> tuple[str, str]:
        missing = self.placeholders() - variables.keys()
        if missing:
            raise PromptError(f"{self.ref}: missing variables {sorted(missing)}")
        return Template(self.system).substitute(variables), Template(self.user).substitute(variables)


def parse_prompt(name: str, version: int, raw: str) -> Prompt:
    parts = _SPLIT.split(raw)
    # parts = [preamble, role, body, role, body, ...]
    sections: dict[str, str] = {}
    for i in range(1, len(parts) - 1, 2):
        role, body = parts[i], parts[i + 1]
        if role in sections:
            raise PromptError(f"{name}@{version}: duplicate <<<{role}>>> section")
        sections[role] = body.strip()
    if "user" not in sections:
        raise PromptError(f"{name}@{version}: missing <<<user>>> section")
    return Prompt(name=name, version=version, system=sections.get("system", ""), user=sections["user"],
                  sha256=hashlib.sha256(raw.encode()).hexdigest())


def load_prompt(ref: str, root: str | Path = PROMPTS_DIR) -> Prompt:
    """Load ``"checker/entail@1"`` from ``prompts/checker/entail/v1.md``."""
    m = _REF.match(ref)
    if not m:
        raise PromptError(f"bad prompt ref {ref!r}; expected name@version")
    name, version = m["name"], int(m["version"])
    path = Path(root) / name / f"v{version}.md"
    if not path.exists():
        raise PromptError(f"prompt file not found: {path}")
    return parse_prompt(name, version, path.read_text(encoding="utf-8"))
