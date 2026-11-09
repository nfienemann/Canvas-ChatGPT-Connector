param(
    [Parameter(Mandatory=$true)][string]$DeploymentRoot,
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$BasePython,
    [Parameter(Mandatory=$true)][int]$Port,
    [Parameter(Mandatory=$true)][string]$ResourceUrl
)
$ErrorActionPreference = 'Stop'
# Invoked only after the upgrade command's explicit maintenance confirmation.
# Never invoke the installed launcher's Stop action: it stops PostgreSQL too.
$bridgePidPath = Join-Path $DeploymentRoot 'service.pid'
if (-not (Test-Path -LiteralPath $bridgePidPath)) { throw 'Service identity unavailable; stop application manually.' }
$bridgeParent = [int](Get-Content -LiteralPath $bridgePidPath -Raw)
$bridgePython = (Resolve-Path -LiteralPath $Python).Path
$bridgeBasePython = (Resolve-Path -LiteralPath $BasePython).Path
$bridgeProcesses = @(Get-CimInstance Win32_Process)
$bridgeParentProcess = $bridgeProcesses | Where-Object { $_.ProcessId -eq $bridgeParent }
$bridgeListeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if (($bridgeListeners.Count -eq 0 -or @($bridgeListeners | Where-Object { $_.OwningProcess -gt 0 }).Count -eq 0) -and $bridgeParentProcess) {
    # Listener enumeration can be empty or report only PID 0 across Windows
    # app/privilege boundaries. PID 0 is not a process ownership observation.
    # Verify the recorded process tree and resource instead of silently doing nothing.
    $bridgeMetadata = Invoke-RestMethod -Uri ("http://127.0.0.1:"+$Port+"/.well-known/oauth-protected-resource") -TimeoutSec 5
    if ($bridgeMetadata.resource -cne $ResourceUrl -or
        $bridgeParentProcess.ExecutablePath -ine $bridgePython -or
        $bridgeParentProcess.CommandLine -notmatch '\s-m\s+canvas_bridge\s+serve(?:\s|$)') {
        throw 'Application identity mismatch; no process stopped.'
    }
    $bridgeChildren = @($bridgeProcesses | Where-Object {
        $_.ParentProcessId -eq $bridgeParent -and
        ($_.ExecutablePath -ieq $bridgePython -or $_.ExecutablePath -ieq $bridgeBasePython) -and
        $_.CommandLine -match '\s-m\s+canvas_bridge\s+serve(?:\s|$)'
    })
    $bridgeListeners = @($bridgeChildren | ForEach-Object { [pscustomobject]@{OwningProcess=$_.ProcessId} })
    $bridgeListeners += [pscustomobject]@{OwningProcess=$bridgeParent}
}
if ($bridgeListeners.Count -gt 0) {
    $bridgeMetadata = Invoke-RestMethod -Uri ("http://127.0.0.1:"+$Port+"/.well-known/oauth-protected-resource") -TimeoutSec 5
    if ($bridgeMetadata.resource -cne $ResourceUrl) { throw 'Service resource identity mismatch.' }
}
foreach ($bridgeListener in $bridgeListeners) {
    $bridgeProcess = $bridgeProcesses | Where-Object { $_.ProcessId -eq $bridgeListener.OwningProcess }
    if (-not $bridgeParentProcess -or $bridgeParentProcess.ExecutablePath -ine $bridgePython -or
        $bridgeParentProcess.CommandLine -notmatch '\s-m\s+canvas_bridge\s+serve(?:\s|$)' -or
        -not $bridgeProcess -or
        ($bridgeProcess.ProcessId -ne $bridgeParent -and $bridgeProcess.ParentProcessId -ne $bridgeParent) -or
        ($bridgeProcess.ExecutablePath -ine $bridgePython -and $bridgeProcess.ExecutablePath -ine $bridgeBasePython) -or
        $bridgeProcess.CommandLine -notmatch '\s-m\s+canvas_bridge\s+serve(?:\s|$)') {
        throw 'Application identity mismatch; no process stopped.'
    }
}
# Validate every listener before stopping any. PostgreSQL and ngrok are untouched.
foreach ($bridgeListener in $bridgeListeners) {
    Stop-Process -Id $bridgeListener.OwningProcess -ErrorAction Stop
    Wait-Process -Id $bridgeListener.OwningProcess -Timeout 15 -ErrorAction SilentlyContinue
}
# Unknown/background workers are deliberately not killed; database session checks refuse upgrade.
