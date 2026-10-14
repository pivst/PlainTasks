#!/usr/bin/env python3
"""Build deterministic PlainTasks packages and a Windows 4215 delivery bundle."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "PlainTasks.sublime-package"
BUNDLE_NAME = "PlainTasks-windows-4215.zip"
# Explicit runtime allowlist. New source files must be reviewed and added here.
PACKAGE_FILES = (
    ".python-version", "APlainTasksCommon.py", "PlainTasks.py", "PlainTasksDates.py",
    "PlainTasksToHTML.py", "plist_parser.py", "LICENSE", "Readme.md",
    "Context.sublime-menu", "Main.sublime-menu", "Default.sublime-commands",
    "Default.sublime-keymap", "Default (Linux).sublime-keymap",
    "Default (OSX).sublime-keymap", "Default (Windows).sublime-keymap",
    "PlainTasks (Linux).sublime-settings", "PlainTasks (OSX).sublime-settings",
    "PlainTasks (Windows).sublime-settings", "PlainTasks.sublime-completions",
    "PlainTasks.sublime-syntax", "PlainTasks.tmLanguage", "separator.sublime-snippet",
    "Indentation.tmPreferences", "Symbol List.tmPreferences", "dependencies.json",
    "messages.json", "messages/Tutorial.todo", "messages/install.txt",
    "templates/template.html", "templates/export.html", "icons/TODO.ico", "icons/TODO.icns",
    "icons/png/TODO_16x16x32.png", "icons/png/TODO_24x24x32.png",
    "icons/png/TODO_32x32x32.png", "icons/png/TODO_48x48x32.png",
    "icons/png/TODO_128x128x32.png", "icons/png/TODO_256x256x32.png",
    "tasks.hidden-tmTheme", "tasks-dark.hidden-tmTheme", "tasks-gray.hidden-tmTheme",
    "tasks-monokai.hidden-tmTheme", "tasks-eighties-dark.hidden-tmTheme",
    "tasks-eighties-colored.hidden-tmTheme", "tasks-solarized-dark.hidden-tmTheme",
    "tasks-solarized-light.hidden-tmTheme",
)
WINDOWS_FILES = (
    "Common.ps1", "Install-PlainTasks.ps1", "Restore-PlainTasks.ps1", "Test-PlainTasks4215.ps1",
)
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


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
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def source_dirty() -> bool:
    inputs = list(PACKAGE_FILES) + ["tools", "docs", "tests/editor_smoke.py"]
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal", "--", *inputs],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return bool(result.stdout.strip()) or result.returncode != 0


def collect_libraries(directory: Path) -> dict[str, bytes]:
    """Only include reviewed dateutil/six runtime sources and their license files."""
    files: dict[str, bytes] = {}
    if not directory.is_dir():
        raise ValueError(f"Missing dependency directory: {directory}")
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(directory)
        parts = relative.parts
        allowed = (
            (parts[0] == "dateutil" and "__pycache__" not in parts
             and path.suffix not in (".pyc", ".pyo") and path.name != ".DS_Store")
            or relative.as_posix() == "six.py"
            or (parts[0].endswith(".dist-info")
                and parts[0].startswith(("python_dateutil-", "six-"))
                and "__pycache__" not in parts)
            or (len(parts) == 1 and path.name.upper().startswith(("LICENSE", "COPYING")))
        )
        if allowed:
            files[f"lib/python314/{relative.as_posix()}"] = read_file(path)
    for name in ("lib/python314/dateutil/__init__.py", "lib/python314/six.py"):
        if name not in files:
            raise ValueError(f"Dependency bundle is incomplete: {name}")
    if not any(Path(name).name.upper().startswith(("LICENSE", "COPYING")) for name in files):
        raise ValueError("Dependency bundle must include the dateutil and six license files")
    return files


def build(output: Path, libraries: Path | None) -> dict[str, str]:
    runtime = {name: read_file(ROOT / name) for name in PACKAGE_FILES}
    if runtime[".python-version"].strip() != b"3.14":
        raise ValueError("The release must explicitly select the Python 3.14 plugin host")
    package = reproducible_zip(runtime)
    package_manifest = json_bytes({
        "package": PACKAGE_NAME, "sha256": sha256(package), "files": records(runtime),
    })
    bundle = {
        PACKAGE_NAME: package,
        "PlainTasks.package-manifest.json": package_manifest,
        "README.zh-CN.md": read_file(ROOT / "tools/windows/README.zh-CN.md"),
        "WINDOWS_4215.md": read_file(ROOT / "docs/WINDOWS_4215.md"),
        "PR_REVIEW.md": read_file(ROOT / "docs/PR_REVIEW.md"),
        "smoke/editor_smoke.py": read_file(ROOT / "tests/editor_smoke.py"),
    }
    for name in WINDOWS_FILES:
        bundle[f"windows/{name}"] = read_file(ROOT / "tools/windows" / name)
    if libraries is not None:
        bundle.update(collect_libraries(libraries))
    bundle["manifest.json"] = json_bytes({
        "format": 1, "target": {"sublime_build": 4215, "platform": "windows", "arch": "x64"},
        "source_commit": source_commit(), "source_dirty": source_dirty(), "package_sha256": sha256(package),
        "dependency_libraries_included": libraries is not None, "files": records(bundle),
    })
    bundle["SHA256SUMS"] = "".join(
        f"{sha256(contents)}  {name}\n" for name, contents in sorted(bundle.items())
    ).encode("utf-8")
    delivery = reproducible_zip(bundle)
    output.mkdir(parents=True, exist_ok=True)
    for name, contents in {
        PACKAGE_NAME: package, "PlainTasks.package-manifest.json": package_manifest,
        f"{PACKAGE_NAME}.sha256": f"{sha256(package)}  {PACKAGE_NAME}\n".encode(),
        BUNDLE_NAME: delivery,
        f"{BUNDLE_NAME}.sha256": f"{sha256(delivery)}  {BUNDLE_NAME}\n".encode(),
    }.items():
        target = output / name
        if target.is_symlink():
            raise ValueError(f"Refusing to overwrite a symlink: {target}")
        target.write_bytes(contents)
    return {"package": str(output / PACKAGE_NAME), "bundle": str(output / BUNDLE_NAME),
            "package_sha256": sha256(package), "bundle_sha256": sha256(delivery)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--libraries", type=Path, help="Directory containing dateutil/, six.py and licenses")
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.output.resolve(), arguments.libraries), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
