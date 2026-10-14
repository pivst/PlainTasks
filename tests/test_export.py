"""HTML export content, editor API, and temporary-file regressions."""

import re
from html import unescape
from pathlib import Path
from unittest import TestCase, skipUnless
from unittest.mock import patch
from urllib.parse import urlparse
from urllib.request import url2pathname

import sublime
from PlainTasks.tests.support.sublime_stub import Region, View, Window

from PlainTasks import PlainTasksToHTML as export


@skipUnless(getattr(sublime, "_plaintasks_test_stub", False), "Standalone editor API contracts")
class TestHtmlExport(TestCase):
    def tearDown(self):
        export.plugin_unloaded()

    @staticmethod
    def token_view(parts, line_scope="meta.item.todo.pending"):
        view = View("".join(text for text, _ in parts))
        tokens = []
        point = 0
        for text, scope in parts:
            tokens.append((Region(point, point + len(text)), f"text.todo {line_scope} {scope}"))
            point += len(text)
        view.scope = f"text.todo {line_scope}"
        view.extract_tokens_with_scopes = lambda region: tokens
        return view

    def test_bulk_tokens_preserve_escaping_and_inline_markup(self):
        view = self.token_view(
            [
                (" ", ""),
                ("☐", "punctuation.definition.bullet.pending.todo"),
                (" Read ", ""),
                ("**", "todo.bold punctuation.definition.bold"),
                ("<中文>_", "todo.bold"),
                ("**", "todo.bold punctuation.definition.bold"),
                (" ", ""),
                ("*", "todo.italic punctuation.definition.italic"),
                ("italics", "todo.italic"),
                ("*", "todo.italic punctuation.definition.italic"),
                (" @high", "string.other.tag.todo.high"),
            ]
        )
        document = export.PlainTasksConvertToHtml(view).render_line(Region(0, view.size()))
        self.assertIn("<b>&lt;中文&gt;_</b>", document)
        self.assertIn("<i>italics</i>", document)
        self.assertIn('<span class="tag-high"> @high</span>', document)
        visible = unescape(re.sub("<[^>]+>", "", document))
        self.assertEqual(visible, " ☐ Read <中文>_ italics @high")

    def test_bulk_tokens_avoid_per_character_scope_calls(self):
        view = self.token_view(
            [("☐", "punctuation.definition.bullet.pending.todo"), (" " + "x" * 100_000, "")]
        )
        with (
            patch.object(view, "scope_name", wraps=view.scope_name) as scope_name,
            patch.object(
                view, "extract_tokens_with_scopes", wraps=view.extract_tokens_with_scopes
            ) as tokens,
        ):
            export.PlainTasksConvertToHtml(view).render_line(Region(0, view.size()))
        self.assertEqual(scope_name.call_count, 1)
        self.assertEqual(tokens.call_count, 1)

    def test_missing_token_gaps_are_preserved(self):
        view = self.token_view([(" ☐ left <right> tail", "")])
        view.extract_tokens_with_scopes = lambda region: [
            (Region(8, 15), "text.todo meta.item.todo.pending todo.bold")
        ]
        document = export.PlainTasksConvertToHtml(view).render_line(Region(0, view.size()))
        self.assertEqual(unescape(re.sub("<[^>]+>", "", document)), view.text)

    def test_token_regions_are_clipped_without_duplicate_text(self):
        view = self.token_view([("prefix selected suffix", "")])
        view.extract_tokens_with_scopes = lambda region: [
            (Region(0, 16), "text.todo meta.item.todo.pending"),
            (Region(10, 30), "text.todo meta.item.todo.pending"),
        ]
        document = export.PlainTasksConvertToHtml(view).render_line(Region(7, 15))
        self.assertEqual(unescape(re.sub("<[^>]+>", "", document)), "selected")

    def test_links_escape_attributes_and_reject_active_schemes(self):
        view = View()
        command = export.PlainTasksConvertToHtml(view)
        for target in (
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "vbscript:alert(1)",
        ):
            view.text = "<" + target + ">"
            document = command.render_scope(
                Region(0, view.size()), "note", "text.todo notes.todo todo.url"
            )
            self.assertNotIn("<a ", document)
            self.assertIn("&lt;", document)
        view.text = 'https://example.com/"?a=<b>&x=1'
        document = command.render_scope(
            Region(0, view.size()), "note", "text.todo notes.todo todo.url"
        )
        self.assertIn('href="https://example.com/&quot;?a=&lt;b&gt;&amp;x=1"', document)

    def test_url_punctuation_and_scheme_less_links(self):
        view = self.token_view(
            [("<", "todo.url punctuation.definition.url"), ("example.com/?x=1&y=2>", "todo.url")],
            "notes.todo",
        )
        document = export.PlainTasksConvertToHtml(view).render_line(Region(0, view.size()))
        self.assertEqual(
            document,
            '<span class="note"><a href="https://example.com/?x=1&amp;y=2">'
            "example.com/?x=1&amp;y=2</a></span>",
        )

    def test_scope_names_match_whole_tokens(self):
        view = View("**literal**")
        command = export.PlainTasksConvertToHtml(view)
        self.assertEqual(
            command.render_scope(
                Region(0, view.size()), "open", "text.todo meta.item.todo.pending user.todo.boldish"
            ),
            "**literal**",
        )

    def test_theme_resolution_uses_actual_parent_scopes(self):
        view = View(settings={"color_scheme": "Packages/PlainTasks/tasks.hidden-tmTheme"})

        def style(scope):
            return {
                "foreground": "#abcdef",
                "bold": "meta.tag.todo" in scope,
                "italic": "notes.todo" in scope,
                "underline": scope.endswith("todo.url"),
            }

        view.style_for_scope = style
        css = export.PlainTasksConvertToHtml(view).export_css()
        self.assertIn("background-color: #ffffff;", css[0])
        self.assertIn(
            "font-weight: bold;", next(rule for rule in css if rule.startswith(".tag-done "))
        )
        self.assertIn(
            "font-style: italic;", next(rule for rule in css if rule.startswith(".note "))
        )
        self.assertIn(
            "text-decoration: underline;", next(rule for rule in css if rule.startswith("a "))
        )
        with patch.object(
            sublime, "load_resource", side_effect=AssertionError("No theme parsing needed")
        ):
            self.assertEqual(export.PlainTasksConvertToHtml(view).export_css(), css)

    def test_saved_html_and_title_are_literal(self):
        view = self.token_view([('☐ <task>&" $css $title', "")])
        view._filename = "/tmp/<title&>.todo"
        view._window = Window()
        export.PlainTasksConvertToHtml(view).run(view.edit, ask=True)
        output = view.window().created[0]
        self.assertIn("<title>&lt;title&amp;&gt;.todo</title>", output.text)
        self.assertIn("&lt;task&gt;&amp;&quot; $css $title", output.text)
        self.assertEqual(view.window().commands, [("save_as", None)])
        self.assertEqual(view.text, '☐ <task>&" $css $title')

    def test_browser_export_cleanup_and_failed_launch_message(self):
        view = View("项目:")
        with (
            patch.object(export.webbrowser, "open_new_tab", return_value=False) as browser,
            patch.object(sublime, "error_message") as message,
        ):
            export.PlainTasksConvertToHtml(view).run(view.edit)
        path = Path(url2pathname(urlparse(browser.call_args.args[0]).path))
        self.assertIn("项目:", path.read_text(encoding="utf-8"))
        self.assertIn(str(path), message.call_args.args[0])
        export.plugin_unloaded()
        self.assertFalse(path.exists())
        self.assertFalse(path.parent.exists())
