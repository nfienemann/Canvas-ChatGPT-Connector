# Operator-only Windows clock maintenance. Never changes connector configuration.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Apply,
    [string]$BackupRoot = (Join-Path $env:LOCALAPPDATA 'CanvasBridge\clock-backups')
)

$ErrorActionPreference = 'Stop'
$serviceKey = 'HKLM:\SYSTEM\CurrentControlSet\Services\W32Time'
$configKey = Join-Path $serviceKey 'Config'
$parametersKey = Join-Path $serviceKey 'Parameters'
$clientKey = Join-Path $serviceKey 'TimeProviders\NtpClient'
$triggerKey = Join-Path $serviceKey 'TriggerInfo'
$policyKey = 'HKLM:\SOFTWARE\Policies\Microsoft\W32Time'
$sc = Join-Path $env:SystemRoot 'System32\sc.exe'
$w32tm = Join-Path $env:SystemRoot 'System32\w32tm.exe'
$reg = Join-Path $env:SystemRoot 'System32\reg.exe'

function Read-ClockConfiguration {
    $service = Get-Service W32Time
    $parameters = Get-ItemProperty -LiteralPath $parametersKey
    $client = Get-ItemProperty -LiteralPath $clientKey
    $config = Get-ItemProperty -LiteralPath $configKey
    [ordered]@{
        CapturedAtUtc = [DateTime]::UtcNow.ToString('o')
        DomainJoined = [bool](Get-CimInstance Win32_ComputerSystem).PartOfDomain
        PolicyManaged = Test-Path -LiteralPath $policyKey
        Status = [string]$service.Status
        StartType = [string]$service.StartType
        Type = $parameters.Type
        NtpServer = $parameters.NtpServer
        NtpClientEnabled = $client.Enabled
        SpecialPollInterval = $client.SpecialPollInterval
        MinPollInterval = $config.MinPollInterval
        MaxPollInterval = $config.MaxPollInterval
        TriggersPresent = (Test-Path -LiteralPath $triggerKey) -and
            (@(Get-ChildItem -LiteralPath $triggerKey).Count -gt 0)
    }
}

$before = Read-ClockConfiguration
if (-not $Apply) {
    $before | ConvertTo-Json
    & $w32tm /query /status
    exit $LASTEXITCODE
}

# Refuse to override institutional/domain time policy or repurpose another source.
if ($before.DomainJoined -or $before.PolicyManaged -or $before.Type -ne 'NTP') {
    throw 'Managed/domain time configuration: ask its administrator; nothing changed.'
}
if ($before.NtpServer -ne 'time.windows.com,0x9' -or $before.NtpClientEnabled -ne 1) {
    throw 'This repair requires the existing enabled Microsoft NTP client; nothing changed.'
}
if ([math]::Pow(2, $before.MinPollInterval) -gt 3600 -or
    [math]::Pow(2, $before.MaxPollInterval) -lt 3600) {
    throw 'Hourly polling falls outside the existing allowed range; nothing changed.'
}
if (-not $PSCmdlet.ShouldProcess('Windows Time only',
    'Back up settings; enable automatic startup, remove service triggers, poll the existing source hourly, restart and resynchronize')) {
    exit 0
}
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script in PowerShell as administrator. Nothing changed.'
}

$backup = Join-Path $BackupRoot ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ'))
New-Item -ItemType Directory -Path $backup -ErrorAction Stop | Out-Null
$before | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backup 'before.json') -Encoding UTF8
if ($before.TriggersPresent) {
    & $reg export 'HKLM\SYSTEM\CurrentControlSet\Services\W32Time\TriggerInfo' (Join-Path $backup 'triggers.reg') /y
    if ($LASTEXITCODE -ne 0) { throw 'Trigger backup failed; clock settings were not changed.' }
}
Write-Output "Clock-only backup: $backup"

# Microsoft KB 2385818, method 1; no account, ACL, firewall or token changes.
Set-Service -Name W32Time -StartupType Automatic
& $sc triggerinfo W32Time delete
if ($LASTEXITCODE -ne 0) { throw "Trigger update failed. Review the backup at $backup" }
# Microsoft KB 3205089, workaround 1; keep the existing NTP source and bounds.
Set-ItemProperty -LiteralPath $clientKey -Name SpecialPollInterval -Value 3600
Restart-Service -Name W32Time
$after = Read-ClockConfiguration
if ($after.StartType -ne 'Automatic' -or $after.Status -ne 'Running' -or
    $after.TriggersPresent -or $after.SpecialPollInterval -ne 3600 -or
    $after.NtpServer -ne $before.NtpServer) {
    throw "Clock configuration verification failed. Review the backup at $backup"
}
$after | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backup 'after.json') -Encoding UTF8
Write-Output 'Persistent clock settings verified: automatic startup, existing source, hourly polling.'
& $w32tm /resync /rediscover
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'Settings are applied, but immediate synchronization was not confirmed. Check status and time-service events; do not weaken token validation.'
}
& $w32tm /query /status
