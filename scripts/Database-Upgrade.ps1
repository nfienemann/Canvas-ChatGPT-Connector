param(
    [Parameter(Mandatory=$true)][string]$DeploymentRoot,
    [ValidateSet('Check','Status','BackupOnly','BackupAndApply')][string]$Mode='Check',
    [string]$ExpectedTarget,
    [string]$BackupDirectory,
    [switch]$StopApplication
)
$ErrorActionPreference = 'Stop'
$bridgeProject = Split-Path -Parent $PSScriptRoot
$bridgePython = Join-Path $bridgeProject '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $bridgePython)) { throw 'Repository virtual environment is required.' }
$bridgeMode = @{Check='--check';Status='--status';BackupOnly='--backup-only';BackupAndApply='--backup-and-apply'}
$bridgeArguments = @('-m','canvas_bridge','database-upgrade','--deployment-root',$DeploymentRoot,$bridgeMode[$Mode])
if ($ExpectedTarget) { $bridgeArguments += @('--expected-target',$ExpectedTarget) }
if ($BackupDirectory) { $bridgeArguments += @('--backup-dir',$BackupDirectory) }
if ($StopApplication) { $bridgeArguments += '--stop-application' }
& $bridgePython @bridgeArguments
exit $LASTEXITCODE
