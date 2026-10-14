# Shared helpers for Windows PowerShell 5.1. No administrator rights are required.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-PTUtf8([string]$Path, [string]$Contents) {
    [IO.File]::WriteAllText($Path, $Contents, (New-Object Text.UTF8Encoding($false)))
}

function Assert-PTNoReparsePoint([string]$Path) {
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Symlink/junction paths are unsupported: $current"
            }
        }
        $parent = Split-Path -Parent $current
        if ($parent -eq $current) { break }
        $current = $parent
    }
}

function Get-PTFingerprint([string]$Path) {
    if (!(Test-Path -LiteralPath $Path)) { return $null }
    Assert-PTNoReparsePoint $Path
    $item = Get-Item -LiteralPath $Path -Force
    if (!$item.PSIsContainer) { return 'file:' + (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
    $prefix = $item.FullName.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    $lines = @()
    foreach ($child in @(Get-ChildItem -LiteralPath $Path -Recurse -Force)) { Assert-PTNoReparsePoint $child.FullName }
    foreach ($file in @(Get-ChildItem -LiteralPath $Path -File -Recurse -Force |
        Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and $_.Extension -notin @('.pyc', '.pyo') } |
        Sort-Object FullName)) {
        Assert-PTNoReparsePoint $file.FullName
        $relative = $file.FullName.Substring($prefix.Length).Replace('\', '/')
        $lines += $relative + ':' + (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return 'directory:' + ([BitConverter]::ToString($hash.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $hash.Dispose() }
}

function Get-PTBundle([string]$Root) {
    $Root = [IO.Path]::GetFullPath($Root)
    Assert-PTNoReparsePoint $Root
    Assert-PTNoReparsePoint (Join-Path $Root 'manifest.json')
    $manifest = Get-Content -LiteralPath (Join-Path $Root 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.format -ne 1 -or $manifest.target.sublime_build -ne 4215) { throw 'Unexpected bundle manifest.' }
    $listed = @{}
    foreach ($entry in $manifest.files) {
        if ($entry.path -match '(^/|^[A-Za-z]:|(^|/)\.\.(/|$)|\\)') { throw "Unsafe manifest path: $($entry.path)" }
        $path = Join-Path $Root $entry.path
        $listed[$entry.path] = $true
        Assert-PTNoReparsePoint $path
        if (!(Test-Path -LiteralPath $path -PathType Leaf)) { throw "Bundle file is missing: $($entry.path)" }
        if ((Get-Item -LiteralPath $path).Length -ne $entry.size -or
            (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $entry.sha256) {
            throw "Bundle integrity check failed: $($entry.path)"
        }
    }
    $libraryRoot = Join-Path $Root 'lib\python314'
    if (Test-Path -LiteralPath $libraryRoot) {
        foreach ($item in @(Get-ChildItem -LiteralPath $libraryRoot -Recurse -Force)) {
            Assert-PTNoReparsePoint $item.FullName
            if (!$item.PSIsContainer) {
                $relative = $item.FullName.Substring($Root.TrimEnd([IO.Path]::DirectorySeparatorChar).Length + 1).Replace('\', '/')
                if (!$listed.ContainsKey($relative)) { throw "Unlisted library file: $relative" }
            }
        }
    }
    $package = Join-Path $Root 'PlainTasks.sublime-package'
    if ((Get-FileHash -LiteralPath $package -Algorithm SHA256).Hash -ne $manifest.package_sha256) {
        throw 'PlainTasks package hash does not match the manifest.'
    }
    return $manifest
}

function Assert-PTExecutable([string]$Executable) {
    if (!(Test-Path -LiteralPath $Executable -PathType Leaf)) { throw "Missing executable: $Executable" }
    Assert-PTNoReparsePoint $Executable
    $info = [Diagnostics.FileVersionInfo]::GetVersionInfo($Executable)
    if (($info.FileVersion + ' ' + $info.ProductVersion) -notmatch '\b4215\b') {
        throw "Expected Sublime Text build 4215; got file=$($info.FileVersion), product=$($info.ProductVersion)."
    }
    $stream = [IO.File]::OpenRead($Executable)
    $reader = New-Object IO.BinaryReader($stream)
    try {
        if ($reader.ReadUInt16() -ne 0x5A4D) { throw 'Not a Windows PE executable.' }
        $stream.Position = 0x3c
        $offset = $reader.ReadUInt32()
        $stream.Position = $offset
        if ($reader.ReadUInt32() -ne 0x4550 -or $reader.ReadUInt16() -ne 0x8664) {
            throw 'Expected the official Windows x64 executable.'
        }
    } finally { $reader.Dispose(); $stream.Dispose() }
    return $info.FileVersion
}
