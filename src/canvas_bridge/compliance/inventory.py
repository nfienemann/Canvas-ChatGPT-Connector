"""Bounded repository metadata. Never read settings, databases or authentication logs."""

import ast
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from canvas_bridge.compliance.models import EvidenceError, FixtureCatalog, Registry, Source

ROOT_FILES = {
    "evidence/release-gates.md",
    ".gitignore",
    ".gitattributes",
    "pyproject.toml",
    "uv.lock",
    "Dockerfile",
    "Codex_Spec.md",
    "AGENTS.md",
    "README.md",
    "SECURITY.md",
    "LICENSE-STATUS.md",
    "institutions.json",
    ".gitleaks.toml",
    ".env.example",
}
PREFIXES = (
    "src/",
    "tests/",
    "scripts/",
    "migrations/",
    "docs/",
    "governance/",
    "ui/",
    ".github/",
    "plugin/",
)


def git(root, *args):
    executable = shutil.which("git")
    if not executable:
        raise EvidenceError("REPOSITORY_METADATA_UNAVAILABLE")
    result = subprocess.run(  # noqa: S603
        [executable, "--no-optional-locks", "-C", str(root), *args],
        capture_output=True,
        timeout=20,
        check=False,  # noqa: S607
    )
    if result.returncode:
        raise EvidenceError("REPOSITORY_METADATA_UNAVAILABLE")
    return result.stdout.decode("utf-8")


def safe_path(root, name):
    if not re.fullmatch(r"[A-Za-z0-9_./ -]+", name) or ".." in Path(name).parts:
        raise EvidenceError("UNSAFE_REPOSITORY_REFERENCE")
    path = root / name
    if Path(name).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise EvidenceError("UNSAFE_REPOSITORY_REFERENCE")
    if any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
        raise EvidenceError("SYMLINK_EVIDENCE_REJECTED")
    return path


def bounded_json(path, maximum=2_000_000):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise EvidenceError("INVALID_EVIDENCE_FILE")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise EvidenceError("INVALID_EVIDENCE_JSON") from exc


def source_state(root):
    root = root.resolve()
    if Path(git(root, "rev-parse", "--show-toplevel").strip()).resolve() != root:
        raise EvidenceError("EXACT_REPOSITORY_ROOT_REQUIRED")
    names = sorted(
        set(git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0"))
        - {""}
    )
    hashes = {}
    for name in names:
        if name not in ROOT_FILES and not name.startswith(PREFIXES):
            continue
        path = safe_path(root, name)
        if not path.is_file():
            continue
        if path.stat().st_size > 25_000_000:
            raise EvidenceError("OVERSIZED_SOURCE_FILE")
        data = path.read_bytes()
        # Git's platform line-ending conversion does not change the source identity.
        try:
            data = data.decode("utf-8").replace("\r\n", "\n").encode()
        except UnicodeError:
            pass
        if name == "governance/controls.json":
            document = json.loads(data)
            # Review attestations bind this source hash; exclude their own values
            # to avoid a circular hash. Their full register is separately hashed.
            for group in ("approvals", "manual_reviews"):
                document[group] = [
                    {
                        key: item[key]
                        for key in (
                            "id",
                            "requirement",
                            "targets",
                            "party" if group == "approvals" else "owner",
                        )
                    }
                    for item in document[group]
                ]
            data = json.dumps(document, sort_keys=True).encode()
        hashes[name] = hashlib.sha256(data).hexdigest()
    if not hashes:
        raise EvidenceError("NO_REVIEWABLE_SOURCE")
    return Source(
        commit=git(root, "rev-parse", "HEAD").strip(),
        dirty=bool(git(root, "status", "--porcelain", "--untracked-files=normal").strip()),
        digest=hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
        files=len(hashes),
    )


def test_index(root):
    result = set()
    for path in sorted((root / "tests").glob("test_*.py")):
        safe_path(root, path.relative_to(root).as_posix())
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
                "test_"
            ):
                result.add(f"tests/{path.name}::{node.name}")
    return result


def validate_repository(root):
    registry = Registry.model_validate(bounded_json(safe_path(root, "governance/controls.json")))
    controls = {c.id for c in registry.controls}
    for group in (
        registry.controls,
        registry.policies,
        registry.approvals,
        registry.manual_reviews,
    ):
        if len({item.id for item in group}) != len(group):
            raise EvidenceError("DUPLICATE_REGISTRY_ID")
    known_tests = test_index(root)
    for incident in registry.operational_regressions:
        for ref in incident.tests:
            if ref not in known_tests and not any(t.startswith(ref + "::") for t in known_tests):
                raise EvidenceError("UNKNOWN_OPERATIONAL_REGRESSION_TEST")
    from canvas_bridge.compliance.checks import COMMAND_IDS

    if set(registry.required_checks) - COMMAND_IDS:
        raise EvidenceError("UNKNOWN_REQUIRED_CHECK")
    for control in registry.controls:
        if (
            not control.objective
            or not control.manual_verification
            or not control.residual_limitation
        ):
            raise EvidenceError("INCOMPLETE_CONTROL")
        if set(control.checks) - COMMAND_IDS:
            raise EvidenceError("UNKNOWN_CONTROL_CHECK")
        for ref in control.components + control.enforcement:
            name, _, symbol = ref.partition(":")
            path = safe_path(root, name)
            if not path.is_file():
                raise EvidenceError("MISSING_ENFORCEMENT_REFERENCE")
            if symbol and symbol not in path.read_text(encoding="utf-8"):
                raise EvidenceError("MISSING_ENFORCEMENT_SYMBOL")
        for ref in control.tests:
            if ref not in known_tests and not any(t.startswith(ref + "::") for t in known_tests):
                raise EvidenceError("UNKNOWN_TEST_REFERENCE")
    for policy in registry.policies:
        if set(policy.controls) - controls or policy.review_due <= policy.reviewed_on:
            raise EvidenceError("INVALID_POLICY_MAPPING")
        if not policy.url.startswith("https://") or not policy.sections:
            raise EvidenceError("INCOMPLETE_POLICY_SOURCE")
    if len(registry.templates) < 15:
        raise EvidenceError("INCOMPLETE_REVIEW_TEMPLATES")
    for name in registry.templates.values():
        path = safe_path(root, name)
        if not path.is_file() or "UNVERIFIED" not in path.read_text(encoding="utf-8"):
            raise EvidenceError("UNVERIFIED_TEMPLATE_MARKER_REQUIRED")
    validate_fixtures(root)
    return registry


def validate_fixtures(root):
    catalog = FixtureCatalog.model_validate(
        bounded_json(safe_path(root, "governance/fixtures.json"))
    )
    actual = {}
    names = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
    for name in sorted(set(names)):
        if not name.startswith(("tests/fixtures/", "governance/demo/")):
            continue
        path = safe_path(root, name)
        if path.is_file():
            actual[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != catalog.files:
        raise EvidenceError("UNREVIEWED_OR_CHANGED_FIXTURE_DATA")
    # A digest is only change detection; provenance still requires human review.
    return catalog
