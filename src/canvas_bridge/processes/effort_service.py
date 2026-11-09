"""Owned effort journal and phase-C episode bindings. All clocks/owner IDs come from the service."""

from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from canvas_bridge.analytics.effort_history import (
    Completion,
    Coverage,
    Estimate,
    HistoryScope,
    Instant,
    Interval,
    Issued,
    Minutes,
    Reading,
)
from canvas_bridge.analytics.personal_forecast import Override, Target, forecast
from canvas_bridge.domain import Result
from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes import readiness as rd
from canvas_bridge.processes.models import AcademicRecord, Model, Ref
from canvas_bridge.processes.state import failure


class Mutation(Model):
    record_id: Ref
    work_revision: int = Field(ge=1)
    journal_revision: int = Field(ge=0)
    idempotency_key: Ref


class ForecastRequest(Mutation):
    work_id: Ref
    scope_id: Ref
    task_family: Ref
    scope_kind: Literal["whole_episode", "remaining_episode"]
    scope_start: Instant | None = None
    baseline: Estimate | None = None
    baseline_policy: Ref = "declared-v1"
    baseline_origin: Ref = "student_estimate"
    user_override: Estimate | None = None


class WorkLog(Mutation):
    work_id: Ref
    scope_id: Ref
    observation_id: Ref
    expected_observation_revision: int = Field(ge=0)
    scope_start: Instant
    through: Instant
    completed: bool
    complete_coverage: bool
    minutes: Minutes | None = None
    sessions: tuple[Interval, ...] = Field(default=(), max_length=32)
    pauses: tuple[Interval, ...] = Field(default=(), max_length=32)
    retracted: bool = False
    representation_group: Ref | None = None
    correction_reason: Ref | None = None
    basis: Ref = "student_recorded_active_time"

    @model_validator(mode="after")
    def valid(self):
        if self.scope_start > self.through:
            raise ValueError("Measurement boundary is reversed.")
        if self.minutes is not None and self.sessions:
            raise ValueError("Choose one measured representation.")
        if any(s.start < self.scope_start or s.end > self.through for s in self.sessions):
            raise ValueError("Sessions must belong to this measured scope.")
        if any(
            not any(s.start <= p.start and p.end <= s.end for s in self.sessions)
            for p in self.pauses
        ):
            raise ValueError("A pause must belong to an active session.")
        return self


def journal_key(record):
    return fingerprint(["effort-plan-v1", record.scope.model_dump(mode="json")])


async def authorize(service, owner, record_id):
    service.enabled()
    record = rd.snapshot(service.repository, owner, record_id)
    bindings = {
        (b.get("document_id"), b.get("content_hash")): rd.Binding.model_validate(b)
        for b in record.data["bindings"]
    }
    key = journal_key(record)
    # No caller-supplied principal or institutional scope enters the journal lookup.
    with service.repository.store.transaction() as session:
        _, state = service.repository._load(session, owner)
        prev = state.records.get(key)
        if prev:
            service.repository._require(session, owner, prev)
            if prev.data.get("payload_type") != "effort_plan":
                failure("PROCESS_RECORD_NOT_VALID")
    if prev:
        for i, t in enumerate(prev.sources):
            bindings.setdefault(
                (t.id, t.version),
                rd.Binding(
                    logical_id=f"s{i}", role="other", document_id=t.id, content_hash=t.version
                ),
            )
    # Reauthorize each distinct exact source once per call, even when both the
    # assignment and its journal bind it. Each decision consumes a bounded receipt.
    await rd.authorize_bindings(service.bridge, owner, bindings.values(), planning=True)
    return record, prev


def eligible(record):
    if record.data.get("pending_change"):
        failure("EFFORT_REVIEW_PENDING")
    return {
        w["work_id"]: w
        for w in rd.project(record.data, record.data["requirements"])["remaining_work"]
    }


def episode(work, record_id):
    return work.get("episode_id") or fingerprint([record_id, work["work_id"], "episode"])


def mutate(service, owner, record, request, update, *, extra_bases=()):
    key = journal_key(record)

    def build(prior, now):
        data = (
            deepcopy(prior.data)
            if prior
            else dict(
                payload_type="effort_plan",
                forecasts=[],
                measurements=[],
                plans=[],
            )
        )
        update(data, now)
        tags = {t.key: t for t in (*record.sources, *(prior.sources if prior else ()))}
        return AcademicRecord(
            id=key,
            kind="plan",
            revision=request.journal_revision + 1,
            scope=record.scope,
            data=data,
            sources=tuple(tags.values()),
            updated_at=now,
        )

    receipt = service.repository.save_readiness(
        owner,
        key,
        request.journal_revision,
        request.idempotency_key,
        fingerprint([type(request).__name__, request.model_dump(mode="json")]),
        build,
        payload_type="effort_plan",
        required_bases=[(record.id, request.work_revision), *extra_bases],
    )
    return receipt


def histories(data, cutoff):
    issues = defaultdict(list)
    measures = defaultdict(list)
    for f in data["forecasts"]:
        issues[(f["episode_id"], f["scope_id"])].append(f)
    for m in data["measurements"]:
        if datetime.fromisoformat(m["known_at"]) <= cutoff:
            measures[(m["episode_id"], m["scope_id"])].append(m)
    output = []
    for key, rows in measures.items():
        selected = {}
        for m in rows:
            if (
                m["observation_id"] not in selected
                or m["revision"] > selected[m["observation_id"]]["revision"]
            ):
                selected[m["observation_id"]] = m
        active = [m for m in selected.values() if not m["retracted"]]
        if not active or key not in issues:
            continue
        final = max(active, key=lambda m: (m["through"], m["known_at"]))
        readings = []
        for m in active:
            for i, s in enumerate(m["sessions"]):
                readings.append(
                    Reading(
                        observation_id=fingerprint([m["observation_id"], i]),
                        revision=m["revision"],
                        known_at=m["known_at"],
                        scope_id=key[1],
                        kind="active_interval",
                        basis=m["basis"],
                        representation_group=m.get("representation_group"),
                        **s,
                        pauses=[
                            p
                            for p in m["pauses"]
                            if datetime.fromisoformat(s["start"])
                            <= datetime.fromisoformat(p["start"])
                            and datetime.fromisoformat(p["end"]) <= datetime.fromisoformat(s["end"])
                        ],
                    )
                )
            if m["minutes"] is not None:
                readings.append(
                    Reading(
                        observation_id=m["observation_id"],
                        revision=m["revision"],
                        known_at=m["known_at"],
                        scope_id=key[1],
                        kind="duration_total",
                        basis=m["basis"],
                        representation_group=m.get("representation_group"),
                        minutes=m["minutes"],
                    )
                )
        # Different issue policies/families retain their own training populations.
        groups = defaultdict(list)
        for f in issues[key]:
            groups[
                (f["task_family"], f["scope_kind"], f["baseline_policy"], f["scope_start"])
            ].append(f)
        for (family, kind, policy, boundary), predictions in groups.items():
            start = datetime.fromisoformat(boundary)
            earliest = datetime.fromisoformat(final["scope_start"])
            scoped = readings
            if start != earliest:
                if (
                    kind != "remaining_episode"
                    or not earliest < start < datetime.fromisoformat(final["through"])
                    or not readings
                    or any(r.kind != "active_interval" for r in readings)
                ):
                    continue
                scoped = [
                    r.model_copy(
                        update={
                            "start": max(start, r.start),
                            "pauses": tuple(
                                p.model_copy(update={"start": max(start, p.start)})
                                for p in r.pauses
                                if p.end > start
                            ),
                        }
                    )
                    for r in readings
                    if r.end > start
                ]
                if not scoped:
                    continue
            frozen = [
                Issued(
                    forecast_id=f["forecast_id"],
                    scope_id=key[1],
                    frozen_at=f["cutoff"],
                    known_at=f["cutoff"],
                    baseline=f["baseline"],
                    published=f["published"],
                    baseline_origin=f["baseline_origin"],
                    baseline_policy=policy,
                    budget=f["planning_budget_minutes"],
                )
                for f in predictions
            ]
            output.append(
                HistoryScope(
                    history_id=fingerprint([*key, family, kind, policy, boundary]),
                    user_id=final["owner_key"],
                    task_family=family,
                    scope_kind=kind,
                    baseline_policy=policy,
                    episode_id=key[0],
                    scope_id=key[1],
                    scope_start_at=start,
                    scope_end_at=final["through"],
                    completion=Completion(
                        complete=final["completed"],
                        completed_at=final["through"] if final["completed"] else None,
                        known_at=final["known_at"],
                        basis=final["basis"],
                    ),
                    coverage=Coverage(
                        state="complete" if final["complete_coverage"] else "partial",
                        known_at=final["known_at"],
                        basis=final["basis"],
                    ),
                    forecasts=frozen,
                    observations=scoped,
                )
            )
    return output


async def log_work(service, owner, request):
    record, _ = await authorize(service, owner, request.record_id)

    def update(data, now):
        prior = [m for m in data["measurements"] if m["observation_id"] == request.observation_id]
        if len(prior) != request.expected_observation_revision:
            failure("PROCESS_REVISION_MISMATCH")
        old = prior[-1] if prior else None
        w = None if old else eligible(record).get(request.work_id)
        if old and (old["record_id"], old["work_id"], old["scope_id"], old["scope_start"]) != (
            record.id,
            request.work_id,
            request.scope_id,
            request.scope_start.isoformat(),
        ):
            failure("EFFORT_SCOPE_MISMATCH")
        if not old and not w:
            failure("READINESS_WORK_UNAVAILABLE")
        if request.through > now:
            failure("EFFORT_FUTURE_ACTUAL")
        info = request.model_dump(
            mode="json",
            exclude={"idempotency_key", "journal_revision", "expected_observation_revision"},
        )
        info.update(
            scope_start=request.scope_start.isoformat(),
            through=request.through.isoformat(),
            episode_id=old["episode_id"] if old else episode(w, record.id),
            revision=len(prior) + 1,
            known_at=now.isoformat(),
            owner_key=fingerprint(owner),
        )
        if any(
            m["episode_id"] == info["episode_id"]
            and m["scope_id"] == info["scope_id"]
            and m["scope_start"] != info["scope_start"]
            for m in data["measurements"]
        ):
            failure("EFFORT_SCOPE_MISMATCH")
        if len(data["measurements"]) >= 500:
            failure("PROCESS_STORAGE_BUDGET")
        same_scope = {
            m["observation_id"]: m
            for m in [*data["measurements"], info]
            if (m["episode_id"], m["scope_id"]) == (info["episode_id"], info["scope_id"])
        }
        if sum(max(1, len(m["sessions"])) for m in same_scope.values() if not m["retracted"]) > 256:
            failure("PROCESS_STORAGE_BUDGET")
        data["measurements"].append(info)

    return Result(
        summary="Scoped effort observation saved.",
        data=mutate(service, owner, record, request, update),
    )


def stale_forecast(data, issue, cutoff):
    """Only changes to this episode or its eligible calibration population affect demand."""
    when = datetime.fromisoformat(issue["cutoff"])
    changed = [m for m in data["measurements"] if datetime.fromisoformat(m["known_at"]) > when]
    if not changed:
        return False
    if any(
        (m["episode_id"], m["scope_id"]) == (issue["episode_id"], issue["scope_id"])
        for m in changed
    ):
        return True
    target = Target(
        forecast_id=issue["forecast_id"],
        scope_id=issue["scope_id"],
        episode_id=issue["episode_id"],
        user_id=changed[0]["owner_key"],
        cutoff=cutoff,
        task_family=issue["task_family"],
        scope_kind=issue["scope_kind"],
        baseline_policy=issue["baseline_policy"],
        baseline=issue["baseline"],
        baseline_origin=issue["baseline_origin"],
    )
    return (
        forecast(histories(data, cutoff), target)["training_snapshot_id"]
        != issue["training_snapshot_id"]
    )


async def issue(service, owner, request):
    record, _ = await authorize(service, owner, request.record_id)

    def update(data, now):
        w = eligible(record).get(request.work_id)
        if w is None:
            failure("READINESS_WORK_UNAVAILABLE")
        start = request.scope_start or now
        if start < now:
            previous_boundary = any(
                f["scope_id"] == request.scope_id
                and f["episode_id"] == episode(w, record.id)
                and datetime.fromisoformat(f["scope_start"]) == start
                for f in data["forecasts"]
            )
            if not previous_boundary or request.scope_kind != "remaining_episode":
                failure("EFFORT_FORECAST_BOUNDARY")
            # A refreshed remaining-work prediction begins at issue time; its original
            # prediction and the explicitly measured earlier boundary remain frozen.
            start = now
        known = None if w.get("effort_review_needed") else w.get("effort")
        episode_measurements = [
            m for m in data["measurements"] if m["episode_id"] == episode(w, record.id)
        ]
        latest_observations = {m["observation_id"]: m for m in episode_measurements}
        active_observations = [m for m in latest_observations.values() if not m["retracted"]]
        if (
            known
            and request.scope_kind == "remaining_episode"
            and any(
                not known.get("as_of")
                or datetime.fromisoformat(known["as_of"]) < datetime.fromisoformat(m["through"])
                for m in active_observations
            )
        ):
            known = None
        baseline = request.baseline or (
            Estimate(
                low=known["minimum_minutes"],
                high=known["maximum_minutes"],
                point=known.get("point_estimate_minutes"),
            )
            if known
            else Estimate()
        )
        previous_override = next(
            (
                f.get("manual_override")
                for f in reversed(data["forecasts"])
                if (f["episode_id"], f["scope_id"]) == (episode(w, record.id), request.scope_id)
            ),
            None,
        )
        override = (
            Override(
                override_id=fingerprint([record.id, request.idempotency_key]),
                scope_id=request.scope_id,
                episode_id=episode(w, record.id),
                known_at=now,
                values=request.user_override,
                basis="explicit_user_remaining_estimate",
            )
            if request.user_override
            else previous_override
        )
        measurements = [
            m
            for m in data["measurements"]
            if (m["work_id"], m["episode_id"], m["scope_id"])
            == (w["work_id"], episode(w, record.id), request.scope_id)
        ]
        current = {m["observation_id"]: m for m in measurements}
        completed = any(
            m["completed"] and m["complete_coverage"] and not m["retracted"]
            for m in current.values()
        )
        t = Target(
            forecast_id=fingerprint([journal_key(record), request.idempotency_key]),
            scope_id=request.scope_id,
            episode_id=episode(w, record.id),
            user_id=fingerprint(owner),
            cutoff=now,
            task_family=request.task_family,
            baseline_policy=request.baseline_policy,
            baseline=baseline,
            baseline_origin=request.baseline_origin
            if request.baseline or not known
            else known["origin"],
            scope_kind=request.scope_kind,
            manual_override=override,
            completed=completed or w["progress_state"] == "student_marked_done",
        )
        f = forecast(histories(data, now), t)
        f.update(
            record_id=record.id,
            work_id=w["work_id"],
            work_revision=record.revision,
            personal_progress=w["progress_state"],
            progress_basis=w.get("progress_basis", "unknown"),
            current_observation_refs=[
                f"{m['observation_id']}@{m['revision']}"
                for m in active_observations
                if m["scope_id"] == request.scope_id
            ],
            baseline_basis="explicit_current_estimate"
            if request.baseline
            else "current_saved_effort"
            if known
            else "missing_current_baseline",
            lineage_id=w.get("lineage_id"),
            scope_start=start.isoformat(),
            scope_kind=t.scope_kind,
            task_family=t.task_family,
            baseline_policy=t.baseline_policy,
            manual_override=t.manual_override.model_dump(mode="json")
            if t.manual_override
            else None,
        )
        if (
            len(data["forecasts"]) >= 200
            or sum(
                (old["scope_id"], old["episode_id"]) == (f["scope_id"], f["episode_id"])
                for old in data["forecasts"]
            )
            >= 80
        ):
            failure("PROCESS_STORAGE_BUDGET")
        data["forecasts"].append(f)

    receipt = mutate(service, owner, record, request, update)
    # A retry returns the exact frozen issue even after a later correction or forecast.
    saved = service.repository.read(owner, journal_key(record))
    f = next(
        f
        for f in saved.data["forecasts"]
        if f["forecast_id"] == fingerprint([saved.id, request.idempotency_key])
    )
    return Result(
        summary="Frozen scoped effort forecast.",
        data=receipt | {"forecast": f},
        sources=service.citations(owner, saved.sources),
    )
