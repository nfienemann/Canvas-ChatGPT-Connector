"""Synthetic complete-slide rendering, transport and fail-closed regressions."""

import base64
import hashlib
import json
import os
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from canvas_bridge.domain import DomainError
from canvas_bridge.full_slides import render_slide
from canvas_bridge.presentation_worker import render_preflight
from canvas_bridge.presentations import read_slide
from tests.conftest import seed
from tests.test_mcp_contract import running as running
from tests.test_presentations import presentation
from tests.test_presentations import readable_presentation as readable_presentation
from tests.test_workbooks import rewrite

FIXTURE = Path(__file__).parent / "fixtures/full-slide.pptx"


def test_preflight_preserves_true_order_and_rejects_external_resources():
    assert render_preflight(FIXTURE.read_bytes())["slide_count"] == 2
    data = presentation()
    external = rewrite(
        data,
        "ppt/slides/_rels/slide2.xml.rels",
        lambda s: s.replace(
            'Target="../media/image1.png"',
            'TargetMode="External" Target="http://127.0.0.1/private"',
        ),
    )
    with pytest.raises(ValueError, match="invalid_office_reference"):
        render_preflight(external)
    internal_url = rewrite(
        data,
        "ppt/slides/_rels/slide2.xml.rels",
        lambda s: s.replace('Target="../media/image1.png"', 'Target="file:///private.png"'),
    )
    with pytest.raises(ValueError, match="invalid_office_reference"):
        render_preflight(internal_url)
    action = rewrite(
        data,
        "ppt/slides/slide2.xml",
        lambda s: s.replace("<a:r>", '<a:r action="ppaction://macro?name=test">', 1),
    )
    with pytest.raises(ValueError, match="active_office_content"):
        render_preflight(action)


def test_optional_renderer_missing_fails_closed(settings, monkeypatch):
    settings.slide_renderer_root = None
    monkeypatch.setattr(
        "canvas_bridge.full_slides.extract_isolated",
        lambda *a, **k: pytest.fail("No parser or conversion should start"),
    )
    with pytest.raises(DomainError, match="optional Windows"):
        render_slide(FIXTURE.read_bytes(), settings, 1)
    for slide in (0, 201, True):
        with pytest.raises(DomainError):
            render_slide(FIXTURE.read_bytes(), settings, slide)


@pytest.mark.parametrize("failure", ["timeout", "corrupt", "page_count", "oversize"])
def test_failed_render_cleanup_and_no_fallback(failure, settings, tmp_path, monkeypatch):
    import canvas_bridge.full_slides as module

    settings.file_reading_enabled = True
    settings.parser_root = tmp_path
    settings.slide_renderer_root = tmp_path / "trusted-office"
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    jobs = []

    def extraction(data, kind, *args, **kwargs):
        if kind == "pptx":
            return {"metadata": {"render_preflight": {"slide_count": 2}}}
        return {"page_count": 2}

    def office(runtime, work, slide):
        jobs.append(work)
        assert slide == 1 and (work / "input.pptx").is_file()
        if failure == "timeout":
            raise TimeoutError()
        (work / "input.pdf").write_bytes(
            b"not PDF"
            if failure == "corrupt"
            else b"%PDF-" + b"x" * 10_000_001
            if failure == "oversize"
            else b"%PDF-1.7"
        )

    monkeypatch.setattr(module, "extract_isolated", extraction)
    monkeypatch.setattr("canvas_bridge.windows_sandbox.run_office", office)
    with pytest.raises(DomainError):
        render_slide(FIXTURE.read_bytes(), settings, 1)
    assert jobs and all(not path.exists() for path in jobs)
    assert not module._slot.locked()


@pytest.fixture
def installed_renderer(settings, tmp_path):
    root = os.environ.get("BRIDGE_TEST_SLIDE_RENDERER_ROOT")
    if os.name != "nt" or not root:
        pytest.skip("Requires the explicitly configured Windows LibreOffice test runtime")
    settings.file_reading_enabled = True
    settings.parser_root = tmp_path / "parser"
    settings.slide_renderer_root = Path(root)
    return settings


def test_real_complete_slide_labels_background_picture_hidden_order_and_cleanup(
    installed_renderer, monkeypatch
):
    from io import BytesIO

    from PIL import Image

    from canvas_bridge import windows_sandbox

    jobs = []
    original = windows_sandbox.run_office

    def observe(runtime, work, slide):
        jobs.append(work)
        return original(runtime, work, slide)

    monkeypatch.setattr(windows_sandbox, "run_office", observe)

    data = FIXTURE.read_bytes()
    first = render_slide(data, installed_renderer, 1)
    second = render_slide(data, installed_renderer, 2)
    assert first["visual_kind"] == "pptx_slide" and first["page_count"] == 2
    assert first["page"] == 1 and second["page"] == 2 and second["hidden"]
    assert first["content_hash"] == hashlib.sha256(data).hexdigest()
    assert first["text_layer_characters"] > 100
    assert second["text_layer_characters"] >= len("HIDDEN SECOND SLIDE")
    assert first["image_hash"] != second["image_hash"]
    # Synthetic visual proof retained in pytest's temporary directory for review.
    for item in (first, second):
        (installed_renderer.parser_root / f"proof-slide-{item['page']}.png").write_bytes(
            base64.b64decode(item["png"])
        )
    with Image.open(BytesIO(base64.b64decode(first["png"]))) as image:
        assert image.width > image.height
        # Navy slide background, teal diagram cells and white overlay labels
        # must all survive composition. This is not the isolated embedded image.
        colors = image.convert("RGB").get_flattened_data()
        assert sum(r < 40 and 20 < g < 65 and 30 < b < 90 for r, g, b in colors) > 10000
        assert sum(40 < r < 120 and 140 < g < 210 and 120 < b < 190 for r, g, b in colors) > 1000
        assert sum(r > 240 and g > 240 and b > 240 for r, g, b in colors) > 1000
    assert len(jobs) == 2 and all(not path.exists() for path in jobs)
    assert not list((installed_renderer.parser_root / "jobs").iterdir())


async def test_full_slide_access_source_version_and_citations(
    bridge,
    owner,
    seeded,
    readable_presentation,
    monkeypatch,
):
    _, ref = readable_presentation
    calls = []

    def renderer(data, settings, slide):
        calls.append(slide)
        return {
            "png": "synthetic",
            "visual_kind": "pptx_slide",
            "content_hash": hashlib.sha256(data).hexdigest(),
            "image_locator": f"Slide {slide}",
            "page": slide,
            "page_count": 2,
        }

    monkeypatch.setattr("canvas_bridge.full_slides.render_slide", renderer)
    result, image = await read_slide(bridge, owner, seeded, ref, 1)
    assert image == "synthetic" and result.sources[0].locator == "Slide 1"
    assert result.sources[0].extraction_status == "slide_rendered"
    assert result.data["content_boundary"] == "untrusted_source_data"
    assert result.data["source_version"] and result.data["ocr_performed"] is False
    other = await seed(bridge, "other-owner", "other-connection")
    with pytest.raises(DomainError):
        await read_slide(bridge, "other-owner", other, ref, 1)
    with pytest.raises(DomainError, match="changed"):
        await read_slide(bridge, owner, seeded, ref, 1, "0" * 64)
    assert calls == [1]
    bridge.synthetic.data["files"]["11"][0]["hidden_for_user"] = True
    with pytest.raises(DomainError):
        await read_slide(bridge, owner, seeded, ref, 1)
    assert calls == [1]
    assert all(r.method == "GET" for r in bridge.synthetic.requests)


def test_office_worker_private_files_network_processes_and_timeout(
    installed_renderer, tmp_path, monkeypatch
):
    from canvas_bridge.windows_sandbox import _run

    office = installed_renderer.slide_renderer_root
    executable = next((office / "program").glob("python-core-*/bin/python.exe"))
    secret = tmp_path / "outside.txt"
    secret.write_text("synthetic-canary", encoding="utf-8")
    work = tmp_path / "probe"
    work.mkdir()
    script = work / "probe.py"
    monkeypatch.setenv("BRIDGE_SLIDE_SECRET_CANARY", "synthetic-only")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with socket.create_connection(listener.getsockname(), 2):
            connection, _ = listener.accept()
            connection.close()
        (work / "request.json").write_text(
            json.dumps({"secret": str(secret), "port": listener.getsockname()[1]}), encoding="utf-8"
        )
        script.write_text(
            """import json, os, socket, subprocess, sys
from pathlib import Path
w=Path(sys.argv[1]); request=json.loads((w/'request.json').read_text())
proof={'environment': 'BRIDGE_SLIDE_SECRET_CANARY' not in os.environ}
for name, action in [
    ('private_file', lambda:Path(request['secret']).read_bytes()),
    ('network', lambda:socket.create_connection(('127.0.0.1', request['port']), 1)),
    ('child', lambda:subprocess.run([sys.executable, '-c', 'pass'], check=True)),
    ('runtime_write', lambda:Path(sys.executable).with_name('canary.txt').write_text('bad')),
    ('memory', lambda:bytearray(800*1024*1024)),
]:
    try: action(); proof[name]=False
    except (OSError, MemoryError): proof[name]=True
(w/'proof.json').write_text(json.dumps(proof))
""",
            encoding="utf-8",
        )
        arguments = [str(executable), "-I", "-S", str(script), str(work)]
        _run(office, work, timeout=10, memory_mb=768, office_arguments=arguments)
        assert all(json.loads((work / "proof.json").read_text()).values())
        listener.settimeout(0.1)
        with pytest.raises(TimeoutError):
            listener.accept()
    script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    with pytest.raises(TimeoutError):
        _run(office, work, timeout=0.2, memory_mb=768, office_arguments=arguments)


async def test_real_mcp_complete_slide_image_and_source(
    running, bridge, owner, seeded, readable_presentation, token_factory, installed_renderer
):
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    _, ref = readable_presentation
    data = FIXTURE.read_bytes()
    bridge.settings.slide_renderer_root = installed_renderer.slide_renderer_root
    bridge.synthetic.data["file_bodies"]["51"] = data
    bridge.synthetic.data["files"]["11"][0]["size"] = len(data)
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token_factory(scope='academic:read')}"}, timeout=90
    ) as http:
        async with streamable_http_client(running + "/mcp", http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(
                    "render_course_slide",
                    {"connection_id": seeded, "file_id": ref, "slide": 1},
                )
                assert result.structuredContent["status"] == "ok"
                assert result.structuredContent["data"]["visual_kind"] == "pptx_slide"
                assert result.structuredContent["sources"][0]["locator"] == "Slide 1"
                images = [c for c in result.content if c.type == "image"]
                assert len(images) == 1 and len(base64.b64decode(images[0].data)) > 10000
                assert "png" not in json.dumps(result.structuredContent)
    assert all(r.method == "GET" for r in bridge.synthetic.requests)
