"""Local, bounded diagnostic journal. Lookup accepts only an opaque request ID."""

import argparse
import hashlib
import json
import logging
import os
import re
from datetime import timedelta
from functools import cache
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field, ValidationError

from canvas_bridge import __version__
from canvas_bridge.domain import FailureDiagnostic, Result, utcnow
from canvas_bridge.failure_diagnostics import current, public_fields
from canvas_bridge.lifecycle import locked_file
from canvas_bridge.policy import Endpoint

MAX_BYTES = 10 * 1024 * 1024
SEGMENT_BYTES = 512 * 1024
SEGMENT = re.compile(r"[0-9]{8}T[0-9]{12}-[0-9a-f]{8}\.jsonl")
logger = logging.getLogger(__name__)


@cache
def build_identifier():
    # Frozen application builds may omit Python sources. Fall back to the
    # packaged version in that case; never fingerprint operator configuration.
    try:
        digest = hashlib.sha256()
        for name in (
            "app.py",
            "auth.py",
            "auth_diagnostics.py",
            "egress_transport.py",
            "egress_policy.py",
            "failure_diagnostics.py",
            "failure_events.py",
            "canvas.py",
            "obligations.py",
            "retrieval.py",
            "inventory_recovery.py",
            "course_files.py",
            "paged_inventory.py",
            "privacy/transport.py",
        ):
            digest.update((Path(__file__).parent / name).read_bytes())
        return __version__ + "+" + digest.hexdigest()[:16]
    except OSError:
        return __version__


def journal(settings):
    return settings.vault_key_file.parent / "failure-events"


BRANCH_ROUTES = {
    "assignments": Endpoint.ASSIGNMENTS,
    "classic_quizzes": Endpoint.QUIZZES,
    "discussion_topics": Endpoint.DISCUSSIONS,
    "calendar_events": Endpoint.CALENDAR_EVENTS,
    "calendar_assignments": Endpoint.CALENDAR_EVENTS,
    "files": Endpoint.FILES,
    "modules": Endpoint.MODULES,
    "module_items": Endpoint.MODULE_ITEMS,
    "folders": Endpoint.FOLDERS,
    "folder_metadata": Endpoint.FOLDER,
    "folder_files": Endpoint.FOLDER_FILES,
    "file": Endpoint.FILE,
    "pages": Endpoint.PAGES,
}


class LocalEvent(FailureDiagnostic):
    branch: (
        Literal[
            "assignments",
            "classic_quizzes",
            "discussion_topics",
            "calendar_events",
            "calendar_assignments",
            "files",
            "modules",
            "module_items",
            "folders",
            "folder_metadata",
            "folder_files",
            "file",
            "pages",
        ]
        | None
    ) = None
    pages_consumed: int | None = Field(default=None, ge=0, le=20)
    route_template: Endpoint | None = None
    http_method: Literal["GET"] | None = None
    attempt_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    timestamp: AwareDatetime
    exception_class: Literal["runtime", "value", "timeout", "type", "io", "other", "domain"] | None
    policy_mode: Literal["strict", "permissive"]
    build: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:\+[a-f0-9]{16})?$")
    failure_handler_version: Literal["1"]


def segments(root):
    if root.is_symlink() or root.is_junction():
        return []
    return sorted(
        p for p in root.glob("*.jsonl") if SEGMENT.fullmatch(p.name) and not p.is_symlink()
    )


def expire_events(root):
    files = segments(root)
    cutoff = (utcnow() - timedelta(days=7)).strftime("%Y%m%dT%H%M%S%f")
    if files and files[0].name[:21] < cutoff:
        with locked_file(root / "journal.lock"):
            for path in segments(root):
                if path.name[:21] < cutoff:
                    path.unlink()


def append_event(root, event):
    from canvas_bridge.database_upgrade import private_directory

    if not root.exists():
        # Publish only after access restrictions have been applied.
        temp = root.with_name(".failure-events-" + uuid4().hex)
        private_directory(temp)
        try:
            temp.rename(root)
        except OSError:
            if not root.is_dir():
                raise
        finally:
            if temp.exists():
                temp.rmdir()
    if root.is_symlink() or root.is_junction():
        return
    if os.name != "nt" and (root.stat().st_mode & 0o077 or root.stat().st_uid != os.getuid()):
        return
    lock = root / "journal.lock"
    if lock.is_symlink():
        return
    lock.touch(mode=0o600, exist_ok=True)
    line = (json.dumps(event, separators=(",", ":")) + "\n").encode()
    now = utcnow()
    cutoff = (now - timedelta(days=7)).strftime("%Y%m%dT%H%M%S%f")
    with locked_file(lock):
        files = segments(root)
        while files and files[0].name[:21] < cutoff:
            files.pop(0).unlink()
        size = sum(p.stat().st_size for p in files)
        while files and size + len(line) > MAX_BYTES:
            oldest = files.pop(0)
            size -= oldest.stat().st_size
            oldest.unlink()
        if (
            files
            and files[-1].stat().st_size + len(line) <= SEGMENT_BYTES
            and files[-1].name.startswith(now.strftime("%Y%m%d"))
        ):
            target = files[-1]
        else:
            target = root / (now.strftime("%Y%m%dT%H%M%S%f") + "-" + uuid4().hex[:8] + ".jsonl")
        with os.fdopen(
            os.open(target, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600), "ab"
        ) as stream:
            stream.write(line)


def record(engine, *, branch=None, pages=None):
    attempt = current.get()
    if not attempt or not attempt.diagnostic:
        return
    try:
        diagnostic = attempt.diagnostic
        event = dict(
            public_fields(diagnostic),
            attempt_id=attempt.attempt_id,
            timestamp=utcnow().isoformat(),
            exception_class=attempt.exception,
            policy_mode=engine.bridge.settings.egress_mode,
            build=build_identifier(),
            failure_handler_version="1",
        )
        if branch in BRANCH_ROUTES:
            event.update(
                branch=branch, route_template=BRANCH_ROUTES[branch].value, http_method="GET"
            )
            if type(pages) is int and 0 <= pages <= 20:
                event["pages_consumed"] = pages
        append_event(journal(engine.bridge.settings), event)
        logger.warning("tool_failed request_id=%s code=%s", attempt.request_id, diagnostic.code)
    except Exception:
        # The error path must remain usable with a full disk or broken log sink.
        return


def record_branch(engine, detail, *, branch=None, pages=None):
    from canvas_bridge.domain import Result
    from canvas_bridge.egress_errors import safe_error_result
    from canvas_bridge.failure_diagnostics import Attempt, describe

    parent = current.get()
    if parent is None:
        return
    token = current.set(
        Attempt(
            request_id=parent.request_id, attempt_id=parent.attempt_id, operation=parent.operation
        )
    )
    try:
        result = safe_error_result(Result(status="partial_data", summary="", data=detail))
        describe(result, "not_evaluated")
        record(engine, branch=branch, pages=pages)
    except Exception:
        return  # Diagnostic recording cannot change the inventory response.
    finally:
        current.reset(token)


def lookup(root, request_id):
    if not re.fullmatch(r"[0-9a-f]{32}", request_id):
        raise ValueError("Invalid request ID")
    from canvas_bridge.egress_errors import SAFE_CODES
    from canvas_bridge.failure_diagnostics import Attempt, rule_for
    from canvas_bridge.policy_surfaces import OFFLINE_TOOLS, TOOL_CATEGORIES

    operations = set(TOOL_CATEGORIES) | OFFLINE_TOOLS
    cutoff = utcnow() - timedelta(days=7)
    for path in segments(root):
        try:
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        event = LocalEvent.model_validate_json(line)
                    except ValidationError:
                        continue
                    if (
                        event.request_id == request_id
                        and event.timestamp >= cutoff
                        and event.code in SAFE_CODES
                        and (
                            event.requested_operation is None
                            or event.requested_operation in operations
                        )
                    ):
                        output = event.model_dump(mode="json", exclude_unset=True)
                        # Resolve the support-copy action through the public registry.
                        # Never lose an event because a newer build added a remedy.
                        observation = Result(
                            status="needs_input"
                            if event.stage == "input_validation"
                            else "operation_failed",
                            summary="",
                            data={
                                "upstream_http_status": event.upstream_http_status,
                                "retrieval_constraint": event.retrieval_constraint,
                            },
                        )
                        rule = rule_for(
                            event.code, observation, Attempt(policy=event.requested_content_policy)
                        )
                        if event.next_action != rule.action:
                            output.pop("next_action")
                        yield output
        except (FileNotFoundError, ValueError, KeyError):
            continue


def main():
    from canvas_bridge.config import Settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_id")
    args = parser.parse_args()
    for event in lookup(journal(Settings()), args.request_id):
        print(json.dumps(event, sort_keys=True))


if __name__ == "__main__":
    main()
