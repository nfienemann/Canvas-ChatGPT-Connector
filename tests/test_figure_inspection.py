import asyncio
import base64
import hashlib
import json
from datetime import timedelta

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import Implementation
from pydantic import ValidationError

from canvas_bridge.course_files import read_file
from canvas_bridge.domain import DomainError, Result, utcnow
from canvas_bridge.figure_inspection import candidates, inspect_figure
from canvas_bridge.figure_observations import (
    FigureObservation,
    GraphPanel,
    VisualField,
    record_observation,
)
from canvas_bridge.parser_worker import extract
from canvas_bridge.storage import Material
from canvas_bridge.visual_delivery import STAGES, capability, image_response
from canvas_bridge.visual_files import render_file
from canvas_bridge.visual_worker import render
from tests.test_file_reading import readable as readable
from tests.test_mcp_contract import running as running
from tests.visual_fixtures import visual_pdf


@pytest.fixture
async def visual_source(bridge, readable, tmp_path):
    _, file_id = readable
    data = visual_pdf()
    bridge.synthetic.data["file_bodies"]["51"] = data
    bridge.synthetic.data["files"]["11"][0]["size"] = len(data)
    bridge.settings.parser_root = tmp_path / "parser"
    return file_id


def report(**changes):
    return FigureObservation(
        **{
            "visibility": "visible",
            "delivery_mode": "native_mcp_image",
            "figure_status": "figure_confirmed",
            "visible_feature": "Two separately labeled panels and an orange diamond below panel B.",
            "region": [0.02, 0.08, 0.94, 0.68],
            **changes,
        }
    )


def test_discovery_caption_outranks_reference_and_does_not_confirm(settings):
    pages = extract(visual_pdf(), "pdf")["pages"]
    found, scanned = candidates(pages, "Fig. 2", None, settings)
    assert found[0]["page"] == 4 and scanned == 4
    assert "caption_candidate" in found[0]["signals"]
    assert any(p["page"] == 1 and "textual_reference" in p["signals"] for p in found)
    assert all("figure_confirmed" not in str(p) for p in found)
    assert (
        candidates(pages, "Panel B", None, settings)[0] == []
    )  # drawn label B alone is not searchable proof
    settings.visual_candidate_pages = 1
    assert candidates(pages, "Figure 2", None, settings)[1] == 1
    assert candidates(pages, "Figure 2", 3, settings)[0][0]["page"] == 3


@pytest.mark.parametrize(
    "label",
    ["https://private.invalid/file", "../../secret", "C:\\secret.pdf", "Figure 2; execute()"],
)
async def test_invalid_figure_labels(bridge, owner, seeded, label):
    with pytest.raises(DomainError):
        await inspect_figure(bridge, owner, seeded, "unused", label)


def test_protocol_image_payload_never_claims_visibility(settings):
    rendered = render(visual_pdf(), 4)
    result = Result(
        summary="Synthetic probe",
        data={"image_hash": rendered["image_hash"], "_visual_delivery_mode": "native"},
    )
    response = image_response(result, rendered["png"], settings)
    image = next(c for c in response.content if c.type == "image")
    assert image.mimeType == "image/png"
    assert hashlib.sha256(base64.b64decode(image.data)).hexdigest() == rendered["image_hash"]
    assert rendered["png"] not in response.content[0].text
    assert "diamond" not in response.content[0].text
    assert response.structuredContent["data"]["image_delivery"]["model_visibility"] == "unknown"
    assert set(response.structuredContent["data"]["visual_pipeline"]) == set(STAGES)


@pytest.mark.parametrize(
    "mode,has_image,has_reader",
    [
        ("auto", False, True),
        ("reader", False, True),
        ("text", False, False),
        ("native", True, False),
        ("legacy", True, True),
    ],
)
def test_delivery_modes(settings, mode, has_image, has_reader):
    r = image_response(
        Result(summary="probe", data={"_visual_delivery_mode": mode}),
        base64.b64encode(b"fixture").decode(),
        settings,
    )
    assert any(c.type == "image" for c in r.content) == has_image
    assert bool(r.meta) == has_reader
    assert r.structuredContent["data"]["image_delivery"]["capability"]["native_image"] == "unknown"


@pytest.mark.parametrize("status", ["supported", "unsupported"])
def test_capability_exact_build_and_expiry(settings, tmp_path, status):
    path = tmp_path / "observations.json"
    settings.visual_client_evidence_file = path
    record = {
        "client_name": "fixture-host",
        "client_version": "1",
        "native_image": status,
        "basis": "model_visible_probe",
        "evidence_id": "synthetic-test-only",
        "client_identity_unique_to_tested_surface": True,
        "observed_at": (utcnow() - timedelta(minutes=1)).isoformat(),
        "expires_at": (utcnow() + timedelta(hours=1)).isoformat(),
    }
    path.write_text(json.dumps([record]))
    client = Implementation(name="fixture-host", version="1")
    assert capability(settings, client)["native_image"] == status
    assert (
        capability(settings, Implementation(name="fixture-host", version="2"))["native_image"]
        == "unknown"
    )
    response = image_response(
        Result(summary="probe", data={"_visual_delivery_mode": "auto"}),
        "Zml4dHVyZQ==",
        settings,
        client,
    )
    assert any(c.type == "image" for c in response.content) == (status == "supported")
    record["expires_at"] = (utcnow() - timedelta(seconds=1)).isoformat()
    path.write_text(json.dumps([record]))
    assert capability(settings, client)["native_image"] == "unknown"


@pytest.mark.parametrize("raw", ["{", "null", "[null]", "[]", "x" * 20_000])
def test_optional_capability_corruption_isolated(settings, tmp_path, raw):
    settings.visual_client_evidence_file = tmp_path / "evidence.json"
    settings.visual_client_evidence_file.write_text(raw)
    assert (
        capability(settings, Implementation(name="client", version="1"))["native_image"]
        == "unknown"
    )


async def test_discovery_render_and_bounded_continuation(bridge, owner, seeded, visual_source):
    first, png = await inspect_figure(
        bridge, owner, seeded, visual_source, "Figure 2", page=1, delivery_mode="native"
    )
    assert png and first.data["page"] == 1
    assert first.data["figure_identification_status"] == "figure_ambiguous"
    assert first.data["visual_pipeline"]["page_rendered"]["status"] == "established"
    assert first.data["visual_pipeline"]["image_visible_to_model"]["status"] == "unknown"
    token = bridge.vault.open(first.data["continuation"], owner, seeded)
    assert all("excerpt" not in p for p in token["remaining"])
    second, _ = await inspect_figure(
        bridge, owner, seeded, visual_source, continuation=first.data["continuation"]
    )
    assert second.data["page"] == 4
    third, _ = await inspect_figure(
        bridge, owner, seeded, visual_source, continuation=second.data["continuation"]
    )
    assert third.data["search_budget"]["render_attempts"] == 3
    assert third.data["continuation"] is None
    assert not list((bridge.settings.parser_root / "jobs").iterdir())


async def test_negative_control_and_spatial_corrections_do_not_overwrite(
    bridge, owner, seeded, visual_source
):
    r, _ = await inspect_figure(bridge, owner, seeded, visual_source, page=3)
    negative = await record_observation(
        bridge,
        owner,
        seeded,
        r.data["render_receipt"],
        report(
            figure_status="figure_not_found",
            visible_feature="Two separate columns of prose, no graph.",
            region=None,
        ),
    )
    assert negative.data["figure_identification_status"] == "figure_not_found"
    assert not negative.data["observation"]["panels"]
    assert negative.data["visual_pipeline"]["image_visible_to_model"]["status"] == "reported"
    assert not negative.data["interpretation_verified"]
    r, _ = await inspect_figure(bridge, owner, seeded, visual_source, "Table 1", page=2)
    with bridge.store.transaction() as session:
        before = session.get(Material, visual_source).text
    correction = {
        "kind": "misassigned_table_cells",
        "extracted_text": "122",
        "visual_observation": "The rightmost value aligns near PubMed; the note below spans all databases.",
        "proposed_interpretation": "122 is the combined final review count, not the PubMed-only count.",
        "region": [0.05, 0.1, 0.95, 0.55],
        "confidence": "high",
    }
    result = await record_observation(
        bridge,
        owner,
        seeded,
        r.data["render_receipt"],
        report(
            reconciliation=[
                correction,
                {
                    **correction,
                    "kind": "column_interleaving",
                    "extracted_text": "Left column",
                    "proposed_interpretation": "Read each prose column separately.",
                },
            ]
        ),
    )
    assert result.data["reconciliation"][0]["text_comparison"] == "exact_anchor_found"
    assert result.data["reconciliation"][0]["verified"] is False
    with bridge.store.transaction() as session:
        assert session.get(Material, visual_source).text == before
    with pytest.raises(DomainError, match="anchor"):
        await record_observation(
            bridge,
            owner,
            seeded,
            r.data["render_receipt"],
            report(reconciliation=[{**correction, "extracted_text": "fabricated anchor"}]),
        )


def test_structured_graph_uncertainty_and_panel_separation():
    def observed(value):
        return VisualField(status="observed", value=value)

    a = GraphPanel(
        region=[0.05, 0.2, 0.5, 0.6],
        panel_label=observed("A"),
        graph_type=observed("line plot"),
        x_axis_label=observed("Dose"),
        x_axis_units=observed("mg/L"),
        y_axis_label=observed("Response"),
        y_axis_units=observed("%"),
        legend_and_groups=observed("Blue treated; red control"),
        visible_trends=observed("Blue rises; red stays nearly flat"),
        statistical_annotations=observed("p = 0.03"),
    )
    b = GraphPanel(
        region=[0.55, 0.2, 0.9, 0.6],
        panel_label=observed("B"),
        x_axis_label=observed("Time"),
        x_axis_units=observed("h"),
        y_axis_label=observed("Count"),
    )
    r = report(panels=[a, b])
    assert r.panels[0].uncertainty_indicators.status == "unknown"
    assert r.panels[1].y_axis_units.status == "unknown"
    assert r.panels[1].legend_and_groups.value is None
    with pytest.raises(ValidationError):
        report(figure_status="figure_not_found", panels=[a])
    with pytest.raises(ValidationError):
        report(visibility="unavailable")
    with pytest.raises(ValidationError):
        VisualField(status="unknown", value="SD")
    with pytest.raises(ValidationError):
        report(source_interpretation=observed("Invented author claim"))
    with pytest.raises(ValidationError):
        report(panels=[a.model_copy(update={"region": [0.0, 0.0, 1, 1]})])


async def test_revocation_blocks_receipt_and_continuation(bridge, owner, seeded, visual_source):
    r, _ = await inspect_figure(bridge, owner, seeded, visual_source, "Figure 2")
    bridge.synthetic.data["files"]["11"][0]["hidden_for_user"] = True
    for operation in [
        inspect_figure(bridge, owner, seeded, visual_source, continuation=r.data["continuation"]),
        record_observation(bridge, owner, seeded, r.data["render_receipt"], report()),
        render_file(bridge, owner, seeded, visual_source),
    ]:
        with pytest.raises(DomainError):
            await operation


async def test_version_hash_owner_expiry_checks(bridge, owner, seeded, visual_source):
    r, _ = await inspect_figure(bridge, owner, seeded, visual_source, "Figure 2")
    for operation in [
        inspect_figure(
            bridge, "another-owner", seeded, visual_source, continuation=r.data["continuation"]
        ),
        inspect_figure(bridge, owner, seeded, visual_source, expected_hash="0" * 64),
    ]:
        with pytest.raises(DomainError):
            await operation
    proof = bridge.vault.open(r.data["render_receipt"], owner, seeded)
    proof["expires"] = (utcnow() - timedelta(seconds=1)).isoformat()
    with pytest.raises(DomainError):
        await record_observation(
            bridge, owner, seeded, bridge.vault.seal(proof, owner, seeded), report()
        )
    bridge.synthetic.data["files"]["11"][0]["updated_at"] = "2026-10-23T00:00:00Z"
    with pytest.raises(DomainError):
        await inspect_figure(
            bridge, owner, seeded, visual_source, continuation=r.data["continuation"]
        )


@pytest.mark.parametrize("failure", ["crash", "timeout", "memory", "malformed"])
async def test_renderer_failure_isolation(
    bridge, owner, seeded, visual_source, monkeypatch, failure
):
    async def broken(*args, **kwargs):
        if failure == "timeout":
            raise TimeoutError()
        if failure == "memory":
            raise MemoryError("private raw data must not escape")
        if failure == "malformed":
            raise DomainError(
                "unsupported_feature",
                "private diagnostic",
                reason_code="RENDER_UNREADABLE_OR_RENDERING_LIMIT",
            )
        raise RuntimeError("private raw data must not escape")

    monkeypatch.setattr("canvas_bridge.figure_inspection.render_file", broken)
    r, png = await inspect_figure(bridge, owner, seeded, visual_source, "Figure 2")
    assert png is None and r.status == "partial_data"
    assert r.data["figure_identification_status"] == "visual_inspection_unavailable"
    assert "private raw" not in r.model_dump_json()
    assert (await read_file(bridge, owner, seeded, visual_source)).data["text"]
    assert (await bridge.list_courses(owner, seeded)).status == "ok"


async def test_byte_and_time_limits(bridge, owner, seeded, visual_source, monkeypatch):
    bridge.settings.visual_total_image_bytes = 1
    r, png = await inspect_figure(bridge, owner, seeded, visual_source, "Figure 2")
    assert png is None and r.data["fallback_reason"] == "FIGURE_IMAGE_BUDGET"
    assert r.data["continuation"] is None
    bridge.settings.visual_execution_seconds = 0.02

    async def slow(*args, **kwargs):
        await asyncio.sleep(0.1)

    monkeypatch.setattr("canvas_bridge.figure_inspection.read_file", slow)
    r, png = await inspect_figure(bridge, owner, seeded, visual_source, "Figure 2")
    assert png is None and r.data["fallback_reason"] == "FIGURE_EXECUTION_LIMIT"


async def test_text_fallback_and_missing_signals_do_not_claim_absence(
    bridge, owner, seeded, visual_source, monkeypatch
):
    async def must_not_render(*args, **kwargs):
        pytest.fail("Text-only discovery must not render")

    monkeypatch.setattr("canvas_bridge.figure_inspection.render_file", must_not_render)
    r, png = await inspect_figure(
        bridge, owner, seeded, visual_source, "Figure 2", delivery_mode="text"
    )
    assert png is None and r.data["remaining_candidates"][0]["page"] == 4
    assert r.data["search_budget"]["render_attempts"] == 0
    r, png = await inspect_figure(bridge, owner, seeded, visual_source, "Figure 99")
    assert png is None and r.data["figure_identification_status"] == "visual_inspection_unavailable"
    assert r.data["observations"] is None


async def test_deselection_during_render_discards_pixels_and_excerpts(
    bridge, owner, seeded, visual_source, monkeypatch
):
    async def revoked(*args, **kwargs):
        r = await render_file(*args, **kwargs)
        bridge.select_courses(owner, seeded, [], "UTC")
        return r

    monkeypatch.setattr("canvas_bridge.figure_inspection.render_file", revoked)
    with pytest.raises(DomainError):
        await inspect_figure(bridge, owner, seeded, visual_source, "Figure 2")


def test_numerical_precision_and_missing_visibility_are_explicit():
    from canvas_bridge.figure_observations import NumericalReading

    with pytest.raises(ValidationError):
        NumericalReading(value="42", evidence="bar top", region=[0.1, 0.1, 0.2, 0.2])
    estimate = NumericalReading(
        value="approximately 42",
        precision="visual_estimate",
        evidence="Estimated bar height against axis ticks",
        region=[0.1, 0.1, 0.2, 0.2],
    )
    assert estimate.units.status == "unknown"
    unavailable = FigureObservation(
        visibility="unavailable",
        delivery_mode="unknown",
        figure_status="visual_inspection_unavailable",
    )
    assert not unavailable.panels and unavailable.caption.value is None


def test_conflicting_and_ambiguous_capability_evidence_stays_unknown(settings, tmp_path):
    settings.visual_client_evidence_file = tmp_path / "capability.json"
    record = {
        "client_name": "test",
        "client_version": "1",
        "native_image": "supported",
        "basis": "model_visible_probe",
        "evidence_id": "fixture",
        "observed_at": utcnow().isoformat(),
        "expires_at": (utcnow() + timedelta(days=1)).isoformat(),
    }
    settings.visual_client_evidence_file.write_text(json.dumps([record]))
    client = Implementation(name="test", version="1")
    assert capability(settings, client)["native_image"] == "unknown"
    record["client_identity_unique_to_tested_surface"] = True
    settings.visual_client_evidence_file.write_text(json.dumps([record, record]))
    assert capability(settings, client)["native_image"] == "unknown"


async def test_reduced_worker_memory_is_enforced_and_cannot_raise_ceiling(
    bridge, owner, seeded, visual_source
):
    from canvas_bridge.parser_sandbox import extract_isolated

    bridge.settings.visual_worker_memory_mb = 256
    r, png = await render_file(bridge, owner, seeded, visual_source, page=4)
    assert png and r.data["render_diagnostics"]["worker_memory_limit_bytes"] == 256 * 1024 * 1024
    for value in (0, 127, 385, True):
        with pytest.raises(DomainError) as denied:
            extract_isolated(
                visual_pdf(),
                "pdf",
                bridge.settings.parser_root,
                visual={"page": 1, "rotation": 0, "memory_mb": value},
            )
        assert denied.value.reason_code == "VISUAL_MEMORY_LIMIT_INVALID"


@pytest.mark.contract
async def test_real_mcp_transport_discovery_legacy_and_failure_survival(
    running, bridge, seeded, visual_source, token_factory, monkeypatch
):
    async with httpx.AsyncClient(
        timeout=60, headers={"Authorization": f"Bearer {token_factory(scope='academic:read')}"}
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as client:
                await client.initialize()
                r = await client.call_tool(
                    "inspect_course_figure",
                    {
                        "connection_id": seeded,
                        "file_id": visual_source,
                        "figure_label": "Figure 2",
                        "delivery_mode": "native",
                    },
                )
                assert r.structuredContent["data"]["page"] == 4
                assert any(c.type == "image" for c in r.content)
                assert r.structuredContent["data"]["image_delivery"]["status"] == "prepared"
                assert "image_visible_to_model" in r.structuredContent["data"]["visual_pipeline"]
                r = await client.call_tool(
                    "inspect_course_figure",
                    {"connection_id": seeded, "file_id": visual_source, "page": 3},
                )
                assert not any(c.type == "image" for c in r.content)
                assert r.meta["canvas_bridge_page"]["png"]
                assert r.structuredContent["data"]["image_delivery"]["mode"] == "native_page_reader"
                legacy = await client.call_tool(
                    "render_course_file_page", {"connection_id": seeded, "file_id": visual_source}
                )
                assert any(c.type == "image" for c in legacy.content)
                denied = await client.call_tool(
                    "inspect_course_figure",
                    {"connection_id": seeded, "file_id": "../../etc/passwd"},
                )
                assert not any(c.type == "image" for c in denied.content)

                async def crash(*args, **kwargs):
                    raise RuntimeError("private failure")

                monkeypatch.setattr("canvas_bridge.figure_inspection.render_file", crash)
                failed = await client.call_tool(
                    "inspect_course_figure",
                    {"connection_id": seeded, "file_id": visual_source, "page": 1},
                )
                assert failed.structuredContent["data"]["fallback_reason"] == "FIGURE_RENDER_FAILED"
                assert (await client.call_tool("get_connection_status", {})).structuredContent[
                    "status"
                ] == "ok"
