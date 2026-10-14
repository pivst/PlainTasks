<# Create a fresh portable instance, run real editor tests, save JSON/logs, and return 0 only on success. #>
[CmdletBinding(DefaultParameterSetName = 'Zip')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'Zip')][string]$PortableZip,
    [Parameter(Mandatory = $true, ParameterSetName = 'Path')][string]$PortablePath,
    [string]$WorkRoot,
    [string]$BundleRoot,
    [ValidateRange(15, 600)][int]$TimeoutSeconds = 120,
    [switch]$KeepOpen
)
if (!$BundleRoot) { $BundleRoot = Split-Path -Parent $PSScriptRoot }
if (!$WorkRoot) { $WorkRoot = Join-Path ([IO.Path]::GetTempPath()) ('PlainTasks-4215-' + [Guid]::NewGuid().ToString('N')) }
. (Join-Path $PSScriptRoot 'Common.ps1')
$editor = $null
try {
    $null = Get-PTBundle $BundleRoot
    $WorkRoot = [IO.Path]::GetFullPath($WorkRoot)
    Assert-PTNoReparsePoint $WorkRoot
    if (Test-Path -LiteralPath $WorkRoot) { throw "Choose a new WorkRoot; it must not exist: $WorkRoot" }
    $runtimeRoot = Join-Path $WorkRoot 'portable'
    $null = New-Item -ItemType Directory -Path $runtimeRoot -Force
    if ($PSCmdlet.ParameterSetName -eq 'Zip') {
        Expand-Archive -LiteralPath $PortableZip -DestinationPath $runtimeRoot
        $executables = @(Get-ChildItem -LiteralPath $runtimeRoot -Filter 'sublime_text.exe' -File -Recurse)
        if ($executables.Count -ne 1) { throw 'The portable ZIP must contain exactly one sublime_text.exe.' }
        $runtimeRoot = $executables[0].Directory.FullName
    } else {
        $PortablePath = [IO.Path]::GetFullPath($PortablePath)
        $null = Assert-PTExecutable (Join-Path $PortablePath 'sublime_text.exe')
        foreach ($item in Get-ChildItem -LiteralPath $PortablePath -Force) {
            if ($item.Name -eq 'Data') { continue }
            Assert-PTNoReparsePoint $item.FullName
            if ($item.PSIsContainer) {
                foreach ($child in Get-ChildItem -LiteralPath $item.FullName -Recurse -Force) { Assert-PTNoReparsePoint $child.FullName }
            }
            Copy-Item -LiteralPath $item.FullName -Destination $runtimeRoot -Recurse
        }
    }
    $executable = Join-Path $runtimeRoot 'sublime_text.exe'
    $version = Assert-PTExecutable $executable
    $data = Join-Path $runtimeRoot 'Data'
    if (Test-Path -LiteralPath $data) {
        $profileItems = @(Get-ChildItem -LiteralPath $data -Force)
        foreach ($item in $profileItems) { Assert-PTNoReparsePoint $item.FullName }
        $customItems = @($profileItems | Where-Object { $_.Name -ne 'KEEPME' -or $_.PSIsContainer -or $_.Length -ne 0 })
        if ($customItems.Count -gt 0) {
            throw 'The ZIP contains an existing Data profile. Use a fresh official portable ZIP or -PortablePath (its Data is excluded).'
        }
    }
    & (Join-Path $PSScriptRoot 'Install-PlainTasks.ps1') -PortablePath $runtimeRoot -BundleRoot $BundleRoot
    $user = Join-Path $data 'Packages\User'
    $null = New-Item -ItemType Directory -Path $user -Force
    Copy-Item -LiteralPath (Join-Path $BundleRoot 'smoke\editor_smoke.py') -Destination (Join-Path $user 'PlainTasksSmoke.py')
    $report = Join-Path $WorkRoot 'smoke-result.json'
    Write-PTUtf8 (Join-Path $user 'plain-tasks-smoke-request.json') (@{ output_path = $report } | ConvertTo-Json)
    Write-PTUtf8 (Join-Path $user 'Preferences.sublime-settings') (@{
        update_check = $false; hot_exit = $false; remember_open_files = $false
    } | ConvertTo-Json)
    $signature = Get-AuthenticodeSignature -LiteralPath $executable
    Write-PTUtf8 (Join-Path $WorkRoot 'environment.json') (@{
        windows_version = [Environment]::OSVersion.VersionString; powershell = $PSVersionTable.PSVersion.ToString()
        executable = $executable; file_version = $version; sha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash
        signature_status = $signature.Status.ToString(); signer = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
    } | ConvertTo-Json)
    $editor = Start-Process -FilePath $executable -ArgumentList @('--multiinstance', '--debug') -WorkingDirectory $runtimeRoot -PassThru -RedirectStandardOutput (Join-Path $WorkRoot 'debug.stdout.log') -RedirectStandardError (Join-Path $WorkRoot 'debug.stderr.log')
    Write-Host "Testing isolated build 4215; results: $WorkRoot"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $result = $null
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $report -PathType Leaf) {
            try { $result = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json; break } catch { }
        }
        if ($editor.HasExited) { throw 'The isolated editor exited before writing the test report.' }
        Start-Sleep -Milliseconds 500
    }
    if (!$result) { throw "Timed out after $TimeoutSeconds seconds; inspect debug logs in $WorkRoot." }
    $expectedPackages = [IO.Path]::GetFullPath((Join-Path $data 'Packages')).TrimEnd('\')
    $actualPackages = [IO.Path]::GetFullPath([string]$result.packages_path).TrimEnd('\')
    $actualPlugin = [IO.Path]::GetFullPath([string]$result.plugin_file)
    $expectedData = [IO.Path]::GetFullPath($data).TrimEnd('\') + '\'
    if ($actualPackages -ne $expectedPackages -or
        !$actualPlugin.StartsWith($expectedData, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The report came from a different Sublime profile; the isolated package was not tested.'
    }
    if ($result.build -ne '4215' -or $result.platform -ne 'windows' -or $result.arch -ne 'x64' -or
        $result.python -notmatch '^3\.14\.' -or $result.dateutil_available -ne $true -or
        $result.ok -ne $true -or $result.failed -ne 0 -or $result.passed -lt 1 -or
        $result.passed -ne $result.expected_checks) {
        throw "Editor tests failed or ran in the wrong runtime; inspect $report."
    }
    Write-Host "PASS: $($result.passed) checks; report: $report"
    Write-Host 'Complete the native keyboard, Save As, browser and popup checks in docs/development.md.'
    $exitCode = 0
} catch {
    Write-Error -Message $_ -ErrorAction Continue
    $exitCode = 1
} finally {
    if ($editor -and !$KeepOpen -and !$editor.HasExited) {
        $null = $editor.CloseMainWindow()
        if (!$editor.WaitForExit(5000)) { Write-Warning 'The isolated editor is still open. Close its window manually; no production process was stopped.' }
    }
}
exit $exitCode
