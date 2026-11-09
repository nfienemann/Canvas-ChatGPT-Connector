"""Execute PowerShell 5.1 with synthetic process inventory; never stop real processes."""

import base64
import os
import subprocess
import sys
from pathlib import Path

import pytest

from canvas_bridge.resources import resource_root


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell 5.1 acceptance")
@pytest.mark.parametrize("mismatch", [False, True])
@pytest.mark.parametrize("missing_listener", [False, True, "zero", "unrelated"])
def test_application_stop_is_bound_to_synthetic_identity(tmp_path, mismatch, missing_listener):
    service = tmp_path / "service with spaces"
    service.mkdir()
    (service / "service.pid").write_text("123")
    env = os.environ.copy()
    env.update(
        FIXTURE_ROOT=str(service),
        FIXTURE_PYTHON=sys.executable,
        FIXTURE_BASE_PYTHON=sys._base_executable,
        FIXTURE_SCRIPT=str(resource_root() / "scripts/Stop-BridgeApplication.ps1"),
        FIXTURE_MISMATCH=str(mismatch),
        FIXTURE_MISSING_LISTENER=str(missing_listener),
    )
    script = r"""
$ErrorActionPreference='Stop'
function Get-CimInstance {
  [pscustomobject]@{ProcessId=123;ParentProcessId=1;ExecutablePath=$env:FIXTURE_PYTHON;CommandLine='python.exe -m canvas_bridge serve'}
  [pscustomobject]@{ProcessId=456;ParentProcessId=123;ExecutablePath=$env:FIXTURE_BASE_PYTHON;CommandLine='python.exe -m canvas_bridge serve'}
  [pscustomobject]@{ProcessId=789;ParentProcessId=1;ExecutablePath='postgres.exe';CommandLine='postgres.exe'}
}
function Get-NetTCPConnection {
  if ($env:FIXTURE_MISSING_LISTENER -eq 'zero') { [pscustomobject]@{OwningProcess=0} }
  elseif ($env:FIXTURE_MISSING_LISTENER -eq 'unrelated') { [pscustomobject]@{OwningProcess=789} }
  elseif ($env:FIXTURE_MISSING_LISTENER -ne 'True') { [pscustomobject]@{OwningProcess=456} }
}
function Invoke-RestMethod {
  if ($env:FIXTURE_MISMATCH -eq 'True') { [pscustomobject]@{resource='https://wrong.invalid'} }
  else { [pscustomobject]@{resource='https://fixture.invalid'} }
}
function Stop-Process { param($Id) Write-Output "STOP:$Id" }
function Wait-Process { param($Id,$Timeout) }
try {
  . $env:FIXTURE_SCRIPT -DeploymentRoot $env:FIXTURE_ROOT -Python $env:FIXTURE_PYTHON -BasePython $env:FIXTURE_BASE_PYTHON -Port 55555 -ResourceUrl 'https://fixture.invalid'
} catch { Write-Output 'REFUSED'; exit 2 }
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode()
    shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run(  # noqa: S603 - fixed shell with synthetic function mocks
        [str(shell), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        env=env,
        capture_output=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert b"STOP:789" not in result.stdout
    if mismatch or missing_listener == "unrelated":
        assert result.returncode == 2 and b"STOP:" not in result.stdout
    else:
        assert result.returncode == 0 and b"STOP:456" in result.stdout
