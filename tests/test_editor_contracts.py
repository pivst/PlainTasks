"""Regression tests for Python 3.14 and the Sublime Text 4215 API contracts."""

from datetime import datetime
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch

import sublime
from PlainTasks.tests.support.sublime_stub import Region, View, Window

from PlainTasks import APlainTasksCommon as common
from PlainTasks import PlainTasks as tasks
from PlainTasks import PlainTasksDates as dates
from PlainTasks import PlainTasksToHTML as export


class TestModernDates(TestCase):
    def test_local_timestamp_is_aware(self):
        now = tasks.tznow()
        self.assertIsNotNone(now.utcoffset())
        self.assertLess(abs(now.timestamp() - datetime.now().timestamp()), 2)

    def test_parse_without_default(self):
        date, error = dates.parse_date("0")
        self.assertIsNone(error)
        self.assertEqual(date.date(), datetime.now().date())

    def test_fallback_without_dateutil(self):
        now = datetime(2026, 12, 31, 23)
        with patch.object(dates, "dateutil_parser", None):
            for text, expected in [("1-1", datetime(2027, 1, 1, 23)), ("(26-12-31 23:00)", now)]:
                with self.subTest(text=text):
                    date, error = dates.parse_date(text, default=now)
                    self.assertEqual(date, expected)
                    self.assertIsNone(error)

    def test_unexpected_dateutil_errors_are_not_hidden(self):
        with patch.object(
            dates.dateutil_parser, "parse", side_effect=RuntimeError("programming error")
        ):
            with self.assertRaises(RuntimeError):
                dates.parse_date("2026-Oct-13", default=datetime(2026, 1, 1))

    def test_old_year_requires_full_year_format(self):
        default = datetime(2026, 12, 31, 23)
        date, error = dates.parse_date("233", default=default)
        self.assertIsNone(date)
        self.assertIsNotNone(error)
        date, error = dates.parse_date("233", date_format="(%Y-%m-%d %H:%M)", default=default)
        self.assertEqual(date.year, 233)
        self.assertIsNone(error)


@skipUnless(getattr(sublime, "_plaintasks_test_stub", False), "Standalone API-contract doubles")
class TestEditorContracts(TestCase):
    def setUp(self):
        self.stats = patch.object(tasks.PlainTasksStatsStatus, "set_stats")
        self.stats.start()
        self.addCleanup(self.stats.stop)

    def test_complete_and_reopen_unicode_task(self):
        view = View(" ☐ 中文任务")
        command = tasks.PlainTasksCompleteCommand(view)
        command.run(view.edit)
        self.assertTrue(view.text.startswith(" ✔ 中文任务 @done"))
        command.run(view.edit)
        self.assertEqual(view.text, " ☐ 中文任务")

    def test_cancel_and_reopen_task(self):
        view = View(" ☐ 任务")
        command = tasks.PlainTasksCancelCommand(view)
        command.run(view.edit)
        self.assertTrue(view.text.startswith(" ✘ 任务 @cancelled"))
        command.run(view.edit)
        self.assertEqual(view.text, " ☐ 任务")

    def test_format_date_is_unicode(self):
        command = common.PlainTasksBase(View())
        command.date_format = "(任务 %Y-%m-%d)"
        command.before_date_space = " "
        command.done_date = True
        suffix, date = command.format_line_end("@done", datetime(2026, 10, 13))
        self.assertEqual(suffix, " @done (任务 2026-10-13)")
        self.assertEqual(date, "(任务 2026-10-13)")

    def test_popup_passes_integer_sizes_and_preserves_zero(self):
        view = View("☐ task")
        view.scope = "text.todo meta.item.todo.pending "
        # Simulate hovering over a bullet.
        original = view.scope_name
        view.scope_name = lambda point: (
            original(point) + ("punctuation.definition.bullet.pending.todo " if point == 0 else "")
        )
        tasks.PlainTasksHover(view).on_hover(0, sublime.HOVER_TEXT)
        self.assertEqual(view.popup[1:], (0, 901, 300))
        self.assertIn("Toggle complete", view.popup[0])

    def test_save_html_uses_output_view_edit(self):
        view = View("Project:")
        window = Window()
        view._window = window
        command = export.PlainTasksConvertToHtml(view)
        command.run(view.edit, ask=True)
        self.assertEqual(len(window.created), 1)
        output = window.created[0]
        self.assertIn('<span class="header">Project:</span>', output.text)
        self.assertEqual(output.settings().get("syntax"), "Packages/HTML/HTML.sublime-syntax")
        self.assertIn(("save_as", None), window.commands)
        self.assertEqual(view.text, "Project:")

    def test_browser_html_is_utf8_and_uses_file_uri(self):
        view = View("中文项目:")
        with patch.object(export.webbrowser, "open_new_tab") as browser:
            export.PlainTasksConvertToHtml(view).run(view.edit)
        uri = browser.call_args.args[0]
        from urllib.parse import urlparse
        from urllib.request import url2pathname

        path = Path(url2pathname(urlparse(uri).path))
        self.addCleanup(path.unlink)
        self.assertTrue(uri.startswith("file:///"))
        self.assertIn("中文项目:", path.read_text(encoding="utf-8"))

    def test_resource_export_escapes_title_and_preserves_user_placeholders(self):
        view = View(settings={"color_scheme": "Packages/PlainTasks/tasks.hidden-tmTheme"})
        with patch.object(sublime, "load_resource", wraps=sublime.load_resource) as resources:
            html = export.PlainTasksConvertToHtml(view).produce_html_from_template(
                "<中文&>", ["$css $title"]
            )
        self.assertIn("<title>&lt;中文&amp;&gt;</title>", html)
        self.assertIn("$css $title", html)
        self.assertIn("body {", html)
        resources.assert_any_call("Packages/PlainTasks/templates/template.html")

    def test_modern_scheme_uses_sublime_resolved_styles(self):
        view = View(
            settings={
                "color_scheme": "Packages/Color Scheme - Default/Mariana.sublime-color-scheme"
            }
        )
        css = export.PlainTasksConvertToHtml(view).export_css()
        self.assertTrue(any("color: #112233;" in line for line in css))

    def test_modern_scheme_preserves_font_and_completed_scopes(self):
        view = View(
            settings={
                "color_scheme": "Packages/Color Scheme - Default/Mariana.sublime-color-scheme"
            }
        )

        def style(scope):
            return {
                "foreground": "#ABCDEF" if "comment.line.completed.todo" in scope else "#112233",
                "italic": False,
                "bold": False,
            }

        view.style_for_scope = style
        css = export.PlainTasksConvertToHtml(view).export_css()
        done = next(line for line in css if line.startswith(".done {"))
        self.assertIn("color: #ABCDEF;", done)
        self.assertIn("font-style: normal;", done)
        self.assertIn("font-weight: normal;", done)
        body = next(line for line in css if line.startswith("body {"))
        self.assertIn("background-color: #ffffff;", body)
        with patch.object(view, "style_for_scope", wraps=style) as styles:
            export.PlainTasksConvertToHtml(view).export_css()
        styles.assert_any_call(export.CSS_SCOPES[".tag-done"])
        styles.assert_any_call(export.CSS_SCOPES[".tag-cancelled"])

    def test_markup_content_retains_literal_delimiters(self):
        view = View("_literal_")
        view.scope = "text.todo meta.item.todo.pending todo.bold "
        command = export.PlainTasksConvertToHtml(view)
        self.assertEqual(command.render_scope(Region(0, view.size()), "open"), "<b>_literal_</b>")
        view.text = "**"
        view.scope += "punctuation.definition.bold "
        self.assertEqual(command.render_scope(Region(0, view.size()), "open"), "")

    def test_windows_external_handler_receives_unmodified_argument(self):
        with (
            patch.object(tasks, "NT", True),
            patch.object(tasks.os, "startfile", create=True) as launch,
        ):
            for target in (r"C:\中文 目录\任务 & notes.todo", "https://example.com/?a=1&b=2"):
                tasks.open_external_url(target)
                launch.assert_called_with(target)

    def test_inline_text_and_link_attributes_are_escaped(self):
        view = View('<https://example.com/"?q=<task>&x=1>')
        view.scope = "text.todo notes.todo todo.url "
        html = export.PlainTasksConvertToHtml(view).render_scope(Region(0, view.size()), "note")
        self.assertIn('href="https://example.com/&quot;?q=&lt;task&gt;&amp;x=1"', html)
        self.assertNotIn("<task>", html)
        view.text = '<task>&"'
        view.scope = "text.todo meta.item.todo.pending string.other.tag.todo.high "
        self.assertEqual(
            export.PlainTasksConvertToHtml(view).render_scope(Region(0, view.size()), "open"),
            '<span class="tag-high">&lt;task&gt;&amp;&quot;</span>',
        )

    def test_unmatched_parentheses_returns_error(self):
        view = View(" ☐ 任务 @due(1")
        date, error, region = dates.expand_short_date(
            view, view.size() - 1, view.size() - 1, datetime(2026, 10, 13), "(%y-%m-%d %H:%M)"
        )
        self.assertIsNone(date)
        self.assertIsNotNone(error)

    def test_calendar_navigation_without_dateutil(self):
        view = View()
        command = dates.PlainTasksCalendar(view)
        command.action("next_month:2028-1-31-12-0")
        self.assertIn("day:2028-2-29-12-0", view.popup)
        command.action("prev_month:2028-1-31-12-0")
        self.assertIn("day:2027-12-31-12-0", view.popup)
        command.action("next_year:2028-2-29-12-0")
        self.assertIn("day:2029-2-28-12-0", view.popup)
        command.action("calendar:2028-2-29-12-0")
        self.assertIn("day:2028-2-29-12-0", view.popup)

    def test_invalid_link_does_not_crash(self):
        result = tasks.PlainTasksOpenLinkCommand(View()).parse_link(" ☐ No link here")
        self.assertEqual(result, (None, None, 0, 0, None))

    def test_link_formats_preserve_positions(self):
        command = tasks.PlainTasksOpenLinkCommand(View())
        for text in ('[README](README.md ":12:3")', "[[README.md::12:3]]"):
            with self.subTest(text=text):
                filename, symbol, line, column, search = command.parse_link(text)
                self.assertEqual(filename, "README.md")
                self.assertEqual((line, column), ("12", "3"))

    def test_inline_scope_boundaries_preserve_text_and_markup(self):
        parts = [
            (" ☐ ", "punctuation.definition.bullet.pending.todo"),
            ("Read ", ""),
            ("**", "todo.bold punctuation.definition.bold"),
            ("<中文>", "todo.bold"),
            ("**", "todo.bold punctuation.definition.bold"),
            (" @high", "string.other.tag.todo.high"),
        ]
        view = View("".join(text for text, _ in parts))
        positions = []
        for text, scope in parts:
            positions.extend(["text.todo meta.item.todo.pending " + scope] * len(text))
        view.scope_name = lambda point: positions[point]
        command = export.PlainTasksConvertToHtml(view)
        html = command.render_line(Region(0, view.size()))
        self.assertIn("Read <b>&lt;中文&gt;</b>", html)
        self.assertIn('<span class="tag-high"> @high</span>', html)
        self.assertNotIn("**", html)
        self.assertEqual(html.count("&lt;中文&gt;"), 1)

    def test_finished_file_search_is_not_joined_again(self):
        view = View(" ☐ No link here")
        command = tasks.PlainTasksOpenLinkCommand(view)

        class FinishedThread:
            def is_alive(self):
                return False

            def join(self):
                raise AssertionError("A finished search should not be cancelled")

        command.thread = FinishedThread()
        command.run(view.edit)

    def test_fold_empty_list_is_safe(self):
        view = View()
        calls = []
        view.unfold = calls.append
        common.PlainTasksFold(view).exec_folding([])
        self.assertEqual(len(calls), 1)
