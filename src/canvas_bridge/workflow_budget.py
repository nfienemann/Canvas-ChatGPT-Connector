"""Request-local resource accounting; existing admission, rate limits and workers remain authoritative."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from canvas_bridge.domain import DomainError

if TYPE_CHECKING:
    from canvas_bridge.workflow_registry import Limits


@dataclass
class Budget:
    limits: Limits
    http_calls: int = 0
    api_bytes: int = 0
    document_bytes: int = 0
    file_ids: set = field(default_factory=set)
    exhausted: bool = False

    def fail(self):
        self.exhausted = True
        raise DomainError(
            "partial_data",
            "The workflow resource budget is exhausted; narrow the scope.",
            reason_code="WORKFLOW_BUDGET_EXHAUSTED",
        )

    def request(self):
        if self.exhausted or self.http_calls >= self.limits.http_calls:
            self.fail()
        self.http_calls += 1

    def consume(self, amount, *, document=False):
        key = "document_bytes" if document else "api_bytes"
        if getattr(self, key) + amount > getattr(self.limits, key):
            self.fail()
        setattr(self, key, getattr(self, key) + amount)

    def document(self, course, file):
        if (course, file) not in self.file_ids and len(self.file_ids) >= self.limits.files:
            self.fail()
        self.file_ids.add((course, file))


active_budget: ContextVar[Budget | None] = ContextVar("academic_workflow_budget", default=None)


def count_request():
    if budget := active_budget.get():
        budget.request()


def count_bytes(amount, *, document=False):
    if budget := active_budget.get():
        budget.consume(amount, document=document)
