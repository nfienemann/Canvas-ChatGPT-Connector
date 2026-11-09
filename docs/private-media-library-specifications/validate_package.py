"""Validate specification artifacts only. Requires Python and jsonschema."""

import csv
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent
checks = []


def require(condition, label):
    if not condition:
        raise AssertionError(label)
    checks.append(label)


def read_json(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


for path in ROOT.rglob("*.json"):
    json.loads(path.read_text(encoding="utf-8"))
checks.append("All JSON files parse")

schema_examples = {
    "library-item": "library-item",
    "intake-request": "intake-request",
    "intake-receipt": "intake-receipt",
}
for schema_name, example_name in schema_examples.items():
    schema = read_json(f"schemas/{schema_name}.schema.json")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        read_json(f"examples/{example_name}.json")
    )
checks.append("Three Draft 2020-12 schemas and their examples validate")

tool = read_json("contracts/submit-library-files.tool.json")
Draft202012Validator.check_schema(tool["inputSchema"])
Draft202012Validator.check_schema(tool["outputSchema"])
Draft202012Validator(tool["inputSchema"]).validate(
    read_json("examples/submit-library-files.input.json")
)
Draft202012Validator(tool["outputSchema"]).validate(read_json("examples/intake-receipt.json"))
require(
    tool["_meta"]["openai/fileParams"] == ["files"],
    "File parameter metadata points to top-level files",
)
file_shape = tool["inputSchema"]["properties"]["files"]["items"]
require(
    set(file_shape["properties"]) == {"download_url", "file_id", "mime_type", "file_name"},
    "All four host file fields declared",
)
require(
    set(file_shape["required"]) == {"download_url", "file_id"},
    "Only the two mandatory host file fields are required",
)
require(tool["annotations"]["readOnlyHint"] is False, "Import is marked as a mutation")

fixture = (ROOT / "examples/fictional-note.txt").read_bytes()
item = read_json("examples/library-item.json")
require(
    item["original_sha256"] == hashlib.sha256(fixture).hexdigest()
    and item["size_bytes"] == len(fixture),
    "Example identity matches actual fictional fixture bytes",
)
require(
    read_json("examples/intake-receipt.json")["files"][0]["original_sha256"]
    == item["original_sha256"],
    "Receipt hash matches example original",
)

# Negative contract checks catch accidental acceptance of ownership overrides,
# missing transfer fields and success receipts without actual source identity.
invalid = dict(read_json("examples/intake-request.json"), owner_id="forged")
require(
    not Draft202012Validator(read_json("schemas/intake-request.schema.json")).is_valid(invalid),
    "Client owner override rejected by intake schema",
)
invalid = read_json("examples/submit-library-files.input.json")
del invalid["files"][0]["download_url"]
require(
    not Draft202012Validator(tool["inputSchema"]).is_valid(invalid),
    "Missing transfer URL rejected by tool schema",
)
invalid = read_json("examples/intake-receipt.json")
invalid["files"][0]["original_sha256"] = None
require(
    not Draft202012Validator(tool["outputSchema"]).is_valid(invalid),
    "Published receipt requires an original checksum",
)

for path in ROOT.glob("*.md"):
    for target in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
        if re.match(r"https?://", target):
            continue
        relative = target.split("#", 1)[0]
        if relative:
            require((path.parent / relative).is_file(), f"Internal link resolves: {relative}")

with (ROOT / "requirements.csv").open(encoding="utf-8", newline="") as handle:
    requirements = list(csv.DictReader(handle))
with (ROOT / "acceptance.csv").open(encoding="utf-8", newline="") as handle:
    cases = list(csv.DictReader(handle))
require(
    {row["requirement_id"] for row in requirements} == {f"PL-{i:02}" for i in range(1, 25)},
    "All 24 requirements appear exactly once",
)
require(len(requirements) == 24, "No duplicate requirements")
case_ids = {row["case_id"] for row in cases}
require(
    case_ids == {f"AT-{i:02}" for i in range(1, 37)} and len(cases) == 36,
    "All 36 acceptance cases appear exactly once",
)
referenced = set()
for row in requirements:
    ids = set(row["acceptance_cases"].split(";"))
    require(bool(ids) and ids <= case_ids, f"Requirement mapped: {row['requirement_id']}")
    referenced |= ids
require(referenced == case_ids, "Every acceptance case is mapped to a requirement")
require(
    all(row["verification"] == "not_run" for row in requirements),
    "Requirements do not claim product verification",
)
require(
    all(row["status"] == "not_run" for row in cases),
    "Acceptance ledger does not claim executed product tests",
)

manifest_path = ROOT / "MANIFEST.json"
if manifest_path.exists():
    manifest = read_json("MANIFEST.json")
    expected = {row["path"] for row in manifest["files"]}
    actual = {
        p.relative_to(ROOT).as_posix()
        for p in ROOT.rglob("*")
        if p.is_file() and p.name != "MANIFEST.json"
    }
    require(actual == expected, "Manifest covers every non-manifest package file")
    for row in manifest["files"]:
        data = (ROOT / row["path"]).read_bytes()
        require(
            len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"],
            f"Manifest checksum: {row['path']}",
        )

if len(sys.argv) > 1:
    archive_path = Path(sys.argv[1]).resolve()
    with zipfile.ZipFile(archive_path) as archive:
        require(archive.testzip() is None, "ZIP CRC integrity")
        names = archive.namelist()
        prefix = ROOT.name + "/"
        require(
            all(
                name.startswith(prefix) and ".." not in Path(name).parts and "\\" not in name
                for name in names
            ),
            "ZIP uses safe paths under one package root",
        )
        actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()}
        require(
            {name[len(prefix) :] for name in names} == actual and len(names) == len(actual),
            "ZIP membership exactly matches package",
        )
        for name in names:
            require(
                archive.read(name) == (ROOT / name[len(prefix) :]).read_bytes(),
                f"ZIP byte match: {name[len(prefix) :]}",
            )

print(
    json.dumps(
        {
            "status": "pass",
            "checks": len(checks),
            "requirements": len(requirements),
            "acceptance_cases": len(cases),
            "product_tests_run": False,
        },
        indent=2,
    )
)
