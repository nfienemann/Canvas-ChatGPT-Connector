"""Explicit operator benchmark, excluded from ordinary pytest discovery.

Run with scripts/run_stress_repair.py. These are product executions, separate
from the supplied fixture self-checks and from installed-connector smoke calls.
"""

import asyncio
import base64
import hashlib
import json
import os
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from canvas_bridge.domain import DomainError
from tests.stress_support import NOW, ROOT, adapt, course_sources, load_records
from tests.test_discussions import discussion as discussion
from tests.test_file_reading import readable as readable
from tests.test_integrity_workflows import configured
from tests.test_mcp_contract import running as running
from tests.test_permission_consistency_contract import client_session
from tests.test_recovery_independence import parsed_locally as parsed_locally

CATALOG = json.loads((ROOT / "gold/scenario_catalog.json").read_text())


@pytest.fixture
def corpus_dependencies(request, case):
    if case["id"] == "KN-04":
        return request.getfixturevalue("readable")
    return None


class Blocked(Exception):
    pass


class Harness:
    def __init__(self, bridge, owner, session, case, seeded):
        self.bridge, self.owner, self.session, self.case, self.seeded = (
            bridge,
            owner,
            session,
            case,
            seeded,
        )
        self.calls, self.imports, self.limits = (
            [],
            [],
            [
                "Disposable synthetic profile; no personal database or live LMS.",
                "Parser runs locally against fictional bytes; this is not OS sandbox acceptance.",
                "No installed client, live Calendar, email or publishing operation.",
            ],
        )

    async def call(self, tool, arguments):
        response = await self.session.call_tool(tool, arguments)
        result = response.structuredContent
        assert result is not None
        assert json.loads(response.content[0].text) == result
        # Encrypted session receipts are capabilities, not benchmark evidence.
        recorded = json.loads(json.dumps(result))
        if isinstance(recorded.get("data"), dict) and recorded["data"].get("study_receipt"):
            recorded["data"]["study_receipt"] = "REDACTED_SYNTHETIC_SESSION_CAPABILITY"
        self.calls.append({"tool": tool, "input": arguments, "observed": recorded})
        return result

    def observe(self, operation, inputs, result):
        def serial(value):
            return value.model_dump(mode="json") if hasattr(value, "model_dump") else value

        self.calls.append({"operation": operation, "input": inputs, "observed": serial(result)})
        return result

    async def ingest(self, raw, name, *, locator=None):
        ident = await self.bridge.independent.ingest(
            self.owner,
            raw,
            name,
            "application/octet-stream" if not name.endswith(".txt") else "text/plain",
            own_material=True,
            share_text=True,
            share_visual=True,
            allow_academic_analysis=True,
        )
        status = await self.call("get_local_document_status", {"document_id": ident})
        if status["status"] not in {"ok", "partial_data"}:
            raise Blocked(
                "Import status unavailable: " + status["data"].get("reason_code", "unknown")
            )
        selected = {"document_id": ident, "expected_hash": status["data"]["content_hash"]}
        self.imports.append(
            {
                **selected,
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "locator": locator or name,
                "course": self.case["course"],
            }
        )
        return selected

    async def documents(self):
        selections = []
        for path in course_sources(self.case["course"]):
            selections.append(
                await self.ingest(
                    path.read_bytes(), path.name, locator=path.relative_to(ROOT).as_posix()
                )
            )
        return selections

    async def workflow(self, capability, **kwargs):
        return await self.call(
            "run_independent_academic_workflow", {"request": {"capability": capability, **kwargs}}
        )

    async def dataset(self, course=None, variant=None):
        native, sidecar = adapt(course or self.case["course"], variant)
        self.observe("validated_schema_adapter", sidecar, native)
        return await self.ingest(
            json.dumps(native).encode(), "academic-records.txt", locator=sidecar
        )

    async def policy(self):
        text = course_sources(self.case["course"])[0].read_text()
        scope = await configured(self.bridge, self.owner, self.seeded, text)
        self.limits.append(
            "Policy authority supplied only by the disposable SyntheticProvider; local imports remain student supplied."
        )
        return scope.model_dump(mode="json")


async def execute(h):
    c, ident = h.case, h.case["id"]
    if ident == "KN-04":
        from tests.test_file_reading import scientific_pdf

        _, file_id = h.dependencies
        path = course_sources(h.case["course"])[0]
        raw = scientific_pdf([path.read_text(encoding="utf-8")])
        h.bridge.synthetic.data["file_bodies"]["51"] = raw
        h.bridge.synthetic.data["files"]["11"][0]["size"] = len(raw)
        h.imports.append(
            {
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "original_source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "locator": path.relative_to(ROOT).as_posix(),
                "course": h.case["course"],
            }
        )
        result = await h.call(
            "prepare_study_session",
            {
                "connection_id": h.seeded,
                "request": {"mode": "active_recall", "material_ids": [file_id]},
            },
        )
        questions = result["data"]["questions"]
        assert questions and not result["data"]["concepts"]
        assert all(
            "expected_answer" not in q and "source_passage" not in q and q["not_instructor_exam"]
            for q in questions
        )
        assert any("wait" in action for action in result["data"]["next_actions"])
        h.limits.append(
            "Original C11 syllabus text wrapped in a synthetic PDF for the existing provider study route; no live provider or learner answer supplied."
        )
        return
    if ident in {"DP-01", "DP-04", "DP-05"}:
        import httpx

        from tests.test_discussions import BASE, entry

        state = h.pytest_request.getfixturevalue("discussion")
        args = {"connection_id": h.seeded, "course_id": state["course"], "topic_id": "20"}
        if ident == "DP-05":
            state["view"]["view"] = [entry(user=999, message="PRIVATE-PEER-PAYLOAD"), entry(2)]
            result = await h.call("read_discussion_topic", args)
            assert "PRIVATE-PEER-PAYLOAD" not in str(result)
            state["topic"].update(require_initial_post=True, user_can_see_posts=False)
            before = len(h.bridge.synthetic.requests)
            result = await h.call("read_discussion_topic", args)
            assert not any(
                r.url.path.endswith(("/view", "/entries"))
                for r in h.bridge.synthetic.requests[before:]
            )
            assert "PRIVATE-PEER-PAYLOAD" not in str(result)
        else:
            state["overrides"][(BASE + "/view", "1")] = httpx.Response(503)
            if ident == "DP-01":
                data, _ = load_records()
                rows = [
                    entry(
                        int(r["id"][1:]),
                        user=101
                        if r["user_id"] == data.discussion["authenticated_user_id"]
                        else 999,
                        parent_id=99 if r["parent_id"] else None,
                        deleted=r["deleted"],
                    )
                    for r in data.discussion["records"]
                ]

                def first(request):
                    return httpx.Response(
                        200,
                        json=rows,
                        headers={
                            "Link": f'<{request.url.copy_set_param("page", "2")}>; rel="next"'
                        },
                    )

                state["overrides"][(BASE + "/entries", "1")] = first
                state["overrides"][(BASE + "/entries", "2")] = httpx.Response(503)
            else:
                state["overrides"][(BASE + "/entries", "1")] = httpx.Response(429)
            result = await h.call("get_my_discussion_participation", args)
            participation = result["data"]["participation"]
            assert (
                participation["state"] != "verified_absent"
                and not participation["coverage"]["complete"]
            )
            if ident == "DP-01":
                assert participation["top_level_posts"] == 1 and participation["replies"] == 1
        return
    if ident.startswith("GR-"):
        variant = {"GR-04": "empty", "GR-06": "bonus", "GR-07": "nonlinear", "GR-08": "review"}.get(
            ident
        )
        dataset = await h.dataset(variant=variant)
        args = {"dataset": dataset}
        if ident in {"GR-02", "GR-07"}:
            args.update(
                grade_mode="required_score",
                scenario={"target_percent": "80", "acknowledge_visible_scope": True},
            )
            h.limits.append(
                "Visible-inventory acknowledgment is an explicit synthetic test input only."
            )
        result = await h.workflow("grades", **args)
        calc = result["data"]["calculation"]
        if ident == "GR-01":
            assert Decimal(calc["calculated_percentage"]) == Decimal("83.3333")
            assert "F" not in calc["included_assessments"]
        elif ident == "GR-02":
            assert Decimal(calc["required_score"]["uniform_remaining_percent"]) == 70
            assert calc["required_score"]["remaining_assessment_ids"] == ["F"]
        elif ident in {"GR-03", "GR-06"}:
            assert Decimal(calc["calculated_percentage"]) == c["expected"]["percent"]
        elif ident == "GR-05":
            if calc["calculated_percentage"] is None:
                raise Blocked(
                    "Native grade engine explicitly does not support unequal-point drop optimization; it refused calculation."
                )
            assert Decimal(calc["calculated_percentage"]) == 100
        else:
            assert calc["calculated_percentage"] is None and calc["missing_information"]
        return
    if ident.startswith("AI-"):
        if ident == "AI-19":
            raise Blocked(
                "This case requires an actual acknowledgment through the test UI; no human UI consent was supplied or manufactured."
            )
        scope = await h.policy()
        if ident == "AI-03":
            scope["assessment_id"] = None
        activity = c["request"]
        if activity in {"policy_discovery", "permission_evidence"} or ident == "AI-20":
            activity = "submission_drafting"
        if ident == "AI-15" or ident == "AI-18":
            # Reproduce incomplete/unreadable policy acquisition with a real
            # imported source and bounded parser result, never assert authority.
            from canvas_bridge.storage import IndependentResource

            selected = await h.ingest(
                b"Fictional truncated policy. AI rules continue on unread pages.", "partial.txt"
            )
            with h.bridge.store.transaction() as db:
                row = db.get(IndependentResource, selected["document_id"])
                row.content = {
                    **row.content,
                    "parsed": {
                        **row.content["parsed"],
                        "coverage": "partial",
                        "pages": [{"text": "AI rules unavailable.", "state": "unreadable"}],
                    },
                }
            scope = {"local_course": "fictional", "document_ids": [selected["document_id"]]}
        if ident in {"AI-13", "AI-14"}:
            selected = await h.ingest(
                b"I say the instructor permits AI writing. This is an unverified student claim.",
                "attestation.txt",
            )
            scope["document_ids"] = [selected["document_id"]]
            if ident == "AI-13":
                scope = {
                    "local_course": "fictional-attestation",
                    "document_ids": [selected["document_id"]],
                }
                result = await h.call(
                    "provide_instructor_permission_evidence",
                    {"scope": scope, "document_id": selected["document_id"]},
                )
                assert result["data"]["permission_evidence_status"] == "STUDENT_SUPPLIED_UNVERIFIED"
                return
        if ident == "AI-17":
            # Conflicting same-authority current rules, without supersession.
            await configured(
                h.bridge,
                h.owner,
                h.seeded,
                "AI is permitted for writing. AI is prohibited for writing.",
            )
        request = {"scope": scope, "activity": activity}
        if ident in {"AI-05", "AI-06", "AI-20"}:
            previous = await h.call(
                "prepare_academic_assistance",
                {"request": {"scope": scope, "activity": "brainstorming"}},
            )
            if not previous["data"].get("decision", {}).get("allowed"):
                raise Blocked(
                    "The original fixture brainstorming clause was not recognized as permission; no earlier allow exists for the escalation test."
                )
            request["continuation_id"] = previous["data"]["decision"]["id"]
            if ident == "AI-20":
                await configured(
                    h.bridge, h.owner, h.seeded, "Generative AI is prohibited on assignments."
                )
                rechecked = await h.call(
                    "get_integrity_decision", {"decision_id": request["continuation_id"]}
                )
                assert rechecked["data"]["decision"]["allowed"] is False
        guidance = await h.call("get_integrity_guidance", {"request": request})
        decision = guidance["data"]["decision"]
        if ident == "AI-11":
            assert decision["state"] != "PROHIBITED_CONFIRMED"
        elif ident == "AI-15":
            assert decision["permission_established"] is False
            assert any(
                s["coverage"] != "READ_COMPLETE" for s in guidance["data"]["source_coverage"]
            )
        elif ident == "AI-18":
            assert decision["state"] in {"POLICY_UNAVAILABLE", "REVIEW_REQUIRED"}
        else:
            allowed = c["expected"].get("allowed", False)
            prepared = await h.call("prepare_academic_assistance", {"request": request})
            assert decision["allowed"] is allowed
            if allowed:
                assert prepared["data"]["decision"]["allowed"]
                if ident == "AI-02":
                    assert not prepared["data"]["assistance_evidence"]
                if ident == "AI-04":
                    assert prepared["data"].get("editable_disclosure_template")
            else:
                assert prepared["status"] == "permission_denied" and not prepared["sources"]
        return
    if ident.startswith("VI-"):
        name = (
            "scientific_figure.pdf"
            if ident in {"VI-01", "VI-02", "VI-03"}
            else "full_syllabus_12_pages.pdf"
            if ident == "VI-04"
            else "requirements_conflict.docx"
            if ident == "VI-09"
            else "gradebook_fixture.xlsx"
            if ident == "VI-10"
            else "lecture_continuation.pptx"
        )
        path = ROOT / "sources/formats" / name
        selected = await h.ingest(path.read_bytes(), name)
        parts, cursor = [], 1
        while cursor:
            result = await h.call(
                "read_local_document",
                {"document_id": selected["document_id"], "start_part": cursor, "limit": 3},
            )
            assert result["data"]["content_hash"] == selected["expected_hash"]
            parts.extend(result["data"]["parts"])
            cursor = result["data"]["next_part"]
            assert len(parts) <= 200
        if ident in {"VI-01", "VI-02"}:
            h.bridge.settings.file_reading_enabled = True
            h.bridge.settings.parser_root = (
                h.pytest_request.getfixturevalue("tmp_path") / "visual-parser"
            )
            response = await h.session.call_tool(
                "render_local_document_page", {"document_id": selected["document_id"], "page": 1}
            )
            result = response.structuredContent
            images = [block for block in response.content if block.type == "image"]
            h.observe(
                "render_local_document_page",
                {"document_id": selected["document_id"], "page": 1},
                result,
            )
            if not images:
                raise Blocked(
                    "No native pixels were delivered by the permitted PDF renderer: "
                    + str(result.get("data", {}).get("reason_code"))
                )
            raw = base64.b64decode(images[0].data, validate=True)
            pixel_hash = hashlib.sha256(raw).hexdigest()
            destination = Path(os.environ["CANVAS_BRIDGE_STRESS_OUTPUT"]) / (ident + ".png")
            destination.write_bytes(raw)
            h.observe(
                "native_pixels_saved_for_review",
                {"source_sha256": selected["expected_hash"]},
                {"image_sha256": pixel_hash, "path": destination.name},
            )
            observation_path = os.environ.get("CANVAS_BRIDGE_VISUAL_OBSERVATIONS")
            if not observation_path:
                raise Blocked(
                    "Native PNG saved; actual model pixel review has not yet been recorded."
                )
            observation = json.loads(
                await asyncio.to_thread(Path(observation_path).read_text, encoding="utf-8")
            )
            if (
                observation.get("image_sha256") != pixel_hash
                or observation.get("source_sha256") != selected["expected_hash"]
            ):
                raise Blocked("Recorded pixel observation is for a different source or rendering.")
            h.observe("recorded_model_pixel_observation", {"image_sha256": pixel_hash}, observation)
            if ident == "VI-01":
                assert (
                    observation["control"] == 50
                    and observation["treatment"] == 75
                    and observation["ratio"] == 1.5
                )
                assert observation["author_claim_twice"] == "contradicted"
            else:
                assert (
                    observation["p_value"] == "unknown"
                    and observation["n"] == "unknown"
                    and observation["error_bars"] == "not_shown"
                )
            h.limits.append(
                "External model observation of this exact saved PNG, not automatic backend interpretation or installed personal-client acceptance."
            )
            return
        if ident == "VI-08":
            response = await h.session.call_tool(
                "render_local_document_page", {"document_id": selected["document_id"], "page": 10}
            )
            assert not any(block.type == "image" for block in response.content)
            assert response.structuredContent["status"] == "unsupported_feature"
            h.observe("render_local_document_page", {"page": 10}, response.model_dump(mode="json"))
            raise Blocked(
                "The independent page-render route does not support PPTX and no trusted slide converter is configured. Original-slide pixel delivery and observation remain unverified."
            )
        if ident == "VI-03":
            result = await h.workflow("assessment", documents=[selected])
            assert result["data"]["figure_interpretation"] == "not_performed"
        elif ident == "VI-04":
            assert len(parts) == 12 and "AI" in parts[11]["text"]
        elif ident == "VI-05":
            assert len(parts) == 10 and parts[4]["part"] == 5 and not parts[4]["text"].strip()
        elif ident == "VI-06":
            assert "luminal-microfluidic-key-88" in parts[7]["text"]
            assert "note" in parts[7]["text"].lower()
        elif ident == "VI-07":
            assert "downstream-membrane-checkpoint-99" in parts[8]["text"]
        elif ident == "VI-09":
            text = str(parts).replace(",", "")
            assert all(n in text for n in ["1200", "1500", "1800", "2000"])
            tables = parts[0]["structure"]["tables"]
            assert tables and tables[0]["structure_complete"]
            cells = tables[0]["cells"]
            assert len({(c["row"], c["column"]) for c in cells}) == len(cells)
            positions = {(c["row"], c["column"]): c["text"] for c in cells}
            assert [positions[(1, c)] for c in (1, 2, 3)] == ["Criterion", "Requirement", "Scope"]
            assert [positions[(2, c)] for c in (1, 2, 3)] == [
                "Length",
                "Mandatory: 1,800-2,000 words",
                "Protocol Report",
            ]
            h.observe("table_coordinates", {"document_id": selected["document_id"]}, tables)
        else:
            cells = [json.loads(line) for part in parts for line in part["text"].splitlines()]
            current = next(
                cell
                for cell in cells
                if cell.get("formula") == "SUM(Inputs!B5:B6)/SUM(Inputs!C5:C6)"
            )
            assert current["cached_value_present"] is True
            assert abs(
                Decimal(current["cached_value"]["value"]) * 100 - Decimal("83.33333333333333")
            ) < Decimal("0.000000001")
        return
    if ident in {"PL-01", "PL-02", "PL-03", "DE-04", "PL-04"}:
        dataset = await h.dataset("C10", "unknown_effort" if ident == "PL-02" else None)
        if ident in {"PL-01", "PL-02"}:
            result = await h.workflow(
                "planning",
                dataset=dataset,
                plan={
                    "windows": [
                        {
                            "start": NOW.isoformat(),
                            "end": (NOW + timedelta(minutes=180)).isoformat(),
                        }
                    ],
                    "buffer_minutes": 0,
                    "date_only_timezones": {
                        "task-0": "America/New_York",
                        "task-1": "America/New_York",
                    },
                },
            )
            if ident == "PL-02":
                assert result["data"]["information_status"] != "sufficient"
            else:
                assert result["data"]["known_capacity_status"] == "shortfall"
                assert result["data"]["known_shortfall_minutes"] >= 150
        elif ident == "PL-03":
            result = await h.workflow("calendar", dataset=dataset)
            assert (
                result["status"] == "needs_input"
                and result["data"]["reason_code"] == "INDEPENDENT_CALENDAR_MISSING"
            )
        else:
            context = {
                "calendar_id": "synthetic-only",
                "timezone": "America/New_York",
                "retrieved_at": NOW.isoformat(),
                "window_start": NOW.isoformat(),
                "window_end": (NOW + timedelta(days=7)).isoformat(),
                "pagination_complete": True,
                "mapping_search_complete": True,
                "events": [],
            }
            h.limits.append(
                "Calendar context is explicitly synthetic; no live Calendar read is claimed."
            )
            result = await h.workflow("calendar", dataset=dataset, calendar=context)
            assert result["data"]["proposals"], result
            if ident == "DE-04":
                assert all(
                    p["timing"]["start_date"] == "2026-11-01" and "start" not in p["timing"]
                    for p in result["data"]["proposals"]
                )
            else:
                context["events"] = [
                    {
                        "id": "event-" + str(i),
                        "title": "Changed title",
                        "all_day_date": "2026-12-01",
                        "bridge_marker": p["bridge_marker"],
                        "status": "confirmed",
                        "version": "fixture-v1",
                    }
                    for i, p in enumerate(result["data"]["proposals"])
                ]
                updated = await h.workflow("calendar", dataset=dataset, calendar=context)
                assert len(updated["data"]["proposals"]) == 2
                assert all(p["action"] == "update" for p in updated["data"]["proposals"])
                h.limits.append(
                    "Adapted the one-event gold to two fixture work records; exactly one update per marker, zero creates."
                )
        return
    if ident in {"RQ-01", "RQ-02", "DE-05", "DE-06", "OP-01", "DP-02"}:
        docs = await h.documents()
        if ident == "DE-06":
            docs = [
                await h.ingest(
                    b"Protocol Report due 11/12/2026. Date order is unspecified.", "numeric.txt"
                )
            ]
        if ident == "DE-05":
            docs = [
                await h.ingest(
                    b"Fictional assignment due 2026-11-01 01:30 America/New_York.",
                    "ambiguous-time.txt",
                    locator="DE-05 explicit synthetic setup; no fold supplied",
                )
            ]
        capability = (
            "requirements"
            if ident.startswith("RQ")
            else "deadlines"
            if ident.startswith("DE") or ident == "DP-02"
            else "assessment"
        )
        result = await h.workflow(capability, documents=docs)
        if ident == "OP-01":
            assert result["data"]["diagnostics"]["institutional_network_attempted"] is False
            assert all(s["untrusted_content"] for s in result["sources"])
        elif ident == "RQ-01":
            assert result["data"]["requirement_review"]["conflicts"]
        elif ident == "RQ-02":
            review = result["data"]["requirement_review"]
            figures = [r for r in review["rules"] if r["type"] == "figure_requirement"]
            assert figures and all(not r["mandatory"] for r in figures)
        elif ident == "DE-05":
            dates = result["data"]["deadline_review"]["obligations"]
            assert dates and dates[0]["date"] is None
            assert dates[0]["normalization_status"] == "ambiguous"
            assert dates[0]["possible_utc"] == c["expected"]["possible_utc"]
        elif ident == "DE-06":
            obligations = result["data"]["deadline_review"]["obligations"]
            assert obligations and all(o["date"] is None and o["uncertainty"] for o in obligations)
        else:
            obligations = result["data"]["deadline_review"]["obligations"]
            assert any(
                o["date"] == "2026-11-02" and "post" in o["title"].lower() for o in obligations
            )
            assert any(
                o["date"] == "2026-11-04" and "replies" in o["title"].lower() for o in obligations
            )
            assert len({o["id"] for o in obligations}) == len(obligations)
        return
    if ident == "OP-04":
        for capability in (
            "planning",
            "assessment",
            "requirements",
            "grades",
            "deadlines",
            "consistency",
            "calendar",
        ):
            result = await h.workflow(capability)
            assert (
                result["status"] == "needs_input"
                and result["data"]["reason_code"] == "INDEPENDENT_INPUT_MISSING"
            )
            assert result["sources"] == []
        return
    if ident == "OP-02":
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import text

        from canvas_bridge import deployment
        from canvas_bridge.resources import resource_root
        from canvas_bridge.storage import Store

        temp = h.pytest_request.getfixturevalue("tmp_path")
        settings = h.bridge.settings.model_copy(
            update={"database_url": "sqlite:///" + (temp / "migration.db").as_posix()}
        )
        config = Config()
        config.set_main_option("script_location", str(resource_root() / "migrations"))
        config.attributes["database_url"] = settings.database_url
        command.upgrade(config, "9b2a41e5021c")
        store = Store(settings.database_url)
        try:
            with store.engine.begin() as connection:
                connection.execute(text("CREATE TABLE fixture_canary (value TEXT NOT NULL)"))
                connection.execute(
                    text("INSERT INTO fixture_canary VALUES ('fictional retained record')")
                )
        finally:
            store.close()
        migrate = deployment.migrate

        def interrupted(*args):
            migrate(*args)
            raise RuntimeError("synthetic interruption after schema migration")

        monkeypatch = h.pytest_request.getfixturevalue("monkeypatch")
        monkeypatch.setattr(deployment, "migrate", interrupted)
        target = deployment.target_id(settings.database_url)
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            deployment.upgrade(settings, target, temp / "before-interruption.sealed")
        monkeypatch.setattr(deployment, "migrate", migrate)
        resumed = deployment.upgrade(settings, target, temp / "before-resume.sealed")
        assert resumed["preflight"]["service_health"] == "READY"
        store = Store(settings.database_url)
        try:
            with store.engine.connect() as connection:
                assert (
                    connection.execute(text("SELECT value FROM fixture_canary")).scalar_one()
                    == "fictional retained record"
                )
        finally:
            store.close()
        h.observe(
            "interrupted_migration_and_resume",
            {"from_revision": "9b2a41e5021c", "failure_point": "after_schema_before_key_binding"},
            {
                "idempotent_recovery": True,
                "data_preserved": True,
                "backup": resumed["backup"],
                "service_health": resumed["preflight"]["service_health"],
            },
        )
        h.limits.append(
            "One controlled exception boundary tested; not every possible power-loss point or OS installation."
        )
        return
    if ident == "OP-07":
        raise Blocked(
            "A disposable OS installation/previous supported release and controlled migration interruption are not supplied by this fixture package; this run does not replace deployment recovery acceptance."
        )
    await process_case(h)


async def process_case(h):
    """Exact synthetic facts into the existing pure process engines, never MCP authority."""
    from canvas_bridge.processes.evidence import reconcile
    from canvas_bridge.processes.models import (
        AcademicScope,
        EvidenceClaim,
        EvidenceCoverage,
        SourceTag,
    )

    docs = await h.documents()
    scope = AcademicScope(
        principal=h.owner, institution="synthetic", term="2026-fall", course=h.case["course"]
    )
    tag = SourceTag(
        id=docs[0]["document_id"],
        version=docs[0]["expected_hash"],
        origin="synthetic",
        scope=scope,
        locator="Syllabus / policy and rules",
        observed_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    coverage = EvidenceCoverage(
        source=tag, unit="section", total=1, seen={1}, extraction="complete"
    )

    def claim(key, value, **kw):
        return EvidenceClaim(
            id=key,
            entity="Protocol-Report",
            field="deadline",
            value=value,
            coverage=coverage,
            basis="observed",
            authority="instructor",
            issuer="fictional",
            effective_at=NOW,
            **kw,
        )

    ident = h.case["id"]
    h.limits.append(
        "Pure process integration uses explicit, source-bound synthetic facts; it does not prove natural-language extraction or installed MCP support."
    )
    if ident in {"DE-01", "DE-02", "DE-03"}:
        from canvas_bridge.academic_dates import DATES, parse_candidate

        def sourced_date(
            source_name, phrase, claim_id, target_scope, *, supersedes=(), effective=NOW
        ):
            index = next(
                i for i, p in enumerate(course_sources(h.case["course"])) if p.name == source_name
            )
            raw = course_sources(h.case["course"])[index].read_text(encoding="utf-8")
            passage = re.search(phrase, raw).group()
            match = DATES.search(passage)
            value = parse_candidate(match)
            assert value["date"]
            source = tag.model_copy(
                update={
                    "id": docs[index]["document_id"],
                    "version": docs[index]["expected_hash"],
                    "locator": source_name + " / " + passage,
                    "scope": target_scope,
                }
            )
            return EvidenceClaim(
                id=claim_id,
                entity="Protocol-Report",
                field="deadline",
                value=value,
                coverage=coverage.model_copy(update={"source": source}),
                basis="observed",
                authority="instructor",
                issuer="fictional",
                effective_at=effective,
                supersedes=supersedes,
            )

        target = scope.model_copy(
            update={"section": "A", "subject": "Test-01" if ident == "DE-03" else None}
        )
        old = sourced_date("syllabus.md", r"Protocol Report is due[^.]+", "syllabus", target)
        if ident == "DE-01":
            new = sourced_date("materials.md", r"Schedule v2 lists[^.]+", "schedule", target)
        else:
            new = sourced_date(
                "materials.md",
                r"An individual extension[^.]+" if ident == "DE-03" else r"Announcement A[^.]+",
                "extension" if ident == "DE-03" else "announcement",
                target,
                supersedes=(old.id,),
                effective=NOW + timedelta(hours=1),
            )
        result = h.observe(
            "reconcile_scoped_fixture_dates",
            [x.model_dump(mode="json") for x in (old, new)],
            reconcile([old, new], now=NOW + timedelta(hours=2)),
        )
        if ident == "DE-01":
            assert result.status == "unresolved" and result.selected is None
            assert {x.value["date"][:10] for x in result.candidates} == {"2026-11-10", "2026-11-12"}
        else:
            assert result.selected == new.id and old.id in result.superseded
            assert new.value["date"][:10] == ("2026-11-16" if ident == "DE-03" else "2026-11-14")
            other = target.model_copy(
                update={"subject": "Test-02"} if ident == "DE-03" else {"section": "B"}
            )
            foreign = new.model_copy(
                update={
                    "coverage": new.coverage.model_copy(
                        update={"source": new.coverage.source.model_copy(update={"scope": other})}
                    )
                }
            )
            with pytest.raises(ValueError, match="exact scope"):
                reconcile([old, foreign], now=NOW + timedelta(hours=2))
            h.observe("cross_scope_amendment", {"scope": other.model_dump()}, {"applied": False})
        return
    if ident == "OP-05":
        from canvas_bridge.processes.clarification import draft_clarification

        old = claim("syllabus", "2026-11-10")
        result = draft_clarification(reconcile([old, claim("schedule", "2026-11-12")], now=NOW))
        h.observe("draft_clarification", [old.model_dump(mode="json")], result)
        assert not result["message_sent"] and result["request"]
        return
    if ident == "DG-01":
        from canvas_bridge.processes.degree import (
            CourseCredit,
            CourseRule,
            DegreeRules,
            project_degree,
        )

        data, _ = load_records()
        rules = DegreeRules(
            institution="synthetic",
            program="fictional",
            version="v1",
            minimum_credits=3,
            required=frozenset(data.proposed_courses),
            courses=tuple(
                CourseRule(course=k, prerequisites=tuple(v)) for k, v in data.prerequisites.items()
            ),
            source=tag,
        )
        credits = [
            CourseCredit(course=k, credits=3, planned_term=1, source=tag)
            for k in data.proposed_courses
        ]
        result = h.observe(
            "project_degree",
            {
                "rules": rules.model_dump(mode="json"),
                "credits": [x.model_dump(mode="json") for x in credits],
            },
            project_degree(rules, credits, now=NOW),
        )
        assert result["status"] == "provisional" and not result["certifies_graduation"]
        assert any(p["requires"] == "Intro Modeling" for p in result["blocked_plan"])
        return
    if ident == "KN-01":
        from canvas_bridge.processes.knowledge import Concept, LearningEvidence, competency

        concept = Concept(id="potential", label="Potential", sources=(tag,))
        exposure = LearningEvidence(
            concept_id=concept.id,
            kind="exposure",
            source=tag,
            observed_at=NOW,
            review_at=NOW + timedelta(days=1),
        )
        result = h.observe(
            "competency",
            {
                "concept": concept.model_dump(mode="json"),
                "evidence": exposure.model_dump(mode="json"),
            },
            competency(concept, [exposure], now=NOW),
        )
        assert result["category"] == "exposed" and not result["mastery_certified"]
        return
    if ident in {"KN-02", "KN-03"}:
        from canvas_bridge.study_engine import evaluate, relationships
        from canvas_bridge.study_models import PracticeResponse

        if ident == "KN-02":
            question = {
                "id": "fixture-practice",
                "concept_id": "western-blotting",
                "source_id": tag.id,
                "rubric": [],
                "locator": tag.locator,
                "format": "recall",
                "expected_answer": "western blotting",
                "source_passage": "Introductory laboratory course introduces western blotting.",
                "source": tag.model_dump(mode="json"),
            }
            response = PracticeResponse(
                question_id=question["id"], response="western blotting", assistance_used=True
            )
            result = h.observe(
                "evaluate_practice",
                {"question": question, "response": response.model_dump(mode="json")},
                evaluate(question, response),
            )
            assert result["practice_state"] == "correct_with_assistance"
        else:
            concepts = [
                {
                    "id": "circuits",
                    "name": "potential",
                    "course_id": "circuits",
                    "material_id": tag.id,
                    "source_id": tag.id,
                    "source": tag.model_dump(mode="json"),
                },
                {
                    "id": "stem-cells",
                    "name": "potential",
                    "course_id": "stem-cells",
                    "material_id": tag.id,
                    "source_id": tag.id,
                    "source": tag.model_dump(mode="json"),
                },
            ]
            result = h.observe("relationships", concepts, relationships(concepts, []))
            assert result and all(r["conceptual_relationship_verified"] is False for r in result)
        return
    if ident.startswith("ST-") or ident == "OP-03":
        from canvas_bridge.processes.identity import ExternalEntityKey, match_entities
        from canvas_bridge.processes.impact import impact_proposals
        from canvas_bridge.processes.models import AcademicRecord
        from canvas_bridge.processes.state import ProcessRepository, indexed

        denied = set()

        def authorize(db, principal, source, purpose):
            if principal != h.owner or source.id in denied:
                raise DomainError("permission_denied", "Synthetic source revoked.")
            row = h.bridge.independent.require(principal, source.id)
            if row.version_hash != source.version:
                raise DomainError("source_changed", "Synthetic source changed.")

        repo = ProcessRepository(h.bridge.store, clock=lambda: NOW, authorize=authorize)
        record = AcademicRecord(
            id="due",
            kind="claim",
            scope=scope,
            sources=(tag,),
            updated_at=NOW,
            data={"deadline": "2026-11-10"},
        )

        def save(item, key):
            change = repo.propose(h.owner, item.id, item, "create")
            receipt = repo.commit(h.owner, change, confirmed=True, idempotency_key=key)
            h.observe("process_commit", change.model_dump(mode="json"), receipt)

        if ident == "ST-04":
            left = ExternalEntityKey(
                provider="import",
                external_id="course-a",
                scope=scope,
                kind="course",
                course_code="SAME",
                sources=(tag,),
            )
            right = left.model_copy(
                update={
                    "external_id": "course-b",
                    "scope": scope.model_copy(update={"term": "2027-spring"}),
                }
            )
            result = h.observe(
                "match_entities",
                [left.model_dump(mode="json"), right.model_dump(mode="json")],
                match_entities(left, right),
            )
            assert result["merge_allowed"] is False
            return
        save(record, "create-due")
        plan = record.model_copy(update={"id": "plan", "kind": "plan", "depends_on": ("due",)})
        save(plan, "create-plan")
        newer = record.model_copy(update={"revision": 2, "data": {"deadline": "2026-11-08"}})
        if ident in {"ST-02", "ST-03"}:
            if ident == "ST-02":
                newer = record.model_copy(
                    update={"revision": 2, "data": record.data | {"title": "Protocol Report!"}}
                )
            state = indexed({record.id: record, plan.id: plan})
            first = impact_proposals(state, record, newer, now=NOW)
            second = impact_proposals(state, record, newer, now=NOW)
            h.observe("impact_proposals_replayed", newer.model_dump(mode="json"), [first, second])
            assert first == second and len(first) == 1
            assert first[0]["reschedule_proposed"] is (ident == "ST-03")
            return
        if ident == "ST-01":
            change = repo.propose(h.owner, record.id, newer, "correction")
            receipt = repo.commit(h.owner, change, confirmed=True, idempotency_key="correction")
            h.observe("correct_source_record", change.model_dump(mode="json"), receipt)
            with pytest.raises(DomainError):
                repo.read(h.owner, "plan")
            h.observe("read_stale_plan", {"id": "plan"}, {"withheld": True})
            return
        if ident == "ST-05":
            independent = tag.model_copy(
                update={
                    "id": docs[1]["document_id"],
                    "version": docs[1]["expected_hash"],
                    "origin": "local_document",
                }
            )
            notes = record.model_copy(update={"id": "notes", "sources": (independent,)})
            mixed = record.model_copy(update={"id": "mixed", "sources": (tag, independent)})
            save(notes, "notes")
            save(mixed, "mixed")
            denied.add(tag.id)
            with pytest.raises(DomainError):
                repo.read(h.owner, "mixed")
            assert repo.read(h.owner, "notes").sources == (independent,)
            h.observe(
                "mixed_source_revocation",
                {"revoked": tag.id},
                {"restricted_material_released": False, "independent_rights_preserved": True},
            )
            return
        if ident == "OP-03":
            from sqlalchemy import select

            from canvas_bridge.lifecycle import backup, restore
            from canvas_bridge.linking import delete_account
            from canvas_bridge.storage import Connection, IndependentResource, Store

            path = h.pytest_request.getfixturevalue("tmp_path") / "before-account-deletion.sealed"
            # Match this disposable connection's creation time to the explicit
            # corpus clock before testing chronological account-deletion fences.
            with h.bridge.store.transaction() as db:
                db.get(Connection, h.seeded).created_at = NOW - timedelta(hours=1)
            backup(h.bridge, path)
            exported = repo.export(h.owner, ["due", "plan"])
            h.observe("process_export", {"ids": ["due", "plan"]}, exported)
            denied.add(tag.id)
            with pytest.raises(DomainError):
                repo.export(h.owner, ["due"])
            denied.clear()
            delete = repo.propose(h.owner, "due", None, "delete")
            repo.commit(h.owner, delete, confirmed=True, idempotency_key="delete")
            inventory = repo.inventory(h.owner)
            h.observe("confirmed_synthetic_deletion", delete.model_dump(mode="json"), inventory)
            assert inventory["records"] == []
            deleted = await delete_account(h.bridge, h.owner, 0)
            assert deleted.data["active_store"] == "purged"
            original = h.bridge.store
            h.bridge.store = Store("sqlite:///:memory:")
            h.bridge.store.create_fixture_schema()
            try:
                restored = restore(h.bridge, path, h.bridge.settings.deletion_journal)
                with h.bridge.store.transaction() as db:
                    assert not list(db.scalars(select(Connection)))
                    assert not list(
                        db.scalars(
                            select(IndependentResource).where(
                                IndependentResource.kind == "academic_process_state"
                            )
                        )
                    )
                h.observe(
                    "restore_after_account_deletion",
                    {"current_deletion_journal": True},
                    {**restored, "deleted_index_records": 0, "restricted_export": False},
                )
            finally:
                h.bridge.store.close()
                h.bridge.store = original
            return
        if ident == "ST-06":
            from sqlalchemy import select

            from canvas_bridge.lifecycle import backup, restore
            from canvas_bridge.storage import Connection, Store

            temp = h.pytest_request.getfixturevalue("tmp_path")
            path = temp / "older-synthetic.sealed"
            backup(h.bridge, path)
            h.bridge.retention.delete_local(h.owner, h.seeded, confirmed=True)
            original = h.bridge.store
            h.bridge.store = Store("sqlite:///:memory:")
            h.bridge.store.create_fixture_schema()
            try:
                result = restore(h.bridge, path, h.bridge.settings.deletion_journal)
                with h.bridge.store.transaction() as db:
                    assert list(db.scalars(select(Connection))) == []
                h.observe(
                    "restore_older_synthetic_backup",
                    {"current_deletion_journal": True},
                    {**result, "revoked_access_restored": False},
                )
            finally:
                h.bridge.store.close()
                h.bridge.store = original
            return
        raise Blocked(
            "Process state was created in a disposable store; an older database backup and independent deletion journal are required for this restore scenario."
        )
    if ident == "DP-03":
        from canvas_bridge.processes.lifecycle import (
            AssignmentState,
            TransitionEvidence,
            transition,
        )

        state = AssignmentState(assignment_id="draft")
        draft = TransitionEvidence(source=tag, kind="draft_file", assignment_id="draft")
        try:
            transition(state, "submitted_confirmed", draft, policy_sources=[], now=NOW)
        except DomainError as exc:
            h.observe("transition", draft.model_dump(mode="json"), {"reason_code": exc.reason_code})
            assert exc.reason_code == "PROCESS_SUBMISSION_UNCONFIRMED"
            return
        pytest.fail("Draft promoted to confirmed submission")
    if ident == "OP-06":
        from canvas_bridge.processes.portfolio import PortfolioPart, publication_clearance

        parts = [
            PortfolioPart(id=kind, source=tag, origin=kind, content_hash=docs[0]["expected_hash"])
            for kind in ("lab_research", "group_work")
        ]
        result = h.observe(
            "publication_clearance",
            [p.model_dump(mode="json") for p in parts],
            publication_clearance(parts, [], now=NOW),
        )
        assert result["status"] == "held_for_review" and not result["publish_executed"]
        return
    raise Blocked(
        "This scenario requires an additional stateful/provider/practice adapter not implemented in this imported-corpus harness. Existing repository tests are separate evidence, not a pass for this case."
    )


@pytest.mark.parametrize("case", CATALOG, ids=lambda c: c["id"])
async def test_stress_case(
    case,
    bridge,
    owner,
    seeded,
    running,
    token_factory,
    parsed_locally,
    monkeypatch,
    request,
    corpus_dependencies,
):
    output = os.environ.get("CANVAS_BRIDGE_STRESS_OUTPUT")
    if not output:
        pytest.skip("Run the explicit operator harness to save case receipts.")
    bridge.retention.clock = lambda: NOW
    monkeypatch.setattr("canvas_bridge.independent_intelligence.utcnow", lambda: NOW)
    h = None
    status, error = "FAIL", None
    try:
        async with client_session(running, token_factory()) as session:
            h = Harness(bridge, owner, session, case, seeded)
            h.pytest_request = request
            h.dependencies = corpus_dependencies
            try:
                await execute(h)
                status = "PASS"
            except Blocked as exc:
                status, error = "BLOCKED", str(exc)
            except Exception as exc:
                error = type(exc).__name__ + ": " + str(exc)[:1500]
    except Exception as exc:
        error = type(exc).__name__ + ": " + str(exc)[:1500]
    finally:
        receipt = {
            "case": case,
            "status": status,
            "detail": error,
            "sources": h.imports if h else [],
            "calls": h.calls if h else [],
            "coverage_limits": h.limits if h else [],
            "suite": "product_integration",
            "source_fingerprint": os.environ.get("CANVAS_BRIDGE_STRESS_BUILD"),
        }
        path = Path(output)
        (path / (case["id"] + ".json")).write_text(
            json.dumps(receipt, indent=2, default=str), encoding="utf-8"
        )
    if status == "BLOCKED":
        pytest.skip(error)
    if status != "PASS":
        pytest.fail(error or "No complete product execution")
