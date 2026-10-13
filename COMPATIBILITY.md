# Sublime Text 4215 / Python 3.14 migration

Sublime Text [build 4213 and later](https://www.sublimetext.com/download) ship
Python 3.14 and disable the Python 3.3 host by default. The
[API environment documentation](https://www.sublimetext.com/docs/api_environments.html)
specifies `.python-version` containing `3.14` for the new host (available since
build 4205). This branch selects it explicitly and removes the legacy ST2/3 and
Python 2/3.3 compatibility branches. Existing command names and task settings are
preserved.

## Fixed failures

| Trigger | Previous behavior | Updated behavior |
| --- | --- | --- |
| Load HTML export module | Imports removed `cgi`; `cgi.escape` was also removed | Uses `html.escape`, including quoted attributes and document titles |
| Complete/reopen a task | Multiline regex places `(?x)` after leading whitespace, rejected by Python 3.11+ | Places the flag at the start of the pattern |
| Hover a task bullet | Sends float viewport dimensions to integer API arguments | Converts popup sizes to integers and accepts location zero |
| Save as HTML | Reuses the task view's edit token on the new HTML view | Populates the output through its own `append` command and opens Save As |
| Export from a packaged installation | Opens package resources as filesystem files | Reads templates and TextMate themes with `sublime.load_resource` |
| Export with a modern color scheme | Attempts to parse the scheme as an XML plist | Uses Sublime's resolved scope styles |
| Parse plist text/binary data | Uses a Python 2 `cStringIO` path and custom XML parser | Uses `plistlib`, preserving Unicode and supporting binary plists |
| Import under an invalid system locale | Mutates the shared host locale and may fail | Leaves the host locale alone |
| Calendar when dateutil is missing | References an undefined `relativedelta` | Uses standard-library month arithmetic with leap-day clamping |
| Malformed short date / invalid file link | May scan outside the line forever / reference uninitialized values | Returns a bounded parse error / no-link result |

## Refactoring

- A single Python 3.14 path uses relative package imports, Unicode strings, raw
  regex literals, standard aware local timestamps, and `timedelta.total_seconds()`.
- HTML rendering shares the text/tag/markup path, escapes user content, and
  substitutes template placeholders once. Temporary HTML is written with an
  explicit UTF-8 encoding and opened through a valid file URI.
- Inline scope regions are contiguous, disjoint, and clipped to their line.
- Plist parsing keeps the original `parse_file`, `parse_string`, and
  `XmlPropertyListParser.parse` entry points as thin standard-library wrappers.
- Optional dependency handling catches import/parser errors specifically, rather
  than hiding arbitrary programming errors. Three-digit years require `%Y`
  instead of `%y`, consistently across operating systems, matching the original
  date test's intended behavior.
- File-link threads use the `name` property/constructor and call `is_alive()`;
  worker error dialogs are scheduled on the editor thread.

## Validation scope

The standalone suite includes the six original date tests and regression tests
for the failures above. The original baseline failed its ancient-year date case;
that case now passes. The development environment provides Python 3.12, on which
all standalone checks passed. The workflow in `.github/workflows/tests.yml`
requires Python 3.14 on Linux, Windows, and macOS; consult the PR checks for the
actual result.

Live Sublime Text 4215 UI verification is still required. Follow the
[smoke checklist](tests/How%20to%20run%20tests.md); API doubles cannot establish
syntax-engine, Package Control library loading, or GUI behavior.
