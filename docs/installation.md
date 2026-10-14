# Installation

## Requirements

- Sublime Text build 4215, with its embedded Python 3.14 plugin host.
- Windows 10 x64, macOS, or Linux supported by that editor build.
- `python-dateutil` 2.9.0.post0 and `six` 1.17.0 for flexible date parsing.

No system Python is needed to run the plugin. Package Control's upstream
`PlainTasks` listing may install a different project; use this repository's
source or release package.

## Data directory

Choose **Preferences → Browse Packages**. The parent of `Packages` is the data
directory. The default Windows location is `%APPDATA%\Sublime Text`; a portable
installation uses `Data` beside `sublime_text.exe`. Use the actual directory
reported by the editor if it differs.

```text
<Data>/
  Installed Packages/PlainTasks.sublime-package
  Lib/python314/
    dateutil/
    six.py
    python_dateutil-2.9.0.post0.dist-info/
    six-1.17.0.dist-info/
```

Keep the `.sublime-package` archive compressed. Copy the contents of
`lib/python314` into the existing library directory, retaining other libraries
and the included metadata and licenses. An existing `Packages/PlainTasks`
folder takes precedence over the archive; move it to a backup first.

## Windows offline bundle

Extract the complete `PlainTasks-<version>-windows.zip` on the offline computer.
Close Sublime Text, then double-click **Install.cmd** in the extracted directory.
It installs into `%APPDATA%\Sublime Text` and backs up an existing PlainTasks
installation before replacing it. Personal settings are retained; no
administrator account, network connection, or separate Python is required.

For a portable installation, run `Install.cmd "C:\Tools\Sublime Text"` from a
command prompt, substituting your actual editor directory.

To use the PowerShell installer directly, run from the extracted directory:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\Install-PlainTasks.ps1 -DataPath "$env:APPDATA\Sublime Text"
```

For a portable installation, use:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\Install-PlainTasks.ps1 -PortablePath 'C:\Tools\Sublime Text'
```

The script checks the bundle's file hashes before installing the plugin and
libraries. Identical files are skipped. If existing files differ, inspect the
reported paths and add `-BackupExisting` to preserve them before replacement.
Personal settings and shortcuts in `Packages/User` are retained.

Keep the reported backup directory and its `restore.json`. To restore a previous
installation, close Sublime and run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\Restore-PlainTasks.ps1 -JournalPath 'C:\path\to\PlainTasks Backups\backup\restore.json'
```

Restoration stops if installed files have since been modified. The script does
not overwrite those changes. If a file-operation error interrupts restoration,
resolve the reported problem and retry the same journal. Its checkpoint records
completed operations; `installed-*` snapshots retain the version being removed.
After installation, restart Sublime, create a task
from the command palette, and check completing and reopening it.

## Dependencies for a source installation

Package Control reads `dependencies.json` and installs the date library when it
manages this package. To install manually on a connected development machine,
obtain the target library directory in Sublime's console:

```python
from pathlib import Path

print(Path(sublime.packages_path()).parent / "Lib" / "python314")
```

Then use an external Python to install the fixed requirements into that directory:

```sh
python -m pip install --no-compile --target '<library-directory>' -r requirements.txt
```

On an offline computer, transfer the bundled library files instead. A basic
calendar and numeric dates work without dateutil; named months and other
flexible inputs require it.
