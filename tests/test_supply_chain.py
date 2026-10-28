import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from scripts.security_tools import checked_binary
from scripts.supply_chain import add_node_sbom, allowed_license, check_locks


def fixture_locks(
    tmp_path,
    *,
    python_source='registry = "https://pypi.org/simple"',
    npm_url="https://registry.npmjs.org/test/-/test-1.0.0.tgz",
    integrity=None,
):
    (tmp_path / "uv.lock").write_text(
        'version = 1\n[[package]]\nname = "fixture"\nversion = "1.0.0"\n'
        "source = { "
        + python_source
        + ' }\nsdist = { url = "https://files.pythonhosted.org/fixture.tar.gz", hash = "sha256:'
        + "0" * 64
        + '" }\n',
        encoding="utf-8",
    )
    folder = tmp_path / "ui/page-reader"
    folder.mkdir(parents=True)
    (folder / "package-lock.json").write_text(
        json.dumps(
            {
                "packages": {
                    "node_modules/test": {
                        "version": "1.0.0",
                        "resolved": npm_url,
                        "integrity": integrity or "sha512-" + base64.b64encode(b"x" * 64).decode(),
                        "license": "MIT",
                    }
                }
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "source",
    [
        'git = "https://evil.invalid/repo"',
        'registry = "https://evil.invalid/simple"',
        'path = "../outside"',
    ],
)
def test_dependency_source_substitution_fails_closed(tmp_path, source):
    fixture_locks(tmp_path, python_source=source)
    with pytest.raises(ValueError):
        check_locks(tmp_path)


@pytest.mark.parametrize("integrity", ["sha1-abc", "", "sha512-invalid"])
def test_missing_or_weak_node_integrity_is_rejected(tmp_path, integrity):
    fixture_locks(tmp_path, integrity=integrity or "missing")
    with pytest.raises(ValueError):
        check_locks(tmp_path)


def test_unreviewed_node_registry_rejected(tmp_path):
    fixture_locks(tmp_path, npm_url="https://evil.invalid/package.tgz")
    with pytest.raises(ValueError):
        check_locks(tmp_path)


def test_tampered_scanner_archive_is_never_extracted():
    with pytest.raises(ValueError, match="checksum"):
        checked_binary(b"attacker executable", "0" * 64, "gitleaks.exe", zipped=True)


def test_scanner_archive_does_not_extract_extra_paths(tmp_path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("gitleaks.exe", b"synthetic binary")
        archive.writestr("../outside", b"bad")
    data = stream.getvalue()
    assert (
        checked_binary(data, hashlib.sha256(data).hexdigest(), "gitleaks.exe", zipped=True)
        == b"synthetic binary"
    )
    assert not (tmp_path / "outside").exists()


@pytest.mark.parametrize(
    "value", ["UNKNOWN", "Proprietary", "MIT OR AGPL-3.0-only", "unrecognized-approval"]
)
def test_unknown_or_incompatible_license_requires_review(value):
    assert not allowed_license(value)


@pytest.mark.parametrize("value", ["MIT", "Apache-2.0 OR BSD-3-Clause", "MPL-2.0", "LGPL-3.0-only"])
def test_policy_recognizes_documented_license_classes(value):
    assert allowed_license(value)


def test_current_locks_have_integrity_and_sbom_node_edges():
    _, npm = check_locks(Path.cwd())
    bom = {
        "metadata": {"component": {"bom-ref": "root"}},
        "components": [],
        "dependencies": [{"ref": "root", "dependsOn": []}],
    }
    result = add_node_sbom(bom, npm)
    refs = {c["bom-ref"] for c in result["components"]} | {"root"}
    assert len(result["components"]) == len(npm["packages"])
    assert all(set(d["dependsOn"]) <= refs for d in result["dependencies"])
    assert result["dependencies"][0]["dependsOn"]
