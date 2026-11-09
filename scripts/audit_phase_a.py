"""Verify the observable host boundary and compare returned text with native fixture bytes."""

import argparse
import hashlib
import io
import json
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

BUNDLE = Path(__file__).resolve().parents[1] / "benchmarks/academic/phase-a/specs.zip"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def native_lines(archive, member):
    root = ElementTree.fromstring(archive.read(member))  # noqa: S314 - frozen synthetic PPTX
    return [
        " ".join(node.text.split())
        for node in root.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t")
        if node.text and node.text.strip()
    ]


def surface_contains(part, kind, lines):
    if not part:
        return False
    text = part["text"]
    spans = sorted(
        (s["start"], s["end"]) for s in part.get("text_spans", []) if s["source_kind"] == kind
    )
    if any(not 0 <= a < b <= len(text) for a, b in spans):
        return False
    surface = " ".join(" ".join(text[a:b] for a, b in spans).split())
    offset = 0
    for line in lines:
        at = surface.find(line, offset)
        if at < 0:
            return False
        offset = at + len(line)
    return True


def audit(folder, bundle):
    imports = load(folder / "imports.json")
    by_id = {row["document_id"]: row for row in imports}
    before = load(folder / "before.json")["data"]["documents"]
    after = load(folder / "after.json")["data"]["documents"]
    assert before == [] and len(after) == len(imports)
    assert {row["document_id"]: row["content_hash"] for row in after} == {
        ident: row["source"]["sha256"] for ident, row in by_id.items()
    }
    capture = load(folder / "capture.json")
    cases = json.loads(bundle.read("phase_a_baseline/fixtures/index.json"))["cases"]
    case = next((c for c in cases if c["case_id"] == capture["case_id"]), None)
    expected = {f["path"]: f for f in case["model_input_files"]} if case else {}
    if (
        not expected
        or len(imports) != len(expected)
        or len(by_id) != len(imports)
        or {r["source"]["path"]: r["source"] for r in imports} != expected
        or any(r["filename"] != Path(r["source"]["path"]).name for r in imports)
    ):
        raise ValueError("Imported source identities do not match the case manifest.")
    prompt = bundle.read("phase_a_baseline/" + capture["prompt_ref"]).decode()
    assert (folder / "review-prompt.txt").read_text("utf-8") == prompt
    assert all(
        row["source"]["path"].startswith("cases/" + capture["case_id"] + "/") for row in imports
    )
    calls = load(folder / "calls.json")
    events = [
        json.loads(line)
        for line in (folder / "review-events.jsonl").read_text("utf-8").splitlines()
    ]
    items = [e["item"] for e in events if e["type"] == "item.completed"]
    answer = folder / "review-answer.txt"
    messages = [i["text"] for i in items if i["type"] == "agent_message"]
    assert messages[-1].strip() == answer.read_text("utf-8").strip()
    assert all(
        i["type"] in {"agent_message", "mcp_tool_call", "reasoning", "plan_update"} for i in items
    )
    sources = {}
    observed = []
    for item in (i for i in items if i["type"] == "mcp_tool_call"):
        assert item["server"] == "coursework"
        args = item["arguments"]
        ids = ([args["document_id"]] if "document_id" in args else []) + [
            s["document_id"]
            for s in args.get("request", {}).get("documents", [])
            if "document_id" in s
        ]
        assert all(ident in by_id for ident in ids)
        content = (item.get("result") or {}).get("content", [])
        try:
            body = json.loads(content[0]["text"]) if content else {}
        except (KeyError, ValueError):
            body = {}
        data = body.get("data", {})
        observed.append(
            dict(
                item_id=item["id"],
                tool=item["tool"],
                status=body.get("status"),
                reason=data.get("reason_code"),
                arguments=args,
            )
        )
        if item["tool"] != "read_local_document" or not data.get("parts"):
            continue
        row = by_id[args["document_id"]]
        assert row["source"]["sha256"] == data["content_hash"]
        parts = sources.setdefault(row["filename"], {})
        for part in data["parts"]:
            parts[part["part"]] = part
    surfaces = []
    for row in imports:
        source = row["source"]
        raw = bundle.read("phase_a_baseline/fixtures/" + source["path"])
        assert hashlib.sha256(raw).hexdigest() == source["sha256"]
        name = row["filename"]
        if name != "deck.pptx":
            value = sources.get(name, {}).get(1, {}).get("text", "")
            surfaces.append(
                dict(
                    name=name,
                    part=1,
                    all_text=" ".join(raw.decode().split()) in " ".join(value.split()),
                )
            )
            continue
        with ZipFile(io.BytesIO(raw)) as deck:
            for n in range(1, 8):
                part = sources.get(name, {}).get(n, {})
                surfaces.append(
                    dict(
                        name=name,
                        part=n,
                        truncated=part.get("text_truncated"),
                        body=surface_contains(
                            part,
                            "slide_shapes_and_tables",
                            native_lines(deck, f"ppt/slides/slide{n}.xml"),
                        ),
                        notes=surface_contains(
                            part,
                            "speaker_notes",
                            native_lines(deck, f"ppt/notesSlides/notesSlide{n}.xml"),
                        ),
                    )
                )
    return dict(
        case_files=len(imports),
        observed_import_writes=len(after) - len(before),
        host_calls=observed,
        returned_sources=sorted(sources),
        source_surfaces=surfaces,
        raw_evidence="review-events.jsonl",
        server_measurements="calls.json",
        answer_sha256=hashlib.sha256(answer.read_bytes()).hexdigest(),
        host_internal_context=None,
        observation_boundary="MCP results emitted in the Codex host transcript and final answer",
        limitation="The host does not expose the final internal context assembly or per-token use.",
        elapsed_ms=load(folder / "review-status.json")["elapsed_ms"],
        server_elapsed_ms_by_stage={
            s: sum(c["elapsed_ms"] for c in calls if c["stage"] == s)
            for s in sorted({c["stage"] for c in calls})
        },
        human_active_seconds=None,
        manual_interventions=0,
        human_timing_basis="Automated fixture setup. No timed human participant.",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output
    with ZipFile(BUNDLE) as bundle:
        matrix = json.loads(bundle.read("phase_a_baseline/run_matrix.json"))
        for run in matrix["runs"]:
            folder = output / run["run_id"]
            result = audit(folder, bundle)
            (folder / "transcript-audit.json").write_text(
                json.dumps(result, indent=2) + "\n", encoding="utf-8"
            )


if __name__ == "__main__":
    main()
