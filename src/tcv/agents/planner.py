"""Planner — a synthesis question becomes an ordered outline of sub-tasks (FR-2).

Each sub-task becomes one report section and one retrieval pool. The count
is bounded by config (FR-2.3) because it drives the cost of everything
downstream: more sections, more sentences, more claims to check.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from tcv.config import PlannerConfig
from tcv.llm.gateway import Gateway
from tcv.llm.prompts import Prompt
from tcv.schemas import SubTask
from tcv.schemas.ids import subtask_id


class PlannedSubTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str
    question: str


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subtasks: list[PlannedSubTask]


class PlanError(RuntimeError):
    pass


class Planner:
    def __init__(self, gateway: Gateway, prompt: Prompt, config: PlannerConfig = PlannerConfig()):
        self._gateway = gateway
        self._prompt = prompt
        self._config = config

    def plan(self, query: str) -> tuple[SubTask, ...]:
        """Return the ordered sub-tasks.

        Extra sub-tasks beyond the maximum are dropped (the budget is the
        point of the bound); fewer than the minimum is accepted as long as
        there is at least one, since a narrow question may honestly need
        fewer sections.
        """
        res = self._gateway.call("economy", self._prompt, {
            "query": query,
            "min_subtasks": str(self._config.min_subtasks),
            "max_subtasks": str(self._config.max_subtasks),
        }, out=Plan)
        planned = [p for p in res.value.subtasks if p.heading.strip() and p.question.strip()]
        if not planned:
            raise PlanError(f"planner returned no usable sub-tasks ({res.call_id})")
        headings: set[str] = set()
        subtasks = []
        for p in planned[: self._config.max_subtasks]:
            heading = p.heading.strip()
            if heading in headings:  # a duplicate heading would merge two report sections
                heading = f"{heading} ({len(subtasks) + 1})"
            headings.add(heading)
            subtasks.append(SubTask(subtask_id=subtask_id(len(subtasks) + 1), heading=heading,
                                    question=p.question.strip(), order=len(subtasks) + 1))
        return tuple(subtasks)
