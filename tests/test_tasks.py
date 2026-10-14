"""Task editing, archive integrity, link cancellation and scan regressions."""

import itertools
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import patch

import sublime
from PlainTasks.tests.support.sublime_stub import Region, View, Window

from PlainTasks import PlainTasks as tasks


class TaskView(View):
    ids = itertools.count(1)

    def __init__(self, text="", settings=None):
        super().__init__(text, settings)
        self._id = next(self.ids)
        self.revision = 0
        self.selector_calls = []
        self.regex_calls = []
        self.status = {}
        self.scopes = {}
        self.region_calls = []
        self.valid = True
        self.viewport = (0, 0)

    def id(self):
        return self._id

    def change_count(self):
        return self.revision

    def is_valid(self):
        return self.valid

    def is_loading(self):
        return False

    def scope_name(self, point):
        return self.scopes.get(self.line(point).begin(), super().scope_name(point))

    def full_line(self, point):
        line = self.line(point)
        return Region(line.begin(), min(line.end() + 1, self.size()))

    def indentation_level(self, point):
        indent = re.match(r"[ \t]*", self.substr(self.line(point))).group()
        return len(indent.expandtabs(4))

    def indented_region(self, point):
        if point >= self.size():
            return Region(point)
        first = self.line(point)
        level = self.indentation_level(first.begin())
        end = self.full_line(point).end()
        while end < self.size():
            line = self.line(end)
            if self.substr(line).strip() and self.indentation_level(end) < level:
                break
            end = self.full_line(end).end()
        return Region(first.begin(), end)

    def find(self, pattern, start, flags=0):
        matches = self.find_all(pattern, flags)
        return next((region for region in matches if region.begin() >= start), Region(-1))

    def find_all(self, pattern, flags=0):
        self.regex_calls.append(pattern)
        pattern = re.escape(pattern) if flags & sublime.LITERAL else pattern
        return [
            Region(match.start(), match.end()) for match in re.finditer(pattern, self.text, re.M)
        ]

    def find_by_selector(self, selector):
        self.selector_calls.append(selector)
        result = []
        for line in self.lines(Region(0, self.size())):
            scope = self.scope_name(line.begin())
            if any(term.strip() in scope for term in selector.split(",")):
                result.append(line)
        return result

    def set_status(self, key, message):
        self.status[key] = message

    def erase_status(self, key):
        self.status.pop(key, None)

    def add_regions(self, *args):
        self.region_calls.append(("add", args))

    def erase_regions(self, *args):
        self.region_calls.append(("erase", args))

    def _track(self, region, replacement):
        start, end = region.begin(), region.end()
        delta = len(replacement) - (end - start)

        def move(point):
            if point >= end:
                return point + delta
            if point > start:
                return start + min(point - start, len(replacement))
            return point

        positions = [Region(move(selection.a), move(selection.b)) for selection in self.sel()]
        self.sel().clear()
        self.sel().add_all(positions)
        self.revision += 1

    def replace(self, edit, region, text):
        self._track(region, text)
        super().replace(edit, region, text)

    def insert(self, edit, point, text):
        self._track(Region(point), text)
        return super().insert(edit, point, text)

    def erase(self, edit, region):
        self.replace(edit, region, "")

    def viewport_position(self):
        return self.viewport

    def set_viewport_position(self, point):
        self.viewport = point

    def layout_to_text(self, point):
        return 0

    def show_at_center(self, region):
        self.shown = region

    def show(self, region, animate=False):
        self.shown = region


class TaskWindow(Window):
    def __init__(self):
        super().__init__()
        self.panels = []
        self.opened = []
        self.data = {}
        self.locations = []
        self.symbol_queries = []

    def folders(self):
        return []

    def views(self):
        return []

    def symbol_locations(self, symbol, *, source, type):
        self.symbol_queries.append((symbol, source, type))
        return self.locations

    def show_quick_panel(self, *args):
        self.panels.append(args)

    def project_data(self):
        return self.data

    def set_project_data(self, data):
        self.data = data

    def open_file(self, filename, flags):
        self.opened.append(filename)
        return TaskView()


@skipUnless(getattr(sublime, "_plaintasks_test_stub", False), "Standalone task API doubles")
class TestTaskEditing(TestCase):
    def setUp(self):
        refresh = patch.object(tasks, "refresh_tasks")
        refresh.start()
        self.addCleanup(refresh.stop)

    def test_overlapping_selections_complete_each_line_once(self):
        view = TaskView(" ☐ first\n ☐ second", {"done_date": False})
        view.sel().add(Region(2))
        view.sel().add(Region(0, view.size()))
        tasks.PlainTasksCompleteCommand(view).run(view.edit)
        self.assertEqual(view.text, " ✔ first @done\n ✔ second @done")

    def test_round_trip_keeps_other_tags_and_markdown_line_break(self):
        original = " ☐ task (design) @high @due(26-10-30 10:00) @created(26-10-14 10:00)  "
        for command in (tasks.PlainTasksCompleteCommand, tasks.PlainTasksCancelCommand):
            with self.subTest(command=command.__name__):
                view = TaskView(original)
                editor = command(view)
                editor.run(view.edit)
                editor.run(view.edit)
                self.assertEqual(view.text, original)

    def test_mixed_selections_reopen_and_complete_without_losing_cursors(self):
        view = TaskView(" ☐ first\n ✔ second @done\n note", {"done_date": False})
        view.sel().clear()
        view.sel().add_all([Region(3), Region(13), Region(27)])
        tasks.PlainTasksCompleteCommand(view).run(view.edit)
        self.assertEqual(view.text, " ✔ first @done\n ☐ second\n note")
        self.assertEqual([view.rowcol(region.begin())[0] for region in view.sel()], [0, 1, 2])

    def test_completed_task_cannot_be_cancelled(self):
        original = " ✔ task @done(26-10-14 10:00)"
        view = TaskView(original)
        tasks.PlainTasksCancelCommand(view).run(view.edit)
        self.assertEqual(view.text, original)

    def test_date_only_completion_can_be_reopened(self):
        view = TaskView(" ☐ task", {"done_tag": False})
        command = tasks.PlainTasksCompleteCommand(view)
        command.run(view.edit)
        self.assertNotIn("@done", view.text)
        command.run(view.edit)
        self.assertEqual(view.text, " ☐ task")

    def test_new_task_deduplicates_lines_and_positions_cursors_at_end(self):
        view = TaskView("first\nsecond", {"translate_tabs_to_spaces": True})
        view.sel().add_all([Region(2), Region(0, view.size())])
        tasks.PlainTasksNewCommand(view).run(view.edit)
        self.assertEqual(view.text, " ☐ first\n ☐ second")
        self.assertEqual([selection.begin() for selection in view.sel()], [8, view.size()])

    def test_high_priority_and_custom_date_format_sort_with_notes(self):
        text = (
            "Project:\n ☐ later @due(02/11/2026 10:00)\n"
            " ☐ normal @due(30/10/2026 10:00)\n"
            " ☐ high @high @due(30/10/2026 10:00)  \n  a note\n"
            " ☐ no date"
        )
        view = TaskView(text, {"date_format": "(%d/%m/%Y %H:%M)"})
        tasks.PlainTasksSortByDueDateAndPriorityCommand(view).run(view.edit)
        self.assertLess(view.text.index("high @high"), view.text.index("normal @due"))
        self.assertLess(view.text.index("normal @due"), view.text.index("later @due"))
        self.assertIn("10:00)  \n  a note\n", view.text)
        self.assertTrue(view.text.endswith(" ☐ no date"))

    def test_relative_due_dates_are_sorted_before_later_dates(self):
        view = TaskView("Project:\n ☐ later @due(+2w)\n ☐ sooner @due(+1d)")
        tasks.PlainTasksSortByDueDateAndPriorityCommand(view).run(view.edit)
        self.assertLess(view.text.index("sooner"), view.text.index("later"))

    def test_reopened_task_discards_previous_elapsed_totals(self):
        view = TaskView(" ✔ task @done(26-10-14 10:00) @lasted(1:30) @total(2:00)")
        tasks.PlainTasksCompleteCommand(view).run(view.edit)
        self.assertEqual(view.text, " ☐ task")

    def test_task_mentioning_archive_label_does_not_hide_later_tasks(self):
        view = TaskView(" ☐ Write Archive: section\n ✔ complete @done(26-10-14 10:00)")
        tasks.PlainTasksArchiveCommand(view).run(view.edit)
        self.assertEqual(view.text.count("complete"), 1)
        self.assertIn("\nArchive:\n", view.text)
        self.assertLess(view.text.index("\nArchive:\n"), view.text.index("complete"))

    def test_project_containing_only_notes_is_unchanged_when_sorted(self):
        text = "Project:\n  notes only"
        view = TaskView(text)
        tasks.PlainTasksSortByDueDateAndPriorityCommand(view).run(view.edit)
        self.assertEqual(view.text, text)

    def test_archive_includes_last_project_and_note_at_eof_once(self):
        view = TaskView("Project:\n ✔ complete @done(26-10-14 10:00)\n  EOF note")
        tasks.PlainTasksArchiveCommand(view).run(view.edit)
        self.assertEqual(view.text.count("EOF note"), 1)
        self.assertIn("@project(Project)", view.text)
        self.assertLess(view.text.index("Archive:"), view.text.index("complete"))

    def test_archive_at_start_is_recognised_and_not_recreated(self):
        original = "Archive:\n ✔ old @done(26-10-14 10:00)"
        view = TaskView(original)
        tasks.PlainTasksArchiveCommand(view).run(view.edit)
        self.assertEqual(view.text, original)

    def test_archive_sort_uses_dates_and_retains_trailing_note(self):
        view = TaskView(
            "Archive:\n ✔ newer @done(02/11/2026 10:00)\n"
            " ✔ older @done(30/10/2026 10:00)\n  old note",
            {"date_format": "(%d/%m/%Y %H:%M)"},
        )
        tasks.PlainTasksSortByDate(view).run(view.edit)
        self.assertLess(view.text.index("newer"), view.text.index("older"))
        self.assertEqual(view.text.count("old note"), 1)
        self.assertEqual(view.text.count("Archive:"), 1)

    def test_org_archive_requires_saved_document(self):
        view = TaskView(" ☐ task")
        with patch.object(tasks.sublime, "error_message") as error:
            tasks.PlainTasksArchiveOrgCommand(view).run(view.edit)
        self.assertEqual(view.text, " ☐ task")
        self.assertIn("Save", error.call_args.args[0])

    def test_org_archive_writes_subtree_and_keeps_sibling(self):
        with tempfile.TemporaryDirectory() as directory:
            view = TaskView("Project:\n ☐ child\nSibling:\n ☐ keep")
            view._filename = str(Path(directory) / "source.todo")
            tasks.PlainTasksArchiveOrgCommand(view).run(view.edit)
            archived = (Path(directory) / "source_archive.todo").read_text()
        self.assertIn("Project:\n ☐ child\n", archived)
        self.assertEqual(view.text, "Sibling:\n ☐ keep")

    def test_org_archive_failure_keeps_original_task(self):
        view = TaskView(" ☐ task")
        view._filename = "/source.todo"
        with patch("builtins.open", side_effect=OSError("read only")):
            tasks.PlainTasksArchiveOrgCommand(view).run(view.edit)
        self.assertEqual(view.text, " ☐ task")

    def test_org_archive_cannot_append_to_its_source(self):
        view = TaskView(" ☐ task", {"archive_org_filemask": "{dir}{sep}{base}{ext}"})
        view._filename = "/source.todo"
        with patch("builtins.open") as write:
            tasks.PlainTasksArchiveOrgCommand(view).run(view.edit)
        write.assert_not_called()
        self.assertEqual(view.text, " ☐ task")

    def test_toggle_bold_at_cursor_preserves_every_content_character(self):
        view = TaskView(" ☐ **abcdef** @work")
        view.sel().clear()
        view.sel().add(Region(8))
        tasks.PlainTasksRemoveBold(view).run(view.edit)
        self.assertEqual(view.text, " ☐ abcdef @work")

    def test_toggle_bold_with_overlapping_selections_removes_delimiters_once(self):
        view = TaskView(" ☐ __abcdef__")
        view.sel().clear()
        view.sel().add_all([Region(5, 8), Region(6)])
        tasks.PlainTasksRemoveBold(view).run(view.edit, char="_")
        self.assertEqual(view.text, " ☐ abcdef")

    def test_empty_bold_toggle_removes_only_the_paired_delimiters(self):
        for markup, char in (("****", "*"), ("____", "_")):
            view = TaskView(" ☐ " + markup)
            view.sel().clear()
            view.sel().add(Region(5))
            tasks.PlainTasksRemoveBold(view).run(view.edit, char=char)
            self.assertEqual(view.text, " ☐ ")

    def test_missing_bold_delimiters_inserts_requested_character(self):
        view = TaskView(" ☐ abcdef")
        view.sel().clear()
        view.sel().add(Region(6))
        tasks.PlainTasksRemoveBold(view).run(view.edit, char="_")
        self.assertEqual(view.text, " ☐ abc_def")


@skipUnless(getattr(sublime, "_plaintasks_test_stub", False), "Standalone task API doubles")
class TestStatsAndTags(TestCase):
    def setUp(self):
        tasks.PlainTasksStatsStatus._cache.clear()
        tasks.PlainTasksAddGutterIconsForTags._cache.clear()

    def test_stats_use_one_scan_and_cache_until_edit_or_setting_change(self):
        view = TaskView("\n".join(" ☐ task" for _ in range(1000)), {"stats_format": "$o/$a"})
        self.assertEqual(tasks.PlainTasksStatsStatus.get_stats(view), "1000/1000")
        for _ in range(10):
            self.assertEqual(tasks.PlainTasksStatsStatus.get_stats(view), "1000/1000")
        self.assertEqual(len(view.selector_calls), 1)
        self.assertEqual(view.regex_calls, [])
        view.replace(view.edit, Region(0, view.line(0).end()), " ✔ task @done(26-10-14 10:00)")
        self.assertEqual(tasks.PlainTasksStatsStatus.get_stats(view), "999/1000")
        view.settings().set("stats_format", "$d/$a")
        self.assertEqual(tasks.PlainTasksStatsStatus.get_stats(view), "1/1000")
        self.assertEqual(len(view.selector_calls), 3)

    def test_stats_ignore_archive_for_counts_tags_and_last_date(self):
        view = TaskView(
            " ☐ task @high @high\n ✔ done @done(30/10/2026 10:00)\n"
            "Archive:\n ✔ archived @high @done(02/11/2026 10:00)",
            {
                "stats_ignore_archive": True,
                "date_format": "(%d/%m/%Y %H:%M)",
                "stats_format": "$o/$d/$c {{@high}} $last",
            },
        )
        self.assertEqual(
            tasks.PlainTasksStatsStatus.get_stats(view), "1/1/0 1/0/0 (30/10/2026 10:00)"
        )
        view.settings().set("stats_ignore_archive", False)
        self.assertEqual(
            tasks.PlainTasksStatsStatus.get_stats(view), "1/2/0 1/1/0 (02/11/2026 10:00)"
        )

    def test_stats_ignore_only_real_archive_header(self):
        view = TaskView(
            " ☐ Write Archive: section\n ✔ complete @done(26-10-14 10:00)",
            {"stats_format": "$o/$d", "stats_ignore_archive": True},
        )
        self.assertEqual(tasks.PlainTasksStatsStatus.get_stats(view), "1/1")

    def test_stats_invalid_timestamps_do_not_replace_unknown_with_empty_string(self):
        view = TaskView(" ✔ done @done(not a date)", {"stats_format": "$last"})
        self.assertEqual(tasks.PlainTasksStatsStatus.get_stats(view), "(UNKNOWN)")

    def test_status_cache_is_cleaned_when_view_closes(self):
        view = TaskView(" ☐ task")
        tasks.PlainTasksStatsStatus.get_stats(view)
        tasks.PlainTasksStatsStatus().on_close(view)
        self.assertNotIn(view.id(), tasks.PlainTasksStatsStatus._cache)

    def test_gutter_scans_only_enabled_icons_and_reuses_results(self):
        view = TaskView(" ☐ task @high", {"icon_high": "dot"})
        listener = tasks.PlainTasksAddGutterIconsForTags()
        listener.on_activated(view)
        listener.on_post_save(view)
        self.assertEqual(view.selector_calls, ["string.other.tag.todo.high"])
        view.settings().set("icon_high", "")
        listener.on_activated(view)
        self.assertEqual(view.region_calls[-3][0], "erase")

    def test_tag_extraction_terminates_at_buffer_start_and_end(self):
        view = TaskView("@high task @foobar")
        result = tasks.PlainTasksFoldToTags(view).extract_tags([Region(0), Region(view.size())])
        self.assertEqual(result, ["@foobar", "@high"])

    def test_goto_tag_without_tags_keeps_selection(self):
        view = TaskView(" ☐ task")
        view._window = window = TaskWindow()
        tasks.PlainTasksGotoTag(view).run(view.edit)
        self.assertEqual(window.panels, [])
        self.assertEqual(view.sel(), [Region(0)])

    def test_goto_tag_ignores_negative_preview_index(self):
        view = TaskView("@high")
        command = tasks.PlainTasksGotoTag(view)
        command.tags = [Region(0, 5)]
        command.on_highlighted(-1)
        self.assertEqual(view.sel(), [Region(0)])


@skipUnless(getattr(sublime, "_plaintasks_test_stub", False), "Standalone task API doubles")
class TestLinks(TestCase):
    def setUp(self):
        tasks._active_searches.clear()
        tasks.plugin_loaded()
        self.addCleanup(tasks.plugin_loaded)

    def test_all_documented_file_link_forms(self):
        command = tasks.PlainTasksOpenLinkCommand(TaskView())
        cases = [
            (".\\another filename\\", ("another filename", None, 0, 0, None)),
            (r".\filename:11:8", ("filename", None, "11", "8", None)),
            (r".\filename>symbol", ("filename", "symbol", 0, 0, None)),
            (r'.\filename"any text"', ("filename", None, 0, 0, "any text")),
            ("[](path)", ("path", None, 0, 0, None)),
            ('[](path ":11:8")', ("path", None, "11", "8", None)),
            ('[](path ">symbol")', ("path", "symbol", 0, 0, None)),
            ('[](path "any text")', ("path", None, 0, 0, "any text")),
            ("[[path::11:8]]", ("path", None, "11", "8", None)),
            ("[[path::*symbol]]", ("path", "symbol", 0, 0, None)),
            ("[[path::any text]]", ("path", None, 0, 0, "any text")),
            ('[[path]] ":11:8"', ("path", None, "11", "8", None)),
            ('[[path]] ">symbol"', ("path", "symbol", 0, 0, None)),
            ('[[path]] "any text"', ("path", None, 0, 0, "any text")),
            ("[[path][description]]", ("path", None, 0, 0, None)),
            (
                "[name](path(with parentheses).todo)",
                ("path(with parentheses).todo", None, 0, 0, None),
            ),
            (r"[[path\[with brackets\].todo]]", ("path[with brackets].todo", None, 0, 0, None)),
        ]
        for contents, expected in cases:
            with self.subTest(contents=contents):
                self.assertEqual(command.parse_link(contents), expected)

    def test_file_uri_decodes_spaces_and_windows_drive(self):
        command = tasks.PlainTasksOpenLinkCommand(TaskView())
        with patch.object(tasks, "NT", True):
            self.assertEqual(
                command.parse_link("[name](<file:///C:/中文%20目录/file.todo>)")[0],
                "C:/中文 目录/file.todo",
            )
            self.assertEqual(
                command.parse_link("[[file://server/share/file.todo]]")[0],
                "//server/share/file.todo",
            )

    def test_unclosed_links_have_bounded_work_even_on_long_lines(self):
        command = tasks.PlainTasksOpenLinkCommand(TaskView())
        for contents in ("[](a" + "x" * 30000, "[[a" + "x" * 30000):
            self.assertEqual(command.parse_link(contents), (None, None, 0, 0, None))

    def test_unclosed_url_scope_does_not_scan_outside_line(self):
        view = TaskView(" ☐ <https://example.com")
        view.scope = "text.todo markup.underline.link.todo.url "
        view.sel().clear()
        view.sel().add(Region(8))
        with patch.object(tasks, "open_external_url") as launch:
            tasks.PlainTasksOpenUrlCommand(view).run(view.edit)
        launch.assert_called_once_with("https://example.com")

    def test_bare_url_under_cursor_preserves_parentheses_and_query(self):
        view = TaskView("See https://example.com/path_(name)?a=1&b=2. Next")
        view.sel().clear()
        view.sel().add(Region(15))
        with patch.object(tasks, "open_external_url") as launch:
            tasks.PlainTasksOpenUrlCommand(view).run(view.edit)
        launch.assert_called_once_with("https://example.com/path_(name)?a=1&b=2")

    def test_url_detection_is_linear_for_malformed_punctuation(self):
        view = TaskView("https://" + "." * 30000)
        with patch.object(tasks, "open_external_url") as launch:
            tasks.PlainTasksOpenUrlCommand(view).run(view.edit)
        launch.assert_not_called()

    def test_wrapped_url_keeps_balanced_parentheses_and_trims_punctuation(self):
        view = TaskView("[link](https://example.com/a_(b(c))).")
        view.sel().clear()
        view.sel().add(Region(12))
        with patch.object(tasks, "open_external_url") as launch:
            tasks.PlainTasksOpenUrlCommand(view).run(view.edit)
        launch.assert_called_once_with("https://example.com/a_(b(c))")

    def test_link_search_text_can_contain_unbalanced_parentheses(self):
        command = tasks.PlainTasksOpenLinkCommand(TaskView())
        self.assertEqual(
            command.parse_link('[Notes](notes.txt "a)b(")'), ("notes.txt", None, 0, 0, "a)b(")
        )

    def test_absolute_path_does_not_walk_project(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "target.todo"
            file.write_text("task")
            search = tasks.LinkSearch()
            with patch.object(
                tasks.os, "walk", side_effect=AssertionError("Absolute links must not walk")
            ):
                tasks.search_files(search, [directory], str(file), 12, 3)
        self.assertEqual(search.results, [(str(file), 12, 3, "f")])
        self.assertTrue(search.done.is_set())

    def test_overlapping_project_folders_do_not_duplicate_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            child = Path(directory) / "child"
            child.mkdir()
            file = child / "target.todo"
            file.write_text("task")
            search = tasks.LinkSearch()
            tasks.search_files(search, [directory, str(child), directory], "target.todo")
        self.assertEqual(search.results, [(str(file), 0, 0, "f")])

    def test_cancelling_worker_prevents_filesystem_scan(self):
        search = tasks.LinkSearch()
        search.cancelled.set()
        with patch.object(tasks.os, "walk", side_effect=AssertionError("Cancelled work must stop")):
            tasks.search_files(search, ["/large/project"], "target.todo")
        self.assertEqual(search.results, [])
        self.assertTrue(search.done.is_set())

    def test_restarting_search_does_not_join_background_thread(self):
        view = TaskView("no link")
        command = tasks.PlainTasksOpenLinkCommand(view)
        previous = command._search = tasks.LinkSearch()

        class RunningThread:
            def join(self):
                raise AssertionError("UI thread must not block waiting for filesystem I/O")

        command.thread = RunningThread()
        command.run(view.edit)
        self.assertTrue(previous.cancelled.is_set())

    def test_cancelled_or_stale_result_never_opens_file(self):
        view = TaskView()
        window = TaskWindow()
        command = tasks.PlainTasksOpenLinkCommand(view)
        search = command._search = tasks.LinkSearch()
        search.cancelled.set()
        command._select_result(search, window, [("target.todo", 1, 1, "f")], 0, None, 0)
        search.cancelled.clear()
        command._search = tasks.LinkSearch()
        command._select_result(search, window, [("target.todo", 1, 1, "f")], 0, None, 0)
        self.assertEqual(window.opened, [])

    def test_missing_search_text_keeps_current_selection(self):
        view = TaskView("contents")
        original = list(view.sel())
        tasks.PlainTasksOpenLinkCommand(view).find_text(view, "not present", 0)
        self.assertEqual(view.sel(), original)

    def test_selected_result_opens_in_originating_window(self):
        view = TaskView()
        window = TaskWindow()
        command = tasks.PlainTasksOpenLinkCommand(view)
        search = command._search = tasks.LinkSearch()
        view._window = window
        command._select_result(search, window, [("target.todo", 12, 3, "f")], 0, None, 0)
        self.assertEqual(window.opened, ["target.todo:12:3"])

    def test_symbol_location_uses_current_index_api_and_preserves_position(self):
        view = TaskView("./target.py>function")
        view._window = window = TaskWindow()
        window.locations = [
            SimpleNamespace(path="/project/target.py", row=12, col=3),
            SimpleNamespace(path="/project/not_target.py", row=90, col=20),
            SimpleNamespace(path="/project/target.py", row=12, col=3),
        ]
        with patch.object(
            tasks.threading,
            "Thread",
            side_effect=AssertionError("Symbols do not need a filesystem search"),
        ):
            tasks.PlainTasksOpenLinkCommand(view).run(view.edit)
        self.assertEqual(window.opened, ["/project/target.py:12:3"])
        self.assertEqual(
            window.symbol_queries,
            [("function", sublime.SymbolSource.INDEX, sublime.SymbolType.DEFINITION)],
        )

    def test_relative_symbol_target_resolves_from_current_document(self):
        view = TaskView('[[../src/target.py]] ">function"')
        view._filename = "/project/docs/tasks.todo"
        view._window = window = TaskWindow()
        window.locations = [SimpleNamespace(path="/project/src/target.py", row=9, col=2)]
        tasks.PlainTasksOpenLinkCommand(view).run(view.edit)
        self.assertEqual(window.opened, ["/project/src/target.py:9:2"])

    def test_missing_symbol_does_not_fall_back_to_plain_file_position(self):
        view = TaskView("./target.py>missing")
        view._window = window = TaskWindow()
        with (
            patch.object(
                tasks.threading,
                "Thread",
                side_effect=AssertionError("Missing symbol must not open arbitrary file position"),
            ),
            patch.object(tasks.sublime, "status_message") as status,
        ):
            tasks.PlainTasksOpenLinkCommand(view).run(view.edit)
        self.assertEqual(window.opened, [])
        self.assertIn('Symbol "missing" was not found', status.call_args.args[0])
        self.assertEqual(tasks._active_searches, {})

    def test_symbol_matching_handles_windows_case_and_path_separators(self):
        view = TaskView()
        window = TaskWindow()
        window.locations = [SimpleNamespace(path=r"c:\src\target.py", row=2, col=1)]
        with patch.object(tasks, "NT", True):
            results = tasks.PlainTasksOpenLinkCommand(view)._symbol_results(
                window, "C:/SRC/target.py", "function"
            )
        self.assertEqual(results, [(r"c:\src\target.py", 2, 1, "f")])

    def test_unloading_plugin_cancels_workers_and_queued_callbacks(self):
        view = TaskView()
        view._window = window = TaskWindow()
        command = tasks.PlainTasksOpenLinkCommand(view)
        search = command._search = tasks.LinkSearch(results=[("target.todo", 1, 1, "f")])
        tasks._active_searches[id(search)] = search, view
        view.set_status("PlainTasksSearch", "searching")
        tasks.plugin_unloaded()
        command._poll_search(search, window, "target.todo", None, 0)
        command._select_result(search, window, search.results, 0, None, 0)
        self.assertTrue(search.cancelled.is_set())
        self.assertEqual(tasks._active_searches, {})
        self.assertNotIn("PlainTasksSearch", view.status)
        self.assertEqual(window.opened, [])

    def test_closed_origin_view_never_opens_search_result(self):
        view = TaskView()
        view._window = window = TaskWindow()
        command = tasks.PlainTasksOpenLinkCommand(view)
        search = command._search = tasks.LinkSearch()
        tasks._active_searches[id(search)] = search, view
        view.valid = False
        command._select_result(search, window, [("target.todo", 1, 1, "f")], 0, None, 0)
        self.assertEqual(window.opened, [])
        self.assertTrue(search.cancelled.is_set())
        self.assertNotIn(id(search), tasks._active_searches)
