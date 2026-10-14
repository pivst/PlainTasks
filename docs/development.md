# Development

## Checks

Use Python 3.14, matching the editor's plugin host:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -W error::SyntaxWarning -m compileall -q APlainTasksCommon.py PlainTasks.py PlainTasksDates.py PlainTasksToHTML.py tests tools
.venv/bin/python -W error::DeprecationWarning tests/run.py
```

On Windows, use `.venv\Scripts\python.exe` and `.venv\Scripts\ruff.exe`.
The standalone suite uses a small Sublime API double for editor contracts; it
cannot establish syntax-engine or native-window behavior. CI runs Python checks
on Linux, Windows, and macOS and exercises the Windows installer through the
Windows PowerShell 5.1 command-line entry point.

## Builds

`VERSION` identifies the release. Build the plugin archive and complete offline
Windows bundle from reviewed source and the fixed dependency requirements:

```sh
python -m pip install --no-compile --target /tmp/plaintasks-libraries -r requirements.txt
python tools/build_release.py --libraries /tmp/plaintasks-libraries
```

`dist/` contains the plugin, bundle, file manifest, and SHA256 files. Runtime
files use an explicit allowlist; tests, development tools, caches, and repository
metadata stay outside the plugin archive. ZIP entries have stable ordering,
timestamps, and permissions. The manifest records the source commit and dirty
state. To check installer behavior using an extracted bundle:

```powershell
powershell.exe -NoProfile -File .\tests\windows_delivery_selftest.ps1 -BundleRoot 'C:\path\to\extracted-bundle'
```

The test creates its own disposable directory. It covers conflicts, backup,
rollback, restore, personal settings, bytecode caches, and the CLI entry point.

## Real editor tests

`tests/editor_smoke.py` uses actual Sublime APIs. Run it only in a test profile.
It verifies the embedded runtime, syntax, task editing, dates, calendar, popups,
resource loading, HTML, file links, and UTF-8/CRLF saving.

On Windows, run the bundle's test script with a local official 4215 portable ZIP:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\Test-PlainTasks4215.ps1 -PortableZip 'C:\path\sublime_text_build_4215_x64.zip' -KeepOpen
```

On macOS, extract the official ZIP with Finder so signature metadata is preserved.
Close existing editor instances, then run:

```sh
python tools/test_macos4215.py --app '/path/Sublime Text.app' \
  --package dist/PlainTasks.sublime-package --libraries /tmp/plaintasks-libraries \
  --output validation
```

The runner preserves the signed application and uses official Safe Mode. It
backs up any existing Safe Mode data before startup. Accept the Safe Mode
notification; a console bootstrap is printed if automatic loading stalls. Add
`--loose` to test the same package as an unpacked directory.

Automated reports are saved with the exact runtime and package hash. Before
release, check native keyboard shortcuts, Save As, browser/protocol handlers,
file jumps, display scaling, popup appearance, and a restart on the target OS.
