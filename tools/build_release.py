#!/usr/bin/env python3
"""Build deterministic PlainTasks packages and a Windows 4215 delivery bundle."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import zipfile
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
PACKAGE_NAME = "PlainTasks.sublime-package"
BUNDLE_NAME = f"PlainTasks-{VERSION}-windows.zip"
# Explicit runtime allowlist. New source files must be reviewed and added here.
PACKAGE_FILES = (
    ".python-version",
    "APlainTasksCommon.py",
    "PlainTasks.py",
    "PlainTasksDates.py",
    "PlainTasksToHTML.py",
    "LICENSE",
    "README.md",
    "VERSION",
    "docs/installation.md",
    "docs/usage.md",
    "docs/development.md",
    "Context.sublime-menu",
    "Main.sublime-menu",
    "Default.sublime-commands",
    "Default.sublime-keymap",
    "Default (Linux).sublime-keymap",
    "Default (OSX).sublime-keymap",
    "Default (Windows).sublime-keymap",
    "PlainTasks.sublime-settings",
    "PlainTasks (Windows).sublime-settings",
    "PlainTasks.sublime-completions",
    "PlainTasks.sublime-syntax",
    "separator.sublime-snippet",
    "Indentation.tmPreferences",
    "Symbol List.tmPreferences",
    "dependencies.json",
    "messages.json",
    "messages/Tutorial.todo",
    "messages/install.txt",
    "templates/template.html",
    "tasks.hidden-tmTheme",
    "tasks-dark.hidden-tmTheme",
    "tasks-gray.hidden-tmTheme",
    "tasks-monokai.hidden-tmTheme",
    "tasks-eighties-dark.hidden-tmTheme",
    "tasks-eighties-colored.hidden-tmTheme",
    "tasks-solarized-dark.hidden-tmTheme",
    "tasks-solarized-light.hidden-tmTheme",
)
WINDOWS_FILES = (
    "Common.ps1",
    "Install-PlainTasks.ps1",
    "Restore-PlainTasks.ps1",
    "Test-PlainTasks4215.ps1",
)
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
LIBRARY_DISTRIBUTIONS = {
    "python_dateutil-2.9.0.post0.dist-info": ("python-dateutil", "2.9.0.post0"),
    "six-1.17.0.dist-info": ("six", "1.17.0"),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def read_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected a regular file, not a missing file or symlink: {path}")
    return path.read_bytes()


def reproducible_zip(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, contents in sorted(files.items()):
            info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, contents, compresslevel=9)
    return output.getvalue()


def records(files: dict[str, bytes]) -> list[dict[str, object]]:
    return [
        {"path": name, "size": len(contents), "sha256": sha256(contents)}
        for name, contents in sorted(files.items())
    ]


def source_commit() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def source_dirty() -> bool:
    inputs = list(PACKAGE_FILES) + ["tools", "docs", "tests/editor_smoke.py"]
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal", "--", *inputs],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip()) or result.returncode != 0


def collect_libraries(directory: Path) -> dict[str, bytes]:
    """Only include reviewed dateutil/six runtime sources and their license files."""
    files: dict[str, bytes] = {}
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"Missing dependency directory: {directory}")
    for distribution, (name, version) in LIBRARY_DISTRIBUTIONS.items():
        metadata = BytesParser().parsebytes(read_file(directory / distribution / "METADATA"))
        if metadata.get("Name") != name or metadata.get("Version") != version:
            raise ValueError(f"Expected {name} {version} in {distribution}")
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(directory)
        parts = relative.parts
        allowed = (
            (
                parts[0] == "dateutil"
                and "__pycache__" not in parts
                and path.suffix not in (".pyc", ".pyo")
                and path.name != ".DS_Store"
            )
            or relative.as_posix() == "six.py"
            or (parts[0] in LIBRARY_DISTRIBUTIONS and "__pycache__" not in parts)
            or (len(parts) == 1 and path.name.upper().startswith(("LICENSE", "COPYING")))
        )
        if allowed:
            files[f"lib/python314/{relative.as_posix()}"] = read_file(path)
    for name in ("lib/python314/dateutil/__init__.py", "lib/python314/six.py"):
        if name not in files:
            raise ValueError(f"Dependency bundle is incomplete: {name}")
    for distribution in LIBRARY_DISTRIBUTIONS:
        prefix = f"lib/python314/{distribution}/"
        if not any(
            name.startswith(prefix) and Path(name).name.upper().startswith(("LICENSE", "COPYING"))
            for name in files
        ):
            raise ValueError(f"Missing license for {distribution}")
    return files


def build(output: Path, libraries: Path | None) -> dict[str, str]:
    if output.is_symlink():
        raise ValueError(f"Refusing to write through a symlink: {output}")
    runtime = {name: read_file(ROOT / name) for name in PACKAGE_FILES}
    if runtime[".python-version"].strip() != b"3.14":
        raise ValueError("The release must explicitly select the Python 3.14 plugin host")
    runtime["package-metadata.json"] = json_bytes(
        {
            "version": VERSION,
            "sublime_text": ">=4215",
            "platforms": ["*"],
            "url": "https://github.com/pivst/PlainTasks",
            "description": "Task lists for Sublime Text 4215 and Python 3.14",
        }
    )
    package = reproducible_zip(runtime)
    package_manifest = json_bytes(
        {
            "package": PACKAGE_NAME,
            "sha256": sha256(package),
            "files": records(runtime),
        }
    )
    bundle = {
        PACKAGE_NAME: package,
        "PlainTasks.package-manifest.json": package_manifest,
        "README.md": read_file(ROOT / "README.md"),
        "docs/installation.md": read_file(ROOT / "docs/installation.md"),
        "docs/usage.md": read_file(ROOT / "docs/usage.md"),
        "docs/development.md": read_file(ROOT / "docs/development.md"),
        "smoke/editor_smoke.py": read_file(ROOT / "tests/editor_smoke.py"),
    }
    for name in WINDOWS_FILES:
        bundle[f"windows/{name}"] = read_file(ROOT / "tools/windows" / name)
    if libraries is not None:
        bundle.update(collect_libraries(libraries))
    bundle["manifest.json"] = json_bytes(
        {
            "format": 1,
            "version": VERSION,
            "target": {"sublime_build": 4215, "platform": "windows", "arch": "x64"},
            "source_commit": source_commit(),
            "source_dirty": source_dirty(),
            "package_sha256": sha256(package),
            "dependency_libraries_included": libraries is not None,
            "files": records(bundle),
        }
    )
    bundle["SHA256SUMS"] = "".join(
        f"{sha256(contents)}  {name}\n" for name, contents in sorted(bundle.items())
    ).encode("utf-8")
    delivery = reproducible_zip(bundle)
    output.mkdir(parents=True, exist_ok=True)
    for name, contents in {
        PACKAGE_NAME: package,
        "PlainTasks.package-manifest.json": package_manifest,
        f"{PACKAGE_NAME}.sha256": f"{sha256(package)}  {PACKAGE_NAME}\n".encode(),
        BUNDLE_NAME: delivery,
        f"{BUNDLE_NAME}.sha256": f"{sha256(delivery)}  {BUNDLE_NAME}\n".encode(),
    }.items():
        target = output / name
        if target.is_symlink():
            raise ValueError(f"Refusing to overwrite a symlink: {target}")
        target.write_bytes(contents)
    return {
        "package": str(output / PACKAGE_NAME),
        "bundle": str(output / BUNDLE_NAME),
        "package_sha256": sha256(package),
        "bundle_sha256": sha256(delivery),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument(
        "--libraries", type=Path, help="Directory containing dateutil/, six.py and licenses"
    )
    arguments = parser.parse_args()
    print(
        json.dumps(
            build(arguments.output.absolute(), arguments.libraries), ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
