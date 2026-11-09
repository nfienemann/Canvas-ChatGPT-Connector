"""Minimal accounting tables. No paths, tokens, response bodies or academic content."""

from sqlalchemy import JSON, BigInteger, Column, Float, Integer, MetaData, String, Table

metadata = MetaData()


def table(name, *columns):
    return Table(name, metadata, *columns)


lock = table(
    "usage_governor_lock",
    Column("id", Integer, primary_key=True),
    Column("restore_hold", Float, nullable=False, server_default="0"),
)
contracts = table(
    "contract_budget",
    Column("id", String(64), primary_key=True),
    Column("provider", String(80), nullable=False, index=True),
    Column("contract", String(80), nullable=False),
    Column("version", Integer, nullable=False),
    Column("effective", Float, nullable=False),
    Column("policy", JSON, nullable=False),
    Column("actor", String(64), nullable=False),
    Column("created", Float, nullable=False),
)
periods = table(
    "usage_period",
    Column("id", String(64), primary_key=True),
    Column("provider", String(80), nullable=False),
    Column("contract", String(80), nullable=False),
    Column("start", Float, nullable=False),
    Column("end", Float, nullable=False),
    Column("policy", String(64), nullable=False),
    Column("usable", BigInteger, nullable=False),
    Column("settled", BigInteger, nullable=False),
    Column("last_settled_at", Float),
    Column("reserved", BigInteger, nullable=False),
    Column("uncertain", BigInteger, nullable=False),
    Column("external", BigInteger, nullable=False),
    Column("vendor_total", BigInteger),
    Column("vendor_spend", String(40)),
    Column("vendor_asof", Float),
    Column("vendor_final", Integer, nullable=False, server_default="0"),
    Column("quarantined", Integer, nullable=False),
    Column("version", Integer, nullable=False),
)
pools = table(
    "budget_pool",
    Column("period", String(64), primary_key=True),
    Column("name", String(24), primary_key=True),
    Column("target", BigInteger, nullable=False),
    Column("booked", BigInteger, nullable=False),
    Column("borrowed", BigInteger, nullable=False),
)
attempts = table(
    "usage_attempt",
    Column("id", String(64), primary_key=True),
    Column("parent", String(64)),
    Column("period", String(64), nullable=False, index=True),
    Column("policy", String(64), nullable=False),
    Column("owner", String(64), index=True),
    Column("tenant", String(64), index=True),
    Column("token", String(64), index=True),
    Column("task", String(64), index=True),
    Column("operation", String(80), nullable=False),
    Column("workload", String(24), nullable=False),
    Column("state", String(24), nullable=False, index=True),
    Column("reservation", BigInteger, nullable=False),
    Column("settled", BigInteger, nullable=False),
    Column("allocation", JSON, nullable=False),
    Column("status", Integer),
    Column("throttle_cost", Float),
    Column("created", Float, nullable=False, index=True),
    Column("expires", Float, nullable=False),
    Column("duration_ms", Float),
    Column("body_bytes", BigInteger, nullable=False, server_default="0"),
    Column("max_body_bytes", BigInteger, nullable=False, server_default="0"),
    Column("reported_units", BigInteger),
    Column("settled_at", Float),
)
throttles = table(
    "usage_throttle",
    Column("id", String(64), primary_key=True),
    Column("blocked_until", Float, nullable=False),
    Column("failures", Integer, nullable=False),
    Column("updated", Float, nullable=False),
)
adjustments = table(
    "budget_adjustment",
    Column("id", String(64), primary_key=True),
    Column("period", String(64), nullable=False),
    Column("actor", String(64), nullable=False),
    Column("evidence", String(64), nullable=False),
    Column("reason", String(80), nullable=False),
    Column("delta", BigInteger, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("created", Float, nullable=False),
)
events = table(
    "usage_event",
    Column("id", String(64), primary_key=True),
    Column("period", String(64), nullable=False, index=True),
    Column("kind", String(80), nullable=False),
    Column("count", BigInteger, nullable=False),
    Column("created", Float, nullable=False),
)
