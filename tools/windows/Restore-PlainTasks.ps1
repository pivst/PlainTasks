<# Restore one installation journal. Interrupted restorations can be resumed safely. #>
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$JournalPath)
. (Join-Path $PSScriptRoot 'Common.ps1')
$JournalPath = [IO.Path]::GetFullPath($JournalPath)
Assert-PTNoReparsePoint $JournalPath
$backupRoot = Split-Path -Parent $JournalPath
if (Test-Path -LiteralPath (Join-Path $backupRoot 'ROLLED_BACK.txt')) { throw 'This installation was already automatically rolled back.' }
if (Test-Path -LiteralPath (Join-Path $backupRoot 'RESTORED.txt')) { throw 'This journal was already restored.' }
$journal = Get-Content -LiteralPath $JournalPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($journal.format -ne 1) { throw 'Unexpected journal format.' }
$dataRoot = [IO.Path]::GetFullPath($journal.data_path).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
$progressPath = Join-Path $backupRoot 'restore-progress.json'
Assert-PTNoReparsePoint $progressPath
$journalHash = (Get-FileHash -LiteralPath $JournalPath -Algorithm SHA256).Hash

function Save-PTRestoreProgress {
    # Replace the progress file atomically so a failed write leaves the last
    # complete checkpoint available. File.Replace is supported by .NET 4/PS5.1.
    $temporary = $progressPath + '.tmp'
    Assert-PTNoReparsePoint $temporary
    Write-PTUtf8 $temporary ($progress | ConvertTo-Json -Depth 8)
    if (Test-Path -LiteralPath $progressPath) {
        [IO.File]::Replace($temporary, $progressPath, [NullString]::Value)
    } else {
        [IO.File]::Move($temporary, $progressPath)
    }
}

foreach ($operation in $journal.operations) {
    $target = [IO.Path]::GetFullPath($operation.target)
    if (!$target.StartsWith($dataRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Journal target is outside its data directory.' }
    if (!(($target -eq (Join-Path $journal.data_path 'Installed Packages\PlainTasks.sublime-package')) -or
          ($target -eq (Join-Path $journal.data_path 'Packages\PlainTasks')) -or
          ($target.StartsWith((Join-Path $journal.data_path 'Lib\python314\'), [StringComparison]::OrdinalIgnoreCase)))) {
        throw "Unsupported restore target: $target"
    }
    Assert-PTNoReparsePoint $target
    if ($operation.backup) {
        $backup = [IO.Path]::GetFullPath($operation.backup)
        if (!$backup.StartsWith($backupRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Invalid backup path: $backup"
        }
        Assert-PTNoReparsePoint $backup
    }
}

if (Test-Path -LiteralPath $progressPath) {
    $progress = Get-Content -LiteralPath $progressPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($progress.format -ne 1 -or $progress.journal_sha256 -ne $journalHash -or
        @($progress.operations).Count -ne @($journal.operations).Count) {
        throw 'Restore checkpoint does not match its installation journal.'
    }
} else {
    $states = @()
    for ($index = 0; $index -lt @($journal.operations).Count; $index++) {
        $operation = $journal.operations[$index]
        $snapshot = Join-Path $backupRoot ('installed-' + $index)
        if (Test-Path -LiteralPath $snapshot) { throw "Unexpected restore snapshot: $snapshot" }
        if ((Get-PTFingerprint $operation.target) -ne $operation.installed_fingerprint) {
            throw "Changed since installation; refusing to overwrite: $($operation.target)"
        }
        $previous = if ($operation.backup) { Get-PTFingerprint $operation.backup } else { $null }
        if ($operation.backup -and !$previous) { throw "Missing backup: $($operation.backup)" }
        $states += [pscustomobject]@{ previous_fingerprint = $previous; completed = $false }
    }
    $progress = [pscustomobject]@{ format = 1; journal_sha256 = $journalHash; operations = $states }
}

# Validate every operation before mutating anything, including ones restored by
# an earlier interrupted invocation. Matching fingerprints also recover a move
# that succeeded just before its checkpoint could be saved.
for ($index = 0; $index -lt @($journal.operations).Count; $index++) {
    $operation = $journal.operations[$index]
    $state = $progress.operations[$index]
    $snapshot = Join-Path $backupRoot ('installed-' + $index)
    $current = Get-PTFingerprint $operation.target
    $saved = Get-PTFingerprint $snapshot
    $previous = if ($operation.backup) { Get-PTFingerprint $operation.backup } else { $null }
    if ($saved -and $saved -ne $operation.installed_fingerprint) { throw "Changed restore snapshot: $snapshot" }
    $restored = ($current -eq $state.previous_fingerprint -and !$previous)
    if ($state.completed) {
        if (!$restored) { throw "Changed after partial restoration; refusing to overwrite: $($operation.target)" }
    } elseif ($restored) {
        $state.completed = $true
    } else {
        if ($previous -ne $state.previous_fingerprint) { throw "Missing or changed backup: $($operation.backup)" }
        $untouched = ($current -eq $operation.installed_fingerprint -and !$saved)
        $moved = (!$current -and $saved -eq $operation.installed_fingerprint)
        if (!$untouched -and !$moved) { throw "Changed during partial restoration; refusing to overwrite: $($operation.target)" }
    }
}
Save-PTRestoreProgress
try {
    for ($index = 0; $index -lt @($journal.operations).Count; $index++) {
        $operation = $journal.operations[$index]
        $state = $progress.operations[$index]
        if ($state.completed) { continue }
        $snapshot = Join-Path $backupRoot ('installed-' + $index)
        # Rename entire items within the same data directory. Never recursively
        # delete a live library: a locked file must not leave it partly removed.
        if (Test-Path -LiteralPath $operation.target) {
            Move-Item -LiteralPath $operation.target -Destination $snapshot
        }
        if ($operation.backup) { Move-Item -LiteralPath $operation.backup -Destination $operation.target }
        $state.completed = $true
        Save-PTRestoreProgress
    }
    Write-PTUtf8 (Join-Path $backupRoot 'RESTORED.txt') 'Restored. This journal may not be applied again. The replaced installation is retained in installed-* snapshots.'
} catch {
    Write-Host "Restoration was interrupted. Resolve the reported file access problem, then rerun with the same journal: $JournalPath"
    throw
}
Write-Host "Restored the previous PlainTasks package and libraries in: $($journal.data_path)"
