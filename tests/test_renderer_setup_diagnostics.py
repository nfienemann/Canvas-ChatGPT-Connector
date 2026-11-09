"""Sandbox setup remains bounded and distinguishes timeouts from worker errors."""

import os
import subprocess
from pathlib import Path

import pytest

from canvas_bridge.domain import DomainError, Result
from canvas_bridge.egress_errors import safe_error_result

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows sandbox utility")


def test_disk_monitor_tolerates_removed_temporary_directory(tmp_path, monkeypatch):
    from canvas_bridge import windows_sandbox

    transient = tmp_path / "temporary-profile"
    transient.mkdir()
    (tmp_path / "retained.bin").write_bytes(b"12345")
    scandir = os.scandir

    def remove_before_scan(path):
        if Path(path) == transient:
            transient.rmdir()
        return scandir(path)

    monkeypatch.setattr(windows_sandbox.os, "scandir", remove_before_scan)
    assert windows_sandbox.presentation_disk_usage(tmp_path) == 5


def test_disk_monitor_does_not_hide_missing_workspace(tmp_path):
    from canvas_bridge.windows_sandbox import presentation_disk_usage

    with pytest.raises(FileNotFoundError):
        presentation_disk_usage(tmp_path / "missing-workspace")


def test_acl_timeout_has_safe_actionable_diagnostic(monkeypatch):
    from canvas_bridge import windows_sandbox

    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 90
        raise subprocess.TimeoutExpired(["PRIVATE path"], 90, output="PRIVATE output")

    monkeypatch.setattr(windows_sandbox.subprocess, "run", timeout)
    with pytest.raises(DomainError) as caught:
        windows_sandbox.acl(Path("public-runtime"), "/T", timeout=90)
    assert caught.value.reason_code == "DOCUMENT_SANDBOX_SETUP_TIMEOUT"
    clean = safe_error_result(Result(status="retry_later", summary="", data=caught.value.data))
    assert clean.data["error_origin"] == "document_runtime"
    assert clean.data["recommended_action"] == "check_runtime_setup_and_retry"
    assert "PRIVATE" not in clean.model_dump_json()


def test_failed_acl_never_reports_success(monkeypatch):
    from canvas_bridge import windows_sandbox

    def failure(*args, **kwargs):
        assert kwargs["timeout"] == 15
        return subprocess.CompletedProcess([], 1)

    monkeypatch.setattr(windows_sandbox.subprocess, "run", failure)
    with pytest.raises(DomainError, match="Sandbox permissions") as caught:
        windows_sandbox.acl(Path("public-runtime"), "/T")
    assert caught.value.reason_code == "DOCUMENT_SANDBOX_SETUP_FAILED"
