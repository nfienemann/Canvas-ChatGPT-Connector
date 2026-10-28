"""Regenerate traceability from the supplied specification and named tests.

The output is JSON-compatible YAML, requiring no YAML runtime dependency.
An automated fixture mapping is never a claim that the entire requirement passed.
"""

import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = (ROOT / "Codex_Spec.md").read_text(encoding="utf-8")
test_functions = {}
for path in sorted((ROOT / "tests").glob("test_*.py")):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test_"
        ):
            for test_id in re.findall(r"T\d{2}", node.name):
                test_functions.setdefault(test_id, []).append(
                    f"{path.relative_to(ROOT).as_posix()}::{node.name}"
                )

component_map = {
    "R01": ["auth.py", "storage.py", "personal.py"],
    "R02": ["linking.py", "settings_ui.py", "personal.py"],
    "R03": ["canvas.py", "service.py", "obligations.py", "activity_planning.py"],
    "R04": [
        "normalize.py",
        "domain.py",
        "evidence.py",
        "academic_rules.py",
        "academic_dates.py",
        "academic_intelligence.py",
    ],
    "R05": ["normalize.py", "planning_dates.py", "academic_dates.py"],
    "R06": ["planning.py", "change_tracking.py"],
    "R07": [
        "grades.py",
        "service.py",
        "grade_audit.py",
        "grading_engine.py",
        "grading_policy.py",
        "academic/grade_engine.py",
        "academic/models.py",
        "academic/gateway.py",
        "academic/services.py",
        "providers/canvas.py",
        "providers/canvas_grades.py",
    ],
    "R08": ["planning.py", "planning_dates.py", "domain.py", "activity_planning.py"],
    "R09": ["domain.py", "planning.py", "planning_dates.py", "activity_planning.py"],
    "R10": ["policy.py", "canvas.py"],
    "R11": ["vault.py", "linking.py"],
    "R12": ["app.py", "auth.py"],
    "R13": [
        "network.py",
        "request_limits.py",
        "file_download.py",
        "retrieval.py",
        "course_files.py",
        "linux_worker.py",
    ],
    "R14": ["canvas.py", "service.py"],
    "R15": ["lifecycle.py", "linking.py"],
    "R16": ["settings_ui.py"],
    "R17": ["app.py"],
    "R18": ["jobs.py", "lifecycle.py"],
    "R19": ["planning.py", "calendar_sync.py"],
    "R20": [
        "retrieval.py",
        "file_download.py",
        "course_files.py",
        "document_search.py",
        "parser_sandbox.py",
        "parser_worker.py",
        "privacy_text.py",
        "privacy/upstream.py",
        "privacy/output.py",
        "privacy/transport.py",
        "privacy/identity.py",
        "visual_files.py",
        "visual_worker.py",
        "visual_schedule.py",
        "visual_ui.py",
        "ocr_runtime.py",
        "ocr_worker.py",
        "windows_sandbox.py",
        "linux_sandbox.py",
        "linux_worker.py",
    ],
    "R21": ["retrieval.py", "course_files.py", "document_search.py", "obligations.py"],
    "R26": ["settings_ui.py"],
    "R27": ["domain.py", "policy.py"],
    "R28": ["jobs.py"],
    "R29": [],
    "R30": [],
    "R31": [],
    "R34": ["app.py"],
    "R35": ["app.py"],
    "R36": ["settings_ui.py"],
    "R37": [],
    "R38": ["linking.py", "settings_ui.py"],
    "R39": [],
    "R40": [],
    "R41": [],
    "R42": ["retrieval.py"],
    "R43": ["lifecycle.py"],
}
deferred = {"R22", "R23", "R24", "R25", "R32", "R33"}
blocked = {"R31", "R37"}
implemented = {"R29", "R35", "R36", "R39", "R40", "R41"}
requirements = []
for line in spec.splitlines():
    if not re.match(r"\| R\d\d \|", line):
        continue
    columns = [x.strip() for x in line.split("|")[1:-1]]
    ref, priority, requirement, gate, declared, _ = columns
    ids = set(re.findall(r"T\d{2}", declared))
    for start, end in re.findall(r"T(\d{2})[â€“-]T(\d{2})", declared):
        ids.update(f"T{n:02}" for n in range(int(start), int(end) + 1))
    tests = sorted({fn for test_id in ids for fn in test_functions.get(test_id, [])})
    requirements.append(
        {
            "requirement_id": ref,
            "priority": priority,
            "requirement": requirement,
            "gate": gate,
            "delivery_state": "deferred"
            if ref in deferred
            else (
                "blocked" if ref in blocked else "implemented" if ref in implemented else "partial"
            ),
            "verification_state": "IMPLEMENTED_UNVERIFIED" if tests else "NOT_IMPLEMENTED",
            "verification_scope": "Source inventory only. Named test functions are not execution evidence; use current compliance-report receipts. No real institution or ChatGPT acceptance is inferred.",
            "implementation_refs": [f"src/canvas_bridge/{p}" for p in component_map.get(ref, [])],
            "test_refs": sorted(ids),
            "automated_test_functions": tests,
            "test_results": [],
            "commit_sha": None,
            "source_manifest": "evidence/sanitized-results/source-manifest.json",
            "environment": "Not established by this source-only index; use compliance-report execution receipts.",
            "institution": "synthetic only",
            "student_role": "synthetic student",
            "chatgpt_surface_and_plan": None,
            "observed_at": None,
            "limitations": ["See evidence/release-gates.md and docs/tool-contracts.md."],
            "next_proof_required": "Complete the remaining acceptance scenario under the documented milestone and external gates.",
        }
    )

test_index = []
for line in spec.splitlines():
    if not re.match(r"\| T\d\d \|", line):
        continue
    columns = [x.strip() for x in line.split("|")[1:-1]]
    ref, scenario, expected = columns
    test_index.append(
        {
            "test_id": ref,
            "scenario": scenario,
            "required_outcome": expected,
            "fixture_functions": test_functions.get(ref, []),
            "coverage": "fixture_functions_present_not_execution_evidence"
            if test_functions.get(ref)
            else "not_run_or_disabled",
            "actual_chatgpt": "not_run",
            "actual_institution": "not_run",
        }
    )

output = ROOT / "evidence"
output.mkdir(exist_ok=True)
for name, payload in (
    ("requirements.yaml", {"schema_version": 1, "requirements": requirements}),
    ("test-index.yaml", {"schema_version": 1, "acceptance_tests": test_index}),
):
    (output / name).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
manifest = {}
for folder in ("src", "tests", "migrations"):
    for path in sorted((ROOT / folder).rglob("*.py")):
        # Match repository LF text on both Windows and Linux.
        manifest[path.relative_to(ROOT).as_posix()] = hashlib.sha256(
            path.read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest()
(output / "sanitized-results").mkdir(exist_ok=True)
(output / "sanitized-results" / "source-manifest.json").write_text(
    json.dumps(manifest, indent=2) + "\n",
    encoding="utf-8",
)
print(f"Registered {len(requirements)} requirements and {len(test_index)} acceptance scenarios.")
