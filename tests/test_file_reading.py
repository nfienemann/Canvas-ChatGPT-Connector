import io
import json
import os
import socket
from datetime import timedelta
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.errors import PdfReadError
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from canvas_bridge.course_files import list_files, read_file, search_files, status
from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.parser_sandbox import ensure_runtime, extract_isolated
from canvas_bridge.parser_worker import extract
from canvas_bridge.storage import Material
from tests.conftest import seed
from tests.test_course_files import file_client as file_client
from tests.test_course_files import file_record


def scientific_pdf(texts=None):
    writer = PdfWriter()
    writer.add_metadata(
        {"/Title": "Synthetic differentiation study", "/Author": "Fictional researchers"}
    )
    for text in texts or [
        "Abstract: We studied stem cell differentiation using controlled cultures.",
        "Methods: Randomized cultures received synthetic treatment or control.",
        "Results: Treated cultures expressed more markers. Conclusions: Results require replication.",
    ]:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        content = DecodedStreamObject()
        content.set_data(
            (
                "BT /F1 12 Tf 40 700 Td ("
                + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                + ") Tj ET"
            ).encode("ascii")
        )
        page[NameObject("/Contents")] = writer._add_object(content)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


@pytest.fixture
async def readable(bridge, owner, seeded, monkeypatch):
    data = scientific_pdf()
    bridge.synthetic.data["files"] = {
        "11": [
            file_record(
                size=len(data),
                updated_at="2026-10-20T12:00:00Z",
                url="https://canvas.synthetic.invalid/files/51/download",
            )
        ]
    }
    bridge.synthetic.data["file_bodies"] = {"51": data}
    bridge.synthetic.data["module_items"] = {
        "11": [{"title": "Paper 3.pdf", "type": "File", "content_id": 51}]
    }
    bridge.settings.file_reading_enabled = True

    async def fixture_parser(data, kind, settings):
        return extract(data, kind)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", fixture_parser)
    _, courses = bridge.selected(owner, seeded)
    listed = await list_files(bridge, owner, seeded, courses[0].id)
    return courses[0], listed.data["files"][0]["file_id"]


async def test_T11_T12_T25_pdf_read_pages_chunks_and_cache(bridge, owner, seeded, readable):
    course, ref = readable
    before = await status(bridge, owner, seeded, ref)
    assert before.data["state"] == "available" and not before.data["indexed"]
    first = await read_file(bridge, owner, seeded, ref, length=40)
    assert first.status == "ok" and first.data["page_count"] == 3
    assert first.data["metadata"] == {}  # Unnecessary personal document properties are omitted.
    text, result = first.data["text"], first
    while result.data["continuation"]:
        c = result.data["continuation"]
        result = await read_file(
            bridge,
            owner,
            seeded,
            c["file_id"],
            offset=c["offset"],
            length=40,
            expected_hash=c["expected_hash"],
            page_start=c["page_start"],
            page_end=c["page_end"],
        )
        text += result.data["text"]
    assert "Methods:" in text and "Conclusions:" in text
    assert sum("download" in r.url.path for r in bridge.synthetic.requests) == 1
    page = await read_file(bridge, owner, seeded, ref, page_start=2)
    assert "Methods:" in page.data["text"] and "Results:" not in page.data["text"]
    assert page.data["passages"][0]["page"] == 2
    assert page.sources[0].locator.startswith("PDF page 2")
    assert (
        first.data["chunk_id"]
        == (await read_file(bridge, owner, seeded, ref, length=40)).data["chunk_id"]
    )
    assert (await status(bridge, owner, seeded, ref)).data["state"] == "parsed"
    with pytest.raises(DomainError, match="Continuation"):
        await read_file(bridge, owner, seeded, ref, offset=40)
    with pytest.raises(DomainError):
        await read_file(bridge, owner, seeded, ref, page_start=4)


async def test_T13_T26_search_is_current_scoped_and_distinguishes_unindexed(
    bridge, owner, seeded, readable
):
    course, ref = readable
    empty = await search_files(bridge, owner, seeded, course.id, "differentiation")
    assert not empty.data["results"] and len(empty.data["unindexed_documents"]) == 1
    await read_file(bridge, owner, seeded, ref)
    found = await search_files(bridge, owner, seeded, course.id, "differentiation")
    assert found.data["results"][0]["page"] == 1
    bridge.synthetic.data["files"]["11"][0]["hidden_for_user"] = True
    denied = await status(bridge, owner, seeded, ref)
    assert denied.status == "permission_denied" and denied.data["state"] == "inaccessible"
    with bridge.store.transaction() as session:
        assert not session.get(Material, ref).text
    assert not (await search_files(bridge, owner, seeded, course.id, "differentiation")).data[
        "results"
    ]


async def test_T25_version_change_rejects_continuation_and_old_index(
    bridge, owner, seeded, readable
):
    course, ref = readable
    first = await read_file(bridge, owner, seeded, ref, length=20)
    updated = scientific_pdf(["A different revised paper."])
    bridge.synthetic.data["file_bodies"]["51"] = updated
    bridge.synthetic.data["files"]["11"][0].update(
        size=len(updated), updated_at="2026-10-21T12:00:00Z"
    )
    with pytest.raises(DomainError, match="Continuation"):
        await read_file(
            bridge, owner, seeded, ref, offset=20, expected_hash=first.data["content_hash"]
        )
    assert not (await search_files(bridge, owner, seeded, course.id, "differentiation")).data[
        "results"
    ]


async def test_T25_parser_upgrade_invalidates_cached_text(bridge, owner, seeded, readable):
    _, ref = readable
    await read_file(bridge, owner, seeded, ref)
    with bridge.store.transaction() as session:
        row = session.get(Material, ref)
        row.file_state = {**row.file_state, "parser": "obsolete-parser"}
    assert not (await status(bridge, owner, seeded, ref)).data["indexed"]
    with bridge.store.transaction() as session:
        assert not session.get(Material, ref).text


async def test_T13_unicode_search_offsets_use_original_text(bridge, owner, seeded, readable):
    course, ref = readable
    text = "ß" * 200 + "TARGET methods"
    body = text.encode()
    bridge.synthetic.data["file_bodies"]["51"] = body
    bridge.synthetic.data["file_types"] = {"51": "text/plain"}
    bridge.synthetic.data["files"]["11"][0].update(
        size=len(body), filename="methods.txt", **{"content-type": "text/plain"}
    )
    await read_file(bridge, owner, seeded, ref)
    result = await search_files(bridge, owner, seeded, course.id, "target")
    hit = result.data["results"][0]
    assert hit["page_offset"] == 40
    assert "TARGET methods" in hit["passage"]


async def test_T13_duplicate_names_and_other_owner_cannot_share_cache(
    bridge, owner, seeded, readable
):
    course, ref = readable
    await read_file(bridge, owner, seeded, ref)
    other = await seed(bridge, "other", "other-connection")
    with pytest.raises(DomainError):
        await read_file(bridge, "other", other, ref)
    bridge.synthetic.data["files"]["12"] = bridge.synthetic.data["files"]["11"].copy()
    _, courses = bridge.selected(owner, seeded)
    listing = await list_files(bridge, owner, seeded, courses[1].id)
    assert listing.data["files"][0]["file_id"] != ref
    assert not listing.data["files"][0]["indexed"]
    bridge.select_courses(owner, seeded, [courses[1].id], "UTC")
    with pytest.raises(DomainError):
        await read_file(bridge, owner, seeded, ref)


async def test_T34_expired_cache_is_not_returned(bridge, owner, seeded, readable):
    _, ref = readable
    await read_file(bridge, owner, seeded, ref)
    with bridge.store.transaction() as session:
        row = session.get(Material, ref)
        row.file_state = {
            **row.file_state,
            "expires_at": (utcnow() - timedelta(seconds=1)).isoformat(),
        }
    assert not (await status(bridge, owner, seeded, ref)).data["indexed"]
    with bridge.store.transaction() as session:
        assert not session.get(Material, ref).text


async def test_T11_corrupt_and_timed_out_extraction_remain_explicit(
    bridge, owner, seeded, readable, monkeypatch
):
    _, ref = readable

    async def failed(*args):
        raise DomainError("unsupported_feature", "File is corrupt.")

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", failed)
    with pytest.raises(DomainError, match="corrupt"):
        await read_file(bridge, owner, seeded, ref)
    result = await status(bridge, owner, seeded, ref)
    assert result.data["state"] == "unsupported" and not result.data["indexed"]
    assert "corrupt" in result.data["limitations"][0]


def test_T11_scanned_pdf_has_no_invented_content():
    writer, stream = PdfWriter(), io.BytesIO()
    writer.add_blank_page(width=100, height=100)
    writer.write(stream)
    result = extract(stream.getvalue(), "pdf")
    assert result["coverage"] == "partial" and result["pages"][0]["state"] == "no_text"
    assert any("OCR" in x for x in result["warnings"])
    with pytest.raises(PdfReadError):
        extract(b"%PDF-corrupted", "pdf")


def test_T11_markdown_unicode_and_text_limit():
    result = extract(("# Methods\nα β µg/mL\n" + "X" * 250_000).encode(), "md")
    assert result["coverage"] == "partial"
    assert "α β µg/mL" in result["pages"][0]["text"]
    assert len(result["pages"][0]["text"]) == 250_000


def test_T25_large_pdf_budget_includes_page_separators():
    result = extract(scientific_pdf(["A" * 150_000, "B" * 150_000]), "pdf")
    assert result["coverage"] == "partial"
    assert len("\n\n".join(page["text"] for page in result["pages"])) <= 250_000


async def test_T34_backups_exclude_ephemeral_file_text(bridge, owner, seeded, readable, tmp_path):
    from canvas_bridge.lifecycle import backup

    _, ref = readable
    await read_file(bridge, owner, seeded, ref)
    path = tmp_path / "fixture.backup"
    backup(bridge, path)
    payload = bridge.vault.open(path.read_text(), "operator", "backup")
    file = next(m for m in payload["tables"]["materials"] if m["id"] == ref)
    assert not file["text"] and not file["locators"] and not file["version_hash"]


async def test_T12_module_files_resolve_when_canvas_files_tab_is_disabled(
    bridge, owner, seeded, readable
):
    course, ref = readable
    bridge.synthetic.failures["/api/v1/courses/11/files"] = 403
    with bridge.store.transaction() as session:
        session.delete(session.get(Material, ref))
    listing = await list_files(bridge, owner, seeded, course.id)
    assert listing.status == "partial_data"
    assert listing.data["files"][0]["file_id"] == ref
    assert listing.data["files"][0]["modules"][0]["title"] == "Foundations"
    read = await read_file(bridge, owner, seeded, ref)
    assert "Abstract:" in read.data["text"]


def test_T23_pdf_interactive_actions_are_data_never_executed():
    reader = __import__("pypdf").PdfReader(io.BytesIO(scientific_pdf()))
    writer, stream = PdfWriter(), io.BytesIO()
    writer.append(reader)
    with pytest.warns(DeprecationWarning):
        writer.add_js("app.launchURL('https://example.invalid/should-never-open');")
    writer.write(stream)
    result = extract(stream.getvalue(), "pdf")
    assert "Abstract:" in result["pages"][0]["text"]
    assert any("never executed" in w for w in result["warnings"])


async def test_T14_file_read_reuses_existing_oauth_renewal(
    bridge, owner, seeded, readable, monkeypatch
):
    from canvas_bridge.storage import Connection

    _, ref = readable
    refreshed = []

    async def renew(service, principal, connection_id):
        refreshed.append(connection_id)
        credential = service.vault.seal(
            {"access_token": "renewed-fixture-token"}, principal, connection_id
        )
        with service.store.transaction() as session:
            conn = session.get(Connection, connection_id)
            conn.credential = credential
            conn.token_expires_at = utcnow() + timedelta(hours=1)
        return credential

    with bridge.store.transaction() as session:
        session.get(Connection, seeded).token_expires_at = utcnow() - timedelta(seconds=1)
    monkeypatch.setattr("canvas_bridge.linking.refresh_credential", renew)
    await read_file(bridge, owner, seeded, ref)
    assert refreshed == [seeded]
    download = next(r for r in bridge.synthetic.requests if "download" in r.url.path)
    assert download.headers["Authorization"] == "Bearer renewed-fixture-token"


async def test_T18_deselection_during_parse_cannot_resurrect_text(
    bridge, owner, seeded, readable, monkeypatch
):
    _, ref = readable

    async def deselect(data, kind, settings):
        bridge.select_courses(owner, seeded, [], "UTC")
        return extract(data, kind)

    monkeypatch.setattr("canvas_bridge.course_files.extract_document", deselect)
    with pytest.raises(DomainError):
        await read_file(bridge, owner, seeded, ref)
    with bridge.store.transaction() as session:
        assert session.get(Material, ref) is None


async def test_T34_background_retention_removes_expired_extracted_text(
    bridge, owner, seeded, readable
):
    _, ref = readable
    await read_file(bridge, owner, seeded, ref)
    with bridge.store.transaction() as session:
        session.get(Material, ref).retrieved_at = utcnow() - timedelta(hours=25)
    assert bridge.store.purge_file_cache() == 1
    with bridge.store.transaction() as session:
        row = session.get(Material, ref)
        assert not row.text and not row.locators and not row.version_hash


@pytest.mark.parametrize(
    "template",
    [
        "https://*.invalid/{file_id}",
        "https://{file_id}.host.invalid:444",
        "http://{file_id}.host.invalid",
        "https://host.invalid?x={file_id}",
        "https://{unknown}.host.invalid",
        "https://{file_id}.{file_id}.invalid",
    ],
)
def test_T23_file_host_templates_are_not_wildcards(template):
    from pydantic import ValidationError

    from canvas_bridge.policy import Institution

    with pytest.raises(ValidationError):
        Institution(
            id="test", name="Test", status="candidate", download_origin_templates=[template]
        )


def test_T23_template_is_bound_to_requested_file(file_client):
    from canvas_bridge.file_download import download_destination

    client, _ = file_client
    client.institution.download_origin_templates = [
        "https://a1-{file_id}.cluster1.canvas-user-content.com"
    ]
    assert not download_destination(
        "https://a1-51.cluster1.canvas-user-content.com/object", client, "11", "51"
    )
    with pytest.raises(DomainError):
        download_destination(
            "https://a1-99.cluster1.canvas-user-content.com/object", client, "11", "51"
        )


@pytest.mark.skipif(
    os.name != "nt", reason="Real Windows AppContainer OS test; other platforms fail closed."
)
def test_T23_real_appcontainer_pdf_and_private_resource_denial(tmp_path, monkeypatch):
    from canvas_bridge.windows_sandbox import acl, run

    root = Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
    runtime = ensure_runtime(root)
    result = extract_isolated(scientific_pdf(), "pdf", root)
    assert result["page_count"] == 3 and "Conclusions:" in result["pages"][2]["text"]
    secret = tmp_path / "outside-secret.txt"
    secret.write_text("synthetic-not-a-real-credential")
    work = tmp_path / "probe"
    work.mkdir()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    # Positive controls establish that both destinations are reachable outside
    # the container. Windows Firewall can deny by dropping rather than errno 13.
    with socket.create_connection(listener.getsockname(), 2):
        accepted, _ = listener.accept()
        accepted.close()
    with socket.create_connection(("1.1.1.1", 443), 5):
        pass
    monkeypatch.setenv("CANVAS_SECRET_CANARY", "synthetic-secret")
    probe = runtime / "probe.py"
    probe.write_text(
        """import ctypes as C, json, os, socket, subprocess, sys
from pathlib import Path
root=Path(sys.argv[1]); request=json.loads((root/'probe-request.json').read_text())
results={'secret_env_absent': 'CANVAS_SECRET_CANARY' not in os.environ}
for name, action in [('private_file', lambda:Path(request['secret']).read_bytes()),
                     ('loopback', lambda:socket.create_connection(('127.0.0.1',request['port']),1)),
                     ('internet', lambda:socket.create_connection(('1.1.1.1',443),1)),
                     ('child_process', lambda:subprocess.run([sys.executable,'-c','pass'],check=True)),
                     ('runtime_write', lambda:Path(__file__).with_name('unauthorized.txt').write_text('bad')),
                     ('memory_limit', lambda:bytearray(512*1024*1024))]:
    try: action(); results[name]=False
    except (OSError, MemoryError) as exc: results[name]=True; results[name+'_errno']=getattr(exc,'errno',None)
k=C.WinDLL('kernel32'); a=C.WinDLL('advapi32'); k.GetCurrentProcess.restype=C.c_void_p
handle=C.c_void_p(); a.OpenProcessToken.argtypes=[C.c_void_p,C.c_ulong,C.c_void_p]
a.OpenProcessToken(k.GetCurrentProcess(),8,C.byref(handle)); value=C.c_ulong(); length=C.c_ulong()
a.GetTokenInformation.argtypes=[C.c_void_p,C.c_int,C.c_void_p,C.c_ulong,C.c_void_p]
a.GetTokenInformation(handle,29,C.byref(value),C.sizeof(value),C.byref(length))
results['appcontainer']=value.value==1
(root/'proof.json').write_text(json.dumps(results))
""",
        encoding="utf-8",
    )
    acl(probe, "/grant:r", "*S-1-15-2-1:(RX)")
    (work / "probe-request.json").write_text(
        json.dumps({"secret": str(secret), "port": listener.getsockname()[1]})
    )
    try:
        run(runtime, work, script="probe.py")
        proof = json.loads((work / "proof.json").read_text())
        assert all(
            proof[k] is True
            for k in [
                "secret_env_absent",
                "private_file",
                "loopback",
                "internet",
                "child_process",
                "runtime_write",
                "appcontainer",
                "memory_limit",
            ]
        ), proof
        listener.settimeout(0.1)
        with pytest.raises(TimeoutError):
            listener.accept()
    finally:
        listener.close()
        probe.unlink(missing_ok=True)


@pytest.mark.skipif(os.name != "nt", reason="Real Windows Job Object timeout test.")
def test_T23_real_worker_timeout_kills_process(tmp_path):
    from canvas_bridge.windows_sandbox import acl, run

    root = Path(os.environ["LOCALAPPDATA"]) / "CanvasBridge/parser"
    runtime = ensure_runtime(root)
    script = runtime / "timeout_probe.py"
    script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    acl(script, "/grant:r", "*S-1-15-2-1:(RX)")
    try:
        with pytest.raises(TimeoutError):
            run(runtime, tmp_path, script=script.name, timeout=0.2)
    finally:
        script.unlink()
