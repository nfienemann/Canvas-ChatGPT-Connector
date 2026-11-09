<# Read-only OP-07 readiness checks. Never installs, migrates, grants, or removes anything. #>
param([Parameter(Mandatory=$true)][string]$KitRoot)
$ErrorActionPreference = 'Stop'
$kit = (Resolve-Path -LiteralPath $KitRoot).Path
$manifest = Get-Content -LiteralPath (Join-Path $kit 'manifest.json') -Raw | ConvertFrom-Json
$blocks = [System.Collections.Generic.List[string]]::new()
$machineGuid = (Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Cryptography').MachineGuid
$sha = [System.Security.Cryptography.SHA256]::Create()
try { $hostDigest = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($machineGuid)))).Replace('-','').ToLowerInvariant() }
finally { $sha.Dispose() }
if ($hostDigest -eq $manifest.excluded_host_sha256) { $blocks.Add('CURRENT_PERSONAL_HOST_EXCLUDED') }
if ($env:CB_DISPOSABLE_RECOVERY -cne 'YES_DISPOSABLE_OS') { $blocks.Add('DISPOSABLE_OS_NOT_ATTESTED') }
if (-not [Environment]::Is64BitOperatingSystem) { $blocks.Add('WINDOWS_X64_REQUIRED') }
if (@($manifest.publisher_thumbprints).Count -eq 0 -or -not $manifest.release_signers_configured) {
    $blocks.Add('REVIEWED_RELEASE_TRUST_NOT_CONFIGURED')
}
$personalPaths = @(
    (Join-Path $env:LOCALAPPDATA 'CanvasBridge\personal'),
    (Join-Path $env:LOCALAPPDATA 'Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\CanvasBridge\personal')
)
if ($personalPaths | Where-Object { Test-Path -LiteralPath $_ }) { $blocks.Add('PERSONAL_BRIDGE_DATA_PRESENT') }
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{CC5239F2-80A3-4616-84EC-67C2A8AA384A}_is1'
if (Test-Path -LiteralPath $uninstallKey) { $blocks.Add('FRESH_INSTALL_REQUIRES_CLEAN_OS') }
$artifacts = @()
foreach ($name in @('baseline-setup.exe', 'upgrade.zip', 'rollback.zip')) {
    $record = $manifest.artifacts | Where-Object { $_.name -ceq $name }
    $path = Join-Path $kit $name
    if (-not $record -or -not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $blocks.Add("MISSING_ARTIFACT:$name")
        continue
    }
    $file = Get-Item -LiteralPath $path
    if (($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $file.Length -gt 536870912) {
        $blocks.Add("UNSAFE_ARTIFACT:$name")
        continue
    }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -cne $record.sha256) { $blocks.Add("HASH_MISMATCH:$name"); continue }
    if ($name -eq 'baseline-setup.exe') {
        $signature = Get-AuthenticodeSignature -LiteralPath $path
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Thumbprint -notin $manifest.publisher_thumbprints) {
            $blocks.Add('BASELINE_SIGNATURE_UNTRUSTED')
        }
    }
    $artifacts += @{name=$name; sha256=$actual}
}
$result = [ordered]@{
    case_id='OP-07'; status=$(if ($blocks.Count) {'BLOCKED'} else {'READY_FOR_UI_VERIFICATION'})
    observed_at=[DateTimeOffset]::UtcNow.ToString('o'); blockers=@($blocks.ToArray())
    artifacts=$artifacts; institutional_access_enabled=$false; installer_executed=$false
    scope='Read-only preflight. Package signatures, versions and schema must still pass the official update UI. This is never an OP-07 PASS.'
}
$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $kit 'preflight.json') -Encoding UTF8
$result | ConvertTo-Json -Depth 6
if ($blocks.Count) { exit 2 }
