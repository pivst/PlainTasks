"""Task commands and editor integration for Sublime Text 4215."""

import os
import re
import threading
import webbrowser
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import unquote, urlsplit

import sublime
import sublime_plugin

from .APlainTasksCommon import (
    PlainTasksBase,
    PlainTasksEnabled,
    PlainTasksFold,
    find_archive,
    get_all_projects_and_separators,
)
from .PlainTasksDates import increase_date, is_dayfirst, is_yearfirst, parse_date

NT = sublime.platform() == "windows"
_active_searches = {}
_unloading = False


def plugin_loaded():
    global _unloading
    _unloading = False
    if int(sublime.version()) < 4215:
        raise RuntimeError("PlainTasks requires Sublime Text 4215 or later (Python 3.14)")


def plugin_unloaded():
    global _unloading
    _unloading = True
    for search, view in list(_active_searches.values()):
        search.cancelled.set()
        if view.is_valid():
            view.erase_status("PlainTasksSearch")
    _active_searches.clear()
    PlainTasksStatsStatus._cache.clear()
    PlainTasksAddGutterIconsForTags._cache.clear()


def finish_link_search(search, view):
    owned = _active_searches.pop(id(search), None)
    if owned is not None and view.is_valid():
        view.erase_status("PlainTasksSearch")


def open_external_url(url):
    """Pass URLs and file paths directly to the platform's registered handler."""
    if NT:
        os.startfile(url)
    else:
        webbrowser.open_new_tab(url)


def tznow() -> datetime:
    """Return an aware local timestamp using the system timezone."""
    return datetime.now().astimezone()


def check_parentheses(date_format, regex_group, is_date=False):
    """Distinguish a completion timestamp from parentheses in task text."""
    try:
        datetime.strptime(regex_group.strip(), date_format)
    except ValueError:
        return "" if is_date else regex_group
    return regex_group if is_date else ""


def selected_lines(view):
    """Yield each selected line once, from the end so edits preserve positions."""
    lines = {
        (line.begin(), line.end()) for selection in view.sel() for line in view.lines(selection)
    }
    return [sublime.Region(start, end) for start, end in sorted(lines, reverse=True)]


def following_notes(view, task, limit=None):
    """Iterate a task's notes without reading past the end of the buffer."""
    end = view.size() if limit is None else min(limit, view.size())
    point = task.end() + 1
    while point < end and "notes.todo" in view.scope_name(point).split():
        note = view.line(point)
        yield note
        point = note.end() + 1


def refresh_tasks(view):
    PlainTasksStatsStatus.set_stats(view)
    view.run_command("plain_tasks_toggle_highlight_past_due")


class PlainTasksNewCommand(PlainTasksBase):
    def run_command(self, edit):
        header_to_task = self.view.settings().get("header_to_task", False)
        carets = []
        for line in selected_lines(self.view):
            contents = self.view.substr(line)
            match = re.match(r"^([ \t]*)(.*)$", contents)
            indent, text = match.groups()
            scope = self.view.scope_name(line.begin())
            bullet = self.open_tasks_bullet + self.tasks_bullet_space
            if "item" in scope:
                replacement = contents + "\n" + indent + bullet
            elif ("header" in scope and text and not header_to_task) or "separator" in scope:
                replacement = contents + "\n" + indent + self.before_tasks_bullet_spaces + bullet
            else:
                replacement = (indent or self.before_tasks_bullet_spaces) + bullet + text
            self.view.replace(edit, line, replacement)
            delta = len(replacement) - (line.end() - line.begin())
            carets = [point + delta for point in carets]
            carets.append(line.begin() + len(replacement))

        self.view.sel().clear()
        self.view.sel().add_all([sublime.Region(point) for point in reversed(carets)])
        refresh_tasks(self.view)


class PlainTasksNewWithDateCommand(PlainTasksBase):
    def run_command(self, edit):
        self.view.run_command("plain_tasks_new")
        sels = list(self.view.sel())
        suffix = " @created" + tznow().strftime(self.date_format)
        points = []
        for s in reversed(sels):
            if self.view.substr(sublime.Region(s.b - 2, s.b)) == "  ":
                point = s.b - 2  # keep double whitespace at eol
            else:
                point = s.b
            self.view.insert(edit, point, suffix)
            points.append(point)
        self.view.sel().clear()
        offset = len(suffix)
        for i in range(len(sels)):
            point = points[~i] + i * offset
            self.view.sel().add(sublime.Region(point))


def remove_completion_metadata(text, tag, date_format):
    """Remove the state being toggled while retaining the task's other tags."""
    pattern = re.compile(r"(?<!\S)" + re.escape(tag) + r"\b(?:[ \t]*(\([^()\n]*\)))?")

    def remove(match):
        stamp = match.group(1)
        return check_parentheses(date_format, stamp) if stamp else ""

    text, count = pattern.subn(remove, text)
    if not count:
        # A completion date can be present with the done_tag setting disabled.
        match = re.search(r"[ \t]+(\([^()\n]*\))(?=[ \t]*(?:@project|@[wl]asted|$))", text)
        if match and not check_parentheses(date_format, match.group(1)):
            text = text[: match.start()] + text[match.end() :]
    text = re.sub(r"[ \t]+@(?:lasted|wasted|total)\([^()\n]*\)", "", text)
    return text.rstrip()


def toggle_tasks(command, edit, cancel=False):
    """Toggle task state using one line replacement and tracked editor selections."""
    view = command.view
    suffix, now = command.format_line_end(command.canc_tag if cancel else command.done_tag, tznow())
    for line in selected_lines(view):
        contents = view.substr(line)
        scope = view.scope_name(line.begin())
        if not any(state in scope for state in ("pending", "completed", "cancelled", "header")):
            continue
        if cancel and "completed" in scope:
            sublime.status_message("Reopen the completed task before cancelling it")
            continue
        indent = re.match(r"[ \t]*", contents).group()
        is_header = "header" in scope
        if is_header:
            body = " " + contents[len(indent) :]
        else:
            match = re.match(r"^[ \t]*(?:\[[ x-]\]|.)(.*)$", contents)
            if not match:
                continue
            body = match.group(1)
        markdown_break = "  " if contents.endswith("  ") else ""
        reopening = ("cancelled" if cancel else "completed") in scope
        previous_tag = "@cancelled" if "cancelled" in scope else "@done"
        if reopening or ("cancelled" in scope and not cancel):
            body = remove_completion_metadata(body, previous_tag, command.date_format)
        body = body.rstrip()
        bullet = (
            command.open_tasks_bullet
            if reopening
            else command.canc_tasks_bullet
            if cancel
            else command.done_tasks_bullet
        )
        replacement = (
            indent + bullet + body + ("" if reopening else suffix.rstrip()) + markdown_break
        )
        view.replace(edit, line, replacement)
        if not reopening:
            view.run_command(
                "plain_tasks_calculate_time_for_task",
                {
                    "started_matches": re.findall(r"@started(\([^()\n]*\))", contents),
                    "toggle_matches": re.findall(r"@toggle(\([^()\n]*\))", contents),
                    "now": now,
                    "eol": line.begin() + len(replacement),
                    **({"tag": "wasted"} if cancel else {}),
                },
            )
            if is_header:
                view.run_command(
                    "plain_tasks_calculate_total_time_for_project", {"start": line.begin()}
                )
    refresh_tasks(view)


class PlainTasksCompleteCommand(PlainTasksBase):
    def run_command(self, edit):
        toggle_tasks(self, edit)


class PlainTasksInjectDueDateCommand(PlainTasksBase):
    def run_command(self, edit):
        due_re = r"^\s*[^\b]*?\s*@due\([\d\w,\.:\-\/ @]*\).*$"
        regions = selected_lines(self.view)
        point = -1
        for line in regions:
            line_contents = self.view.substr(line)
            current_scope = self.view.scope_name(line.begin())
            due_matches = re.match(due_re, line_contents, re.U)
            if ("item" in current_scope or "header" in current_scope) and not due_matches:
                self.view.insert(edit, line.end(), " @due()")
                point = line.end() + 6
        if point != -1:
            self.view.sel().clear()
            self.view.sel().add(point)


@dataclass
class SortableTask:
    region: sublime.Region
    due: datetime | None
    priority: int


class PlainTasksSortByDueDateAndPriorityCommand(PlainTasksBase):
    DUE = re.compile(r"(?<!\S)@due\(([^()\n]*)\)")
    PRIORITY = re.compile(r"(?<!\S)@(critical|high|low)\b")
    PRIORITIES = {"critical": 1, "high": 2, "low": 4}

    def run_command(self, edit, descending=False):
        now = tznow()
        for project in selected_lines(self.view):
            if "header" not in self.view.scope_name(project.begin()):
                continue
            project_block = self.view.indented_region(project.end() + 1)
            if project_block.empty():
                continue
            tasks = []
            first_indentation = None
            point = project_block.begin()
            while point < project_block.end():
                line = self.view.line(point)
                scope = self.view.scope_name(point)
                indentation = self.view.indentation_level(point)
                if ("item" in scope or "header" in scope) and (
                    first_indentation is None or first_indentation == indentation
                ):
                    if tasks:
                        tasks[-1].region = sublime.Region(tasks[-1].region.begin(), line.begin())
                    else:
                        first_indentation = indentation
                    contents = self.view.substr(line)
                    due = self.DUE.search(contents)
                    due_date = None
                    if due:
                        text = due.group(1).strip()
                        if text.startswith("+"):
                            due_date = increase_date(self.view, line, text, now, self.date_format)[
                                0
                            ]
                        else:
                            due_date = parse_date(
                                "(" + text + ")",
                                date_format=self.date_format,
                                yearfirst=is_yearfirst(self.date_format),
                                dayfirst=is_dayfirst(self.date_format),
                                default=now,
                            )[0]
                    priority = min(
                        (self.PRIORITIES[tag] for tag in self.PRIORITY.findall(contents)), default=3
                    )
                    tasks.append(SortableTask(line, due_date, priority))
                point = line.end() + 1
            if not tasks:
                continue
            tasks[-1].region = sublime.Region(tasks[-1].region.begin(), project_block.end())
            start = tasks[0].region.begin()
            tasks.sort(
                key=lambda task: (task.due is None, task.due or now, task.priority),
                reverse=descending,
            )
            original = self.view.substr(sublime.Region(start, project_block.end()))
            replacement = "\n".join(
                self.view.substr(task.region).removesuffix("\n") for task in tasks
            )
            if original.endswith("\n"):
                replacement += "\n"
            self.view.replace(edit, sublime.Region(start, project_block.end()), replacement)
        refresh_tasks(self.view)


class PlainTasksCancelCommand(PlainTasksBase):
    def run_command(self, edit):
        toggle_tasks(self, edit, cancel=True)


class PlainTasksArchiveCommand(PlainTasksBase):
    STATES = "meta.item.todo.completed, meta.item.todo.cancelled"
    HEADER = re.compile(r"^([ \t]*)(.+):(?=[ \t]|$)")

    def run_command(self, edit, partial=False):
        archive = find_archive(self.view, self.archive_name)
        limit = archive.begin() if archive.begin() >= 0 else self.view.size()
        tasks = self._archivable_tasks(limit, partial)
        if not tasks:
            sublime.status_message("Nothing to archive")
            return
        projects = get_all_projects_and_separators(self.view)
        project_names = self._project_names(tasks, projects)
        contents = []
        for task in tasks:
            text = self.view.substr(task)
            scope = self.view.scope_name(task.begin())
            if any(state in scope for state in ("completed", "cancelled")):
                project = project_names[task.begin()]
                if self.project_postfix:
                    suffix = f" @project({project})" if project else ""
                    markdown_break = "  " if text.endswith("  ") else ""
                    contents.append(
                        self.before_tasks_bullet_spaces
                        + text.strip()
                        + suffix
                        + markdown_break
                        + "\n"
                    )
                else:
                    match = re.match(r"^[ \t]*(\[[x-]\]|.)([ \t]+.*)$", text)
                    if not match:
                        continue
                    prefix = self.tasks_bullet_space + project + ":" if project else ""
                    contents.append(
                        self.before_tasks_bullet_spaces
                        + match.group(1)
                        + prefix
                        + match.group(2)
                        + "\n"
                    )
            else:
                contents.append(self.before_tasks_bullet_spaces * 2 + text.lstrip() + "\n")
        if archive.begin() >= 0:
            point = self.view.full_line(archive).end()
        else:
            section = "\n\n＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿\n" + self.archive_name + "\n"
            self.view.insert(edit, self.view.size(), section)
            point = self.view.size()
        self.view.insert(edit, point, "".join(contents))
        for task in reversed(tasks):
            self.view.erase(edit, self.view.full_line(task))
        self.view.run_command("plain_tasks_sort_by_date")
        refresh_tasks(self.view)

    def _project_names(self, tasks, projects):
        """Resolve task hierarchy in document order rather than scanning per task."""
        index = 0
        hierarchy = []
        names = {}
        for task in tasks:
            while index < len(projects) and projects[index].begin() < task.begin():
                project = projects[index]
                indentation = self.view.indentation_level(project.begin())
                while hierarchy and hierarchy[-1][0] >= indentation:
                    hierarchy.pop()
                match = self.HEADER.match(self.view.substr(project))
                if match:
                    hierarchy.append((indentation, match.group(2)))
                index += 1
            depth = self.view.indentation_level(task.begin())
            names[task.begin()] = " / ".join(name for level, name in hierarchy if level < depth)
        return names

    def _archivable_tasks(self, limit, partial):
        if partial:
            roots = [
                line
                for line in selected_lines(self.view)
                if line.begin() < limit
                and any(
                    state in self.view.scope_name(line.begin())
                    for state in ("completed", "cancelled")
                )
            ]
        else:
            roots = [
                self.view.line(region.begin())
                for region in self.view.find_by_selector(self.STATES)
                if region.begin() < limit
            ]
        lines = {(line.begin(), line.end()) for line in roots}
        for task in roots:
            lines.update(
                (note.begin(), note.end()) for note in following_notes(self.view, task, limit)
            )
        return [sublime.Region(start, end) for start, end in sorted(lines)]


class PlainTasksNewTaskDocCommand(sublime_plugin.WindowCommand):
    def run(self):
        view = self.window.new_file()
        view.assign_syntax("Packages/PlainTasks/PlainTasks.sublime-syntax")
        scheme = sublime.load_settings("PlainTasks.sublime-settings").get("color_scheme")
        if scheme:
            view.settings().set("color_scheme", scheme)


class PlainTasksOpenResourceCommand(sublime_plugin.WindowCommand):
    """Open bundled documentation/settings even from a compressed package."""

    def run(self, resource):
        view = self.window.new_file()
        view.set_name(os.path.basename(resource))
        view.set_scratch(True)
        view.run_command(
            "append", {"characters": sublime.load_resource("Packages/PlainTasks/" + resource)}
        )
        view.assign_syntax(
            "Packages/PlainTasks/PlainTasks.sublime-syntax"
            if resource.endswith(".todo")
            else "Packages/JSON/JSON.sublime-syntax"
        )
        view.set_read_only(not resource.endswith(".todo"))


class PlainTasksOpenUrlCommand(PlainTasksEnabled):
    URL_TOKEN = re.compile(r"[^\s<>\"']+")
    URL_PROTOCOL = re.compile(r"(?i)\b(?:https?://|www\d{0,3}\.)")
    URL_START = re.compile(r"(?i)(?:https?://|www\d{0,3}\.|(?:[a-z0-9-]+\.)+[a-z]{2,}/)")
    END_PUNCTUATION = frozenset(".,;:!?`«»“”‘’…")

    @classmethod
    def _url_in_token(cls, token):
        protocol = cls.URL_PROTOCOL.search(token)
        start = protocol.start() if protocol else len(token) - len(token.lstrip("([{"))
        end = len(token)
        target = token[start:]
        excess = {
            closing: target.count(closing) - target.count(opening)
            for opening, closing in (("(", ")"), ("[", "]"), ("{", "}"))
        }
        while end > start:
            char = token[end - 1]
            if char in cls.END_PUNCTUATION:
                end -= 1
            elif excess.get(char, 0) > 0:
                excess[char] -= 1
                end -= 1
            else:
                break
        target = token[start:end]
        prefix = cls.URL_START.match(target)
        if not prefix or (prefix.end() == len(target) and not target.endswith("/")):
            return None
        if target.lower() in ("http://", "https://"):
            return None
        return start, end, target if "://" in target else "http://" + target

    def run(self, edit):
        selection = self.view.sel()[0]
        point = selection.begin()
        line = self.view.line(point)
        contents = self.view.substr(line)
        offset = point - line.begin()
        if "url" in self.view.scope_name(point):
            start = contents.rfind("<", 0, offset + 1)
            end = contents.find(">", max(start + 1, offset))
            if start >= 0 and end >= 0:
                region = sublime.Region(line.begin() + start + 1, line.begin() + end)
                self.view.sel().add(region)
                open_external_url(self.view.substr(region))
                return
        self.search_bare_weblink_and_open(selection.begin(), selection.end())

    def search_bare_weblink_and_open(self, start, end):
        line = self.view.line(start)
        contents = self.view.substr(line)
        offset = start - line.begin()
        for token in self.URL_TOKEN.finditer(contents):
            if not token.start() <= offset <= token.end():
                continue
            result = self._url_in_token(token.group())
            if result:
                first, last, url = result
                self.view.sel().add(
                    sublime.Region(
                        line.begin() + token.start() + first, line.begin() + token.start() + last
                    )
                )
                open_external_url(url)
                return
        sublime.status_message("Looks like there is nothing to open")


@dataclass
class LinkSearch:
    """Worker-owned filesystem search state; editor calls stay on the UI thread."""

    results: list = field(default_factory=list)
    cancelled: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    location: str = ""
    error: str = ""
    progress_open: bool = False

    def snapshot(self):
        with self.lock:
            return list(self.results), self.location


def search_files(search, folders, filename, line=0, column=0):
    """Search each directory once, stop promptly, and never call the editor API."""
    seen_directories = set()
    seen_results = set(search.results)

    def add(path):
        if search.cancelled.is_set():
            return
        path = os.path.normpath(os.path.abspath(path))
        if os.path.isfile(path):
            item = (path, line, column, "f")
        elif os.path.isdir(path):
            item = (path, 0, 0, "d")
        else:
            return
        if item not in seen_results:
            seen_results.add(item)
            with search.lock:
                search.results.append(item)

    def failed(error):
        search.error = str(error)

    try:
        filename = os.path.expanduser(filename.replace("\\", os.sep).replace("/", os.sep))
        if os.path.isabs(filename):
            add(filename)
            return
        for folder in dict.fromkeys(folders):
            if search.cancelled.is_set():
                return
            for root, directories, _ in os.walk(folder, onerror=failed):
                if search.cancelled.is_set():
                    return
                key = os.path.normcase(os.path.realpath(root))
                if key in seen_directories:
                    directories.clear()
                    continue
                seen_directories.add(key)
                directories[:] = [
                    name
                    for name in directories
                    if os.path.normcase(os.path.realpath(os.path.join(root, name)))
                    not in seen_directories
                ]
                with search.lock:
                    search.location = root
                add(os.path.join(root, filename))
    except OSError as error:
        failed(error)
    finally:
        search.done.set()


class PlainTasksOpenLinkCommand(PlainTasksEnabled):
    LINK_PATTERN = re.compile(r"""(?x)(?:^|[ \t])\.[\\/]
        (?P<fn>(?:[a-zA-Z]:[\\/])?[^:\n">]+?)
        (?:[\\/](?=[ \t]|$)|(?=[>:"]))
        (?:>(?P<sym>\w+))?(?::(?P<line>\d+))?(?::(?P<col>\d+))?(?:"(?P<text>[^\n]*?)")?
        """)
    MD_START = re.compile(r"\][ \t]*\(")
    OPTIONS = re.compile(r":(?P<line>\d+)(?::(?P<col>\d+))?|[>*](?P<sym>\w+)")

    @staticmethod
    def _closing_delimiter(contents, start, delimiter):
        depth = 1
        escaped = False
        quoted = False
        for index in range(start, len(contents)):
            char = contents[index]
            if escaped:
                escaped = False
            elif char == "\\" and index + 1 < len(contents) and contents[index + 1] in '()[]"':
                escaped = True
            elif delimiter == ")" and char == '"':
                quoted = not quoted
            elif quoted:
                continue
            elif delimiter == ")" and char == "(":
                depth += 1
            elif char == delimiter:
                depth -= 1
                if not depth:
                    return index
        return -1

    @classmethod
    def _option(cls, option):
        match = cls.OPTIONS.fullmatch(option)
        return (
            match.group("sym", "line", "col") + (None,)
            if match
            else (None, None, None, option or None)
        )

    @staticmethod
    def _filename(target):
        target = target.strip().removeprefix("<").removesuffix(">")
        if target.startswith("file:"):
            target = target.replace("file+sys:", "file:", 1).replace("file+emacs:", "file:", 1)
            parsed = urlsplit(target)
            target = unquote(parsed.path)
            if parsed.netloc:
                target = "//" + parsed.netloc + target
            elif NT and re.match(r"^/[a-zA-Z]:", target):
                target = target[1:]
        return target

    def parse_link(self, contents):
        direct = self.LINK_PATTERN.search(contents)
        if direct:
            filename, symbol, line, column, text = direct.group("fn", "sym", "line", "col", "text")
            return filename, symbol, line or 0, column or 0, text
        markdown = self.MD_START.search(contents)
        wiki = contents.find("[[")
        if markdown:
            end = self._closing_delimiter(contents, markdown.end(), ")")
            if end < 0:
                return None, None, 0, 0, None
            target = contents[markdown.end() : end].strip()
            option = ""
            if target.endswith('"') and target.count('"') >= 2:
                target, option, _ = target.rsplit('"', 2)
            filename = self._filename(target).replace("\\(", "(").replace("\\)", ")")
            symbol, line, column, text = self._option(option)
        elif wiki >= 0:
            end = self._closing_delimiter(contents, wiki + 2, "]")
            if end < 0 or not (
                contents.startswith("]", end + 1) or contents.startswith("[", end + 1)
            ):
                return None, None, 0, 0, None
            target = contents[wiki + 2 : end]
            filename, separator, option = target.partition("::")
            if separator and re.fullmatch(r"\d+(?::\d+)?", option):
                option = ":" + option
            if not separator:
                tail = contents[end + 1 :]
                if tail.startswith("["):
                    description_end = self._closing_delimiter(tail, 1, "]")
                    tail = tail[description_end + 1 :] if description_end >= 0 else ""
                if not tail.startswith("]"):
                    return None, None, 0, 0, None
                match = re.match(r'[ \t]*"([^\n]*?)"', tail[1:])
                option = match.group(1) if match else ""
            filename = self._filename(
                filename.replace("file+sys:", "file:", 1).replace("file+emacs:", "file:", 1)
            )
            filename = filename.replace("\\[", "[").replace("\\]", "]")
            symbol, line, column, text = self._option(option)
            if text:
                text = text.replace("\\[", "[").replace("\\]", "]")
        else:
            return None, None, 0, 0, None
        if not filename or re.match(r"^[a-zA-Z]{2,}://", filename):
            return None, None, 0, 0, None
        return filename, symbol, line or 0, column or 0, text

    @staticmethod
    def _format_result(result):
        filename, line, column, kind = result
        return [
            filename,
            f"line: {line} column: {column}" if kind == "f" else "Add folder to project",
        ]

    def run(self, edit):
        previous = getattr(self, "_search", None)
        if previous:
            previous.cancelled.set()
            finish_link_search(previous, self.view)
        self.view.erase_status("PlainTasksSearch")
        if _unloading:
            return
        point = self.view.sel()[0].begin()
        filename, symbol, line, column, text = self.parse_link(
            self.view.substr(self.view.line(point))
        )
        if not filename:
            sublime.status_message("Line does not contain a valid link to file")
            return
        window = self.view.window()
        if not window:
            return
        line, column = int(line), int(column)
        search = self._search = LinkSearch()
        _active_searches[id(search)] = search, self.view
        if symbol:
            search.results = self._symbol_results(window, filename, symbol)
            search.done.set()
            if search.results:
                self._poll_search(search, window, filename, text, line)
            else:
                sublime.status_message(f'Symbol "{symbol}" was not found in "{filename}"')
                finish_link_search(search, self.view)
            return
        folders = window.folders() + [
            os.path.dirname(view.file_name()) for view in window.views() if view.file_name()
        ]
        self.thread = threading.Thread(
            target=search_files, args=(search, folders, filename, line, column), daemon=True
        )
        self.thread.start()
        if not search.done.is_set():
            search.progress_open = True
            window.show_quick_panel(
                [["Stop search", filename]], lambda index: self._cancel_progress(search)
            )
        self._poll_search(search, window, filename, text, line)

    def _symbol_results(self, window, filename, symbol):
        def normalise(path):
            path = os.path.normpath(path.replace("\\", "/")).replace("\\", "/")
            return path.casefold() if NT else path

        target = normalise(filename)
        absolute = os.path.isabs(target) or re.match(r"^[a-zA-Z]:/", target)
        folders = window.folders()
        if self.view.file_name():
            folders = [os.path.dirname(self.view.file_name()), *folders]
        resolved = {normalise(os.path.join(folder, filename)) for folder in folders}
        results = []
        seen = set()
        for location in window.symbol_locations(
            symbol, source=sublime.SymbolSource.INDEX, type=sublime.SymbolType.DEFINITION
        ):
            path = normalise(location.path)
            matches = (
                path == target
                if absolute
                else (path == target or path.endswith("/" + target) or path in resolved)
            )
            key = path, location.row, location.col
            if matches and key not in seen:
                seen.add(key)
                results.append((location.path, location.row, location.col, "f"))
        return results

    def _cancel_progress(self, search):
        if search.progress_open:
            search.cancelled.set()
            search.progress_open = False
            finish_link_search(search, self.view)

    def _poll_search(self, search, window, filename, text, line):
        if _unloading or self._search is not search or search.cancelled.is_set():
            finish_link_search(search, self.view)
            return
        if not self.view.is_valid() or self.view.window() != window:
            search.cancelled.set()
            finish_link_search(search, self.view)
            return
        finished = search.done.is_set()
        results, location = search.snapshot()
        if finished:
            progress_open = search.progress_open
            search.progress_open = False
            self.view.erase_status("PlainTasksSearch")
            if progress_open:
                window.run_command("hide_overlay")
            if not results:
                detail = "\n\n" + search.error if search.error else ""
                sublime.error_message(f"File was not found\n\n{filename}{detail}")
                finish_link_search(search, self.view)
            elif len(results) == 1:
                self._select_result(search, window, results, 0, text, line)
            else:
                window.show_quick_panel(
                    [self._format_result(result) for result in results],
                    lambda index: self._select_result(search, window, results, index, text, line),
                )
            return
        self.view.set_status("PlainTasksSearch", f"Searching {filename} in {location}…")
        sublime.set_timeout(lambda: self._poll_search(search, window, filename, text, line), 100)

    def _select_result(self, search, window, results, index, text, line):
        if (
            _unloading
            or index < 0
            or index >= len(results)
            or search.cancelled.is_set()
            or self._search is not search
            or not self.view.is_valid()
            or self.view.window() != window
        ):
            search.cancelled.set()
            finish_link_search(search, self.view)
            return
        filename, row, column, kind = results[index]
        if kind == "d":
            data = window.project_data() or {}
            folders = data.setdefault("folders", [])
            if not any(
                os.path.normcase(os.path.realpath(folder["path"]))
                == os.path.normcase(os.path.realpath(filename))
                for folder in folders
                if "path" in folder
            ):
                folders.append({"path": filename})
                window.set_project_data(data)
            finish_link_search(search, self.view)
        else:
            view = window.open_file(f"{filename}:{row}:{column}", sublime.ENCODED_POSITION)
            if text:
                self.find_text(view, text, line, search=search)
            else:
                finish_link_search(search, self.view)

    def find_text(self, view, text, line, retries=100, search=None):
        if search is not None and (
            _unloading or self._search is not search or search.cancelled.is_set()
        ):
            finish_link_search(search, self.view)
            return
        if not view.is_valid():
            if search is not None:
                finish_link_search(search, self.view)
            return
        if view.is_loading():
            if retries:
                sublime.set_timeout(
                    lambda: self.find_text(view, text, line, retries - 1, search), 50
                )
            elif search is not None:
                finish_link_search(search, self.view)
            return
        result = view.find(text, view.sel()[0].begin() if line else 0, sublime.LITERAL)
        if search is not None:
            finish_link_search(search, self.view)
        if result.begin() < 0:
            sublime.status_message(f"Text was not found: {text}")
            return
        view.sel().clear()
        view.sel().add(result)
        view.show_at_center(result)


class PlainTasksSortByDate(PlainTasksBase):
    DATE = re.compile(r"(?<!\S)@(?:done|cancelled)[ \t]*(\([^()\n]*\))")

    def run_command(self, edit):
        archive = find_archive(self.view, self.archive_name)
        if archive.begin() < 0:
            sublime.status_message("Nothing to sort")
            return
        tasks = []
        for region in self.view.find_by_selector(PlainTasksArchiveCommand.STATES):
            line = self.view.line(region.begin())
            if line.begin() <= archive.end():
                continue
            match = self.DATE.search(self.view.substr(line))
            if not match:
                continue
            try:
                date = datetime.strptime(match.group(1), self.date_format)
            except ValueError:
                continue
            notes = list(following_notes(self.view, line))
            block = sublime.Region(
                line.begin(), self.view.full_line(notes[-1] if notes else line).end()
            )
            tasks.append((date, block, self.view.substr(block)))
        if not tasks:
            return
        for _, block, _ in reversed(tasks):
            self.view.erase(edit, block)
        tasks.sort(key=lambda task: task[0], reverse=self.view.settings().get("new_on_top", True))
        contents = "\n".join(text.removesuffix("\n") for _, _, text in tasks) + "\n"
        point = self.view.full_line(archive).end()
        if point == self.view.size() and not self.view.substr(
            sublime.Region(max(0, point - 1), point)
        ).endswith("\n"):
            contents = "\n" + contents
        self.view.insert(edit, point, contents)
        refresh_tasks(self.view)


class PlainTasksRemoveBold(PlainTasksEnabled):
    MARKUP = re.compile(r"(?<!\S)(\*\*|__)(.*?)\1(?!\w)")

    def run(self, edit, char="*"):
        edits = {}
        for selection in self.view.sel():
            line = self.view.line(selection.begin())
            start, end = selection.begin() - line.begin(), selection.end() - line.begin()
            match = next(
                (
                    match
                    for match in self.MARKUP.finditer(self.view.substr(line))
                    if match.start() <= start and end <= match.end()
                ),
                None,
            )
            if match is None:
                edits[selection.begin(), selection.end()] = char
            else:
                edits[line.begin() + match.start(), line.begin() + match.start() + 2] = ""
                edits[line.begin() + match.end() - 2, line.begin() + match.end()] = ""
        for (start, end), replacement in sorted(edits.items(), reverse=True):
            self.view.replace(edit, sublime.Region(start, end), replacement)


class PlainTasksStatsStatus(sublime_plugin.EventListener):
    DEFAULT_FORMAT = "$n/$a done ($percent%) $progress Last task @done $last"
    SETTINGS = (
        "syntax",
        "stats_format",
        "stats_ignore_archive",
        "archive_name",
        "date_format",
        "bar_full",
        "bar_empty",
    )
    COMPLETED_DATE = re.compile(r"(?<!\S)@done[ \t]*(\([^()\n]*\))")
    _cache = {}

    def on_activated(self, view):
        if view.score_selector(0, "text.todo") > 0:
            self.set_stats(view)
        else:
            view.erase_status("PlainTasks")

    on_post_save = on_activated
    on_load = on_activated

    def on_close(self, view):
        self._cache.pop(view.id(), None)

    @classmethod
    def set_stats(cls, view):
        view.set_status("PlainTasks", cls.get_stats(view))

    @classmethod
    def get_stats(cls, view):
        settings = view.settings()
        signature = (view.change_count(), *(settings.get(key) for key in cls.SETTINGS))
        cached = cls._cache.get(view.id())
        if cached and cached[0] == signature:
            return cached[1]
        message = settings.get("stats_format", cls.DEFAULT_FORMAT)
        limit = view.size()
        if settings.get("stats_ignore_archive", False):
            archive = find_archive(view, settings.get("archive_name", "Archive:"))
            if archive.begin() >= 0:
                limit = archive.begin()
        states = ("pending", "completed", "cancelled")
        groups = {state: set() for state in states}
        for region in view.find_by_selector("meta.item.todo"):
            point = view.line(region).begin()
            if point >= limit:
                continue
            scope = view.scope_name(region.begin())
            state = next((state for state in states if "meta.item.todo." + state in scope), None)
            if state:
                groups[state].add(point)
        for placeholder in set(re.findall(r"{{(.*?)}}", message)):
            try:
                matches = {view.line(match).begin() for match in view.find_all(placeholder)}
            except ValueError, re.error:
                matches = set()
            counts = "/".join(str(len(groups[state] & matches)) for state in states)
            message = message.replace("{{" + placeholder + "}}", counts)
        pending, done, cancelled = (len(groups[state]) for state in states)
        total = pending + done + cancelled
        percent = (done + cancelled) / total * 100 if total else 0
        factor = int(round(percent / 10)) if percent < 90 else int(percent / 10)
        progress = (
            (
                settings.get("bar_full", "■") * factor
                + settings.get("bar_empty", "□") * (10 - factor)
            )
            if factor
            else ""
        )
        last = "(UNKNOWN)"
        latest = None
        if "$last" in message:
            date_format = settings.get("date_format", "(%y-%m-%d %H:%M)")
            for point in groups["completed"]:
                match = cls.COMPLETED_DATE.search(view.substr(view.line(point)))
                if not match:
                    continue
                try:
                    date = datetime.strptime(match.group(1), date_format)
                except ValueError:
                    continue
                if latest is None or date > latest:
                    latest, last = date, match.group(1)
        values = {
            "o": pending,
            "d": done,
            "c": cancelled,
            "n": done + cancelled,
            "a": total,
            "percent": int(percent),
            "progress": progress,
            "last": last,
        }
        message = re.sub(
            r"\$(o|d|c|n|a|percent|progress|last)\b",
            lambda match: str(values[match.group(1)]),
            message,
        )
        cls._cache[view.id()] = signature, message
        return message


class PlainTasksCopyStats(PlainTasksEnabled):
    def run(self, edit):
        msg = PlainTasksStatsStatus.get_stats(self.view)
        replacements = self.view.settings().get("replace_stats_chars", [])
        if replacements:
            for o, r in replacements:
                msg = msg.replace(o, r)

        sublime.set_clipboard(msg)


class PlainTasksArchiveOrgCommand(PlainTasksBase):
    def run_command(self, edit):
        source = self.view.file_name()
        if not source:
            sublime.error_message("Save the task document before archiving to a file")
            return
        filename = self._archive_filename(source)
        if os.path.normcase(os.path.realpath(filename)) == os.path.normcase(
            os.path.realpath(source)
        ):
            sublime.error_message("The archive filename must differ from the task document")
            return
        region = self._current_subtree()
        data = (
            "--- ✄ -----------------------\nArchived "
            + tznow().strftime(self.date_format)
            + ":\n"
            + self.view.substr(region).removesuffix("\n")
            + "\n"
        )
        try:
            with open(filename, "a", encoding="utf-8", newline="\n") as archive:
                archive.write(data)
        except OSError as error:
            sublime.error_message(f"Unable to append to {filename}\n{error}")
            return
        self.view.erase(edit, region)
        sublime.status_message(f"Archived tree to {filename}")
        refresh_tasks(self.view)

    def _archive_filename(self, source):
        path_base, extension = os.path.splitext(source)
        directory, base = os.path.split(path_base)
        parameters = {"dir": directory, "base": base, "ext": extension, "sep": os.sep}
        try:
            filename = self.archive_org_filemask.format(**parameters)
            if not filename.strip():
                raise ValueError("The filemask is empty")
        except KeyError, IndexError, ValueError:
            sublime.error_message(
                f"Invalid archive filemask: {self.archive_org_filemask}\nUsing {self.archive_org_default_filemask}"
            )
            filename = self.archive_org_default_filemask.format(**parameters)
        filename = os.path.expanduser(filename)
        return filename if os.path.isabs(filename) else os.path.join(directory, filename)

    def _current_subtree(self):
        line = self.view.full_line(self.view.sel()[0].begin())
        if line.end() < self.view.size() and self.view.indentation_level(
            line.end()
        ) > self.view.indentation_level(line.begin()):
            subtree = self.view.indented_region(line.end())
            return sublime.Region(line.begin(), max(line.end(), subtree.end()))
        return line


class PlainTasksFoldToTags(PlainTasksFold):
    TAG = r"(?u)@\w+"

    def run(self, edit):
        tag_sels = [s for s in list(self.view.sel()) if "tag.todo" in self.view.scope_name(s.a)]
        if not tag_sels:
            sublime.status_message("Cursor(s) must be placed on tag(s)")
            return

        tags = self.extract_tags(tag_sels)
        pattern = r"[ \t](?:" + "|".join(re.escape(tag) for tag in tags) + r")\b"
        tasks = [
            self.view.line(region)
            for region in self.view.find_all(pattern)
            if "pending" in self.view.scope_name(region.begin())
        ]
        if not tasks:
            sublime.status_message("Pending tasks with given tags are not found")
            return
        self.exec_folding(self.add_projects_and_notes(tasks))

    def extract_tags(self, tag_sels):
        tags = set()
        for selection in tag_sels:
            line = self.view.line(selection.begin())
            offset = selection.begin() - line.begin()
            for match in re.finditer(self.TAG, self.view.substr(line)):
                if match.start() <= offset <= match.end():
                    tags.add(match.group())
                    break
        return sorted(tags)


class PlainTasksAddGutterIconsForTags(sublime_plugin.EventListener):
    TAGS = ("critical", "high", "low", "today")
    _cache = {}

    def on_activated(self, view):
        icons = tuple(view.settings().get("icon_" + tag, "") for tag in self.TAGS)
        signature = (view.change_count(), icons, view.score_selector(0, "text.todo") > 0)
        if self._cache.get(view.id()) == signature:
            return
        self._cache[view.id()] = signature
        for tag, icon in zip(self.TAGS, icons, strict=True):
            if signature[-1] and icon:
                scope = "string.other.tag.todo." + tag
                regions = view.find_by_selector(scope)
                view.add_regions(tag, regions, scope, icon, sublime.HIDDEN)
            else:
                view.erase_regions(tag)

    on_post_save = on_activated
    on_load = on_activated

    def on_close(self, view):
        self._cache.pop(view.id(), None)


class PlainTasksHover(sublime_plugin.ViewEventListener):
    """Show popup with actions when hover over bullet"""

    msg = (
        "<style>"  # four curly braces because it will be modified with format method twice
        "html {{{{background-color: color(var(--background) blenda(white 75%))}}}}"
        "body {{{{margin: .1em .3em}}}}"
        "p {{{{margin: .5em 0}}}}"
        "a {{{{text-decoration: none}}}}"
        "span.icon {{{{font-weight: bold; font-size: 1.3em}}}}"
        "#icon-done {{{{color: var(--greenish)}}}}"
        "#icon-cancel {{{{color: var(--redish)}}}}"
        "#icon-archive {{{{color: var(--bluish)}}}}"
        "#icon-outside {{{{color: var(--purplish)}}}}"
        "#done {{{{color: var(--greenish)}}}}"
        "#cancel {{{{color: var(--redish)}}}}"
        "#archive {{{{color: var(--bluish)}}}}"
        "#outside {{{{color: var(--purplish)}}}}"
        "</style><body>"
        "{actions}"
    )

    complete = '<a href="complete\v{point}"><span class="icon" id="icon-done">✔</span> <span id="done">Toggle complete</span></a>'
    cancel = '<a href="cancel\v{point}"><span class="icon" id="icon-cancel">✘</span> <span id="cancel">Toggle cancel</span></a>'
    archive = '<a href="archive\v{point}"><span class="icon" id="icon-archive">📚</span> <span id="archive">Archive</span></a>'
    archivetofile = '<a href="tofile\v{point}"><span class="icon" id="icon-outside">📤</span> <span id="outside">Archive to file</span></a>'

    actions = {
        "text.todo meta.item.todo.pending": f"<p>{complete}</p><p>{cancel}</p>",
        "text.todo meta.item.todo.completed": f"<p>{archive}</p><p>{archivetofile}</p><p>{complete}</p>",
        "text.todo meta.item.todo.cancelled": f"<p>{archive}</p><p>{archivetofile}</p><p>{complete}</p><p>{cancel}</p>",
    }

    @classmethod
    def is_applicable(cls, settings):
        return settings.get("syntax") == "Packages/PlainTasks/PlainTasks.sublime-syntax"

    def on_hover(self, point, hover_zone):
        self.view.hide_popup()
        if hover_zone != sublime.HOVER_TEXT:
            return

        line = self.view.line(point)
        line_scope_name = self.view.scope_name(line.a).strip()
        if "meta.item.todo" not in line_scope_name:
            return

        bullet = any("bullet" in self.view.scope_name(p) for p in (point, point - 1))
        if not bullet:
            return

        width, height = self.view.viewport_extent()
        actions = next(
            (value for scope, value in self.actions.items() if scope in line_scope_name), ""
        )
        self.view.show_popup(
            self.msg.format(actions=actions).format(point=point),
            0,
            point,
            int(width),
            int(height / 2),
            self.exec_action,
        )

    def exec_action(self, msg):
        action, at = msg.split("\v")

        case = {
            "complete": lambda: self.view.run_command("plain_tasks_complete"),
            "cancel": lambda: self.view.run_command("plain_tasks_cancel"),
            "archive": lambda: self.view.run_command("plain_tasks_archive", {"partial": True}),
            "tofile": lambda: self.view.run_command("plain_tasks_archive_org"),
        }
        self.view.sel().clear()
        self.view.sel().add(sublime.Region(int(at)))
        case[action]()
        self.view.hide_popup()


class PlainTasksGotoTag(PlainTasksEnabled):
    SELECTOR = "meta.tag.todo, string.other.tag.todo.critical, string.other.tag.todo.high, string.other.tag.todo.low, string.other.tag.todo.today"

    def run(self, edit):
        self.initial_viewport = self.view.viewport_position()
        self.initial_sels = list(self.view.sel())
        regions = {
            (region.begin(), region.end())
            for region in self.view.find_by_selector(self.SELECTOR)
            if not any(
                state in self.view.scope_name(region.begin())
                for state in ("completed", "cancelled")
            )
        }
        self.tags = [sublime.Region(start, end) for start, end in sorted(regions)]
        if not self.tags:
            sublime.status_message("No tags in pending tasks")
            return
        window = self.view.window()
        if not window:
            return
        items = [
            [
                self.view.substr(tag),
                f"{self.view.rowcol(tag.begin())[0] + 1}: {self.view.substr(self.view.line(tag)).strip()}",
            ]
            for tag in self.tags
        ]
        closest = bisect_left(
            [tag.begin() for tag in self.tags], self.view.layout_to_text(self.initial_viewport)
        )
        window.show_quick_panel(
            items, self.on_done, 0, min(closest, len(self.tags) - 1), self.on_highlighted
        )

    def on_done(self, index):
        if not self.view.is_valid():
            return
        self.view.sel().clear()
        if index < 0 or index >= len(self.tags):
            self.view.sel().add_all(self.initial_sels)
            self.view.set_viewport_position(self.initial_viewport)
        else:
            self.view.sel().add(sublime.Region(self.tags[index].begin()))
            self.view.show_at_center(self.tags[index])

    def on_highlighted(self, index):
        if self.view.is_valid() and 0 <= index < len(self.tags):
            self.view.sel().clear()
            self.view.sel().add(self.tags[index])
            self.view.show(self.tags[index], True)
