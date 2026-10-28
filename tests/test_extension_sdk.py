"""Fictional contract, isolation, upgrade and arithmetic proofs; no live provider."""

import builtins
import json
import socket
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from canvas_bridge.academic.cli import run
from canvas_bridge.academic.contracts import compatible
from canvas_bridge.domain import DomainError
from canvas_bridge.extensions.forecast import grade_forecast_manifest
from canvas_bridge.extensions.interpreter import evaluate
from canvas_bridge.extensions.runtime import ExtensionRegistry
from canvas_bridge.providers.canvas import AuthorizedCanvasProvider
from canvas_bridge.providers.future_mcp import FutureApprovedMCPProvider
from canvas_bridge.providers.local_grades import LocalGradeProvider
from canvas_bridge.providers.synthetic import SyntheticProvider
from tests.test_grade_audit import grade_data as grade_data
from tests.test_provider_architecture import Clock, demo_request, local

ASSUMPTIONS = {"future_possible_points": "100", "future_score_percent": "90"}


def registry():
    result = ExtensionRegistry()
    result.register(grade_forecast_manifest())
    return result


def test_published_example_version_has_stable_content_and_vectors():
    receipt = ExtensionRegistry().register(grade_forecast_manifest())
    # Changing published module semantics requires a new module version and migration.
    assert receipt == {
        "module_id": "grade_forecast",
        "module_version": "1.0.0",
        "sha256": "e0af0b38cdb58afdf88c9d6f677b7f50baf1b8ecf5a66926c2957854f0c9d4c3",
        "tests_passed": 3,
    }


def execute(extensions, provider, packet, **kwargs):
    return extensions.execute(
        "grade_forecast",
        "1.0.0",
        provider.gateway,
        packet,
        assumptions=kwargs.get("assumptions", ASSUMPTIONS),
    )


def local_grades(**changes):
    data = {
        "schema_version": "local-grades-1",
        "complete": True,
        "rows": [
            {"possible": "100", "result": {"state": "posted", "score": "80"}},
            {"possible": "100", "result": {"state": "posted", "score": "90"}},
        ],
        **changes,
    }
    # Reuse the existing hash-bound local ownership fixture and change only purpose.
    document, request = local(json.dumps(data).encode())
    provider = LocalGradeProvider(
        document._data,
        replace(document.permit, purpose="grade_planning"),
        clock=document.gateway.clock,
    )
    return provider, replace(request, purpose="grade_planning")


def test_provider_discovery_is_versioned_and_does_not_grant_access():
    provider = SyntheticProvider()
    manifest = provider.describe()
    assert manifest.api_version == "1.0.0" and manifest.normalized_schema == "academic-1"
    caps = provider.get_source_capabilities()
    assert caps["get_grade_summary"]["supported"]
    for cap in caps.values():
        assert cap["permission_granted"] is False and cap["read_only"]
        assert cap["permission_requirements"] and cap["limits"]["max_bytes"] <= 2_000_000
    assert caps["get_schedule"]["available_fields"] == []
    assert caps["get_schedule"]["downstream_model_sharing"] == "unavailable"


@pytest.mark.parametrize(
    "version", [None, "0.9.0", "2.0.0", "1.1.0", "1.0.1", "1.0.0-alpha", "01.0.0"]
)
async def test_old_or_new_incompatible_provider_cannot_retrieve(version, monkeypatch):
    provider = SyntheticProvider()
    provider.api_version = version

    async def unexpected(*args):
        pytest.fail("Incompatible provider retrieved data")

    monkeypatch.setattr(provider, "retrieve", unexpected)
    with pytest.raises(DomainError):
        await provider.get_grade_summary(demo_request())


def test_stable_compatible_upgrade_keeps_old_interfaces_and_rejects_new_requirements():
    compatible("1.0.0", "1.2.3")
    compatible("1.2.0", "1.2.3")
    for need, host in [("1.2.4", "1.2.3"), ("2.0.0", "1.9.9"), ("1.0.0", "2.0.0")]:
        with pytest.raises(DomainError):
            compatible(need, host)


async def test_equivalent_forecasts_across_synthetic_local_and_canvas_adapter(
    bridge, owner, seeded, grade_data
):
    bridge.synthetic.data["course_details"]["11"]["apply_assignment_group_weights"] = False
    second = bridge.synthetic.data["assignments"]["11"][1]
    second["points_possible"] = 100
    second["submission"]["score"] = 90
    canvas = AuthorizedCanvasProvider(bridge, owner, seeded)
    imported, request = local_grades()
    synthetic = SyntheticProvider(clock=Clock())
    results = []
    for provider, req in [
        (synthetic, demo_request()),
        (imported, request),
        (canvas, canvas.request(grade_data)),
    ]:
        packet = await provider.get_grade_summary(req)
        result = execute(registry(), provider, packet)
        results.append(result["values"])
        assert result["sources"] and result["restrictions"]
    assert (
        results
        == [
            {
                "current_percent": "85.0000",
                "forecast_percent": "86.6667",
                "change_percentage_points": "1.6667",
            }
        ]
        * 3
    )


async def test_extension_preserves_privacy_metadata_and_exposes_only_numeric_projection(
    monkeypatch,
):
    provider, request = local_grades()
    packet = await provider.get_grade_summary(request)
    data = provider.gateway.consume(packet)
    seen = []

    def inspect(manifest, inputs, **kwargs):
        seen.append(inputs)
        return evaluate(manifest, inputs, **kwargs)

    extensions = registry()
    monkeypatch.setattr("canvas_bridge.extensions.runtime.evaluate", inspect)
    result = execute(extensions, provider, packet)
    assert set(seen[0]) == {"earned_points", "possible_points", *ASSUMPTIONS}
    assert result["restrictions"] == [
        r.restrictions.model_dump(mode="json") for r in data.records()
    ]
    assert all(s["verified_at"] is None for s in result["sources"])
    assert all(r["recipients"] == ["local"] for r in result["restrictions"])
    with pytest.raises(DomainError):
        await provider.get_grade_summary(replace(request, recipient="chatgpt"))


async def test_explicit_missing_capability_and_disabled_future_provider():
    provider, request = local()
    packet = await provider.get_authorized_document(request)
    with pytest.raises(DomainError, match="lacks required"):
        execute(registry(), provider, packet)
    future = FutureApprovedMCPProvider()
    assert not any(c.supported for c in future.describe().operations.values())
    with pytest.raises(DomainError):
        await future.get_grade_summary(demo_request())


async def test_canvas_authorization_failure_propagates_before_acquisition(
    bridge, owner, seeded, monkeypatch
):
    def denied(*args, **kwargs):
        raise DomainError("permission_denied", "Synthetic approval missing")

    monkeypatch.setattr(bridge, "connection_policy", denied)
    provider = AuthorizedCanvasProvider(bridge, owner, seeded)
    before = len(bridge.synthetic.requests)
    with pytest.raises(DomainError):
        await provider.get_grade_summary(provider.request("unselected"))
    assert len(bridge.synthetic.requests) == before


async def test_revocation_during_extension_execution_denies_release():
    provider, request = local_grades()
    packet = await provider.get_grade_summary(request)
    extensions = registry()

    def revoke():
        provider.revoke()
        return 0

    extensions._timer = revoke
    with pytest.raises(DomainError):
        execute(extensions, provider, packet)


async def test_expired_and_forged_receipts_cannot_enter_extension():
    provider, request = local_grades()
    packet = await provider.get_grade_summary(request)
    with pytest.raises(DomainError):
        execute(
            registry(), provider, replace(packet, _request=replace(request, principal="intruder"))
        )
    provider.gateway.clock.now = provider.permit.expires_at
    with pytest.raises(DomainError):
        execute(registry(), provider, packet)


@pytest.mark.parametrize(
    "change",
    [
        {"sdk_version": "2.0.0"},
        {"normalized_schema": "academic-2"},
        {"language": "python"},
        {"network": True},
        {"filesystem": ["*"]},
        {"permission_requirements": ["provider_approval"]},
        {"recipient": "chatgpt"},
        {"projection": "raw_records"},
        {"required_capabilities": ["arbitrary_http"]},
        {"budget": {"max_steps": 100000}},
    ],
)
def test_manifest_cannot_expand_authority_or_execute_code(change):
    manifest = {**json.loads(grade_forecast_manifest()), **change}
    with pytest.raises(DomainError):
        ExtensionRegistry().register(json.dumps(manifest).encode())


def test_unknown_operation_cycle_bad_vector_and_duplicate_json_fail_registration():
    for mutation in ("op", "cycle", "vector", "steps"):
        manifest = json.loads(grade_forecast_manifest())
        if mutation == "op":
            manifest["steps"][0]["op"] = "__import__"
        elif mutation == "cycle":
            manifest["steps"][0]["left"] = {"ref": "forecast"}
        elif mutation == "steps":
            manifest["budget"] = {"max_steps": 1}
        else:
            manifest["tests"][0]["expected"]["forecast_percent"] = "99"
        with pytest.raises(DomainError):
            ExtensionRegistry().register(json.dumps(manifest).encode())
    with pytest.raises(DomainError):
        ExtensionRegistry().register(b'{"sdk_version":"1.0.0","sdk_version":"2.0.0"}')


def test_manifest_size_registry_budget_and_pinned_upgrades():
    extensions = registry()
    with pytest.raises(DomainError):
        extensions.register(b" " * 64001)
    with pytest.raises(DomainError):
        extensions.register(grade_forecast_manifest())
    v2 = json.loads(grade_forecast_manifest())
    v2["module_version"] = "1.1.0"
    extensions.register(json.dumps(v2).encode())
    assert extensions.describe("grade_forecast", "1.0.0").module_version == "1.0.0"
    assert extensions.describe("grade_forecast", "1.1.0").module_version == "1.1.0"
    with pytest.raises(DomainError):
        extensions.describe("grade_forecast", "latest")
    copy = extensions.describe("grade_forecast", "1.0.0")
    copy.emit.clear()
    assert extensions.describe("grade_forecast", "1.0.0").emit
    for index in range(30):
        v2["module_id"] = f"fictional_{index}"
        extensions.register(json.dumps(v2).encode())
    with pytest.raises(DomainError):
        extensions.register(grade_forecast_manifest())


async def test_network_and_filesystem_are_unavailable_to_extension(monkeypatch):
    provider = SyntheticProvider(clock=Clock())
    packet = await provider.get_grade_summary(demo_request())
    extensions = registry()

    def forbidden(*args, **kwargs):
        pytest.fail("Numeric module attempted I/O")

    with monkeypatch.context() as isolated:
        isolated.setattr(socket.socket, "connect", forbidden)
        isolated.setattr(socket, "getaddrinfo", forbidden)
        isolated.setattr(builtins, "open", forbidden)
        isolated.setattr(Path, "open", forbidden)
        result = execute(extensions, provider, packet)
    assert result["values"]["forecast_percent"] == "86.6667"


async def test_time_budget_is_deterministic_and_failed_run_does_not_poison_registry():
    provider = SyntheticProvider(clock=Clock())
    packet = await provider.get_grade_summary(demo_request())
    extensions = registry()
    ticks = iter([0, 1])
    extensions._timer = lambda: next(ticks)
    with pytest.raises(DomainError, match="time budget"):
        execute(extensions, provider, packet)
    extensions._timer = lambda: 0
    assert execute(extensions, provider, packet)["status"] == "hypothetical_scenario"


@pytest.mark.parametrize(
    "value",
    ["NaN", "Infinity", "1e99999", "1e-99999", "x" * 100, "__import__('os')", True, "-1", "101"],
)
async def test_bad_scenario_is_rejected_without_echo(value):
    provider = SyntheticProvider(clock=Clock())
    packet = await provider.get_grade_summary(demo_request())
    with pytest.raises(DomainError) as error:
        execute(
            registry(), provider, packet, assumptions={**ASSUMPTIONS, "future_score_percent": value}
        )
    assert str(value) not in error.value.message


async def test_missing_or_unknown_grades_remain_indeterminate():
    for changes in (
        {"complete": False},
        {"rows": [{"possible": "100", "result": {"state": "unavailable"}}]},
    ):
        provider, request = local_grades(**changes)
        packet = await provider.get_grade_summary(request)
        result = execute(registry(), provider, packet)
        assert result["status"] == "indeterminate" and result["values"] is None


async def test_weighted_and_drop_rules_are_explicitly_unsupported():
    class Weighted(SyntheticProvider):
        async def retrieve(self, operation, request):
            data = await super().retrieve(operation, request)
            return data.model_copy(
                update={
                    "grading_rules": data.grading_rules.model_copy(update={"method": "weighted"})
                }
            )

    provider = Weighted(clock=Clock())
    packet = await provider.get_grade_summary(demo_request())
    result = execute(registry(), provider, packet)
    assert result["status"] == "indeterminate" and result["values"] is None


async def test_offline_forecast_cli_requires_ownership_and_ignores_live_environment(
    tmp_path, monkeypatch
):
    provider, _ = local_grades()
    path = tmp_path / "fictional-grades.json"
    path.write_bytes(provider._data)
    args = SimpleNamespace(
        command="forecast-grades",
        path=path,
        acknowledge_own_material=False,
        future_points="100",
        future_percent="90",
    )
    with pytest.raises(DomainError):
        await run(args)
    args.acknowledge_own_material = True
    monkeypatch.setenv("BRIDGE_PROFILE", "hosted")
    monkeypatch.setenv("BRIDGE_DATABASE_URL", "must-not-be-opened")
    result = await run(args)
    assert result["values"]["forecast_percent"] == "86.6667"


async def test_operation_bound_receipt_and_capability_downgrade_are_rechecked():
    provider = SyntheticProvider(clock=Clock())
    packet = await provider.get_grade_summary(demo_request(recipient="chatgpt"))
    with pytest.raises(DomainError):
        execute(registry(), provider, replace(packet, _operation="list_courses"))
    provider.downstream_model_sharing = "local_only"
    with pytest.raises(DomainError):
        execute(registry(), provider, packet)
    with pytest.raises(DomainError):
        await provider.get_grade_summary(demo_request(recipient="chatgpt"))


@pytest.mark.parametrize("limit", [{"max_records": 1}, {"max_bytes": 1024}])
async def test_declared_provider_resource_limits_are_enforced(limit):
    class Limited(SyntheticProvider):
        def describe(self):
            manifest = super().describe()
            cap = manifest.operations["get_grade_summary"]
            manifest.operations["get_grade_summary"] = cap.model_copy(
                update={"limits": cap.limits.model_copy(update=limit)}
            )
            return manifest

    with pytest.raises(DomainError, match="resource budget"):
        await Limited(clock=Clock()).get_grade_summary(demo_request())


async def test_missing_advertised_fields_cannot_be_inferred_from_returned_records():
    provider = SyntheticProvider(clock=Clock())
    provider.capability_fields = {**provider.capability_fields, "get_grade_summary": ("courses",)}
    packet = await provider.get_grade_summary(demo_request())
    with pytest.raises(DomainError, match="lacks required"):
        execute(registry(), provider, packet)


def test_division_by_zero_numeric_and_output_exhaustion_fail_closed():
    for mode in ("zero", "overflow", "output"):
        manifest = json.loads(grade_forecast_manifest())
        if mode == "zero":
            manifest["steps"][0]["right"] = {"constant": "0"}
        elif mode == "overflow":
            manifest["steps"][0].update(op="multiply", right={"constant": "1000000000"})
        else:
            names = [f"long_numeric_result_field_{i}" for i in range(12)]
            manifest["outputs"] = {name: {"minimum": "0", "maximum": "1000"} for name in names}
            manifest["emit"] = {name: "current" for name in names}
            manifest["budget"] = {"max_output_bytes": 128}
            for vector in manifest["tests"]:
                vector["expected"] = {name: "85" for name in names}
        with pytest.raises(DomainError):
            ExtensionRegistry().register(json.dumps(manifest).encode())


async def test_arbitrary_personal_fields_and_extreme_local_numbers_are_rejected():
    for changes in (
        {"email": "fictional@example.invalid"},
        {"rows": [{"possible": "100", "result": {"state": "posted", "score": "1e99999"}}]},
    ):
        provider, request = local_grades(**changes)
        with pytest.raises(DomainError):
            await provider.get_grade_summary(request)


async def test_an_independent_numeric_module_registers_without_core_changes():
    manifest = json.loads(grade_forecast_manifest())
    manifest["module_id"] = "points_remaining_scenario"
    manifest["steps"] = [
        {
            "name": "additional",
            "op": "subtract",
            "left": {"ref": "future_possible_points"},
            "right": {"constant": "0"},
        }
    ]
    manifest["outputs"] = {"additional_points": {"minimum": "0", "maximum": "1000000"}}
    manifest["emit"] = {"additional_points": "additional"}
    for vector in manifest["tests"]:
        vector["expected"] = {"additional_points": vector["inputs"]["future_possible_points"]}
    extensions = ExtensionRegistry()
    extensions.register(json.dumps(manifest).encode())
    provider = SyntheticProvider(clock=Clock())
    packet = await provider.get_grade_summary(demo_request())
    result = extensions.execute(
        "points_remaining_scenario", "1.0.0", provider.gateway, packet, assumptions=ASSUMPTIONS
    )
    assert result["values"] == {"additional_points": "100.0000"}
    assert result["restrictions"] and result["sources"]


async def test_provider_timeout_cancels_retrieval_and_never_issues_receipt(monkeypatch):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def immediate_timeout(seconds):
        raise TimeoutError
        yield  # pragma: no cover

    provider = SyntheticProvider(clock=Clock())
    monkeypatch.setattr("canvas_bridge.academic.gateway.asyncio.timeout", immediate_timeout)
    with pytest.raises(DomainError, match="time budget"):
        await provider.get_grade_summary(demo_request())
    assert not provider._records
