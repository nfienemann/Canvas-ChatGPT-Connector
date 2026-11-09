"""Bounded, owner/epoch-bound request coalescing and conditional read cache.

Content stays in memory for at most sixty seconds and never enters usage telemetry.
Every follower and every cache hit rechecks the current authorization callback.
"""

import asyncio
import copy
import json
import time
from collections import OrderedDict
from datetime import UTC, datetime

from canvas_bridge.domain import DomainError
from canvas_bridge.usage.ledger import deny


class AuthorizedCache:
    def __init__(
        self, *, clock=time.monotonic, wall=time.time, max_items=128, max_bytes=16_000_000
    ):
        self.clock, self.wall = clock, wall
        self.max_items, self.max_bytes = max_items, max_bytes
        self.entries, self.flights = OrderedDict(), {}
        self.hits = self.coalesced = self.revalidated = 0

    async def get(self, key, authorize, fetch, *, ttl=0):
        authorize()
        now = self.clock()
        for old_key, value in list(self.entries.items()):
            if now - value["stored"] >= 60:
                self.entries.pop(old_key, None)
        cached = self.entries.get(key)
        if ttl and cached and now - cached["stored"] < ttl:
            authorize()
            self.hits += 1
            return copy.deepcopy(cached["value"]), self.provenance(cached, "cache")
        if key in self.flights:
            future, followers = self.flights[key]
            if followers >= 32:
                deny("LOCAL_REQUEST_BUSY")
            self.flights[key] = (future, followers + 1)
            try:
                value, evidence = await asyncio.shield(future)
                authorize()
                self.coalesced += 1
                return copy.deepcopy(value), {**evidence, "source": "coalesced"}
            finally:
                active = self.flights.get(key)
                if active is not None and active[0] is future:
                    self.flights[key] = future, active[1] - 1
        if len(self.flights) >= 64:
            deny("LOCAL_REQUEST_BUSY")
        future = asyncio.get_running_loop().create_future()
        self.flights[key] = future, 0
        try:
            validators = cached["validators"] if cached else {}
            payload, next_link, headers = await fetch(validators)
            authorize()
            if payload is None:
                if not cached:
                    deny("GOVERNOR_UNAVAILABLE")
                value = cached["value"]
                self.revalidated += 1
                source = "conditional_revalidation"
            else:
                value = payload, next_link
                source = "upstream"
            validators = {}
            for header, outgoing in (
                ("etag", "If-None-Match"),
                ("last-modified", "If-Modified-Since"),
            ):
                v = headers.get(header)
                if isinstance(v, str) and len(v) <= 512 and all(32 <= ord(c) < 127 for c in v):
                    validators[outgoing] = v
            entry = {
                "value": value,
                "stored": self.clock(),
                "retrieved_at": self.wall(),
                "validators": validators,
                "bytes": len(json.dumps(value).encode()),
            }
            evidence = self.provenance(entry, source)
            if ttl and entry["bytes"] <= self.max_bytes:
                self.entries[key] = entry
                self.entries.move_to_end(key)
                while (
                    len(self.entries) > self.max_items
                    or sum(e["bytes"] for e in self.entries.values()) > self.max_bytes
                ):
                    self.entries.popitem(last=False)
            future.set_result((value, evidence))
            return copy.deepcopy(value), evidence
        except asyncio.CancelledError:
            # The upstream attempt belongs to this caller and its transport/ledger
            # lifetime. Other callers can retry under their own authorization.
            future.set_exception(
                DomainError(
                    "retry_later",
                    "The shared read was interrupted. Retry the request.",
                    reason_code="SHARED_READ_INTERRUPTED",
                )
            )
            future.exception()
            raise
        except BaseException as exc:
            future.set_exception(exc)
            # Retrieve leader exception even when no followers were waiting.
            future.exception()
            raise
        finally:
            self.flights.pop(key, None)

    @staticmethod
    def provenance(entry, source):
        return {
            "source": source,
            "retrieved_at": datetime.fromtimestamp(entry["retrieved_at"], UTC).isoformat(),
            "authorization": "rechecked",
            "coverage": "one_response_only",
        }

    def clear(self):
        self.entries.clear()


def annotate(result, context):
    entries = context.usage_cache
    reused = [e for e in entries if e["source"] != "upstream"]
    if reused:
        result.meta.upstream_cache = reused[:100]
        earliest = min(datetime.fromisoformat(e["retrieved_at"]) for e in reused)
        result.meta.retrieved_at = min(earliest, result.meta.retrieved_at)
        result.meta.freshness = "cached"
        result.meta.warnings.append(
            "Some upstream reads were reused after current authorization checks; cache retrieval times are recorded."
        )
        for source in result.sources:
            source.retrieved_at = min(earliest, source.retrieved_at)
    return result
