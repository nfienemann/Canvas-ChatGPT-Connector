"""Explicit opt-in pytest recorder. Emits outcomes, never captured output or parameters."""

import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from canvas_bridge.compliance.inventory import source_state, test_index
from canvas_bridge.compliance.models import Counts, TestRun


def pytest_addoption(parser):
    parser.addoption(
        "--compliance-results", default=None, help="Write sanitized source-bound outcomes."
    )


def pytest_configure(config):
    destination = config.getoption("--compliance-results")
    if destination:
        complete = not any(
            config.getoption(name, default=False)
            for name in ("keyword", "markexpr", "deselect", "lf")
        ) and not any("::" in str(arg) for arg in config.args)
        config.pluginmanager.register(
            Recorder(Path(config.rootpath), Path(destination), complete_selection=complete),
            "compliance-recorder",
        )


class Recorder:
    def __init__(self, root, destination, *, complete_selection=False):
        self.root, self.destination = root, destination
        self.source = source_state(root)
        self.known = test_index(root)
        self.items = {}
        self.outcomes = {}
        self.complete_selection = complete_selection

    def pytest_deselected(self, items):
        if items:
            self.complete_selection = False

    def pytest_collection_finish(self, session):
        self.items = {
            item.nodeid: item.nodeid.split("[", 1)[0].replace("\\", "/") for item in session.items
        }

    def pytest_runtest_logreport(self, report):
        if report.failed:
            self.outcomes[report.nodeid] = "failed" if report.when == "call" else "error"
        elif report.skipped and self.outcomes.get(report.nodeid) not in {"failed", "error"}:
            self.outcomes[report.nodeid] = "skipped"
        elif report.when == "call" and report.passed and report.nodeid not in self.outcomes:
            self.outcomes[report.nodeid] = "passed"

    def pytest_sessionfinish(self, session, exitstatus):
        cases = defaultdict(Counter)
        for node, base in self.items.items():
            if base not in self.known:
                continue
            cases[base]["collected"] += 1
            cases[base][self.outcomes.get(node, "error")] += 1
        run = TestRun(
            schema_version="test-run-1",
            source=self.source,
            finished_on=datetime.now(UTC).date(),
            source_unchanged=source_state(self.root).digest == self.source.digest,
            exit_code=int(exitstatus),
            interrupted=int(exitstatus) in {2, 3, 4, 5},
            complete_selection=self.complete_selection
            and all(base in self.known for base in self.items.values()),
            cases={name: Counts(**counts) for name, counts in sorted(cases.items())},
            runtime=sys.platform
            if sys.platform in {"linux", "darwin"}
            else "windows"
            if sys.platform == "win32"
            else "other",
        )
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        with self.destination.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(run.model_dump(mode="json"), indent=2) + "\n")
