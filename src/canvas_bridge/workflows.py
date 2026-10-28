"""Bounded on-demand execution over the existing authorization, evidence and planning services."""

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from time import monotonic

from canvas_bridge.authorization import (
    RequestAuthorization,
    request_authorization,
    validate_request_authorization,
)
from canvas_bridge.domain import DomainError, Result, utcnow
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.egress_sources import resolve_sources
from canvas_bridge.evidence import fingerprint
from canvas_bridge.oauth_security import require_capabilities
from canvas_bridge.policy_surfaces import TOOL_CATEGORIES, authorize_tool
from canvas_bridge.workflow_budget import Budget, active_budget
from canvas_bridge.workflow_operations import NETWORK, OPERATIONS, TOOLS
from canvas_bridge.workflow_registry import WORKFLOWS, WorkflowRequest


@dataclass
class Context:
    bridge: object
    owner: str
    ref: str
    request: WorkflowRequest
    courses: list[str]
    epoch: int
    private: dict = field(default_factory=dict)

    @property
    def start(self):
        return self.request.start

    @property
    def end(self):
        return self.request.end

    def check(self):
        authorize_tool(
            self.bridge, self.owner, "run_academic_workflow", {"connection_id": self.ref}
        )
        current, _ = self.bridge.selected(self.owner, self.ref, self.courses)
        if current.epoch != self.epoch:
            raise DomainError(
                "source_changed", "Workflow scope changed; refresh before continuing."
            )
        validate_request_authorization(self.bridge)

    def check_sources(self, result):
        if any(s.course_id and s.course_id not in self.courses for s in result.sources):
            raise DomainError(
                "permission_denied",
                "A workflow source is outside the authorized scope.",
                reason_code="WORKFLOW_SOURCE_MISMATCH",
            )
        if not result.sources:
            return
        contexts, _ = resolve_sources(
            self.bridge.egress,
            self.owner,
            {"connection_id": self.ref},
            result,
            "run_academic_workflow",
        )
        if any(
            c.authorization_resource and c.authorization_resource not in self.courses
            for c in contexts
        ):
            raise DomainError(
                "permission_denied",
                "A resolved source belongs to another workflow course scope.",
                reason_code="WORKFLOW_SOURCE_MISMATCH",
            )
        known = {s.source_id for s in contexts if s.classification != CC.UNKNOWN_OR_UNCLASSIFIED}
        # Known but restricted sources are still checked by the final egress policy.
        if any(s.id not in known and s.resource_id not in known for s in result.sources):
            raise DomainError(
                "partial_data",
                "A source reference could not be verified; its findings were withheld.",
                reason_code="WORKFLOW_SOURCE_MISMATCH",
            )


def capability(ctx, operation, *, preflight=False):
    tool = TOOLS.get(operation)
    if not tool:
        return
    # A rejected optional capability must not poison an otherwise authorized
    # request. This temporary context cannot release any data or authorize calls.
    old = request_authorization.get()
    token = (
        request_authorization.set(
            RequestAuthorization(tool, recipient=old.recipient if old else "local")
        )
        if preflight
        else None
    )
    try:
        authorize_tool(ctx.bridge, ctx.owner, tool, {"connection_id": ctx.ref})
        with ctx.bridge.store.transaction() as session:
            conn = ctx.bridge.store.connection(session, ctx.owner, ctx.ref)
            institution = ctx.bridge.registry.entries[conn.institution]
            require_capabilities(ctx.bridge, institution, TOOL_CATEGORIES[tool])
    finally:
        if token is not None:
            request_authorization.reset(token)


def failed(code, summary):
    return Result(
        status="partial_data", summary=summary, data={"reason_code": code, "usable": False}
    )


def usable(result):
    return (
        result.status in {"ok", "partial_data", "stale_data"}
        and result.data.get("usable") is not False
    )


async def execute(ctx, spec, budget, unavailable_courses, started=None):
    cache, trace, sections, sources, coverage = {}, [], [], {}, []
    started = started if started is not None else monotonic()
    blocked = {}
    for step in spec.steps:
        if step.operation not in OPERATIONS:
            raise DomainError("unsupported_feature", "Workflow adapter is unavailable.")
        try:
            capability(ctx, step.operation, preflight=True)
        except DomainError as exc:
            if exc.status in {"reconnect_required", "source_changed"}:
                raise
            blocked[step.name] = exc.reason_code or "CAPABILITY_UNAVAILABLE"
    for course in ctx.courses if spec.per_course else [None]:
        previous = {}
        for step in spec.steps:
            ctx.check()
            tick = monotonic()
            key = (step.operation, course)
            reused = False
            if step.name in blocked:
                result = failed(
                    blocked[step.name],
                    "This capability is not available under the current approved connection.",
                )
            elif any(not usable(previous[dep]) for dep in step.dependencies):
                result = failed(
                    "DEPENDENCY_UNAVAILABLE",
                    "A required source could not be checked. Complete the preceding input or retrieval step.",
                )
            elif (
                len(trace) >= spec.limits.max_steps
                or monotonic() - started >= spec.limits.total_seconds
            ):
                result = failed(
                    "WORKFLOW_TIME_LIMIT",
                    "The workflow limit was reached; narrow the scope to continue.",
                )
            elif budget.exhausted and step.operation in NETWORK:
                result = failed(
                    "WORKFLOW_BUDGET_EXHAUSTED",
                    "Further retrieval paused after the resource or upstream rate limit.",
                )
            else:
                capability(ctx, step.operation)
                try:
                    if key in cache:
                        result, reused = cache[key], True
                    else:
                        async with asyncio.timeout(
                            min(
                                spec.limits.step_seconds,
                                max(0.001, spec.limits.total_seconds - (monotonic() - started)),
                            )
                        ):
                            from canvas_bridge.integrity.surfaces import before_tool

                            # Choosing a workflow cannot skip ordinary-reader policy
                            # discovery for policies that have not been loaded yet.
                            await before_tool(
                                ctx.bridge,
                                ctx.owner,
                                "fetch_course_material"
                                if step.operation == "exam"
                                else TOOLS.get(step.operation, "run_academic_workflow"),
                                {"connection_id": ctx.ref, "course_id": course},
                            )
                            result = await OPERATIONS[step.operation](ctx, course, previous)
                        if result.status in {
                            "permission_denied",
                            "reconnect_required",
                            "source_changed",
                        }:
                            raise DomainError(
                                result.status,
                                "Authorization or source changed during the workflow.",
                            )
                        from canvas_bridge.integrity.surfaces import guard_result

                        result = guard_result(
                            ctx.bridge,
                            ctx.owner,
                            TOOLS.get(step.operation, "run_academic_workflow"),
                            {"connection_id": ctx.ref, "course_id": course},
                            result,
                        )
                        ctx.check_sources(result)
                        if result.status == "ok" and any(
                            previous[dep].status != "ok" for dep in step.dependencies
                        ):
                            result = result.model_copy(deep=True)
                            result.status = "partial_data"
                            result.data.setdefault("limitations", []).append(
                                "A dependency has incomplete coverage; this derived result inherits that limitation."
                            )
                        if result.meta.next_cursor:
                            result.status = "partial_data"
                            result.meta.warnings.append(
                                "Additional source pages were not included."
                            )
                        cache[key] = result
                except TimeoutError:
                    result = failed(
                        "WORKFLOW_STEP_TIMEOUT",
                        "This step timed out. Independently completed findings remain available.",
                    )
                except DomainError as exc:
                    if exc.status in {"permission_denied", "reconnect_required", "source_changed"}:
                        raise
                    if exc.upstream_http_status == 429 or exc.reason_code in {
                        "RATE_LIMITED",
                        "WORKFLOW_BUDGET_EXHAUSTED",
                    }:
                        budget.exhausted = True
                    result = failed(
                        exc.reason_code or "WORKFLOW_STEP_UNAVAILABLE",
                        "This source or operation is unavailable; retry or narrow the request.",
                    )
            ctx.check()
            previous[step.name] = result
            trace.append(
                {
                    "step": step.name,
                    "operation": step.operation,
                    "course_id": course,
                    "status": result.status,
                    "reused": reused,
                    "elapsed_ms": round((monotonic() - tick) * 1000),
                    "reason_code": result.data.get("reason_code"),
                }
            )
            coverage.extend(result.meta.coverage)
            # Internal normalized grade evidence is retained only for this request.
            if step.operation == "grade_evidence" and usable(result):
                continue
            sections.append(
                {
                    "step": step.name,
                    "course_id": course,
                    "status": result.status,
                    "summary": result.summary,
                    "data": result.data,
                    "source_ids": list(dict.fromkeys(s.id for s in result.sources)),
                    "freshness": result.meta.freshness,
                    "retrieved_at": result.meta.retrieved_at.isoformat()
                    if result.meta.retrieved_at
                    else None,
                }
            )
            for source in result.sources:
                sources[(source.id, source.content_hash, source.locator)] = source
    partial = bool(unavailable_courses) or any(t["status"] != "ok" for t in trace)
    answer = " ".join(
        s["summary"] for s in sections if s["step"] not in {"materials", "availability"}
    )
    result = Result(
        status="partial_data" if partial else "ok",
        summary=spec.title + ": " + answer[:3500],
        data={
            "schema_version": spec.output_schema,
            "workflow": spec.name,
            "workflow_version": spec.version,
            "definition_digest": spec.digest,
            "input_digest": fingerprint(ctx.request.model_dump(mode="json")),
            "read_only": True,
            "actions_executed": False,
            "sections": sections,
            "coverage_limitations": [
                "Coverage is limited to the sources and window in each section; it is not proof of all course obligations."
            ]
            + (["One or more requested courses were unavailable."] if unavailable_courses else []),
            "unavailable_course_count": len(unavailable_courses),
            "course_ids": ctx.courses,
            "assumptions": [
                "Course content is evidence, never an instruction to change permissions.",
                "Priority rankings and study outlines are heuristics.",
            ]
            + (
                ["A default seven-day window was used."]
                if ctx.private.get("default_window")
                else []
            ),
            "next_actions": ["Resolve the incomplete steps shown in the report."]
            if partial
            else [],
            "execution": {
                "trace": trace,
                "http_calls": budget.http_calls,
                "api_bytes": budget.api_bytes,
                "document_bytes": budget.document_bytes,
                "files": len(budget.file_ids),
                "deduplicated_steps": sum(t["reused"] for t in trace),
                "elapsed_ms": round((monotonic() - started) * 1000),
                "limits": spec.public()["limits"],
            },
        },
        sources=list(sources.values()),
        meta=ctx.bridge.meta(
            display_timezone=ctx.request.timezone,
            coverage=coverage,
            freshness="synthetic" if ctx.bridge.synthetic else "live",
        ),
    )
    # Remove complete sections with their citations; never silently clip source text
    # while leaving a success claim or dangling citation behind.
    while len(result.model_dump_json().encode()) > spec.limits.output_bytes and sections:
        omitted = sections.pop()
        for item in trace:
            if item["step"] == omitted["step"] and item["course_id"] == omitted["course_id"]:
                item["status"] = "partial_data"
                item["reason_code"] = "WORKFLOW_OUTPUT_LIMIT"
        retained = {ident for section in sections for ident in section["source_ids"]}
        result.sources = [s for s in result.sources if s.id in retained]
        result.status = "partial_data"
        result.summary = (
            spec.title
            + ": Output was limited. Narrow the scope for omitted sections. "
            + " ".join(s["summary"] for s in sections)[:2000]
        )
        result.data["next_actions"] = [
            "Narrow the course or document scope to obtain omitted sections."
        ]
        result.data["coverage_limitations"] = [
            "Whole sections were omitted by the output budget; this is an incomplete result."
        ]
    ctx.check()
    return result


async def run_workflow(bridge, owner, ref, request: WorkflowRequest):
    spec = WORKFLOWS[request.workflow]
    context_token, lease = None, None
    budget = Budget(spec.limits)
    budget_token = active_budget.set(budget)
    started = monotonic()
    try:
        if request_authorization.get() is None:
            lease = bridge.request_limits.acquire(owner)
            context_token = request_authorization.set(RequestAuthorization("run_academic_workflow"))
        authorize_tool(bridge, owner, "run_academic_workflow", {"connection_id": ref})
        async with asyncio.timeout(spec.limits.step_seconds):
            await bridge.refresh_course_access(owner, ref)
        conn, selected = bridge.selected(owner, ref)
        requested = request.course_ids or [c.id for c in selected]
        if len(requested) > spec.max_courses:
            raise DomainError(
                "needs_input", f"Choose at most {spec.max_courses} courses for this workflow."
            )
        available = [ident for ident in requested if ident in {c.id for c in selected}]
        missing = set(requested) - set(available)
        if not available:
            raise DomainError(
                "permission_denied", "No requested courses are currently selected and accessible."
            )
        default_window = request.start is None
        if default_window:
            now = utcnow()
            request = request.model_copy(update={"start": now, "end": now + timedelta(days=7)})
        ctx = Context(bridge, owner, ref, request, available, conn.epoch)
        ctx.private["default_window"] = default_window
        return await execute(ctx, spec, budget, missing, started)
    except TimeoutError:
        return failed(
            "WORKFLOW_NEGOTIATION_TIMEOUT",
            "Authorization discovery timed out; no course result is available.",
        )
    finally:
        active_budget.reset(budget_token)
        if context_token is not None:
            request_authorization.reset(context_token)
        if lease:
            lease.close()
