#!/usr/bin/env python3
r"""Run real Sublime Text 4215 checks using its official macOS Safe Mode.

Example:
    python3 tools/test_macos4215.py --app '/path/Sublime Text.app' \
        --package dist/PlainTasks.sublime-package \
        --libraries /path/dateutil-and-six --output /tmp/PlainTasks-reports

First extract the official macOS ZIP with Finder / Archive Utility. The source
app must have a valid signature and remain unmodified. Run this tool from a host
terminal with permission to verify signatures and write the Safe Mode profile.
Close all Sublime Text instances before running it.

Each invocation creates a new report subdirectory. Existing nonempty Safe Mode
data is backed up there before Sublime clears that profile on startup. --loose
tests an unpacked package. Accept the editor's Safe Mode notification. If no
report appears, paste the printed fallback line into View > Show Console. The
Safe Mode test profile is retained for diagnosis; only the editor process
started by this tool is stopped. No downloads, app modifications, xattr changes,
production profile edits, or API doubles occur.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SAFE_MODE_RELATIVE_PATH = "Library/Application Support/Sublime Text (Safe Mode)"
BOOTSTRAP_COMMAND = (
    "import sublime_plugin; "
    "[sublime_plugin.reload_plugin('PlainTasks.' + name) for name in "
    "('APlainTasksCommon', 'PlainTasksDates', 'PlainTasks', 'PlainTasksToHTML')]; "
    "sublime_plugin.reload_plugin('User.PlainTasksSmoke')"
)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def app_metadata(app: Path) -> dict:
    if sys.platform != "darwin":
        raise ValueError(
            "This runner requires macOS; use tools/windows/Test-PlainTasks4215.ps1 on Windows"
        )
    if not app.is_dir() or app.suffix != ".app":
        raise ValueError(f"Expected a Sublime Text .app directory: {app}")
    with (app / "Contents/Info.plist").open("rb") as stream:
        metadata = plistlib.load(stream)
    versions = [metadata.get("CFBundleVersion"), metadata.get("CFBundleShortVersionString")]
    if "4215" not in map(str, versions):
        raise ValueError(f"Expected exact Sublime Text build 4215 in Info.plist; found {versions}")
    if metadata.get("CFBundleExecutable") != "sublime_text":
        raise ValueError("The app does not declare the Sublime Text executable")
    if not (app / "Contents/MacOS/sublime_text").is_file():
        raise ValueError("The app is missing Contents/MacOS/sublime_text")
    if (app / "Contents/MacOS/Data").exists():
        raise ValueError("Use an unmodified Finder-extracted app without Contents/MacOS/Data")
    return {
        name: metadata.get(name)
        for name in (
            "CFBundleIdentifier",
            "CFBundleVersion",
            "CFBundleShortVersionString",
            "CFBundleExecutable",
        )
    }


def verify_signature(app: Path) -> dict:
    command = ["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)]
    verification = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    if verification.returncode != 0:
        details = verification.stderr.strip() or verification.stdout.strip()
        raise ValueError(
            "The source app signature could not be verified. Use Finder / Archive Utility "
            "to extract the official ZIP and run with full host permissions. "
            "Do not change xattrs or re-sign the app. codesign: " + details
        )
    return {
        "command": command,
        "ok": True,
        "stdout": verification.stdout.strip(),
        "stderr": verification.stderr.strip(),
    }


def assert_no_running_editor() -> None:
    snapshot = subprocess.run(
        ["/bin/ps", "-axo", "pid=,comm="], capture_output=True, text=True, timeout=10, check=False
    )
    if snapshot.returncode != 0:
        raise RuntimeError(
            "Unable to check for running Sublime Text instances; run with full host permissions"
        )
    running = []
    for line in snapshot.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and Path(fields[1]).name == "sublime_text":
            running.append(fields[0])
    if running:
        raise RuntimeError(
            "Close all Sublime Text instances before Safe Mode testing; running PIDs: "
            + ", ".join(running)
        )


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def install_package(package: Path, data: Path, loose: bool) -> None:
    with zipfile.ZipFile(package) as archive:
        names = set()
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if (
                not entry.filename
                or "\\" in entry.filename
                or path.is_absolute()
                or ".." in path.parts
                or entry.filename in names
                or stat.S_ISLNK(entry.external_attr >> 16)
            ):
                raise ValueError(f"Invalid package archive entry: {entry.filename!r}")
            names.add(entry.filename)
        for name in (
            "PlainTasks.py",
            "PlainTasksDates.py",
            "PlainTasksToHTML.py",
            ".python-version",
        ):
            if name not in names:
                raise ValueError(f"The package must contain {name} at its root")
        if archive.read(".python-version").strip() != b"3.14":
            raise ValueError("The package must explicitly select .python-version = 3.14")
        if loose:
            destination = data / "Packages/PlainTasks"
            if destination.exists():
                raise ValueError(
                    "Safe Mode package directory already exists; refusing to overwrite it"
                )
            with tempfile.TemporaryDirectory(prefix="plaintasks-loose-") as staging:
                staged = Path(staging) / "PlainTasks"
                staged.mkdir()
                for entry in archive.infolist():
                    target = staged.joinpath(*PurePosixPath(entry.filename).parts)
                    if entry.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(entry) as source, target.open("wb") as output:
                            shutil.copyfileobj(source, output)
                # Publish complete sources together so the watcher never loads
                # PlainTasks.py while its sibling modules are still missing.
                shutil.move(str(staged), destination)
        else:
            destination = data / "Installed Packages/PlainTasks.sublime-package"
            if destination.exists():
                raise ValueError("Safe Mode package already exists; refusing to overwrite it")
            staged = destination.with_suffix(".staging")
            shutil.copyfile(package, staged)
            staged.replace(destination)


def install_libraries(directory: Path, data: Path) -> None:
    # Use the delivery builder's reviewed dependency allowlist, including licenses
    # and dist-info metadata, so this test and the Windows bundle use equal files.
    spec = importlib.util.spec_from_file_location(
        "plaintasks_release_builder", ROOT / "tools/build_release.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load tools/build_release.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    for name, content in builder.collect_libraries(directory).items():
        relative = PurePosixPath(name).relative_to("lib")
        destination = data / "Lib" / Path(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)


def validate_report(report: dict, data: Path) -> None:
    expected_packages = (data / "Packages").resolve()
    actual_packages = Path(str(report.get("packages_path", ""))).resolve()
    if actual_packages != expected_packages:
        raise ValueError(
            f"The editor used another profile: {actual_packages}; expected {expected_packages}"
        )
    try:
        Path(str(report.get("plugin_file", ""))).resolve().relative_to(data.resolve())
    except ValueError:
        raise ValueError("The tested plugin was not loaded from the Safe Mode directory") from None
    if (
        report.get("build") != "4215"
        or report.get("platform") != "osx"
        or not re.match(r"^3\.14\.", str(report.get("python", "")))
    ):
        raise ValueError(
            "The smoke suite ran outside macOS Sublime Text 4215 / embedded Python 3.14"
        )
    if (
        report.get("ok") is not True
        or report.get("failed") != 0
        or not isinstance(report.get("passed"), int)
        or report["passed"] < 1
        or report["passed"] != report.get("expected_checks")
    ):
        raise ValueError(
            f"Smoke suite failed: {report.get('passed')} passed, {report.get('failed')} failed"
        )


def wait_for_safe_mode(
    process: subprocess.Popen, data: Path, logs: tuple[Path, Path], deadline: float
) -> None:
    expected = "packages path: " + str(data / "Packages")
    while time.monotonic() < deadline:
        output = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in logs)
        if expected in output and (data / "Packages/User").is_dir():
            return
        if process.poll() is not None:
            raise RuntimeError(
                f"The editor exited before creating its Safe Mode profile (exit {process.returncode})"
            )
        time.sleep(0.25)
    raise TimeoutError("The editor did not confirm its Safe Mode profile; inspect the debug logs")


def wait_for_report(process: subprocess.Popen, path: Path, deadline: float) -> dict:
    while time.monotonic() < deadline:
        if path.is_file():
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except OSError, ValueError:
                # The plugin may still be writing the report.
                pass
            else:
                if not isinstance(report, dict):
                    raise ValueError("The editor smoke report must be a JSON object")
                return report
        if process.poll() is not None:
            raise RuntimeError(
                f"The isolated editor exited before writing a report (exit {process.returncode})"
            )
        time.sleep(0.25)
    raise TimeoutError("No complete smoke report before the deadline; inspect the debug logs")


def stop_editor(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    # Never use killall, process-name matching, or a process group: this PID is
    # exclusively the Safe Mode editor created by this runner.
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run(arguments: argparse.Namespace) -> dict:
    app = arguments.app.resolve()
    package = arguments.package.resolve()
    libraries = arguments.libraries.resolve()
    metadata = app_metadata(app)
    signature = verify_signature(app)
    assert_no_running_editor()
    if not package.is_file():
        raise ValueError(f"Missing package: {package}")
    if not libraries.is_dir():
        raise ValueError(f"Missing library directory: {libraries}")
    if not (ROOT / "tests/editor_smoke.py").is_file():
        raise ValueError("Missing tests/editor_smoke.py")

    output = arguments.output.resolve()
    data = Path.home() / SAFE_MODE_RELATIVE_PATH
    if data.is_symlink():
        raise ValueError("The Safe Mode profile is a symlink; refusing to let Sublime clear it")
    if any(is_within(path, data) for path in (output, package, libraries)):
        raise ValueError(
            "Inputs and reports must be outside the Safe Mode profile that Sublime clears"
        )
    if is_within(output, app):
        raise ValueError("Reports must be outside the signed source app")
    output.mkdir(parents=True, exist_ok=True)
    run_name = (
        "macos4215-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    )
    reports = output / run_name
    reports.mkdir()
    report_path = reports / "smoke-result.json"
    process = None
    result = {
        "ok": False,
        "report_directory": str(reports),
        "report": str(report_path),
        "mode": "loose" if arguments.loose else "packed",
        "safe_mode_profile": str(data),
        "safe_mode_backup": None,
        "console_bootstrap_fallback_available": True,
    }
    try:
        if data.exists() and any(data.iterdir()):
            backup = reports / "safe-mode-data-before"
            shutil.copytree(data, backup, symlinks=True)
            result["safe_mode_backup"] = str(backup)
            print(
                f"Existing Safe Mode data backed up to {backup}; Sublime will clear only its Safe Mode profile",
                flush=True,
            )
        write_json(
            reports / "environment.json",
            {
                "app_metadata": metadata,
                "signature_verification": signature,
                "source_app": str(app),
                "expected_packages_path": str((data / "Packages").resolve()),
                "package": str(package),
                "package_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
                "libraries": str(libraries),
                "mode": result["mode"],
                "smoke_sha256": hashlib.sha256(
                    (ROOT / "tests/editor_smoke.py").read_bytes()
                ).hexdigest(),
                "safe_mode_backup": result["safe_mode_backup"],
                "safe_mode_startup_erases_previous_profile": True,
                "console_bootstrap_fallback_available": True,
                "console_bootstrap_command": BOOTSTRAP_COMMAND,
                "safe_mode_notification_requires_user_ok": True,
            },
        )
        executable = app / "Contents/MacOS/sublime_text"
        print(
            f"Testing Sublime Text 4215 Safe Mode ({result['mode']}); reports: {reports}",
            flush=True,
        )
        logs = reports / "debug.stdout.log", reports / "debug.stderr.log"
        with logs[0].open("wb") as stdout, logs[1].open("wb") as stderr:
            startup_deadline = time.monotonic() + 60
            process = subprocess.Popen(
                [str(executable), "--safe-mode", "--multiinstance", "--debug"],
                cwd=reports,
                stdout=stdout,
                stderr=stderr,
            )
            wait_for_safe_mode(process, data, logs, startup_deadline)
            user = data / "Packages/User"
            (data / "Installed Packages").mkdir(exist_ok=True)
            (data / "Lib/python314").mkdir(parents=True, exist_ok=True)
            write_json(
                user / "Preferences.sublime-settings",
                {
                    "disable_plugin_host_3.3": True,
                    "update_check": False,
                    "hot_exit": False,
                    "remember_open_files": False,
                },
            )
            # Safe Mode clears data at startup: install only after its log and
            # directories prove initialization completed. Install libraries
            # before the package, and the request marker before the smoke
            # plugin. A console reload is available if automatic loading stalls.
            install_libraries(libraries, data)
            install_package(package, data, arguments.loose)
            write_json(user / "plain-tasks-smoke-request.json", {"output_path": str(report_path)})
            staged_smoke = user / "PlainTasksSmoke.staging"
            shutil.copyfile(ROOT / "tests/editor_smoke.py", staged_smoke)
            staged_smoke.replace(user / "PlainTasksSmoke.py")
            (reports / "console-bootstrap.txt").write_text(
                BOOTSTRAP_COMMAND + "\n", encoding="utf-8"
            )
            print(
                "Accept the Safe Mode notification by clicking OK in the test editor.", flush=True
            )
            print(
                "If no report appears after accepting the Safe Mode notification, "
                "open View > Show Console and paste this fallback line:",
                flush=True,
            )
            print(BOOTSTRAP_COMMAND, flush=True)
            print(f"Waiting up to {arguments.timeout:g} seconds for the smoke report", flush=True)
            report = wait_for_report(process, report_path, time.monotonic() + arguments.timeout)
            validate_report(report, data)
            result.update(ok=True, passed=report["passed"], failed=report["failed"])
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        try:
            stop_editor(process)
        except Exception as error:
            result.update(ok=False, shutdown_error=f"{type(error).__name__}: {error}")
        write_json(reports / "runner-result.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--app",
        type=Path,
        required=True,
        help="Signed official build 4215 .app extracted with Finder",
    )
    parser.add_argument(
        "--package", type=Path, required=True, help="PlainTasks.sublime-package to verify"
    )
    parser.add_argument(
        "--libraries",
        type=Path,
        required=True,
        help="dateutil/, six.py and their license/metadata files",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Parent directory for unique report directories"
    )
    parser.add_argument(
        "--loose",
        action="store_true",
        help="Extract the package into the Safe Mode Packages/PlainTasks",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180,
        help="Notification/report wait in seconds (120..600; default: 180)",
    )
    arguments = parser.parse_args()
    if not 120 <= arguments.timeout <= 600:
        parser.error("--timeout must be at least 120 and at most 600 seconds")
    try:
        result = run(arguments)
    except Exception as error:
        result = {"ok": False, "error": f"{type(error).__name__}: {error}"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
