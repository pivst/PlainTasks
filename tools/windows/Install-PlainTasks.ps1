<#
Install a reviewed bundle into an explicitly selected Sublime data directory.
Existing PlainTasks packages/libraries are never replaced without -BackupExisting.
Packages/User (personal settings, shortcuts and task files) is never modified.
#>
[CmdletBinding(DefaultParameterSetName = 'Portable')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'Portable')][string]$PortablePath,
    [Parameter(Mandatory = $true, ParameterSetName = 'Data')][string]$DataPath,
    [string]$BundleRoot,
    [switch]$BackupExisting
)
if (!$BundleRoot) { $BundleRoot = Split-Path -Parent $PSScriptRoot }
. (Join-Path $PSScriptRoot 'Common.ps1')
$manifest = Get-PTBundle $BundleRoot
if (!$manifest.dependency_libraries_included) { throw 'This bundle has no offline dateutil/six libraries. Build with --libraries before installing.' }
if ($PSCmdlet.ParameterSetName -eq 'Portable') {
    $PortablePath = [IO.Path]::GetFullPath($PortablePath)
    $null = Assert-PTExecutable (Join-Path $PortablePath 'sublime_text.exe')
    $DataPath = Join-Path $PortablePath 'Data'
}
$DataPath = [IO.Path]::GetFullPath($DataPath)
Assert-PTNoReparsePoint $DataPath
$operations = @(
    [pscustomobject]@{ source = (Join-Path $BundleRoot 'PlainTasks.sublime-package'); target = (Join-Path $DataPath 'Installed Packages\PlainTasks.sublime-package') },
    [pscustomobject]@{ source = $null; target = (Join-Path $DataPath 'Packages\PlainTasks') }
)
$libraryRoot = Join-Path $BundleRoot 'lib\python314'
if (!(Test-Path -LiteralPath $libraryRoot -PathType Container)) { throw 'Missing offline libraries.' }
$libraryItems = @($manifest.files | Where-Object { $_.path.StartsWith('lib/python314/') } |
    ForEach-Object { ($_.path -split '/')[2] } | Sort-Object -Unique)
foreach ($name in $libraryItems) {
    $item = Get-Item -LiteralPath (Join-Path $libraryRoot $name) -Force
    $operations += [pscustomobject]@{ source = $item.FullName; target = (Join-Path $DataPath ('Lib\python314\' + $item.Name)) }
}
$installedLibraryRoot = Join-Path $DataPath 'Lib\python314'
if (Test-Path -LiteralPath $installedLibraryRoot -PathType Container) {
    foreach ($item in Get-ChildItem -LiteralPath $installedLibraryRoot -Directory -Force) {
        if ($item.Name -match '^(python_dateutil|six)-.+\.dist-info$' -and !(Test-Path -LiteralPath (Join-Path $libraryRoot $item.Name))) {
            $operations += [pscustomobject]@{ source = $null; target = $item.FullName }
        }
    }
}
$pending = @()
foreach ($operation in $operations) {
    Assert-PTNoReparsePoint $operation.target
    $previous = Get-PTFingerprint $operation.target
    $expected = if ($operation.source) { Get-PTFingerprint $operation.source } else { $null }
    if ($previous -eq $expected) { continue }
    if ($previous -and !$BackupExisting) { throw "Conflict: $($operation.target). Close Sublime, inspect it, and rerun with -BackupExisting to keep a restorable backup." }
    $pending += [pscustomobject]@{ source = $operation.source; target = $operation.target; backup = $null; installed_fingerprint = $expected }
}
if ($pending.Count -eq 0) { Write-Host 'The same PlainTasks package and libraries are already installed.'; return }
$backupRoot = Join-Path $DataPath ('PlainTasks Backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
Assert-PTNoReparsePoint $backupRoot
$null = New-Item -ItemType Directory -Path $backupRoot -Force
$journalPath = Join-Path $backupRoot 'restore.json'
$completed = @()
try {
    foreach ($operation in $pending) {
        if (Test-Path -LiteralPath $operation.target) {
            $operation.backup = Join-Path $backupRoot ('previous-' + $completed.Count)
            Move-Item -LiteralPath $operation.target -Destination $operation.backup
        }
        $completed += $operation
        Write-PTUtf8 $journalPath ([pscustomobject]@{ format = 1; data_path = $DataPath; package_sha256 = $manifest.package_sha256; operations = $completed } | ConvertTo-Json -Depth 8)
        if ($operation.source) {
            $null = New-Item -ItemType Directory -Path (Split-Path -Parent $operation.target) -Force
            Copy-Item -LiteralPath $operation.source -Destination $operation.target -Recurse
        }
    }
} catch {
    # Only undo the paths this invocation just moved/copied; personal data is outside this set.
    foreach ($operation in $completed) {
        if (Test-Path -LiteralPath $operation.target) { Remove-Item -LiteralPath $operation.target -Recurse -Force }
        if ($operation.backup -and (Test-Path -LiteralPath $operation.backup)) { Move-Item -LiteralPath $operation.backup -Destination $operation.target }
    }
    Write-PTUtf8 (Join-Path $backupRoot 'ROLLED_BACK.txt') 'Installation failed and its completed operations were automatically rolled back.'
    throw
}
Write-Host "Installed into: $DataPath"
Write-Host "Restore journal: $journalPath"
Write-Host 'Keep this journal and its previous-* files together. Packages/User was preserved.'
