<# Restore one installation journal. Changed files cause a stop instead of data loss. #>
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
foreach ($operation in $journal.operations) {
    $target = [IO.Path]::GetFullPath($operation.target)
    if (!$target.StartsWith($dataRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Journal target is outside its data directory.' }
    if (!(($target -eq (Join-Path $journal.data_path 'Installed Packages\PlainTasks.sublime-package')) -or
          ($target -eq (Join-Path $journal.data_path 'Packages\PlainTasks')) -or
          ($target.StartsWith((Join-Path $journal.data_path 'Lib\python314\'), [StringComparison]::OrdinalIgnoreCase)))) {
        throw "Unsupported restore target: $target"
    }
    if ((Get-PTFingerprint $target) -ne $operation.installed_fingerprint) { throw "Changed since installation; refusing to overwrite: $target" }
    if ($operation.backup) {
        $backup = [IO.Path]::GetFullPath($operation.backup)
        if (!(($backup.StartsWith($backupRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase))) -or !(Test-Path -LiteralPath $backup)) {
            throw "Missing or invalid backup: $backup"
        }
        Assert-PTNoReparsePoint $backup
    }
}
foreach ($operation in $journal.operations) {
    if (Test-Path -LiteralPath $operation.target) { Remove-Item -LiteralPath $operation.target -Recurse -Force }
    if ($operation.backup) { Move-Item -LiteralPath $operation.backup -Destination $operation.target }
}
Write-PTUtf8 (Join-Path $backupRoot 'RESTORED.txt') 'Restored. This journal may not be applied again.'
Write-Host "Restored the previous PlainTasks package and libraries in: $($journal.data_path)"
