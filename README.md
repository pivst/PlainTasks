# PlainTasks

[![Tests](https://github.com/pivst/PlainTasks/actions/workflows/tests.yml/badge.svg)](https://github.com/pivst/PlainTasks/actions/workflows/tests.yml)

PlainTasks turns plain-text files into task lists in Sublime Text **4215**, using
its embedded **Python 3.14** runtime. It supports projects, task states, tags,
dates, time tracking, filtering, file links, and HTML export on Windows, macOS,
and Linux.

```text
Project:
  ☐ Draft the proposal @high @due(+2w)
  ☐ Review the budget
  ✔ Send the invitation @done(26-10-14 09:30)
```

## Installation

Open **Preferences → Browse Packages** to locate your Sublime data directory.
Install `PlainTasks.sublime-package` in its sibling `Installed Packages`
directory. For a source installation, clone this repository into
`Packages/PlainTasks`:

```sh
git clone https://github.com/pivst/PlainTasks.git PlainTasks
```

The package directory must be named `PlainTasks`. Move an existing
`Packages/PlainTasks` outside the data directory before switching to a packaged
installation, because loose files override the archive.

Flexible date parsing requires `python-dateutil` and `six`. The Windows offline
bundle includes both, together with installation and restore scripts. It does
not require an internet connection, a separate Python installation, or Package
Control. See [installation](docs/installation.md) for the directory layout,
offline commands, and manual dependency installation.

## Quick start

1. Open the command palette and choose **Tasks: New document**.
2. Save the file as `.todo`, `.tasks`, `.taskpaper`, or `.todolist`.
3. Write a project heading ending in `:`, then add tasks below it.

| Action | Windows / Linux | macOS |
| --- | --- | --- |
| New task | Ctrl+Enter | Cmd+Enter |
| Complete / reopen | Ctrl+D | Cmd+D |
| Cancel / reopen | Alt+C | Ctrl+C |
| Archive finished tasks | Ctrl+Shift+A | Cmd+Shift+A |
| Open URL | Ctrl+Shift+U | Cmd+Shift+U |
| Open file link | Alt+O | Ctrl+O |

Use **Preferences → Package Settings → PlainTasks → Tutorial** for an editable
practice document. The command palette also provides filtering, date sorting,
statistics, and HTML export.

## Configuration

Choose **Preferences → Package Settings → PlainTasks → Settings**. Put overrides
in the user file; bundled defaults are read-only. For example:

```json
{
  "date_format": "(%Y-%m-%d %H:%M)",
  "show_remain_due": true,
  "stats_ignore_archive": true,
  "color_scheme": "Packages/PlainTasks/tasks-dark.hidden-tmTheme"
}
```

[Usage](docs/usage.md) documents dates, links, TaskPaper mode, time tracking,
and statistics. [Development](docs/development.md) describes checks, release
builds, and real-editor testing.

## License

[MIT](LICENSE). Originally created by Allen Bargi and the PlainTasks contributors.
