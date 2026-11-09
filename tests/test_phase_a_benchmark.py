"""Sequential, opt-in Phase A capture against the local synthetic HTTP service."""

import hashlib
import json
import os
import platform
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import pytest

from tests.test_academic_operations_acceptance import build_identity
from tests.test_independent_intelligence import no_lms_running as no_lms_running
from tests.test_permission_consistency_contract import client_session

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "benchmarks/academic/phase-a/specs.zip"
DIGEST = "99350fab359158a14c471a8f8b028badcd5ccc3b4b7e96f7814a51a1a496d899"
OUTPUT = os.environ.get("BRIDGE_PHASE_A_OUTPUT")
pytestmark = pytest.mark.skipif(not OUTPUT, reason="opt-in synthetic Phase A capture")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def now():
    return datetime.now(UTC).isoformat()


def save(folder, name, data):
    (folder / name).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def member(name):
    with ZipFile(BUNDLE) as archive:
        return archive.read("phase_a_baseline/" + name)


def template(name):
    return json.loads(member(f"templates/{name}.json"))


def git(*arguments):
    return subprocess.check_output([shutil.which("git") or "git", *arguments], cwd=ROOT)  # noqa: S603 - fixed Git queries


async def test_bind(no_lms_running, token_factory):
    folder = Path(OUTPUT)
    folder.mkdir(parents=True, exist_ok=False)  # noqa: ASYNC240 - one-time capture setup
    assert sha(BUNDLE.read_bytes()) == DIGEST
    build = build_identity()
    save(folder, "product-source.json", build)
    async with client_session(no_lms_running, token_factory()) as session:
        catalog = (await session.list_tools()).model_dump(mode="json", exclude_none=True)
    save(folder, "tools.json", catalog)
    profile = dict(
        profile="synthetic",
        provider="SyntheticProvider",
        database="sqlite memory",
        auth="signed fixture principal",
        parser="installed local parser",
        LMS_connections=0,
    )
    save(folder, "profile.json", profile)
    bindings = template("current_build_bindings")
    bindings["status"] = "bound"
    bindings["implementation"].update(
        commit=build["base_commit"],
        branch_or_build=git("branch", "--show-current").decode().strip(),
        dirty=bool(git("status", "--porcelain")),
        diff_sha256=sha(git("diff", "--binary", "HEAD")),
        source_sha256=build["source_sha256"],
        runtime_version=platform.python_version(),
        interface_version=sha((folder / "tools.json").read_bytes()),
        captured_at=now(),
        configuration_profile_ref="profile.json",
        configuration_sha256=sha((folder / "profile.json").read_bytes()),
        host_identity="Codex CLI (synthetic benchmark host)",
        unexposed_identity_reason="Model recorded by host where exposed.",
        package_sha256=DIGEST,
    )
    names = {t["name"] for t in catalog["tools"]}
    routes = [
        "IndependentSources.ingest",
        "get_local_document_status",
        "read_local_document",
        "run_independent_academic_workflow",
        "read_local_document",
        "run_independent_academic_workflow",
        "run_independent_academic_workflow",
        "list_local_documents",
        None,
        "run_independent_academic_workflow",
    ]
    for route, name in zip(bindings["routes"], routes, strict=True):
        route.update(
            current_route_name=name,
            current_schema_ref="tools.json" if name in names else None,
            evidence_level="schema_discovered"
            if name in names
            else "source_observed"
            if name
            else "unknown",
            support_status="partial" if name else "not_checked",
            source_anchor_refs=[
                "src/canvas_bridge/independent.py"
                if name == routes[0]
                else "src/canvas_bridge/app.py"
            ],
        )
    historical = json.loads(member("evidence/source_bindings.json"))
    bindings["historical_commit"] = historical["reviewed_commit"]
    bindings["source_comparison"] = {}
    for item in historical["files"]:
        path = ROOT / item["path"]
        bindings["source_comparison"][item["path"]] = dict(
            active_sha256=sha(path.read_bytes()) if path.exists() else None,
            reviewed_sha256=item["sha256"],
        )
    save(folder, "bindings.json", bindings)


HOST_TOOLS = [
    "list_local_documents",
    "read_local_document",
    "get_local_document_status",
    "run_independent_academic_workflow",
]


async def review_host(
    url, token, prompt, workdir, folder, label, *, tools=HOST_TOOLS, instructions=None
):
    import asyncio
    import shutil

    host = shutil.which("codex")
    if not host:
        save(
            folder,
            label + "-status.json",
            {"status": "blocked", "reason": "codex executable unavailable"},
        )
        return None
    (folder / (label + "-prompt.txt")).write_text(prompt, encoding="utf-8")
    args = [
        host,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "-s",
        "read-only",
        "-C",
        str(workdir),
        "--json",
        "-c",
        f'mcp_servers.coursework.url="{url}/mcp"',
        "-c",
        'mcp_servers.coursework.bearer_token_env_var="PHASE_A_FIXTURE_TOKEN"',
        "-c",
        "mcp_servers.coursework.enabled_tools=" + json.dumps(tools),
        "-c",
        ("developer_instructions=" + json.dumps(instructions))
        if instructions
        else 'developer_instructions="Use only the coursework MCP tools for this synthetic packet. Discover the imported materials, check their status, read them with limit five following continuations, and use the independent academic workflow for requirements or planning as applicable. Do not use files, shell, web, apps, or any other tools."',
        "-o",
        str((folder / (label + "-answer.txt")).resolve()),
        "-",
    ]
    import time

    start = time.monotonic()
    with (folder / (label + "-events.jsonl")).open("wb") as events:
        result = await asyncio.to_thread(
            subprocess.run,
            args,
            input=prompt.encode(),
            stdout=events,
            stderr=subprocess.PIPE,
            timeout=600,
            env=os.environ | {"PHASE_A_FIXTURE_TOKEN": token},
        )
    answer = folder / (label + "-answer.txt")
    save(
        folder,
        label + "-status.json",
        dict(
            exit_code=result.returncode,
            elapsed_ms=round(1000 * (time.monotonic() - start)),
            host_version=(
                await asyncio.to_thread(subprocess.check_output, [host, "--version"], text=True)
            ).strip(),
            final_answer_sha256=sha(answer.read_bytes()) if answer.exists() else None,
        ),
    )
    if result.returncode:
        # Never publish process diagnostics containing environment or headers.
        (workdir / (label + "-stderr.txt")).write_bytes(result.stderr)
    return answer.read_text("utf-8") if answer.exists() else None


@pytest.mark.parametrize(
    "run", json.loads(member("run_matrix.json"))["runs"], ids=lambda r: r["run_id"]
)
async def test_capture(run, bridge, no_lms_running, owner, token_factory, tmp_path, monkeypatch):
    import time
    from typing import Any

    from mcp.server.fastmcp.tools.tool_manager import ToolManager
    from pydantic import TypeAdapter

    output = Path(OUTPUT)
    assert all(
        json.loads((output / f"{kind}-checks.json").read_text())["status"] == "pass"
        for kind in ("package", "fixture")
    )
    bindings = json.loads((output / "bindings.json").read_text())
    assert build_identity()["source_sha256"] == bindings["implementation"]["source_sha256"]
    folder = output / run["run_id"]
    folder.mkdir()
    case = next(
        c
        for c in json.loads(member("fixtures/index.json"))["cases"]
        if c["case_id"] == run["case_id"]
    )
    bridge.settings.file_reading_enabled = True
    if os.name == "nt":
        bridge.settings.parser_root = bridge.settings.parser_runtime_root = (
            Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
        )
    clock = datetime.fromisoformat("2026-11-05T12:00:00+00:00")
    monkeypatch.setattr("canvas_bridge.independent_intelligence.utcnow", lambda: clock)
    token = token_factory(scope="academic:read")
    receipts = []
    stage = "setup"
    original = ToolManager.call_tool

    async def observed(self, name, arguments, *args, **kwargs):
        observed_at = now()
        start = time.monotonic()
        response = await original(self, name, arguments, *args, **kwargs)
        receipts.append(
            dict(
                stage=stage,
                started_at=observed_at,
                elapsed_ms=round(1000 * (time.monotonic() - start)),
                tool=name,
                arguments=arguments,
                response=TypeAdapter(Any).dump_python(response, mode="json"),
            )
        )
        save(folder, "calls.json", receipts)
        return response

    monkeypatch.setattr(ToolManager, "call_tool", observed)
    started = now()
    selections = []
    imports = []
    async with client_session(no_lms_running, token) as session:
        before = (await session.call_tool("list_local_documents", {})).structuredContent
        save(folder, "before.json", before)
        for f in case["model_input_files"]:
            raw = member("fixtures/" + f["path"])
            assert sha(raw) == f["sha256"]
            name = Path(f["path"]).name
            mime = {
                ".md": "text/markdown",
                ".txt": "text/plain",
                ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            }[Path(name).suffix]
            options = dict(own_material=True, share_text=True, allow_academic_analysis=True)
            ident = await bridge.independent.ingest(owner, raw, name, mime, **options)
            imports.append(
                dict(
                    route="IndependentSources.ingest",
                    filename=name,
                    mime=mime,
                    options=options,
                    source=f,
                    document_id=ident,
                    owner="synthetic student-one",
                )
            )
            selections.append(
                dict(
                    document_id=ident,
                    expected_hash=f["sha256"],
                    limit=5,
                    role={"brief.md": "instructions", "deck.pptx": "draft"}.get(name, "material"),
                )
            )
        save(folder, "imports.json", imports)
        workdir = tmp_path / "empty-workspace"
        workdir.mkdir()
        stage = "review"
        answer = await review_host(
            no_lms_running, token, member(run["prompt_ref"]).decode(), workdir, folder, "review"
        )
        stage = "planning"
        if run["run_id"] == "baseline_01" and answer:
            await review_host(
                no_lms_running,
                token,
                member("prompts/current_planning.md").decode()
                + "\n\nPrior review answer:\n"
                + answer,
                workdir,
                folder,
                "planning",
            )
        # Independent protocol verification, kept outside the host context and quality score.
        stage = "protocol_verification"
        for selection in selections:
            doc_id = selection["document_id"]
            await session.call_tool("get_local_document_status", {"document_id": doc_id})
            start = 1
            while start:
                read = (
                    await session.call_tool(
                        "read_local_document",
                        {"document_id": doc_id, "start_part": start, "limit": 5},
                    )
                ).structuredContent
                if read["status"] not in {"ok", "partial_data"}:
                    break
                assert read["data"]["content_hash"] == selection["expected_hash"]
                following = read["data"].get("next_part")
                assert following is None or following > start
                start = following
        await session.call_tool(
            "run_independent_academic_workflow",
            {"request": {"capability": "requirements", "documents": selections}},
        )
        if run["run_id"] == "baseline_01" and not any(
            c["stage"] == "planning" and c["tool"] == "run_independent_academic_workflow"
            for c in receipts
        ):
            await session.call_tool(
                "run_independent_academic_workflow",
                {
                    "request": {
                        "capability": "planning",
                        "documents": selections,
                        "plan": {
                            "windows": [
                                {"start": "2026-11-05T14:00:00Z", "end": "2026-11-05T15:00:00Z"}
                            ]
                        },
                    }
                },
            )
        save(
            folder,
            "after.json",
            (await session.call_tool("list_local_documents", {})).structuredContent,
        )
    host_calls = [c for c in receipts if c["stage"] == "review"]
    capture = template("run_capture")
    capture.update(
        run,
        started_at=started,
        finished_at=now(),
        implementation_revision=bindings["implementation"]["source_sha256"],
        bindings_ref="../bindings.json",
        host_identity="Codex CLI",
        starting_state_ref="before.json",
        case_inventory_ref="imports.json",
        selected_source_ids=[s["document_id"] for s in selections],
        fixture_selection=case["model_input_files"],
        call_records=["calls.json"],
        request_ref="review-prompt.txt",
        model_visible_input_refs=["review-events.jsonl"],
        execution_status="completed" if answer and host_calls else "blocked",
        product_boundary_reached=True,
        core_intake_read_analysis_exercised=bool(
            host_calls and answer and any(c["tool"] == "read_local_document" for c in host_calls)
        ),
        final_host_answer_ref="review-answer.txt" if answer else None,
        final_host_answer_sha256=sha((folder / "review-answer.txt").read_bytes())
        if answer
        else None,
        planning_output_ref="planning-answer.txt"
        if (folder / "planning-answer.txt").exists()
        else None,
        state_observations=["before.json", "after.json"],
        observation_mode="synthetic loopback MCP",
    )
    save(folder, "capture.json", capture)
