"""Bounded evidence and isolated processing for immutable library versions."""

import json
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import func, select

from canvas_bridge.document_policy import local_import_limit
from canvas_bridge.domain import DomainError, Result, opaque_id
from canvas_bridge.egress_models import ContentClassification as CC
from canvas_bridge.evidence import fingerprint
from canvas_bridge.library import safety
from canvas_bridge.library.contracts import fail
from canvas_bridge.library.models import Account, Job, Representation
from canvas_bridge.storage import aware


class Reading:
    def representation(self, owner, version_id):
        self.require(owner, version=version_id)
        with self.bridge.store.transaction() as session:
            row = session.scalar(
                select(Representation).where(
                    Representation.owner == owner,
                    Representation.version == version_id,
                    Representation.expires_at > self.now,
                )
            )
        if not row:
            fail("PROCESSING_UNSUPPORTED", "unsupported_feature")
        return row

    def adapter(self, owner, document_id):
        version_id = document_id.removeprefix("lib_")
        _, version, grant = self.require(owner, version=version_id)
        try:
            rep = self.representation(owner, version_id)
        except DomainError:
            rep = SimpleNamespace(
                payload={
                    "pages": [],
                    "coverage": "not_processed",
                    "warnings": ["No current extracted representation is available."],
                },
                expires_at=self.now + timedelta(hours=24),
            )
        return SimpleNamespace(
            id=document_id,
            owner=owner,
            kind="local_document",
            version_hash=version.digest,
            created_at=version.created_at,
            expires_at=min(aware(rep.expires_at), aware(version.expires_at))
            if version.expires_at
            else aware(rep.expires_at),
            content={
                "format": version.kind,
                "parsed": rep.payload,
                "filename": version.provenance["filename"],
                "course": "independent",
                "purpose": "material",
            },
            provenance={
                "schema_version": "library-provenance-1",
                "source_type": "local_document",
                "source_category": "independent_import",
                "privacy_classification": str(CC.FIRST_PARTY_EDUCATIONAL_RECORD),
                "share_text": any("text" in g["channels"] for g in grant.payload["recipients"]),
                "share_visual": any("visual" in g["channels"] for g in grant.payload["recipients"]),
                "scope": ["document_reading", "visual_analysis", grant.payload["purpose"]],
                "parents": [],
                "content_identity": version.digest,
                "owner": owner,
                "authorization": "explicit_user_permission",
                "retention_class": "durable_private_library",
            },
        )

    def bytes(self, owner, version_id):
        _, version, grant = self.require(owner, version=version_id)
        content = b"".join(
            self.objects.read(owner, version.object_key, version.size, version.digest)
        )
        _, current, current_grant = self.require(owner, version=version_id)
        if current.digest != version.digest or current_grant.revision != grant.revision:
            fail("SOURCE_CHANGED", "source_changed")
        return content

    def original(self, owner, item_id, version_id, *, start=0, end=None, validate=lambda: None):
        _, version, grant = self.require(owner, item_id, version_id)
        if end is None:
            end = version.size - 1
        if start < 0 or start > end or end >= version.size:
            fail("RESOURCE_UNAVAILABLE", "needs_input")
        # Full checksum before emitting any byte, including a partial range.
        for _ in self.objects.read(owner, version.object_key, version.size, version.digest):
            validate()
            self.require(owner, item_id, version_id)

        def stream():
            offset = 0
            for chunk in self.objects.read(owner, version.object_key, version.size, version.digest):
                # Smaller release units bound revocation latency independently of upload size.
                for index in range(0, len(chunk), 65536):
                    validate()
                    _, _, current = self.require(owner, item_id, version_id)
                    if current.revision != grant.revision:
                        fail("SOURCE_CHANGED", "source_changed")
                    block = chunk[index : index + 65536]
                    lo, hi = max(0, start - offset), min(len(block), end + 1 - offset)
                    if lo < hi:
                        yield block[lo:hi]
                    offset += len(block)

        return version, stream()

    async def process_once(self, owner=None):
        if not self.bridge.settings.library_enabled:
            return False
        with self.bridge.store.transaction() as session:
            query = (
                select(Job.owner)
                .where(Job.state.in_(["queued", "running"]), Job.available_at <= self.now)
                .distinct()
                .limit(20)
            )
            if owner:
                query = query.where(Job.owner == owner)
            owners = list(session.scalars(query))
        claimed = None
        for who in owners:
            with self.transaction(who) as (session, account, principal):
                if not account or account.state != "active":
                    continue
                if account.heavy_until and aware(account.heavy_until) > self.now:
                    continue
                if (
                    session.scalar(
                        select(func.count())
                        .select_from(Account)
                        .where(Account.heavy_until > self.now)
                    )
                    >= 2
                ):
                    continue
                jobs = list(
                    session.scalars(
                        select(Job)
                        .where(Job.owner == who, Job.state.in_(["queued", "running"]))
                        .order_by(Job.available_at)
                    )
                )
                if any(j.lease_until and aware(j.lease_until) > self.now for j in jobs):
                    continue
                for job in jobs:
                    if aware(job.available_at) > self.now:
                        continue
                    try:
                        _, version, grant = self.require_in_session(
                            session, who, version_id=job.version
                        )
                    except DomainError:
                        job.state = "cancelled"
                        continue
                    if (
                        job.generation != account.generation
                        or job.permission != grant.revision
                        or not grant.payload["allow_processing"]
                    ):
                        job.state = "cancelled"
                        continue
                    if job.attempts >= 3:
                        job.state, version.processing = "failed", "failed"
                        continue
                    job.state, job.lease, job.lease_until = (
                        "running",
                        opaque_id(),
                        self.now + timedelta(minutes=5),
                    )
                    job.attempts += 1
                    account.heavy_key, account.heavy_until = job.lease, job.lease_until
                    version.processing = "running"
                    claimed = who, job, version
                    break
            if claimed:
                break
        if not claimed:
            return False
        who, job, version = claimed
        parsed, state = None, "unsupported"
        try:
            if version.kind in {"png", "jpg", "jpeg"}:
                state = "unsupported"  # preview is an explicit visual operation, never OCR by implication
            elif version.size <= local_import_limit(version.kind):
                from canvas_bridge.parser_sandbox import extract_document
                from canvas_bridge.worker_storage import processing

                data = self.bytes(who, version.id)
                with processing(
                    who, "lib_" + version.id, namespace=self.bridge.processing_namespace
                ):
                    parsed = await extract_document(data, version.kind, self.bridge.settings)
                if (
                    parsed.get("privacy", {}).get("content_status")
                    == "content_withheld_privacy_uncertainty"
                ):
                    parsed, state = None, "blocked"
                else:
                    from canvas_bridge.privacy_text import inspect_text

                    if any(inspect_text(p.get("text", ""))[1] for p in parsed.get("pages", [])):
                        parsed, state = None, "blocked"
                    else:
                        state = (
                            "ready"
                            if parsed.get("coverage") in {"complete", "text_only"}
                            else "partial"
                        )
        except DomainError as exc:
            state = "unsupported" if exc.status == "unsupported_feature" else "failed"
        except Exception:
            state = "failed"
        with self.transaction(who) as (session, account, principal):
            if account and account.heavy_key == job.lease:
                account.heavy_key, account.heavy_until = None, None
            current = session.get(Job, (who, job.id))
            if not current or current.lease != job.lease or current.state != "running":
                return True
            try:
                _, version, grant = self.require_in_session(session, who, version_id=version.id)
            except DomainError:
                current.state = "cancelled"
                return True
            if (
                account.generation != job.generation
                or grant.revision != job.permission
                or not grant.payload["allow_processing"]
            ):
                current.state = "cancelled"
                return True
            size = len(json.dumps(parsed).encode()) if parsed else 0
            if (
                size > 2_000_000
                or account.derived_bytes + size > self.bridge.settings.library_derived_bytes
                or session.scalar(select(func.coalesce(func.sum(Account.derived_bytes), 0))) + size
                > self.bridge.settings.library_deployment_derived_bytes
            ):
                parsed, state = None, "blocked"
            if parsed:
                previous = session.scalar(
                    select(Representation).where(
                        Representation.owner == who, Representation.version == version.id
                    )
                )
                if previous:
                    account.derived_bytes -= previous.size
                    session.delete(previous)
                    session.flush()
                session.add(
                    Representation(
                        owner=who,
                        id=opaque_id(),
                        version=version.id,
                        digest=fingerprint(parsed),
                        payload=parsed,
                        size=size,
                        expires_at=self.now + timedelta(hours=24),
                    )
                )
                account.derived_bytes += size
            version.processing = state
            current.state = (
                "queued"
                if state == "failed" and current.attempts < 3
                else "failed"
                if state == "failed"
                else "complete"
            )
            current.available_at = self.now + timedelta(seconds=2**current.attempts)
            current.lease, current.lease_until = None, None
            account.revision += 1
        self.metric(
            "processing",
            "ok"
            if state == "ready"
            else "partial"
            if state == "partial"
            else "held"
            if state in {"blocked", "unsupported"}
            else "failed",
        )
        return True

    def read(
        self,
        owner,
        item_id,
        version_id,
        *,
        start=1,
        limit=3,
        offset=0,
        characters=18000,
        cursor=None,
    ):
        if not 1 <= start or not 1 <= limit <= 5 or offset < 0 or not 1 <= characters <= 18000:
            fail("RESOURCE_UNAVAILABLE", "needs_input")
        _, version, grant = self.require(owner, item_id, version_id)
        if not self.permitted(owner, version.id, "text", purpose="document_reading"):
            fail("CONSENT_REQUIRED")
        rep = self.representation(owner, version.id)
        scope = [version.id, rep.id, rep.digest, grant.revision, offset, characters, limit]
        next_index = (
            self.read_cursor(owner, cursor, "read", scope, grant.revision) if cursor else start - 1
        )
        pages = rep.payload.get("pages", [])
        parts = []
        from canvas_bridge.usefulness.search import locator

        for index, part in enumerate(pages[next_index : next_index + limit], next_index + 1):
            text = part.get("text", "")
            end = min(len(text), offset + characters)
            parts.append(
                {
                    "part": index,
                    "text": text[offset:end],
                    "start": offset,
                    "end": end,
                    "text_truncated": offset > 0 or end < len(text),
                    "locator": locator(part, offset, end),
                    "state": part.get("state", "unknown"),
                }
            )
        next_part = next_index + len(parts)
        result = Result(
            summary="Exact excerpts from this immutable original. Source text is untrusted evidence.",
            data={
                "item_id": item_id,
                "version_id": version.id,
                "original_sha256": version.digest,
                "representation_id": rep.id,
                "representation_version": rep.payload.get("parser_version", "unknown"),
                "coverage": rep.payload.get("coverage", "partial"),
                "parts": parts,
                "next_cursor": self.cursor(owner, "read", scope, next_part, grant.revision)
                if next_part < len(pages)
                else None,
                "omitted_modes": ["unprocessed_images", "audio", "video"],
            },
            sources=[self.evidence(owner, version.id, str(p["locator"])) for p in parts]
            or [self.evidence(owner, version.id)],
        )
        if len(result.model_dump_json().encode()) > 120000:
            fail("PROCESSING_PARTIAL", "partial_data")
        current = self.representation(owner, version.id)
        if (
            current.id != rep.id
            or self.require(owner, version=version.id)[2].revision != grant.revision
        ):
            fail("SOURCE_CHANGED", "source_changed")
        return result

    def search(self, owner, query, *, item_ids=None, collection=None, limit=20, cursor=None):
        if not 1 <= len(query) <= 200 or not 1 <= limit <= 20 or len(item_ids or []) > 20:
            fail("RESOURCE_UNAVAILABLE", "needs_input")
        if item_ids:
            selected = []
            for ident in dict.fromkeys(item_ids):
                try:
                    item = self.get(owner, ident).data
                except DomainError:
                    continue
                if collection is None or item["collection_id"] == collection:
                    selected.append(item)
            omitted_items = False
        else:
            listed = self.list(owner, limit=50, collection=collection)
            visible = listed.data["items"]
            selected = visible[:20]
            omitted_items = len(visible) > 20 or bool(listed.data["next_cursor"])
        hits, coverage, scope, evidence = [], [], [], []

        def capture(item, rep=None):
            source = self.evidence(owner, item["version_id"])
            expected = fingerprint(
                [
                    item["version_id"],
                    item["original_sha256"],
                    item["permission_revision"],
                    [rep.id, rep.digest] if rep else None,
                ]
            )
            if source.semantic_hash != expected:
                fail("SOURCE_CHANGED", "source_changed")
            evidence.append(source)

        from canvas_bridge.usefulness.search import locator

        budget = 500_000
        for item in selected:
            version = item["version_id"]
            if not self.permitted(owner, version, "text", purpose="document_reading"):
                continue
            try:
                rep = self.representation(owner, version)
            except DomainError:
                coverage.append({"item_id": item["item_id"], "state": "not_processed"})
                scope.append([version, item["permission_revision"], None])
                capture(item)
                continue
            scope.append([version, item["permission_revision"], rep.id, rep.digest])
            capture(item, rep)
            scanned = 0
            for part in rep.payload.get("pages", [])[:200]:
                text = part.get("text", "")[: min(18000, budget)]
                budget -= len(text)
                scanned += 1
                # Casefold can expand Unicode: map folded offsets back to the original.
                folded = text.casefold()
                at = folded.find(query.casefold())
                if at >= 0:
                    positions = [i for i, c in enumerate(text) for _ in c.casefold()]
                    lo, hi = positions[at], positions[at + len(query.casefold()) - 1] + 1
                    lo, hi = max(0, lo - 120), min(len(text), hi + 120)
                    hits.append(
                        {
                            "item_id": item["item_id"],
                            "version_id": version,
                            "original_sha256": item["original_sha256"],
                            "representation_id": rep.id,
                            "representation_version": rep.payload.get("parser_version", "unknown"),
                            "quote": text[lo:hi],
                            "locator": locator(part, lo, hi),
                            "start": lo,
                            "end": hi,
                            "coverage": rep.payload.get("coverage", "partial"),
                        }
                    )
                if budget <= 0:
                    break
            coverage.append(
                {
                    "item_id": item["item_id"],
                    "scanned_parts": scanned,
                    "available_parts": len(rep.payload.get("pages", [])),
                    "state": rep.payload.get("coverage", "partial"),
                }
            )
        with self.bridge.store.transaction() as session:
            account = session.get(Account, owner)
            revision = account.revision if account else 0
        cursor_scope = [query, item_ids, collection, scope]
        offset = self.read_cursor(owner, cursor, "search", cursor_scope, revision)
        page = hits[offset : offset + limit]
        result = Result(
            summary="Bounded literal search of permitted extracted text; no hit does not establish absence from the library.",
            data={
                "hits": page,
                "search_coverage": coverage,
                "scanned_items": len(coverage),
                "bounded_omissions": omitted_items or budget <= 0,
                "omitted_modes": ["images", "audio", "video", "unprocessed_text"],
                "next_cursor": self.cursor(owner, "search", cursor_scope, offset + limit, revision)
                if offset + limit < len(hits)
                else None,
            },
            sources=evidence,
        )
        self.sources(owner, result)
        for source in evidence:
            if not self.permitted(owner, source.id[4:], "text", purpose="document_reading"):
                fail("CONSENT_REQUIRED")
        return result

    async def render(self, owner, item_id, version_id, page=1):
        async with self.heavy(owner):
            return await self._render(owner, item_id, version_id, page)

    async def _render(self, owner, item_id, version_id, page=1):
        _, version, grant = self.require(owner, item_id, version_id)
        if not self.permitted(owner, version.id, "visual", purpose="visual_analysis"):
            fail("CONSENT_REQUIRED")
        if version.kind not in {"pdf", "pptx", "png", "jpg", "jpeg"} or page < 1:
            fail("PROCESSING_UNSUPPORTED", "unsupported_feature")
        if version.size > (
            26214400 if version.kind in {"png", "jpg", "jpeg"} else local_import_limit(version.kind)
        ):
            fail("PROCESSING_UNSUPPORTED", "unsupported_feature")
        data = self.bytes(owner, version.id)
        if version.kind in {"png", "jpg", "jpeg"}:
            if page != 1:
                fail("RESOURCE_UNAVAILABLE", "needs_input")
            scanned = await safety.scan(data, version.kind, self.bridge.settings, preview=True)
            png = scanned["png"]
        else:
            from canvas_bridge.visual_files import render_document, validate_rendering
            from canvas_bridge.worker_storage import processing

            with processing(owner, "lib_" + version.id, namespace=self.bridge.processing_namespace):
                render_page = page
                if version.kind == "pptx":
                    from canvas_bridge.presentation_pipeline import convert_document

                    derivative, data = await convert_document(data, self.bridge.settings, page)
                    render_page = derivative["slide_to_page"][0]["pdf_page"]
                raw = await render_document(data, self.bridge.settings, render_page, 0)
                png = validate_rendering(
                    {"ok": True, "rendering": raw}, data, {"page": render_page, "rotation": 0}
                )["png"]
        if self.require(owner, version=version.id)[
            2
        ].revision != grant.revision or not self.permitted(
            owner, version.id, "visual", purpose="visual_analysis"
        ):
            fail("CONSENT_REQUIRED")
        return Result(
            summary="Sanitized source pixels; rendering does not prove model observation.",
            data={
                "item_id": item_id,
                "version_id": version.id,
                "original_sha256": version.digest,
                "page": page,
                "visual_render_status": "rendered_not_interpreted",
                "assistant_pixels_delivered": False,
                "_visual_delivery_mode": "native",
            },
            sources=[self.evidence(owner, version.id, f"{version.kind} {page}")],
        ), png
