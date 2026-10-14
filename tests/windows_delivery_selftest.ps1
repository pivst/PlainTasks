<#
Run delivery-tool regression checks without launching Sublime or using a real profile.
Requires an extracted delivery bundle. TestRoot must be new; all mutations stay inside it.
Example: powershell.exe -NoProfile -File .\tests\windows_delivery_selftest.ps1 -BundleRoot 'C:\Delivery\PlainTasks'
PowerShell 7 can also run these file-operation checks on macOS; that does not verify Windows 5.1 or GUI behavior.
#>
[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot),
    [Parameter(Mandatory = $true)][string]$BundleRoot,
    [string]$TestRoot = (Join-Path ([IO.Path]::GetTempPath()) ('PlainTasks-delivery-selftest-' + [Guid]::NewGuid().ToString('N')))
)
$ErrorActionPreference = 'Stop'
$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot)
$BundleRoot = [IO.Path]::GetFullPath($BundleRoot)
$TestRoot = [IO.Path]::GetFullPath($TestRoot)
$scripts = Join-Path $RepositoryRoot 'tools\windows'
. (Join-Path $scripts 'Common.ps1')
Assert-PTNoReparsePoint $TestRoot
if (Test-Path -LiteralPath $TestRoot) { throw "TestRoot must not already exist: $TestRoot" }
$bundlePrefix = $BundleRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if ($TestRoot.StartsWith($bundlePrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'TestRoot must be outside the source bundle directory.'
}
$null = Get-PTBundle $BundleRoot
foreach ($file in Get-ChildItem -LiteralPath $scripts -Filter '*.ps1' -File) {
    $tokens = $null; $errors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) { throw ($errors | Out-String) }
}
Write-Host 'PASS: all delivery PowerShell files parsed'
$null = New-Item -ItemType Directory -Path $TestRoot
$bundle = Join-Path $TestRoot 'bundle'
Copy-Item -LiteralPath $BundleRoot -Destination $bundle -Recurse
$data = Join-Path $TestRoot 'data'
foreach ($relative in @('Installed Packages', 'Packages\PlainTasks', 'Packages\User', 'Lib\python314\dateutil', 'Lib\python314\python_dateutil-old.dist-info')) {
    $null = New-Item -ItemType Directory -Path (Join-Path $data $relative) -Force
}
$package = Join-Path $data 'Installed Packages\PlainTasks.sublime-package'
$oldTask = Join-Path $data 'Packages\PlainTasks\my-task.todo'
$userSettings = Join-Path $data 'Packages\User\PlainTasks.sublime-settings'
$dateutil = Join-Path $data 'Lib\python314\dateutil'
$oldMetadata = Join-Path $data 'Lib\python314\python_dateutil-old.dist-info\METADATA'
Write-PTUtf8 $package 'old-package'
Write-PTUtf8 $oldTask 'personal task in old checkout'
Write-PTUtf8 $userSettings 'personal-user-settings'
Write-PTUtf8 (Join-Path $dateutil '__init__.py') 'old-library'
Write-PTUtf8 $oldMetadata 'old-metadata'
$before = Get-PTFingerprint $data
$blocked = $false
try { & (Join-Path $scripts 'Install-PlainTasks.ps1') -DataPath $data -BundleRoot $bundle } catch { $blocked = $true }
if (!$blocked -or (Get-PTFingerprint $data) -ne $before) { throw 'Conflict check mutated the profile.' }
Write-Host 'PASS: conflicts reject without mutation'
& (Join-Path $scripts 'Install-PlainTasks.ps1') -DataPath $data -BundleRoot $bundle -BackupExisting
$backups = Join-Path $data 'PlainTasks Backups'
$journals = @(Get-ChildItem -LiteralPath $backups -Recurse -Filter 'restore.json' -File)
if ($journals.Count -ne 1) { throw 'Expected exactly one installation journal.' }
$journal = $journals[0].FullName
if ((Get-Content -LiteralPath $userSettings -Raw) -ne 'personal-user-settings') { throw 'User settings changed.' }
if (Test-Path -LiteralPath (Join-Path $data 'Packages\PlainTasks')) { throw 'Unpacked conflict remains.' }
$cache = Join-Path $dateutil '__pycache__'
$null = New-Item -ItemType Directory -Path $cache
Write-PTUtf8 (Join-Path $cache 'cached.pyc') 'bytecode-cache'
$count = @(Get-ChildItem -LiteralPath $backups -Directory).Count
& (Join-Path $scripts 'Install-PlainTasks.ps1') -DataPath $data -BundleRoot $bundle
if (@(Get-ChildItem -LiteralPath $backups -Directory).Count -ne $count) { throw 'Identical reinstall created a backup.' }
Write-Host 'PASS: reinstall ignores runtime bytecode and preserves User settings'
$changed = Join-Path $dateutil 'user-changed.py'
Write-PTUtf8 $changed 'custom-content'
$blocked = $false
try { & (Join-Path $scripts 'Restore-PlainTasks.ps1') -JournalPath $journal } catch { $blocked = $true }
if (!$blocked -or !(Test-Path -LiteralPath $changed)) { throw 'Restore overwrote a user modification.' }
Remove-Item -LiteralPath $changed
& (Join-Path $scripts 'Restore-PlainTasks.ps1') -JournalPath $journal
if ((Get-Content -LiteralPath $package -Raw) -ne 'old-package') { throw 'Original package not restored.' }
if ((Get-Content -LiteralPath $oldTask -Raw) -ne 'personal task in old checkout') { throw 'Old checkout task not restored.' }
if ((Get-Content -LiteralPath (Join-Path $dateutil '__init__.py') -Raw) -ne 'old-library') { throw 'Original dependency not restored.' }
if ((Get-Content -LiteralPath $oldMetadata -Raw) -ne 'old-metadata') { throw 'Original metadata not restored.' }
if ((Get-Content -LiteralPath $userSettings -Raw) -ne 'personal-user-settings') { throw 'User settings changed during restore.' }
Write-Host 'PASS: restore rejects user changes and restores original package, checkout and libraries'
$blocked = $false
try { & (Join-Path $scripts 'Restore-PlainTasks.ps1') -JournalPath $journal } catch { $blocked = $true }
if (!$blocked) { throw 'Restore applied the same journal twice.' }
Write-Host 'PASS: repeat restoration rejected'
$failureData = Join-Path $TestRoot 'failed-install-data'
$null = New-Item -ItemType Directory -Path (Join-Path $failureData 'Installed Packages') -Force
$failurePackage = Join-Path $failureData 'Installed Packages\PlainTasks.sublime-package'
$blockingLib = Join-Path $failureData 'Lib'
Write-PTUtf8 $failurePackage 'original-before-failure'
Write-PTUtf8 $blockingLib 'personal-file-blocking-library-directory'
$blocked = $false
try { & (Join-Path $scripts 'Install-PlainTasks.ps1') -DataPath $failureData -BundleRoot $bundle -BackupExisting } catch { $blocked = $true }
if (!$blocked -or (Get-Content -LiteralPath $failurePackage -Raw) -ne 'original-before-failure' -or
    (Get-Content -LiteralPath $blockingLib -Raw) -ne 'personal-file-blocking-library-directory') {
    throw 'A failed installation did not roll back the package or overwrote the blocking personal file.'
}
$rollbackMarkers = @(Get-ChildItem -LiteralPath (Join-Path $failureData 'PlainTasks Backups') -Recurse -Filter 'ROLLED_BACK.txt' -File)
if ($rollbackMarkers.Count -ne 1) { throw 'Failed installation did not record its automatic rollback.' }
Write-Host 'PASS: installation failure after package replacement automatically restores originals'
Write-PTUtf8 (Join-Path $bundle 'lib\python314\rogue.py') 'unlisted-code'
$blocked = $false
try { $null = Get-PTBundle $bundle } catch { $blocked = $true }
if (!$blocked) { throw 'Integrity check accepted unlisted dependency code.' }
Write-Host 'PASS: unlisted dependency code is rejected'
Write-Host "PASS: delivery regression checks completed in $TestRoot"
