"""One durable lock order: governor -> period -> pool -> attempt -> throttle.

SQLite uses BEGIN IMMEDIATE; PostgreSQL locks a singleton row. No network work
occurs in these transactions. The global row also serializes cross-contract
technical concurrency. A local ceiling is not a guarantee about a vendor invoice.
"""

import hashlib
import math
import time
from collections import deque
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import RLock
from weakref import WeakKeyDictionary

from sqlalchemy import case, delete, func, insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from canvas_bridge.domain import DomainError
from canvas_bridge.request_limits import retry_after
from canvas_bridge.usage import models as m
from canvas_bridge.usage.policy import (
    POOLS,
    ContractBillingAdapter,
    PartnerBudgetContract,
    canonical,
)

ACTIVE = ("RESERVED", "SENT")
HELD = (*ACTIVE, "UNCERTAIN")
REMEDIES = {
    "PROVIDER_NOT_AUTHORIZED": "Provider access is disabled; review connection authorization.",
    "BILLING_CONTRACT_UNCONFIGURED": "Upstream refresh is unavailable pending operator configuration.",
    "UPSTREAM_BUDGET_EXHAUSTED": "Upstream refresh capacity is exhausted; use permitted local information.",
    "WORKLOAD_POOL_DEFERRED": "This retrieval is deferred; narrow the request or use permitted local information.",
    "OWNER_RATE_LIMITED": "Request capacity for this account is temporarily unavailable.",
    "TASK_BUDGET_EXCEEDED": "This task reached its retrieval limit; results may be incomplete.",
    "UPSTREAM_THROTTLED": "Provider access is temporarily throttled or cooling down; try again later.",
    "LOCAL_REQUEST_BUSY": "Another request is using available Canvas request capacity. Wait for it to finish, then retry; reconnecting is not required.",
    "UPSTREAM_CIRCUIT_OPEN": "Provider access is paused while a recovery probe is active.",
    "GOVERNOR_UNAVAILABLE": "Upstream accounting is unavailable; local work may continue.",
}


def deny(code, **observations):
    raise DomainError(
        "permission_denied" if code == "PROVIDER_NOT_AUTHORIZED" else "retry_later",
        REMEDIES[code],
        reason_code=code,
        details={
            **observations,
            "cached_information": "requires_current_authorization",
            "local_processing_available": True,
        },
    )


def digest(*parts):
    return hashlib.sha256(canonical(parts)).hexdigest()


def row(db, table, condition):
    return db.execute(select(table).where(condition)).mappings().first()


class UpstreamUsageGovernor:
    def __init__(
        self, engine, *, fixture_policy=None, development_policy=None, clock=time.time, adapter=None
    ):
        self.engine, self.fixture_policy, self.clock = engine, fixture_policy, clock
        self.development_policy = development_policy
        self.adapter = adapter or ContractBillingAdapter()
        # Serializes StaticPool's one SQLite connection in synthetic tests only.
        self.local_lock = RLock()
        self.queues = WeakKeyDictionary()
        self.admission_samples = deque(maxlen=2048)

    @contextmanager
    def transaction(self):
        try:
            with self.local_lock, self.engine.connect() as db:
                if db.dialect.name == "sqlite":
                    db.exec_driver_sql("BEGIN IMMEDIATE")
                    from sqlalchemy.dialects.sqlite import insert as upsert
                else:
                    from sqlalchemy.dialects.postgresql import insert as upsert
                db.execute(upsert(m.lock).values(id=1).on_conflict_do_nothing())
                db.execute(select(m.lock).where(m.lock.c.id == 1).with_for_update())
                try:
                    yield db
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
        except SQLAlchemyError:
            deny("GOVERNOR_UNAVAILABLE")

    def policy(self, db, provider="canvas", now=None):
        now = self.clock() if now is None else now
        if db.scalar(select(m.lock.c.restore_hold).where(m.lock.c.id == 1)):
            deny("GOVERNOR_UNAVAILABLE")
        record = (
            db.execute(
                select(m.contracts)
                .where(m.contracts.c.provider == provider, m.contracts.c.effective <= now)
                .order_by(m.contracts.c.effective.desc(), m.contracts.c.version.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        if record:
            policy = PartnerBudgetContract.model_validate(record["policy"])
        elif self.fixture_policy and self.fixture_policy.provider == provider:
            policy = self.fixture_policy
            self._insert_policy(db, policy, "synthetic-fixture")
        elif self.development_policy and self.development_policy.provider == provider:
            policy = self.development_policy
            self._insert_policy(db, policy, "personal-development-operator")
        else:
            deny("BILLING_CONTRACT_UNCONFIGURED")
        if policy.mode == "personal_development":
            if self.development_policy is None:
                deny("PROVIDER_NOT_AUTHORIZED")
            # A lowered ceiling takes effect immediately; consumption retains its identity.
            data = policy.model_dump(mode="json")
            data["billing"]["monthly_allowance"] = self.development_policy.billing.monthly_allowance
            data["limits"] = self.development_policy.limits.model_dump(mode="json")
            policy = PartnerBudgetContract.model_validate(data)
            if not row(db, m.contracts, m.contracts.c.id == policy.digest):
                self._insert_policy(db, policy, "personal-development-operator")
        if policy.kill_switch:
            deny("PROVIDER_NOT_AUTHORIZED")
        if (
            policy.billing.status == "unconfigured"
            or not policy.effective_at.timestamp() <= now < policy.expires_at.timestamp()
        ):
            deny("BILLING_CONTRACT_UNCONFIGURED")
        return policy

    def _insert_policy(self, db, policy, actor):
        db.execute(
            insert(m.contracts).values(
                id=policy.digest,
                provider=policy.provider,
                contract=policy.contract_id,
                version=policy.version,
                effective=policy.effective_at.timestamp(),
                policy=policy.model_dump(mode="json"),
                actor=digest(actor),
                created=self.clock(),
            )
        )

    def activate(self, policy, actor, *, expected_digest):
        """Caller must verify an operator signature; compare-and-swap prevents stale apply."""
        with self.transaction() as db:
            latest = (
                db.execute(
                    select(m.contracts)
                    .where(m.contracts.c.provider == policy.provider)
                    .order_by(m.contracts.c.version.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if (latest["id"] if latest else None) != expected_digest:
                raise ValueError("Policy changed; propose and review again.")
            if latest:
                old = PartnerBudgetContract.model_validate(latest["policy"])
                if policy.version <= old.version or policy.effective_at < old.effective_at:
                    raise ValueError("Policy versions and activation dates must increase.")
                # A changed contract/calendar cannot reset a current allowance.
                if policy.effective_at < old.cycle(datetime.fromtimestamp(self.clock(), UTC))[
                    1
                ] and (
                    policy.contract_id != old.contract_id
                    or policy.billing.cycle_timezone != old.billing.cycle_timezone
                    or policy.billing.cycle_day != old.billing.cycle_day
                ):
                    raise ValueError("Contract/calendar changes require a new billing cycle.")
                semantics = (
                    "charge_model",
                    "default_units",
                    "operation_units",
                    "failed_requests",
                    "pagination",
                    "retries",
                    "redirects",
                    "file_downloads",
                    "oauth",
                )
                if any(getattr(old.billing, k) != getattr(policy.billing, k) for k in semantics):
                    raise ValueError(
                        "Counting changes require a reviewed adapter migration, not an allowance update."
                    )
                if (
                    policy.billing.signed_allowance != old.billing.signed_allowance
                    and policy.billing.evidence_sha256 == old.billing.evidence_sha256
                ):
                    raise ValueError("A signed allowance change requires new contract evidence.")
            if policy.effective_at.timestamp() < self.clock() - 300:
                raise ValueError("Backdated policy activation is forbidden.")
            self._insert_policy(db, policy, actor)
        return policy.digest

    def _period(self, db, policy, now):
        start, end = policy.cycle(datetime.fromtimestamp(now, UTC))
        key = digest(policy.provider, policy.contract_id, start.isoformat(), end.isoformat())
        current = row(db, m.periods, m.periods.c.id == key)
        if not current:
            db.execute(
                insert(m.periods).values(
                    id=key,
                    provider=policy.provider,
                    contract=policy.contract_id,
                    start=start.timestamp(),
                    end=end.timestamp(),
                    policy=policy.digest,
                    usable=policy.usable,
                    settled=0,
                    reserved=0,
                    uncertain=0,
                    external=policy.billing.external_usage_buffer_units,
                    quarantined=0,
                    version=1,
                )
            )
            for name, target in policy.targets().items():
                db.execute(
                    insert(m.pools).values(
                        period=key, name=name, target=target, booked=0, borrowed=0
                    )
                )
        elif current["policy"] != policy.digest:
            db.execute(
                update(m.periods)
                .where(m.periods.c.id == key)
                .values(
                    policy=policy.digest,
                    usable=policy.usable,
                    version=current["version"] + 1,
                    external=max(current["external"], policy.billing.external_usage_buffer_units),
                )
            )
            for name, target in policy.targets().items():
                db.execute(
                    update(m.pools)
                    .where(m.pools.c.period == key, m.pools.c.name == name)
                    .values(target=target)
                )
        return row(db, m.periods, m.periods.c.id == key)

    def _event(self, db, period, kind, *, once=False):
        key = digest(period, kind)
        old = row(db, m.events, m.events.c.id == key)
        if old and not once:
            db.execute(update(m.events).where(m.events.c.id == key).values(count=old["count"] + 1))
        elif not old:
            db.execute(
                insert(m.events).values(
                    id=key, period=period, kind=kind, count=1, created=self.clock()
                )
            )

    def _recover(self, db, now):
        for attempt in (
            db.execute(
                select(m.attempts).where(
                    m.attempts.c.state.in_(ACTIVE), m.attempts.c.expires <= now
                )
            )
            .mappings()
            .all()
        ):
            # RESERVED means our authoritative SENT transition never committed.
            self._finish(
                db,
                attempt,
                "CANCELLED_BEFORE_SEND" if attempt["state"] == "RESERVED" else "UNCERTAIN",
                0,
            )

    def reserve(self, ctx, *, authorize, operation, mode):
        started = time.perf_counter()
        authorize()  # No authority flag supplied by a model can replace this callback.
        code = None
        pending_reservation = False
        with self.transaction() as db:
            now = self.clock()
            self._recover(db, now)
            policy = self.policy(db, ctx.provider_id, now)
            if (
                policy.mode != mode
                or ctx.workload_class not in POOLS[:-1]
                or operation.name != ctx.operation
            ):
                deny("PROVIDER_NOT_AUTHORIZED")
            if ctx.contract_id and ctx.contract_id != policy.contract_id:
                deny("PROVIDER_NOT_AUTHORIZED")
            existing = row(db, m.attempts, m.attempts.c.id == ctx.attempt_id)
            if existing:
                # Never return a second send permit for the same idempotency key.
                deny("TASK_BUDGET_EXCEEDED")
            period = self._period(db, policy, now)
            amount = self.adapter.reserve(policy, ctx.operation)
            if type(amount) is not int or not 0 <= amount <= 10**12:
                deny("BILLING_CONTRACT_UNCONFIGURED")
            used = period["settled"] + period["reserved"] + period["uncertain"] + period["external"]
            contract_quarantined = db.scalar(
                select(func.count())
                .select_from(m.periods)
                .where(
                    m.periods.c.provider == policy.provider,
                    m.periods.c.contract == policy.contract_id,
                    m.periods.c.quarantined != 0,
                )
            )
            if contract_quarantined or used + amount > period["usable"]:
                code = "UPSTREAM_BUDGET_EXHAUSTED"
            limits = policy.limits
            for seconds, cap in (
                (60, limits.per_owner_minute_attempts),
                (3600, limits.per_owner_hour_attempts),
                (86400, limits.per_owner_daily_attempts),
            ):
                count = db.scalar(
                    select(func.count())
                    .select_from(m.attempts)
                    .where(m.attempts.c.owner == ctx.owner_id, m.attempts.c.created > now - seconds)
                )
                if count >= cap:
                    code = code or "OWNER_RATE_LIMITED"
            task = db.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(m.attempts.c.reservation), 0),
                    func.min(m.attempts.c.created),
                ).where(m.attempts.c.task == ctx.task_id, m.attempts.c.owner == ctx.owner_id)
            ).one()
            if (
                task[0] >= min(limits.max_attempts_per_task, operation.max_requests)
                or task[1] + amount > limits.max_units_per_task
                or (task[2] is not None and now - task[2] >= limits.task_seconds)
            ):
                code = code or "TASK_BUDGET_EXCEEDED"
            body_usage = db.scalar(
                select(
                    func.coalesce(
                        func.sum(
                            case(
                                (m.attempts.c.state.in_(ACTIVE), m.attempts.c.max_body_bytes),
                                else_=m.attempts.c.body_bytes,
                            )
                        ),
                        0,
                    )
                ).where(m.attempts.c.task == ctx.task_id, m.attempts.c.owner == ctx.owner_id)
            )
            if body_usage + operation.max_body_bytes > limits.max_bytes_per_task:
                code = code or "TASK_BUDGET_EXCEEDED"
            if ctx.operation == "canvas.file_download":
                downloads = db.scalar(
                    select(func.count())
                    .select_from(m.attempts)
                    .where(
                        m.attempts.c.task == ctx.task_id,
                        m.attempts.c.owner == ctx.owner_id,
                        m.attempts.c.operation == ctx.operation,
                    )
                )
                if downloads >= limits.max_download_attempts_per_task:
                    code = code or "TASK_BUDGET_EXCEEDED"
            if limits.per_tenant_daily_units is not None:
                tenant_units = db.scalar(
                    select(func.coalesce(func.sum(m.attempts.c.reservation), 0)).where(
                        m.attempts.c.tenant == ctx.tenant_id, m.attempts.c.created > now - 86400
                    )
                )
                if tenant_units + amount > limits.per_tenant_daily_units:
                    code = code or "OWNER_RATE_LIMITED"
            for condition, cap in (
                (m.attempts.c.token == ctx.token_key, limits.max_concurrency_per_token),
                (m.attempts.c.owner == ctx.owner_id, limits.max_concurrency_per_owner),
                (m.attempts.c.tenant == ctx.tenant_id, limits.max_concurrency_per_tenant),
                (
                    True,
                    limits.max_global_concurrency
                    - (limits.interactive_slots if ctx.workload_class != "interactive" else 0),
                ),
            ):
                active = db.scalar(
                    select(func.count())
                    .select_from(m.attempts)
                    .where(m.attempts.c.state.in_(ACTIVE), condition)
                )
                if active >= cap:
                    code = code or "LOCAL_REQUEST_BUSY"
            throttle = row(db, m.throttles, m.throttles.c.id == ctx.token_key)
            if throttle and throttle["blocked_until"] > now:
                code = code or "UPSTREAM_THROTTLED"
            if throttle and throttle["failures"] >= limits.circuit_failures:
                probes = db.scalar(
                    select(func.count())
                    .select_from(m.attempts)
                    .where(m.attempts.c.token == ctx.token_key, m.attempts.c.state.in_(ACTIVE))
                )
                if probes:
                    code = code or "UPSTREAM_CIRCUIT_OPEN"
            threshold = (
                policy.pause_exploratory_pct
                if ctx.workload_class == "exploratory"
                else policy.pause_sync_pct
            )
            if ctx.workload_class != "interactive" and used * 100 >= period["usable"] * threshold:
                code = code or "WORKLOAD_POOL_DEFERRED"
            allocation = self._allocate(db, period, policy, ctx, amount)
            if allocation is None:
                code = code or "WORKLOAD_POOL_DEFERRED"
            if code:
                if code == "LOCAL_REQUEST_BUSY":
                    # Only describe a reservation belonging to the current owner
                    # and connection. It can finish or expire before a retry.
                    pending_reservation = (
                        db.scalar(
                            select(m.attempts.c.expires)
                            .where(
                                m.attempts.c.owner == ctx.owner_id,
                                m.attempts.c.token == ctx.token_key,
                                m.attempts.c.state == "RESERVED",
                                m.attempts.c.expires > now,
                            )
                            .limit(1)
                        )
                        is not None
                    )
                self._event(db, period["id"], code)
            else:
                db.execute(
                    insert(m.attempts).values(
                        id=ctx.attempt_id,
                        parent=ctx.parent_attempt_id,
                        period=period["id"],
                        policy=policy.digest,
                        owner=ctx.owner_id,
                        tenant=ctx.tenant_id,
                        task=ctx.task_id,
                        token=ctx.token_key,
                        operation=ctx.operation,
                        workload=ctx.workload_class,
                        state="RESERVED",
                        reservation=amount,
                        settled=0,
                        allocation=allocation,
                        created=now,
                        expires=now + limits.reservation_seconds,
                        max_body_bytes=operation.max_body_bytes,
                    )
                )
                db.execute(
                    update(m.periods)
                    .where(m.periods.c.id == period["id"])
                    .values(reserved=period["reserved"] + amount)
                )
                for pool, units in allocation.items():
                    db.execute(
                        update(m.pools)
                        .where(m.pools.c.period == period["id"], m.pools.c.name == pool)
                        .values(booked=m.pools.c.booked + units)
                    )
                borrowed = sum(u for p, u in allocation.items() if p != ctx.workload_class)
                db.execute(
                    update(m.pools)
                    .where(m.pools.c.period == period["id"], m.pools.c.name == ctx.workload_class)
                    .values(borrowed=m.pools.c.borrowed + borrowed)
                )
                self._event(db, period["id"], "admitted")
                for threshold in policy.usage_thresholds_pct:
                    if (used + amount) * 100 >= period["usable"] * threshold:
                        self._event(db, period["id"], "threshold_" + str(threshold), once=True)
        self.admission_samples.append((time.perf_counter() - started) * 1000)
        if code:
            if pending_reservation:
                deny(code, reservation_state="expiration_pending")
            if code == "UPSTREAM_THROTTLED":
                deny(
                    code,
                    blocking_scope="cooldown",
                    retry_after_seconds=math.ceil(throttle["blocked_until"] - now),
                )
            if code == "UPSTREAM_BUDGET_EXHAUSTED" and not contract_quarantined:
                deny(
                    code,
                    blocking_scope="usage_window",
                    retry_after_seconds=math.ceil(period["end"] - now),
                )
            deny(code)
        return policy

    def _allocate(self, db, period, policy, ctx, amount):
        entries = {
            p["name"]: p
            for p in db.execute(select(m.pools).where(m.pools.c.period == period["id"])).mappings()
        }
        order = [ctx.workload_class]
        if policy.allocation.pool_mode != "strict_pools":
            order += [p for p in POOLS[:-1] if p != ctx.workload_class]
        if ctx.operation in policy.allocation.reserve_eligible_operations:
            order += ["reserve"]
        allocation, remaining = {}, amount
        for name in order:
            entry = entries[name]
            floor = (
                int(entry["target"] * policy.allocation.lender_floor_pct / 100)
                if name not in (ctx.workload_class, "reserve")
                else 0
            )
            units = min(remaining, max(0, entry["target"] - entry["booked"] - floor))
            allocation[name] = units
            remaining -= units
        return allocation if remaining == 0 else None

    def sent(self, attempt_id, authorize):
        authorize()
        with self.transaction() as db:
            attempt = row(db, m.attempts, m.attempts.c.id == attempt_id)
            if not attempt or attempt["state"] != "RESERVED" or attempt["expires"] <= self.clock():
                deny("GOVERNOR_UNAVAILABLE")
            recorded = row(db, m.contracts, m.contracts.c.id == attempt["policy"])
            policy = self.policy(db, recorded["provider"])
            if policy.digest != attempt["policy"]:
                deny("GOVERNOR_UNAVAILABLE")
            period = row(db, m.periods, m.periods.c.id == attempt["period"])
            if not period["start"] <= self.clock() < period["end"]:
                deny("WORKLOAD_POOL_DEFERRED")
            if db.scalar(
                select(func.count())
                .select_from(m.periods)
                .where(
                    m.periods.c.provider == policy.provider,
                    m.periods.c.contract == policy.contract_id,
                    m.periods.c.quarantined != 0,
                )
            ):
                deny("UPSTREAM_BUDGET_EXHAUSTED")
            throttle = row(db, m.throttles, m.throttles.c.id == attempt["token"])
            if throttle and throttle["blocked_until"] > self.clock():
                deny(
                    "UPSTREAM_THROTTLED",
                    blocking_scope="cooldown",
                    retry_after_seconds=max(0, math.ceil(throttle["blocked_until"] - self.clock())),
                )
            db.execute(update(m.attempts).where(m.attempts.c.id == attempt_id).values(state="SENT"))

    def _finish(self, db, attempt, state, units):
        if attempt["state"] not in ACTIVE:
            return
        held = attempt["reservation"] if state == "UNCERTAIN" else 0
        refund = attempt["reservation"] - held - units
        db.execute(
            update(m.periods)
            .where(m.periods.c.id == attempt["period"])
            .values(
                reserved=m.periods.c.reserved - attempt["reservation"],
                settled=m.periods.c.settled + units,
                last_settled_at=self.clock()
                if state in {"SETTLED", "RECONCILED"}
                else m.periods.c.last_settled_at,
                uncertain=m.periods.c.uncertain + held,
            )
        )
        # Deterministic refunds undo borrowed/reserve allocations before own pool.
        allocation = dict(attempt["allocation"])
        for pool in reversed(list(allocation)):
            returned = min(max(0, refund), allocation[pool])
            allocation[pool] -= returned
            refund -= returned
            db.execute(
                update(m.pools)
                .where(m.pools.c.period == attempt["period"], m.pools.c.name == pool)
                .values(booked=m.pools.c.booked - returned)
            )
            if pool != attempt["workload"]:
                db.execute(
                    update(m.pools)
                    .where(
                        m.pools.c.period == attempt["period"], m.pools.c.name == attempt["workload"]
                    )
                    .values(borrowed=m.pools.c.borrowed - returned)
                )
        db.execute(
            update(m.attempts)
            .where(m.attempts.c.id == attempt["id"])
            .values(state=state, settled=units, allocation=allocation, settled_at=self.clock())
        )

    def finish(
        self,
        attempt_id,
        *,
        status=None,
        headers=None,
        failed=False,
        actual_units=None,
        body_bytes=0,
        throttled=False,
    ):
        exception = False
        with self.transaction() as db:
            attempt = row(db, m.attempts, m.attempts.c.id == attempt_id)
            if not attempt or attempt["state"] not in ACTIVE:
                return
            policy = PartnerBudgetContract.model_validate(
                row(db, m.contracts, m.contracts.c.id == attempt["policy"])["policy"]
            )
            headers = headers or {}
            uncertain = (
                failed
                or status is None
                or (
                    (status in (403, 429) or status >= 500)
                    and policy.billing.failed_requests != "verified_nonbillable"
                )
            )
            units = (
                actual_units
                if actual_units is not None
                else self.adapter.settle(policy, attempt["operation"], status or 599)
            )
            if type(units) is not int or not 0 <= units <= attempt["reservation"]:
                # Keep the local upper bound held; separately quarantine the mismatch.
                db.execute(
                    update(m.periods)
                    .where(m.periods.c.id == attempt["period"])
                    .values(quarantined=1)
                )
                self._event(db, attempt["period"], "ACCOUNTING_EXCEPTION", once=True)
                exception, uncertain, units = True, True, 0
            state = (
                "CANCELLED_BEFORE_SEND"
                if attempt["state"] == "RESERVED"
                else "UNCERTAIN"
                if uncertain
                else "SETTLED"
            )
            self._finish(db, attempt, state, units if state == "SETTLED" else 0)
            cost = finite_header(headers.get("x-request-cost"))
            db.execute(
                update(m.attempts)
                .where(m.attempts.c.id == attempt_id)
                .values(
                    status=status,
                    throttle_cost=cost,
                    duration_ms=max(0, self.clock() - attempt["created"]) * 1000,
                    body_bytes=max(0, body_bytes),
                    reported_units=actual_units,
                )
            )
            if attempt["state"] == "SENT":
                self._throttle(db, attempt, policy, 429 if throttled else status, headers, failed)
        if exception:
            deny("GOVERNOR_UNAVAILABLE")

    def _throttle(self, db, attempt, policy, status, headers, failed):
        now, limits = self.clock(), policy.limits
        old = row(db, m.throttles, m.throttles.c.id == attempt["token"])
        failures = (
            ((old["failures"] if old else 0) + 1)
            if failed or status == 429 or (status and status >= 500)
            else 0
        )
        if not failures and old and attempt["created"] < old["updated"]:
            failures = old["failures"]
        delay = retry_after(headers.get("retry-after"), wall_time=self.clock)
        # Pathological but valid long delays fail closed; never retry sooner.
        cooldown = delay if delay is not None else 1
        interval = limits.min_interval_seconds
        remaining = finite_header(headers.get("x-rate-limit-remaining"))
        if remaining is not None and remaining < 1:
            interval = max(interval, cooldown)
        if status == 429 or (status and status >= 500):
            interval = max(interval, cooldown)
        if failures >= limits.circuit_failures:
            interval = max(interval, limits.circuit_seconds)
        values = dict(
            blocked_until=max(old["blocked_until"] if old else 0, now + interval),
            failures=failures,
            updated=now,
        )
        if old:
            db.execute(
                update(m.throttles).where(m.throttles.c.id == attempt["token"]).values(**values)
            )
        else:
            db.execute(insert(m.throttles).values(id=attempt["token"], **values))

    def cooldown_seconds(self, token):
        """A wait hint only; admission rechecks the durable state after waiting."""
        with self.transaction() as db:
            throttle = row(db, m.throttles, m.throttles.c.id == token)
            return max(0, throttle["blocked_until"] - self.clock()) if throttle else 0

    def report(self, provider="canvas", cycle=None):
        with self.transaction() as db:
            query = select(m.periods).where(m.periods.c.provider == provider)
            if cycle:
                query = query.where(m.periods.c.id == cycle)
            period = (
                db.execute(query.order_by(m.periods.c.start.desc()).limit(1)).mappings().first()
            )
            if not period:
                return {"state": "no_usage", "vendor_spend": "N/A", "approved_provider_list": []}
            result = dict(period)
            result["contract_quarantined"] = bool(
                db.scalar(
                    select(func.count())
                    .select_from(m.periods)
                    .where(
                        m.periods.c.provider == period["provider"],
                        m.periods.c.contract == period["contract"],
                        m.periods.c.quarantined != 0,
                    )
                )
            )
            recorded = row(db, m.contracts, m.contracts.c.id == period["policy"])
            policy = PartnerBudgetContract.model_validate(recorded["policy"])
            result.update(
                accounting_mode=policy.mode,
                unit=policy.billing.unit,
                vendor_allowance_verified=policy.billing.status != "local_development",
                policy_version=policy.version,
                cycle_timezone=policy.billing.cycle_timezone,
                included_allowance=policy.billing.monthly_allowance,
                safety_margin_pct=str(policy.billing.safety_margin_pct),
                period_start=datetime.fromtimestamp(period["start"], UTC).isoformat(),
                period_end=datetime.fromtimestamp(period["end"], UTC).isoformat(),
                seconds_remaining=max(0, period["end"] - self.clock()),
            )
            result["available"] = max(
                0,
                period["usable"]
                - sum(period[k] for k in ("settled", "reserved", "uncertain", "external")),
            )
            result["vendor_spend"] = period["vendor_spend"] or "N/A"
            result["pools"] = [
                dict(p)
                for p in db.execute(
                    select(m.pools).where(m.pools.c.period == period["id"])
                ).mappings()
            ]
            result["events"] = {
                e["kind"]: e["count"]
                for e in db.execute(
                    select(m.events).where(m.events.c.period == period["id"])
                ).mappings()
            }
            reserve_pool = next(p for p in result["pools"] if p["name"] == "reserve")
            result["reserve_remaining"] = max(0, reserve_pool["target"] - reserve_pool["booked"])
            result["operations"] = [
                dict(r)
                for r in db.execute(
                    select(
                        m.attempts.c.operation,
                        func.count().label("reservations"),
                        func.sum(
                            case(
                                (m.attempts.c.state.in_(("RESERVED", "CANCELLED_BEFORE_SEND")), 0),
                                else_=1,
                            )
                        ).label("attempts"),
                        func.sum(
                            case(
                                (m.attempts.c.state.in_(HELD), m.attempts.c.reservation),
                                else_=m.attempts.c.settled,
                            )
                        ).label("estimated_units"),
                        func.sum(m.attempts.c.throttle_cost).label("technical_cost"),
                    )
                    .where(m.attempts.c.period == period["id"])
                    .group_by(m.attempts.c.operation)
                ).mappings()
            ]
            result["runway_days_estimate"] = {}
            for days in (7, 30):
                recent = db.scalar(
                    select(func.coalesce(func.sum(m.attempts.c.reservation), 0)).where(
                        m.attempts.c.period == period["id"],
                        m.attempts.c.created > self.clock() - days * 86400,
                    )
                )
                result["runway_days_estimate"][str(days)] = (
                    round(result["available"] * days / recent, 2) if recent else None
                )
            result["invoice_accuracy"] = "unverified_local_admission_estimate"
            result["vendor_difference_from_local"] = (
                period["vendor_total"] - period["settled"] - period["uncertain"]
                if period["vendor_total"] is not None
                else None
            )
            cache_hits = result["events"].get("cache", 0)
            cache_misses = result["events"].get("upstream", 0) + result["events"].get(
                "conditional_revalidation", 0
            )
            result["eligible_cache_hit_rate"] = (
                cache_hits / (cache_hits + cache_misses) if cache_hits + cache_misses else None
            )
            result["coalesced_requests_saved"] = result["events"].get("coalesced", 0)
            times = sorted(self.admission_samples)
            result["local_admission_latency_ms"] = {
                "samples": len(times),
                "p50": times[len(times) // 2] if times else None,
                "p95": times[min(len(times) - 1, int(len(times) * 0.95))] if times else None,
                "scope": "this_process_bounded_sample",
            }
            return result

    def reconcile(self, statement, actor):
        with self.transaction() as db:
            key = digest("statement", statement.provider, statement.statement_id)
            prior = row(db, m.adjustments, m.adjustments.c.id == key)
            payload = statement.model_dump(mode="json")
            if prior:
                if prior["payload"] != payload:
                    raise ValueError("Statement replay differs from original.")
                return "already_recorded"
            period = row(db, m.periods, m.periods.c.id == statement.cycle)
            if (
                not period
                or period["provider"] != statement.provider
                or period["contract"] != statement.contract_id
            ):
                raise ValueError("Unknown statement period or contract.")
            if statement.as_of.timestamp() > self.clock() or (
                period["vendor_asof"] and statement.as_of.timestamp() < period["vendor_asof"]
            ):
                raise ValueError("Out-of-order or future vendor statement.")
            for attempt_id, units in statement.settlements.items():
                attempt = row(db, m.attempts, m.attempts.c.id == attempt_id)
                if (
                    not attempt
                    or attempt["period"] != period["id"]
                    or attempt["state"] not in {"UNCERTAIN", "RECONCILED"}
                    or units > attempt["reservation"]
                ):
                    raise ValueError(
                        "Settlement requires an uncertain attempt and bounded verified units."
                    )
                if attempt["state"] == "RECONCILED":
                    if units != attempt["settled"]:
                        raise ValueError("Conflicting attempt reconciliation.")
                    continue
                db.execute(
                    update(m.periods)
                    .where(m.periods.c.id == period["id"])
                    .values(
                        uncertain=m.periods.c.uncertain - attempt["reservation"],
                        reserved=m.periods.c.reserved + attempt["reservation"],
                    )
                )
                self._finish(db, {**attempt, "state": "SENT"}, "RECONCILED", units)
            period = row(db, m.periods, m.periods.c.id == statement.cycle)
            # A lagging aggregate can add a hold but cannot prove which uncertain
            # attempts were free. Explicit per-attempt evidence is needed for refunds.
            local = period["settled"] + period["uncertain"]
            known_at_cutoff = db.scalar(
                select(func.coalesce(func.sum(m.attempts.c.settled), 0)).where(
                    m.attempts.c.period == period["id"],
                    m.attempts.c.state.in_(("SETTLED", "RECONCILED")),
                    m.attempts.c.settled_at <= statement.as_of.timestamp(),
                    ~m.attempts.c.id.in_(statement.settlements),
                )
            )
            known_at_cutoff += sum(statement.settlements.values())
            if (
                period["last_settled_at"] is not None
                and period["last_settled_at"] <= statement.as_of.timestamp()
            ):
                # This aggregate outlives the diagnostic attempt retention window.
                # Only use it when every confirmed settlement predates the cutoff.
                known_at_cutoff = period["settled"]
            external_floor = period["external"]
            if statement.release_external_buffer:
                if statement.status != "final" or statement.as_of.timestamp() < period["end"]:
                    raise ValueError(
                        "Reducing external uncertainty requires a final closed-cycle statement."
                    )
                recorded = row(db, m.contracts, m.contracts.c.id == period["policy"])
                external_floor = PartnerBudgetContract.model_validate(
                    recorded["policy"]
                ).billing.external_usage_buffer_units
            external = max(external_floor, statement.total_units - known_at_cutoff, 0)
            delta = external - period["external"]
            db.execute(
                insert(m.adjustments).values(
                    id=key,
                    period=period["id"],
                    actor=digest(actor),
                    evidence=statement.evidence_sha256,
                    reason=statement.reason,
                    delta=delta,
                    payload=payload,
                    created=self.clock(),
                )
            )
            db.execute(
                update(m.periods)
                .where(m.periods.c.id == period["id"])
                .values(
                    external=external,
                    vendor_total=statement.total_units,
                    vendor_spend=str(statement.spend) if statement.spend is not None else None,
                    vendor_asof=statement.as_of.timestamp(),
                    vendor_final=int(statement.status == "final"),
                    quarantined=int(
                        bool(
                            period["quarantined"]
                            or local + external + period["reserved"] > period["usable"]
                        )
                    ),
                )
            )
            if statement.total_units != local:
                self._event(db, period["id"], "VENDOR_DISCREPANCY", once=True)
            if statement.release_restore_hold:
                hold = db.scalar(select(m.lock.c.restore_hold).where(m.lock.c.id == 1))
                unreconciled = db.scalar(
                    select(func.count())
                    .select_from(m.periods)
                    .where(
                        (m.periods.c.vendor_final == 0)
                        | (m.periods.c.vendor_asof < hold)
                        | m.periods.c.vendor_asof.is_(None)
                        | (m.periods.c.quarantined != 0)
                        | (m.periods.c.reserved != 0)
                        | (m.periods.c.uncertain != 0)
                    )
                )
                if not hold or unreconciled:
                    raise ValueError(
                        "Every restored cycle requires a final current statement and resolved holds."
                    )
                db.execute(update(m.lock).where(m.lock.c.id == 1).values(restore_hold=0))
        return "recorded"

    def recover(self):
        with self.transaction() as db:
            self._recover(db, self.clock())
            # Preserve aggregate financial history; unlink owner/task identities
            # after the bounded diagnostic retention window.
            db.execute(
                update(m.attempts)
                .where(m.attempts.c.created < self.clock() - 30 * 86400)
                .values(owner=None, tenant=None, token=None, task=None)
            )
            db.execute(
                delete(m.throttles).where(
                    m.throttles.c.updated < self.clock() - 86400,
                    m.throttles.c.blocked_until < self.clock(),
                )
            )
            # Aggregates and append-only statements remain; detailed attempt
            # metadata is bounded to the last 90 days after its billing period.
            old_periods = select(m.periods.c.id).where(m.periods.c.end < self.clock() - 90 * 86400)
            db.execute(
                delete(m.attempts).where(
                    m.attempts.c.period.in_(old_periods), ~m.attempts.c.state.in_(HELD)
                )
            )

    def forget_owner(self, owner):
        with self.transaction() as db:
            db.execute(
                update(m.attempts)
                .where(m.attempts.c.owner == owner)
                .values(owner=None, tenant=None, token=None, task=None)
            )

    def note_cache(self, source):
        if source not in {"upstream", "cache", "coalesced", "conditional_revalidation"}:
            raise ValueError("Unknown cache metric.")
        with self.transaction() as db:
            period = db.scalar(
                select(m.periods.c.id)
                .where(m.periods.c.provider == "canvas")
                .order_by(m.periods.c.start.desc())
                .limit(1)
            )
            if period:
                self._event(db, period, source)

    def restore_history(self, db, records):
        """Called inside academic restore's transaction; never resets an existing ledger."""
        for table in m.metadata.sorted_tables:
            if db.execute(select(table).limit(1)).first():
                raise ValueError("Accounting restore requires an empty target.")
        for table in m.metadata.sorted_tables:
            if table is m.lock:
                continue
            for record in records.get(table.name, []):
                value = dict(record)
                if table is m.attempts:
                    value.update(owner=None, tenant=None, token=None, task=None)
                db.execute(insert(table).values(**value))
        db.execute(insert(m.lock).values(id=1, restore_hold=self.clock()))
        self._recover(db, float("inf"))


def finite_header(value):
    try:
        if value is None or len(str(value)) > 64:
            return None
        number = float(value)
        return number if math.isfinite(number) and 0 <= number <= 10**12 else None
    except (ValueError, TypeError):
        return None
