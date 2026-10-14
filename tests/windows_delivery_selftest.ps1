<#
Run delivery-tool regression checks without launching Sublime or using a real profile.
Requires an extracted delivery bundle. TestRoot must be new; all mutations stay inside it.
Example: powershell.exe -NoProfile -File .\tests\windows_delivery_selftest.ps1 -BundleRoot 'C:\Delivery\PlainTasks'
PowerShell 7 can also run these file-operation checks on macOS; that does not verify Windows 5.1 or GUI behavior.
#>
[CmdletBinding()]
param(
    [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)][string]$BundleRoot,
    [string]$TestRoot = (Join-Path ([IO.Path]::GetTempPath()) ('PlainTasks-delivery-selftest-' + [Guid]::NewGuid().ToString('N')))
)
if (!$RepositoryRoot) { $RepositoryRoot = Split-Path -Parent $PSScriptRoot }
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
# Exercise the real -File entry point with omitted BundleRoot from an unrelated CWD.
# Windows PowerShell 5.1 binds script parameters before populating PSScriptRoot.
$cliData = Join-Path $TestRoot 'cli-data'
$cliScript = Join-Path $bundle 'windows\Install-PlainTasks.ps1'
$engine = (Get-Process -Id $PID).Path
Push-Location $TestRoot
try {
    & $engine -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $cliScript -DataPath $cliData
    if ($LASTEXITCODE -ne 0) { throw 'Installer -File entry point failed with the default bundle directory.' }
} finally { Pop-Location }
if (!(Test-Path -LiteralPath (Join-Path $cliData 'Installed Packages\PlainTasks.sublime-package'))) {
    throw 'Installer -File entry point did not install the package.'
}
Write-Host 'PASS: external -File entry point resolves default bundle independently of CWD'
# Exercise the distributed CMD entry point on Windows with the actual built-in
# PowerShell 5.1 engine. Redirect stdin from NUL so pause cannot block CI.
if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
    function Invoke-PTNativeLauncher([string]$Launcher, [string]$Arguments = '') {
        $start = New-Object Diagnostics.ProcessStartInfo
        $start.FileName = $env:ComSpec
        $start.Arguments = '/d /v:on /c ""' + $Launcher + '"' + $Arguments + ' < NUL"'
        $start.UseShellExecute = $false
        $start.CreateNoWindow = $true
        $start.RedirectStandardOutput = $true
        $start.RedirectStandardError = $true
        $process = New-Object Diagnostics.Process
        $process.StartInfo = $start
        try {
            $null = $process.Start()
            $stdout = $process.StandardOutput.ReadToEndAsync()
            $stderr = $process.StandardError.ReadToEndAsync()
            if (!$process.WaitForExit(60000)) {
                $process.Kill()
                $process.WaitForExit()
                throw 'CMD launcher did not finish with NUL stdin.'
            }
            Write-Host ($stdout.GetAwaiter().GetResult() + $stderr.GetAwaiter().GetResult())
            return $process.ExitCode
        } finally { $process.Dispose() }
    }
    $launcher = Join-Path $bundle 'Install.cmd'
    $originalAppData = [Environment]::GetEnvironmentVariable('APPDATA', 'Process')
    $nativeAppData = Join-Path $TestRoot 'CMD AppData with spaces ! & folder'
    $nativeData = Join-Path $nativeAppData 'Sublime Text'
    $nativePackage = Join-Path $nativeData 'Installed Packages\PlainTasks.sublime-package'
    $nativeCheckout = Join-Path $nativeData 'Packages\PlainTasks'
    $nativeLibrary = Join-Path $nativeData 'Lib\python314\dateutil'
    $nativeSettings = Join-Path $nativeData 'Packages\User\PlainTasks.sublime-settings'
    foreach ($directory in @((Split-Path -Parent $nativePackage), $nativeCheckout, $nativeLibrary,
                             (Split-Path -Parent $nativeSettings))) {
        $null = New-Item -ItemType Directory -Path $directory -Force
    }
    Write-PTUtf8 $nativePackage 'previous-package-from-cmd'
    Write-PTUtf8 (Join-Path $nativeCheckout 'my-task.todo') 'personal-task-from-cmd'
    Write-PTUtf8 (Join-Path $nativeLibrary '__init__.py') 'previous-library-from-cmd'
    Write-PTUtf8 $nativeSettings 'personal-settings-from-cmd'
    $originalNativePaths = @{}
    foreach ($path in @($nativePackage, $nativeCheckout, $nativeLibrary)) {
        $originalNativePaths[$path] = Get-PTFingerprint $path
    }
    try {
        [Environment]::SetEnvironmentVariable('APPDATA', $nativeAppData, 'Process')
        if ((Invoke-PTNativeLauncher $launcher) -ne 0) { throw 'Native CMD installer failed.' }
        if ((Get-PTFingerprint $nativePackage) -ne (Get-PTFingerprint (Join-Path $bundle 'PlainTasks.sublime-package'))) {
            throw 'CMD launcher did not install into the exact APPDATA path containing spaces, ! and &.'
        }
        if (Test-Path -LiteralPath $nativeCheckout) { throw 'CMD installer did not remove the old unpacked package.' }
        foreach ($item in Get-ChildItem -LiteralPath (Join-Path $bundle 'lib\python314') -Force) {
            if ((Get-PTFingerprint (Join-Path $nativeData ('Lib\python314\' + $item.Name))) -ne (Get-PTFingerprint $item.FullName)) {
                throw "CMD installer did not install the offline dependency: $($item.Name)"
            }
        }
        if ((Get-Content -LiteralPath $nativeSettings -Raw) -ne 'personal-settings-from-cmd') {
            throw 'CMD installer modified personal settings.'
        }
        $nativeBackups = Join-Path $nativeData 'PlainTasks Backups'
        $nativeJournals = @(Get-ChildItem -LiteralPath $nativeBackups -Recurse -Filter 'restore.json' -File)
        if ($nativeJournals.Count -ne 1) { throw 'CMD upgrade did not create exactly one backup journal.' }
        $nativePlan = Get-Content -LiteralPath $nativeJournals[0].FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($path in $originalNativePaths.Keys) {
            $operation = @($nativePlan.operations | Where-Object { $_.target -eq $path })
            if ($operation.Count -ne 1 -or (Get-PTFingerprint $operation[0].backup) -ne $originalNativePaths[$path]) {
                throw "CMD upgrade did not retain the complete previous item: $path"
            }
        }
        if ((Invoke-PTNativeLauncher $launcher) -ne 0) { throw 'Identical CMD reinstall failed.' }
        if (@(Get-ChildItem -LiteralPath $nativeBackups -Recurse -Filter 'restore.json' -File).Count -ne 1) {
            throw 'Identical CMD reinstall created an unnecessary backup.'
        }
        $installedNative = Get-PTFingerprint $nativeData
        [Environment]::SetEnvironmentVariable('APPDATA', $null, 'Process')
        if ((Invoke-PTNativeLauncher $launcher) -ne 1) { throw 'CMD launcher did not reject missing APPDATA with exit code 1.' }
        [Environment]::SetEnvironmentVariable('APPDATA', $nativeAppData, 'Process')
        $missingPortable = Join-Path $TestRoot 'missing portable with spaces'
        if ((Invoke-PTNativeLauncher $launcher (' "' + $missingPortable + '\"')) -ne 1) {
            throw 'CMD launcher did not preserve the PowerShell failure exit code after pause.'
        }
        if ((Get-PTFingerprint $nativeData) -ne $installedNative) { throw 'Failed CMD invocation changed the installed profile.' }
    } finally {
        [Environment]::SetEnvironmentVariable('APPDATA', $originalAppData, 'Process')
    }
    if ([Environment]::GetEnvironmentVariable('APPDATA', 'Process') -ne $originalAppData) {
        throw 'Native CMD test did not restore the original APPDATA environment.'
    }
    Write-Host 'PASS: native CMD upgrade handles special APPDATA paths, preserves backups/settings and returns correct exit codes'
} else {
    Write-Host 'SKIP: native CMD launcher requires Windows; run this suite in Windows PowerShell 5.1.'
}
# Simulate a locked old-library move after the package was already restored.
# A second invocation must resume safely, and changes to an already restored
# item must stop that invocation before another target is touched.
$resumeData = Join-Path $TestRoot 'resume-restore-data'
$resumePackage = Join-Path $resumeData 'Installed Packages\PlainTasks.sublime-package'
$resumeLibrary = Join-Path $resumeData 'Lib\python314\dateutil'
$null = New-Item -ItemType Directory -Path (Split-Path -Parent $resumePackage) -Force
$null = New-Item -ItemType Directory -Path $resumeLibrary -Force
Write-PTUtf8 $resumePackage 'package-before-interrupted-restore'
Write-PTUtf8 (Join-Path $resumeLibrary '__init__.py') 'library-before-interrupted-restore'
& (Join-Path $scripts 'Install-PlainTasks.ps1') -DataPath $resumeData -BundleRoot $bundle -BackupExisting
$resumeJournal = @(Get-ChildItem -LiteralPath (Join-Path $resumeData 'PlainTasks Backups') -Recurse -Filter 'restore.json' -File)[0].FullName
$resumePlan = Get-Content -LiteralPath $resumeJournal -Raw -Encoding UTF8 | ConvertFrom-Json
$failureBackup = @($resumePlan.operations | Where-Object { $_.target -eq $resumeLibrary })[0].backup
$global:PlainTasksRestoreInjectedBackup = $failureBackup
function Move-Item {
    param([string]$LiteralPath, [string]$Destination)
    if ($LiteralPath -eq $global:PlainTasksRestoreInjectedBackup) { throw 'Injected restore backup move failure' }
    Microsoft.PowerShell.Management\Move-Item -LiteralPath $LiteralPath -Destination $Destination
}
$blocked = $false
try { & (Join-Path $scripts 'Restore-PlainTasks.ps1') -JournalPath $resumeJournal } catch { $blocked = $true; $restoreFailure = $_ }
finally { Remove-Item -LiteralPath 'Function:\Move-Item'; Remove-Variable -Name PlainTasksRestoreInjectedBackup -Scope Global }
if (!$blocked -or (Get-Content -LiteralPath $resumePackage -Raw) -ne 'package-before-interrupted-restore' -or
    !(Test-Path -LiteralPath $failureBackup)) {
    throw "Injected restore failure did not retain the original backups and completed package restoration: $restoreFailure"
}
$checkpoint = Join-Path (Split-Path -Parent $resumeJournal) 'restore-progress.json'
if (!(Test-Path -LiteralPath $checkpoint)) { throw 'Interrupted restore did not retain a resumable checkpoint.' }
Write-PTUtf8 $resumePackage 'user-edit-after-partial-restore'
$blocked = $false
try { & (Join-Path $scripts 'Restore-PlainTasks.ps1') -JournalPath $resumeJournal } catch { $blocked = $true }
if (!$blocked -or (Get-Content -LiteralPath $resumePackage -Raw) -ne 'user-edit-after-partial-restore' -or
    (Test-Path -LiteralPath $resumeLibrary)) {
    throw 'Resuming a restore overwrote a user edit or mutated another target before checking it.'
}
Write-PTUtf8 $resumePackage 'package-before-interrupted-restore'
& (Join-Path $scripts 'Restore-PlainTasks.ps1') -JournalPath $resumeJournal
if ((Get-Content -LiteralPath (Join-Path $resumeLibrary '__init__.py') -Raw) -ne 'library-before-interrupted-restore') {
    throw 'Resumed restore did not restore the original library.'
}
if (!(Test-Path -LiteralPath (Join-Path (Split-Path -Parent $resumeJournal) 'RESTORED.txt'))) {
    throw 'Resumed restore did not record completion.'
}
Write-Host 'PASS: interrupted restoration resumes safely and preserves edits to restored files'
# Also recover a completed file move whose progress checkpoint was not written.
$checkpointData = Join-Path $TestRoot 'checkpoint-restore-data'
$checkpointPackage = Join-Path $checkpointData 'Installed Packages\PlainTasks.sublime-package'
$null = New-Item -ItemType Directory -Path (Split-Path -Parent $checkpointPackage) -Force
Write-PTUtf8 $checkpointPackage 'package-before-missing-checkpoint'
& (Join-Path $scripts 'Install-PlainTasks.ps1') -DataPath $checkpointData -BundleRoot $bundle -BackupExisting
$checkpointJournal = @(Get-ChildItem -LiteralPath (Join-Path $checkpointData 'PlainTasks Backups') -Recurse -Filter 'restore.json' -File)[0].FullName
$checkpointPlan = Get-Content -LiteralPath $checkpointJournal -Raw -Encoding UTF8 | ConvertFrom-Json
$global:PlainTasksRestoreInjectedBackup = $checkpointPlan.operations[0].backup
function Move-Item {
    param([string]$LiteralPath, [string]$Destination)
    Microsoft.PowerShell.Management\Move-Item -LiteralPath $LiteralPath -Destination $Destination
    if ($LiteralPath -eq $global:PlainTasksRestoreInjectedBackup) { throw 'Injected failure after completed backup move' }
}
$blocked = $false
try { & (Join-Path $scripts 'Restore-PlainTasks.ps1') -JournalPath $checkpointJournal } catch { $blocked = $true }
finally { Remove-Item -LiteralPath 'Function:\Move-Item'; Remove-Variable -Name PlainTasksRestoreInjectedBackup -Scope Global }
if (!$blocked -or (Get-Content -LiteralPath $checkpointPackage -Raw) -ne 'package-before-missing-checkpoint') {
    throw 'The backup move completion failure did not leave the original package in place.'
}
$oldCheckpoint = Get-Content -LiteralPath (Join-Path (Split-Path -Parent $checkpointJournal) 'restore-progress.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($oldCheckpoint.operations[0].completed) { throw 'The test did not exercise an unwritten completion checkpoint.' }
& (Join-Path $scripts 'Restore-PlainTasks.ps1') -JournalPath $checkpointJournal
if ((Get-Content -LiteralPath $checkpointPackage -Raw) -ne 'package-before-missing-checkpoint') {
    throw 'Resuming an unwritten checkpoint changed the restored package.'
}
Write-Host 'PASS: completed moves are recovered when their checkpoint was not written'
Write-PTUtf8 (Join-Path $bundle 'lib\python314\rogue.py') 'unlisted-code'
$blocked = $false
try { $null = Get-PTBundle $bundle } catch { $blocked = $true }
if (!$blocked) { throw 'Integrity check accepted unlisted dependency code.' }
Write-Host 'PASS: unlisted dependency code is rejected'
Write-Host "PASS: delivery regression checks completed in $TestRoot"
