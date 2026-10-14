## Standalone regression suite

Use Python 3.14, matching Sublime Text build 4215:

```sh
python -m pip install -r requirements-dev.txt
python -W error::SyntaxWarning -m compileall -q APlainTasksCommon.py PlainTasks.py PlainTasksDates.py PlainTasksToHTML.py plist_parser.py tests
python -W error::DeprecationWarning tests/run.py
```

`tests/run.py` imports all plugin modules under Sublime's package-module layout.
Outside the editor it installs a small API double that rejects foreign edit tokens
and non-integer popup sizes. It runs the existing date tests plus regressions for
commands, HTML export, Unicode/binary plists, calendar navigation, and missing
optional dependencies. It does not emulate Sublime's syntax engine or UI.

The GitHub Actions workflow runs these checks on Python 3.14 on Linux, Windows,
and macOS. A passing standalone suite is not a claim of live editor verification.

## Tests inside Sublime Text

1. Install [UnitTesting](https://github.com/randy3k/UnitTesting) through Package Control.
2. Choose **UnitTesting** in the command palette.
3. Enter `PlainTasks` and run the suite.

The API-double tests are skipped inside the editor; the pure date/plist tests run
against the real plugin environment. Do not copy the standalone stub into
`Packages/User` or run its `install()` function inside Sublime Text.

## Build 4215 smoke checks

The repeatable real-editor suite is `editor_smoke.py`; it uses real APIs and no
standalone stub. For Windows use [the isolated portable runner](../docs/WINDOWS_4215.md).
On macOS, extract the official ZIP with Finder, then use
`tools/test_macos4215.py` with `--app`, `--package`, `--libraries`, and `--output`.
It preserves the signed app and uses official Safe Mode. The current delivery
passed 19 checks in each of compressed and unpacked installations on macOS
4215 / embedded Python 3.14.6; native UI and Windows acceptance remain separate.

Use the default Python 3.14 host and check the Sublime console for tracebacks:

- Create a task document. Add, complete, reopen, cancel, and archive tasks, including
  Chinese text, multiple selections, and TaskPaper mode.
- Hover a bullet at the start of a line and click its complete/cancel actions.
- Expand `@due(1)`, `@due(+2w)`, and `@due(2026-Oct-13)`. Check due highlights,
  previews, and the date picker across month ends and February in a leap year.
- Use **View as HTML** and **Save as HTML…** with both the bundled TextMate theme
  and a modern `.sublime-color-scheme`. Check quotes, `&`, `<`, Chinese text,
  links, and emphasis in the exported document.
- Verify Markdown/wiki file links and a line without a valid link.
- Check loading with the package installed both as a `PlainTasks` folder and as
  a `.sublime-package` archive, especially the HTML template/theme resources.
