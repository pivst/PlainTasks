"""Folding boundaries, task context, and shared settings regressions."""

from unittest import TestCase, skipUnless
from unittest.mock import Mock

import sublime
from PlainTasks.tests.support.sublime_stub import Region, View

from PlainTasks import APlainTasksCommon as common


def positions(regions):
    return [(region.begin(), region.end()) for region in regions]


class FoldingView(View):
    def __init__(self, text, projects=(), separators=(), blocks=None, notes=()):
        super().__init__(text)
        self.projects = projects
        self.separators = separators
        self.blocks = blocks or {}
        self.notes = notes
        self.unfold = Mock()
        self.fold = Mock()
        self.indented_region = Mock(side_effect=lambda point: self.blocks.get(point, Region(point)))

    def find_by_selector(self, selector):
        return self.projects if selector == "keyword.control.header.todo" else self.separators

    def match_selector(self, point, selector):
        assert 0 <= point < self.size(), "Notes must not query beyond EOF"
        return any(region.begin() <= point < region.end() for region in self.notes)


@skipUnless(getattr(sublime, "_plaintasks_test_stub", False), "Standalone editor API contracts")
class TestFolding(TestCase):
    def test_empty_selection_unfolds_document(self):
        view = FoldingView("some text")
        command = common.PlainTasksFold(view)
        command.exec_folding([])
        view.unfold.assert_called_once()
        view.fold.assert_not_called()
        self.assertEqual(command.add_projects_and_notes([]), [])

    def test_unsorted_and_duplicate_visible_lines_keep_newlines(self):
        view = FoldingView("hide\nshow\nhide\nshow\nhide")
        common.PlainTasksFold(view).exec_folding([Region(15, 19), Region(5, 9), Region(5, 9)])
        self.assertEqual(
            positions(call.args[0] for call in view.fold.call_args_list),
            [(0, 4), (10, 14), (20, 24)],
        )

    def test_overlapping_visible_regions_are_not_folded(self):
        view = FoldingView("x" * 30)
        common.PlainTasksFold(view).exec_folding([Region(5, 15), Region(10, 20), Region(15, 10)])
        self.assertEqual(
            positions(call.args[0] for call in view.fold.call_args_list), [(0, 4), (21, 30)]
        )

    def test_note_at_eof_is_included_once_and_terminates(self):
        text = " ☐ task\n note **with markup**"
        task = Region(0, 7)
        note = Region(8, len(text))
        view = FoldingView(text, notes=[note])
        command = common.PlainTasksFold(view)
        self.assertEqual(
            positions(command.add_projects_and_notes([task, task])), [(0, 7), (8, len(text))]
        )

    def test_nested_project_context_is_deduplicated(self):
        text = "Root:\n Child:\n  ☐ first\n  note\n  ☐ second\nOther:\n ☐ unrelated"
        root = View(text).line(0)
        child = View(text).line(text.index(" Child:"))
        first = View(text).line(text.index("first"))
        second = View(text).line(text.index("second"))
        other = View(text).line(text.index("Other:"))
        note = View(text).line(text.index("note"))
        root_block = Region(root.end() + 1, other.begin() - 1)
        child_block = Region(child.end() + 1, other.begin() - 1)
        view = FoldingView(
            text,
            projects=[root, child, other],
            blocks={
                root.end() + 1: root_block,
                child.end() + 1: child_block,
                first.begin(): Region(first.begin(), note.end()),
                second.begin(): Region(second.begin(), second.end()),
            },
            notes=[note],
        )
        result = common.PlainTasksFold(view).add_projects_and_notes([second, first, second])
        self.assertEqual(positions(result), positions([root, child, first, note, second]))
        self.assertEqual(view.indented_region.call_count, 4)

    def test_project_blocks_are_cached_across_many_tasks(self):
        text = "Project:\n" + "\n".join(" ☐ task" for _ in range(100))
        source = View(text)
        tasks = source.split_by_newlines(Region(9, len(text)))
        header = source.line(0)
        blocks = {9: Region(9, len(text))}
        blocks.update({task.begin(): Region(task.begin(), task.end()) for task in tasks[1:]})
        view = FoldingView(text, projects=[header], blocks=blocks)
        result = common.PlainTasksFold(view).add_projects_and_notes(tasks)
        self.assertEqual(len(result), len(tasks) + 1)
        self.assertEqual(view.indented_region.call_count, len(tasks) + 1)

    def test_project_selectors_return_unique_lines(self):
        text = "First:\nSecond:\n---✄---\n"
        view = FoldingView(
            text, projects=[Region(0, 14), Region(7, 14)], separators=[Region(15, 22)]
        )
        self.assertEqual(
            positions(common.get_all_projects_and_separators(view)), [(0, 6), (7, 14), (15, 22)]
        )


@skipUnless(getattr(sublime, "_plaintasks_test_stub", False), "Standalone editor API contracts")
class TestTaskSettings(TestCase):
    def test_taskpaper_settings_preserve_bullets_and_forced_tags(self):
        view = View(
            settings={
                "taskpaper_compatible": True,
                "done_tag": False,
                "translate_tabs_to_spaces": True,
            }
        )
        command = common.PlainTasksBase(view)
        command.run_command = Mock()
        command.run(view.edit, requested=True)
        self.assertEqual(
            (command.open_tasks_bullet, command.done_tasks_bullet, command.canc_tasks_bullet),
            ("-", "-", "-"),
        )
        self.assertEqual((command.done_tag, command.canc_tag), ("@done", "@cancelled"))
        self.assertEqual(command.before_date_space, "")
        self.assertEqual(command.before_tasks_bullet_spaces, "\t")
        self.assertEqual(command.tasks_bullet_space, " ")
        command.run_command.assert_called_once_with(view.edit, requested=True)

    def test_command_availability_accepts_palette_arguments(self):
        command = common.PlainTasksEnabled(View())
        self.assertTrue(command.is_enabled(ask=True))
        self.assertTrue(command.is_visible(start=42))

    def test_editing_commands_are_unavailable_outside_task_documents(self):
        view = View()
        view.score_selector = Mock(return_value=0)
        command = common.PlainTasksBase(view)
        self.assertFalse(command.is_enabled(partial=True))
        self.assertFalse(command.is_visible(descending=True))


@skipUnless(getattr(sublime, "_plaintasks_test_stub", False), "Standalone editor API contracts")
class TestArchiveHeading(TestCase):
    def test_archive_label_in_task_text_is_not_a_heading(self):
        import re

        view = View(" ☐ Write Archive: section\n ✔ Done @done(26-10-14 10:00)\n Archive:  \n")

        def find(pattern, point):
            match = re.search(pattern, view.text[point:], re.MULTILINE)
            return Region(point + match.start(), point + match.end()) if match else Region(-1)

        view.find = find
        region = common.find_archive(view, "Archive:")
        self.assertEqual(view.substr(region).strip(), "Archive:")
        self.assertGreater(region.begin(), view.text.index("Done"))

    def test_custom_archive_name_is_literal(self):
        import re

        view = View("DoneArchive:\nDone [Archive]:\n")

        def find(pattern, point):
            match = re.search(pattern, view.text[point:], re.MULTILINE)
            return Region(point + match.start(), point + match.end()) if match else Region(-1)

        view.find = find
        region = common.find_archive(view, "Done [Archive]:")
        self.assertEqual(view.substr(region), "Done [Archive]:")
