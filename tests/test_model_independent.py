"""Two signed clients on the normal recipient and source-release paths, using synthetic data."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Implementation

from tests.test_mcp_contract import running
from tests.test_recovery_independence import parsed_locally as parsed_locally
from tests.test_usefulness import browser_session, import_text


@pytest.fixture
async def pair(bridge, owner, settings, token_factory, tmp_path, parsed_locally, monkeypatch):
    settings.usefulness_features_enabled = True
    template = bridge.independent.profile()
    clients = {}
    for category in ("chatgpt", "external_ai"):
        policy = template.model_copy(
            update=dict(
                policy_id="review-" + category,
                recipient=category,
                issuer=settings.issuer_url,
                client_id="fixture-" + category,
                workspace="workspace-" + category,
                environment="fixture",
            )
        )
        path = tmp_path / (category + ".json")
        path.write_text(policy.model_dump_json())
        clients[category] = policy
        if category == "chatgpt":
            settings.independent_egress_file = path
            settings.mcp_chatgpt_client_ids = frozenset({policy.client_id})
        else:
            settings.independent_external_egress_file = path
    receipts = []
    sessions = {}
    requests_started = 0
    decide = bridge.egress.decision

    def observed(transfer, code, reason, classifications):
        decision = decide(transfer, code, reason, classifications)
        if any(source.kind == "local_document" for source in transfer.sources):
            from dataclasses import asdict

            receipts.append(
                dict(
                    method="release",
                    identity=asdict(transfer.recipient),
                    purpose=transfer.purpose,
                    channel=transfer.channel,
                    amount=transfer.amount,
                    decision=decision.public(),
                )
            )
        return decision

    monkeypatch.setattr(bridge.egress, "decision", observed)

    @asynccontextmanager
    async def connect(category, **claims):
        policy = clients[category]
        token = token_factory(
            **(
                dict(
                    azp=policy.client_id,
                    bridge_recipient_workspace=policy.workspace,
                    bridge_recipient_environment=policy.environment,
                )
                | claims
            )
        )
        async with httpx.AsyncClient(
            headers={"Authorization": "Bearer " + token}, timeout=90
        ) as http:
            async with streamable_http_client(url + "/mcp", http_client=http) as streams:
                # Same display metadata on both connections; only verified claims select identity.
                async with ClientSession(
                    *streams[:2], client_info=Implementation(name="chatgpt", version="fixture")
                ) as session:
                    session_number = len(sessions) + 1
                    sessions[session] = dict(client=category, session=session_number)
                    init = await session.initialize()
                    receipts.append(
                        dict(
                            **sessions[session],
                            method="initialize",
                            profile=settings.profile,
                            result=init.model_dump(mode="json"),
                        )
                    )
                    yield session

    async def call(session, tool, args=None):
        nonlocal requests_started
        requests_started += 1
        number = requests_started
        result = await session.call_tool(tool, args or {})
        receipts.append(
            dict(
                **sessions[session],
                request_order=number,
                content_types=[part.type for part in result.content],
                tool=tool,
                arguments=args or {},
                result=result.structuredContent,
                error=result.isError,
            )
        )
        return result

    async for url in running.__wrapped__(bridge, settings, None):
        # Load the test issuer's public key into the real verifier before switching to hosted.
        async with connect("chatgpt"):
            pass
        settings.profile = "hosted"
        bridge.synthetic = None
        browser_session(bridge, owner, token_factory)
        async with httpx.AsyncClient(
            base_url=url, cookies={"bridge_session": "usefulness-browser"}, headers={"Origin": url}
        ) as browser:

            async def review(row, selected=True, visual=False):
                response = await browser.post(
                    "/settings/materials/sharing",
                    data=dict(
                        document_id=row.id,
                        expected_hash=row.version_hash,
                        csrf="usefulness-csrf",
                        permission_version=row.provenance.get("permission_version", 0),
                        confirm="reviewed",
                        primary_review=clients["chatgpt"].review_digest(),
                        share="yes",
                        analysis="yes",
                        visual="yes" if visual else "no",
                        **(
                            {"external_review": clients["external_ai"].review_digest()}
                            if selected
                            else {}
                        ),
                    ),
                )
                assert response.status_code == 303, response.text
                receipts.append(
                    dict(
                        method="source_review",
                        source=row.id,
                        version=row.version_hash,
                        revision=row.provenance.get("permission_version", 0) + 1,
                        primary_policy=clients["chatgpt"].review_digest(),
                        additional_policy=clients["external_ai"].review_digest()
                        if selected
                        else None,
                    )
                )

            yield SimpleNamespace(
                url=url,
                connect=connect,
                call=call,
                review=review,
                clients=clients,
                receipts=receipts,
            )
        if output := os.getenv("BRIDGE_TEST_MI_OUTPUT"):
            from tests.test_academic_operations_acceptance import record

            folder = Path(output)
            await asyncio.to_thread(folder.mkdir, exist_ok=True, parents=True)
            record(folder, os.environ["PYTEST_CURRENT_TEST"].split("::")[-1].split()[0], receipts)


async def test_signed_source_review(pair, bridge, owner):
    row = await import_text(bridge, owner, "A fictional assignment requires two tables.")

    async def read(client, **claims):
        async with pair.connect(client, **claims) as session:
            return (
                await pair.call(session, "read_local_document", {"document_id": row.id})
            ).structuredContent

    assert (await read("chatgpt"))["status"] == "ok"

    async def withheld(client, **claims):
        result = await read(client, **claims)
        assert result["status"] == "permission_denied", result
        assert row.content["parsed"]["pages"][0]["text"] not in json.dumps(result)

    await withheld("external_ai")
    for category in ("chatgpt", "external_ai"):
        from dataclasses import asdict

        assert any(
            entry.get("identity") == asdict(pair.clients[category].identity())
            for entry in pair.receipts
        )
    await pair.review(row)
    released = await read("external_ai")
    assert released["data"]["content_hash"] == row.version_hash
    assert "two tables" in str(released["data"]["parts"])
    await withheld("external_ai", bridge_recipient_workspace="other")
    await withheld("external_ai", bridge_recipient_environment="other")
    await withheld("external_ai", azp="unknown")
    await withheld("chatgpt", bridge_recipient_workspace="other")
    policy = pair.clients["external_ai"]
    changed = policy.model_copy(update={"retention_days": 1})
    bridge.settings.independent_external_egress_file.write_text(changed.model_dump_json())
    await withheld("external_ai")
    bridge.settings.independent_external_egress_file.write_text(policy.model_dump_json())
    await pair.review(bridge.independent.require(owner, row.id), selected=False)
    await withheld("external_ai")
    assert (await read("chatgpt"))["status"] == "ok"


@pytest.mark.skipif(not os.getenv("BRIDGE_TEST_MI_SUITE"), reason="requires supplied MI archive")
async def test_protocol_and_academic_values(pair, bridge, owner, monkeypatch):
    from datetime import datetime, timedelta
    from zipfile import ZipFile

    from tests.test_academic_operations_acceptance import PARENTS, sha, sourced_dataset
    from tests.test_verifiable_intelligence_acceptance import claim_signature

    archive = Path(os.environ["BRIDGE_TEST_MI_SUITE"])
    assert (
        sha(await asyncio.to_thread(archive.read_bytes))
        == "591d1944d02a8070e1d6c4ad256b6989b595a6d843b1afda14e8dc0144e5c8cf"
    )
    labels = {
        "SRC001": "BUS_SHARED_Study_Preferences",
        "SRC002": "FIN310-A03",
        "SRC003": "FIN310-N02",
        "SRC005": "FIN310-U01",
        "SRC007": "MKT320-A05",
        "SRC009": "MKT320-N01",
        "SRC010": "OPS330-A05",
    }
    sources, titles = {}, {}

    async def ingest(raw, name):
        ident = await bridge.independent.ingest(
            owner,
            raw,
            name,
            "text/plain",
            own_material=True,
            share_text=True,
            allow_academic_analysis=True,
        )
        row = bridge.independent.require(owner, ident)
        assert row.version_hash == sha(raw)
        await pair.review(row)
        return {"document_id": ident, "expected_hash": row.version_hash}

    with ZipFile(archive) as bundle:
        for key, label in labels.items():
            suffix = ".txt" if key == "SRC001" else ".md"
            raw = bundle.read("fixtures/verifiability/fixtures/" + key + suffix)
            titles[label] = raw.decode().splitlines()[0].lstrip("# ")
            sources[label] = await ingest(raw, key + ".txt")
        base = json.loads(bundle.read("fixtures/operations/request.json"))
        raw = bundle.read("fixtures/operations/academic-input.txt")
        scenario = json.loads(bundle.read("fixtures/operations/scenario.json"))
        assert sha(raw) == scenario["input_sha256"]
    clock = datetime.fromisoformat(scenario["as_of"])
    monkeypatch.setattr("canvas_bridge.independent_intelligence.utcnow", lambda: clock)
    grades = {
        "schema_version": "independent-academic-1",
        "grades": {
            "method": "points",
            "groups": [{"id": "cases", "name": "Cases"}],
            "complete": True,
            "assessments": [
                {
                    "id": "fixture",
                    "title": "Fixture score",
                    "group_id": "cases",
                    "score_state": "posted",
                    "possible": "100",
                    "score": "86",
                    "eligibility_verified": True,
                }
            ],
        },
    }
    grade_input = await ingest(json.dumps(grades).encode(), "grade.txt")
    dataset = await ingest(raw, "controlled-input.txt")
    canonical = None
    observations = {}
    for client in ("chatgpt", "external_ai"):
        async with pair.connect(client) as session:
            catalog = await session.list_tools()
            schemas = {
                t.name: t.model_dump(mode="json")
                for t in catalog.tools
                if t.name
                in {
                    "read_local_document",
                    "run_independent_academic_workflow",
                    "get_saved_study_state",
                }
            }
            assert len(schemas) == 3 and all(s["inputSchema"] for s in schemas.values())
            pair.receipts.append(dict(client=client, method="tools/list", selected=schemas))

            async def workflow(request):
                result = await pair.call(
                    session, "run_independent_academic_workflow", {"request": request}
                )
                assert result.content and result.content[0].type == "text"
                body = result.structuredContent
                assert body["status"] in {"ok", "partial_data"}, body
                return body["data"]

            pref = sources["BUS_SHARED_Study_Preferences"]

            async def excerpt(offset, characters, selection=pref):
                resp = await pair.call(
                    session,
                    "read_local_document",
                    {
                        "document_id": selection["document_id"],
                        "start_offset": offset,
                        "characters": characters,
                    },
                )
                return resp.structuredContent["data"]["parts"][0]

            first = await excerpt(0, 100)
            assert first["text_truncated"]
            rest = await excerpt(first["end"], 18000)
            whole = await excerpt(0, 18000)
            assert first["text"] + rest["text"] == whole["text"]
            preference_quote = {
                "document_id": pref["document_id"],
                "content_hash": pref["expected_hash"],
                "locator": "Part 1",
                "quote": next(
                    line for line in whole["text"].splitlines() if "checking file names" in line
                ),
            }
            values = {"schemas": schemas}
            reviews = {}
            for parent, extras in zip(
                PARENTS, [["MKT320-N01"], [], ["FIN310-N02", "FIN310-U01"]], strict=True
            ):
                docs = [dict(sources[parent], role="instructions")] + [
                    dict(sources[e], role="rubric" if e.endswith("U01") else "schedule")
                    for e in extras
                ]
                req = await workflow({"capability": "consistency", "documents": docs})
                reviews[parent] = req["source_work_steps"]["steps"]
                assert reviews[parent] and all(t["parent_key"] == parent for t in reviews[parent])
                values[parent] = claim_signature(req)
                if parent == "FIN310-A03":
                    assert req["requirement_review"]["conflicts"]
            partial = await workflow(
                {
                    "capability": "requirements",
                    "documents": [
                        sources["MKT320-A05"],
                        {"document_id": "missing-synthetic-document", "expected_hash": "e" * 64},
                    ],
                }
            )
            assert partial["excluded_sources"]
            plan = await workflow(dict(base, dataset=dataset))
            totals = plan["effort_summary"]
            assert (
                totals["allocated_work_minutes"],
                totals["capacity_blocked_minutes"],
                totals["dependency_blocked_minutes"],
            ) == (1010, 70, 300)
            values["effort"] = totals
            if canonical is None:
                grounded, _ = sourced_dataset(raw, sources, titles, reviews, preference_quote)
                canonical = await ingest(grounded, "bound-steps.txt")
            projection = await workflow({"capability": "grades", "dataset": grade_input})
            assert projection["calculation"]["calculated_percentage"] == "86.0000"
            values["grade"] = projection["calculation"]
            calendar = {
                "calendar_id": "synthetic",
                "timezone": "America/New_York",
                "retrieved_at": clock.isoformat(),
                "window_start": clock.isoformat(),
                "window_end": (clock + timedelta(days=12)).isoformat(),
                "pagination_complete": True,
                "mapping_search_complete": True,
                "events": [],
            }
            result = await workflow(
                {"capability": "calendar", "dataset": canonical, "calendar": calendar}
            )
            proposals = result["proposals"]
            assert {p["work_id"] for p in proposals} == set(PARENTS)
            assert not result["provider_writes_executed"]
            values["proposals"] = proposals
            events = [
                dict(
                    id="fixture-" + p["work_id"],
                    title=p["title"],
                    start=p["timing"]["start"],
                    end=p["timing"]["end"],
                    status="confirmed",
                    bridge_marker=p["bridge_marker"],
                    version="1",
                )
                for p in proposals
            ]
            retry = await workflow(
                {
                    "capability": "calendar",
                    "dataset": canonical,
                    "calendar": dict(calendar, events=events),
                }
            )
            assert retry["proposals"] == []
            absent = await pair.call(
                session,
                "run_independent_academic_workflow",
                {"request": {"capability": "calendar", "dataset": canonical}},
            )
            assert absent.structuredContent["data"]["reason_code"] == "INDEPENDENT_CALENDAR_MISSING"
            assert not absent.structuredContent["data"].get("proposals")
            observations[client] = values
    assert observations["chatgpt"] == observations["external_ai"]


async def test_owned_state_and_stale_edits(pair, token_factory):
    async def get(session):
        return (await pair.call(session, "get_saved_study_state")).structuredContent["data"][
            "records"
        ]

    async def save(session, version, minutes):
        result = await pair.call(
            session,
            "update_local_study_preferences",
            {
                "expected_version": version,
                "preferences": {"timezone": "UTC", "break_minutes": minutes},
            },
        )
        return result.structuredContent

    async with pair.connect("chatgpt") as a:
        assert await get(a) == []
        assert (await save(a, 0, 12))["data"]["version"] == 1
    async with pair.connect("external_ai") as b, pair.connect("chatgpt") as a:
        (saved,) = await get(b)
        assert (
            saved["key"] == "default"
            and saved["version"] == 1
            and saved["value"]["break_minutes"] == 12
        )
        assert await get(a) == [saved]
        assert (await save(a, 1, 14))["data"]["version"] == 2
        assert (await save(b, 1, 16))["status"] == "source_changed"
        (current,) = await get(b)
        assert current["version"] == 2 and current["value"]["break_minutes"] == 14
        responses = await asyncio.gather(save(a, 2, 18), save(b, 2, 20))
        assert sorted(r["status"] for r in responses) == ["ok", "source_changed"]
        (winner,) = [r["data"] for r in responses if r["status"] == "ok"]
        assert winner["version"] == 3
    async with pair.connect("external_ai") as fresh:
        (final,) = await get(fresh)
        assert final == dict(kind="preferences", key="default", **winner)
        no_connection = await pair.call(
            fresh, "get_saved_study_state", {"include_institutional": True}
        )
        assert no_connection.structuredContent["status"] == "needs_input"
    async with httpx.AsyncClient() as http:
        denied = await http.post(
            pair.url + "/mcp",
            headers={
                "Authorization": "Bearer " + token_factory(iss="https://other-fixture.invalid")
            },
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
        )
        assert denied.status_code == 401
        pair.receipts.append(
            dict(control="other issuer with same subject", http_status=denied.status_code)
        )
    async with pair.connect("external_ai", sub="other-owner") as other:
        assert await get(other) == []


async def test_source_revalidated_on_resume(pair, bridge, owner):
    row = await import_text(bridge, owner, "Fictional brief with an original deadline.")
    await pair.review(row)
    selection = {"document_id": row.id, "expected_hash": row.version_hash}

    async def use():
        async with pair.connect("external_ai") as fresh:
            result = await pair.call(
                fresh,
                "run_independent_academic_workflow",
                {"request": {"capability": "requirements", "documents": [selection]}},
            )
            return result.structuredContent

    assert (await use())["status"] in {"ok", "partial_data"}
    await bridge.independent.ingest(
        owner,
        b"Fictional replacement deadline.",
        "revised.txt",
        "text/plain",
        own_material=True,
        share_text=True,
        allow_academic_analysis=True,
        course="biology",
        replace_id=row.id,
        expected_hash=row.version_hash,
    )
    changed = bridge.independent.require(owner, row.id)
    withheld = await use()
    assert "Fictional replacement deadline" not in json.dumps(withheld)
    assert withheld["status"] not in {"ok", "partial_data"} or not withheld["data"].get(
        "source_versions"
    )
    await pair.review(changed)
    assert (await use())["status"] == "source_changed"
    selection["expected_hash"] = changed.version_hash
    assert (await use())["data"]["source_versions"]


@pytest.mark.skipif(os.name != "nt", reason="uses the Windows isolated PDF renderer")
async def test_protocol_visual_capability(pair, bridge, owner):
    from tests.test_recovery_independence import import_pdf

    bridge.settings.file_reading_enabled = True
    bridge.settings.parser_root = Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
    ident = await import_pdf(bridge, owner, share_visual=True)
    await pair.review(bridge.independent.require(owner, ident), visual=True)
    for client in ("chatgpt", "external_ai"):
        async with pair.connect(client) as session:
            text = await pair.call(session, "read_local_document", {"document_id": ident})
            assert text.structuredContent["data"]["parts"][0]["text"]
            result = await pair.call(
                session, "render_local_document_page", {"document_id": ident, "page": 2}
            )
            images = [part for part in result.content if part.type == "image"]
            if client == "chatgpt":
                assert len(images) == 1 and images[0].mimeType == "image/png"
                assert (
                    result.structuredContent["data"]["image_delivery"]["model_visibility"]
                    == "unknown"
                )
            else:
                assert not images and result.structuredContent["status"] == "permission_denied"


async def test_external_review_limits(pair, bridge, owner):
    row = await import_text(bridge, owner, "Use these fictional instructions for source review.")
    original = pair.clients["external_ai"]
    for change in (
        {"max_output_bytes": 1},
        {"channels": {"visual"}},
        {"purposes": {"grade_planning"}},
    ):
        restricted = type(original).model_validate(original.model_dump() | change)
        bridge.settings.independent_external_egress_file.write_text(restricted.model_dump_json())
        pair.clients["external_ai"] = restricted
        await pair.review(bridge.independent.require(owner, row.id))
        async with pair.connect("external_ai") as session:
            result = await pair.call(session, "read_local_document", {"document_id": row.id})
            assert result.structuredContent["status"] == "permission_denied"
            assert "fictional instructions" not in result.model_dump_json()
