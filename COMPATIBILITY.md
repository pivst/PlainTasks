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

The local delivery adds fixes for compressed-package menu resources, literal
markup delimiters, Windows external handlers, and modern HTML theme styles.
In particular, the global background comes from `View.style()`; scope styles
can omit it. Completed task/tag selectors match the actual syntax, and normal
font styles explicitly reset the template's inherited italic style.

On 2026-10-14, all 36 standalone tests passed on Python 3.14.8. The same runtime
package passed 19 real-editor checks in each of two macOS Sublime Text 4215 /
embedded Python 3.14.6 installations: compressed and unpacked. These checks use
real syntax, commands, popups, package resources, CSS, dateutil, and UTF-8/CRLF
saving, without API doubles. See [the review and evidence](docs/PR_REVIEW.md).

The offline bundle supplies dateutil and six in `Lib/python314`, including
their licenses, metadata and timezone data. Package Control's dependency
installation flow was not exercised. Windows 10 / PowerShell 5.1, native
shortcuts, Save As, browser handlers, and visual popup behavior still require
target-machine acceptance. Follow [the Windows procedure](docs/WINDOWS_4215.md).
