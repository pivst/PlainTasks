# Usage

## Documents and tasks

Supported filenames include `.todo`, `.tasks`, `.taskpaper`, `.todolist`,
`.todolist.txt`, and `TODO`. A line ending in `:` is a project heading. Indent
subprojects and their tasks to form a hierarchy. Unmarked lines are notes.

The new-task shortcut creates a task, converts a note to a task, or inserts a
new task after the current one. Complete and cancel shortcuts toggle task state.
Multiple cursors apply the action to each selected line.

Archiving moves finished tasks to the `Archive:` project and records the source
project. **Archive (Org-Mode Style)** moves the selected subtree to a sibling
archive file. Undo restores the buffer contents; it does not undo the append to
the external archive file.

## Tags, priority, and filtering

Use tags such as `@work` and `@home`. Built-in priority tags are `@critical`,
`@high`, `@low`, and `@today`. Type `c`, `h`, `l`, or `t` and press Tab to expand
the corresponding completion.

**Filter by tags under cursors** keeps matching pending tasks visible along with
their projects and notes. Use Sublime's Unfold All to clear the filter. The
command palette also offers due-date filtering and date/priority sorting.

## Dates

Place the cursor inside a date tag and press Tab to expand it. F4 adds `@due()`;
the context menu's **Tasks: Show date picker** opens the calendar.

| Input | Meaning |
| --- | --- |
| `@due(0)` | Today |
| `@due(5)` | Next occurrence of day 5 |
| `@due(--1)` | Day 1 of the current month |
| `@due(2-3)` | February 3; next year if the current month is after February |
| `@due(2026-10-14 15:30)` | An explicit date and time |
| `@due(2026-Oct-14)` | Explicit date with a named month; requires dateutil |
| `@due(+)` | Tomorrow |
| `@due(+2w)` | Two weeks from now |
| `@due(+2:)` | Two hours from now |
| `@due(+:30)` | Thirty minutes from now |
| `@due(++3d)` | Three days after `@created`; three days from now if it is absent |

Dots may replace hyphens in numeric dates. Short dates retain the current hour
or minute when omitted. Invalid dates are reported rather than silently changed
to today. `date_format` controls how expanded dates are written; use `%Y` for a
four-digit year. Date highlighting marks overdue, soon-due, and malformed tags.

## Time tracking

Use `@started()` and Tab to record the start time. `@toggle()` alternates pause
and resume. Completing a tracked task appends `@lasted(...)`; cancellation
appends `@wasted(...)`. Press Tab on the time tags to recalculate after editing
timestamps. `decimal_minutes` displays fractional hours.

## Links and HTML

The open-URL shortcut opens web links or bracketed protocol links such as
`<mailto:person@example.com>`. File links may be relative to the task file or a
project folder, or use an absolute path:

```text
[Notes](notes.txt ":12:3")
[[notes.txt::12:3]]
./notes.txt:12:3
```

Quoted link options can select text, and `>symbol` selects a symbol. Directory
links add a folder to the project. File searches run in the background and can
be cancelled without blocking the editor.

**Tasks: Save as HTML…** creates an HTML view and opens the save dialog.
**Tasks: View as HTML** opens a temporary UTF-8 export in the default browser.
Both use the editor's resolved color scheme for bundled TextMate themes and
modern color schemes. User text and link attributes are escaped. Browser exports
are removed when the plugin unloads.

## TaskPaper and statistics

Set `taskpaper_compatible` to `true` to use `-` bullets and TaskPaper-style tags.
Existing task files remain plain text.

`stats_format` controls the status bar:

| Placeholder | Value |
| --- | --- |
| `$o`, `$d`, `$c` | Pending, completed, cancelled counts |
| `$n`, `$a` | Finished count and total count |
| `$percent`, `$progress` | Completion percentage and progress bar |
| `$last` | Most recent completion date |
| `{{regex}}` | Counts matching a regular expression |

Set `stats_ignore_archive` to exclude archived tasks. **Tasks: Copy Statistics**
copies the formatted result. `replace_stats_chars` applies replacements when
copying; `bar_full` and `bar_empty` customize progress cells.
