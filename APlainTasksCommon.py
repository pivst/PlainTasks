"""Shared task settings and context-aware folding commands."""

import re

import sublime
import sublime_plugin


def _ordered_regions(regions):
    """Normalize and deduplicate regions without relying on Region hashing."""
    return [
        sublime.Region(start, end)
        for start, end in sorted({(region.begin(), region.end()) for region in regions})
    ]


def get_all_projects_and_separators(view):
    # Header scopes include their newline and may span several lines.
    projects = [
        line
        for region in view.find_by_selector("keyword.control.header.todo")
        for line in view.lines(region)
        if not line.empty()
    ]
    separators = [
        view.line(region) for region in view.find_by_selector("meta.punctuation.separator.todo")
    ]
    return _ordered_regions(projects + separators)


def find_archive(view, name):
    """Find a complete archive heading, avoiding labels mentioned in task text."""
    return view.find(r"^[ \t]*" + re.escape(name.strip()) + r"[ \t]*$", 0)


class PlainTasksEnabled(sublime_plugin.TextCommand):
    def is_enabled(self, **kwargs):
        return self.view.score_selector(0, "text.todo") > 0

    is_visible = is_enabled


class PlainTasksBase(PlainTasksEnabled):
    def run(self, edit, **kwargs):
        settings = self.view.settings()
        self.taskpaper_compatible = settings.get("taskpaper_compatible", False)
        spaces = settings.get("translate_tabs_to_spaces", False)
        if self.taskpaper_compatible:
            self.open_tasks_bullet = self.done_tasks_bullet = self.canc_tasks_bullet = "-"
            self.before_date_space = ""
        else:
            self.open_tasks_bullet = settings.get("open_tasks_bullet", "☐")
            self.done_tasks_bullet = settings.get("done_tasks_bullet", "✔")
            self.canc_tasks_bullet = settings.get("cancelled_tasks_bullet", "✘")
            self.before_date_space = settings.get("before_date_space", " ")

        self.before_tasks_bullet_spaces = (
            " " * settings.get("before_tasks_bullet_margin", 1)
            if not self.taskpaper_compatible and spaces
            else "\t"
        )
        self.tasks_bullet_space = settings.get(
            "tasks_bullet_space", " " if self.taskpaper_compatible or spaces else "\t"
        )
        self.date_format = settings.get("date_format", "(%y-%m-%d %H:%M)")
        tags = settings.get("done_tag", True) or self.taskpaper_compatible
        self.done_tag, self.canc_tag = ("@done", "@cancelled") if tags else ("", "")
        self.done_date = settings.get("done_date", True)
        self.project_postfix = settings.get("project_tag", True)
        self.archive_name = settings.get("archive_name", "Archive:")
        self.archive_org_default_filemask = "{dir}{sep}{base}_archive{ext}"
        self.archive_org_filemask = settings.get(
            "archive_org_filemask", self.archive_org_default_filemask
        )
        self.run_command(edit, **kwargs)

    def format_line_end(self, tag: str, tznow) -> tuple[str, str]:
        date = tznow.strftime(self.date_format)
        suffix = f" {tag}{self.before_date_space}{date if self.done_date else ''}"
        return suffix.replace("  ", " ").rstrip(), date


class PlainTasksFold(PlainTasksEnabled):
    def exec_folding(self, visible_regions):
        size = self.view.size()
        self.view.unfold(sublime.Region(0, size))
        if not visible_regions:
            return
        point = 0
        for region in _ordered_regions(visible_regions):
            # Leave the newline on either side of a visible line unfolded.
            start = min(size, max(0, region.begin()))
            end = min(size, max(start, region.end()))
            if point < start - 1:
                self.view.fold(sublime.Region(point, start - 1))
            point = max(point, end + 1)
        if point < size:
            self.view.fold(sublime.Region(point, size))

    def add_projects_and_notes(self, task_regions):
        """Keep the selected tasks, ancestor headers, and following notes visible."""
        tasks = _ordered_regions(task_regions)
        if not tasks:
            return []
        visible = {(region.begin(), region.end()) for region in tasks}
        size = self.view.size()

        def add_notes(region):
            point = region.end() + 1
            while point < size and self.view.match_selector(point, "notes.todo"):
                note = self.view.line(point)
                visible.add((note.begin(), note.end()))
                point = note.end() + 1

        # Compute each project's indentation block once. The ordered sweep then
        # considers only still-open ancestors, rather than rescanning all prior
        # headers for every matching task.
        projects = get_all_projects_and_separators(self.view)
        active = []
        index = 0
        for task in tasks:
            add_notes(task)
            while index < len(projects) and projects[index].begin() < task.begin():
                project = projects[index]
                active.append((project, self.view.indented_region(project.end() + 1)))
                index += 1
            active = [(project, block) for project, block in active if block.end() >= task.end()]
            task_block = self.view.indented_region(task.begin())
            for project, block in active:
                key = (project.begin(), project.end())
                if key not in visible and block.contains(task_block):
                    visible.add(key)
                    add_notes(project)
        return [sublime.Region(start, end) for start, end in sorted(visible)]
