"""Export task documents using the editor's resolved syntax and color scheme."""

import tempfile
import webbrowser
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import urlsplit

import sublime

from .APlainTasksCommon import PlainTasksEnabled

LINE_CLASSES = {
    "keyword.control.header.todo": "header",
    "meta.item.todo.pending": "open",
    "meta.item.todo.completed": "done",
    "meta.item.todo.cancelled": "cancelled",
    "meta.punctuation.separator.todo": "sep",
    "meta.punctuation.archive.todo": "sep-archive",
    "notes.todo": "note",
}
TAG_CLASSES = {
    "meta.tag.todo.completed": "tag-done",
    "meta.tag.todo.cancelled": "tag-cancelled",
    "string.other.tag.todo.today": "tag-today",
    "string.other.tag.todo.critical": "tag-critical",
    "string.other.tag.todo.high": "tag-high",
    "string.other.tag.todo.low": "tag-low",
    "meta.tag.todo": "tag",
}
CSS_SCOPES = {
    "body": "text.todo",
    "a": "text.todo todo.url",
    ".header": "text.todo keyword.control.header.todo",
    ".note": "text.todo notes.todo",
    ".open": "text.todo meta.item.todo.pending",
    ".done": "text.todo meta.item.todo.completed comment.line.completed.todo",
    ".cancelled": "text.todo meta.item.todo.cancelled text.cancelled.todo",
    ".bullet-pending": "text.todo meta.item.todo.pending punctuation.definition.bullet.pending.todo",
    ".bullet-done": "text.todo meta.item.todo.completed punctuation.definition.bullet.completed.todo",
    ".bullet-cancelled": "text.todo meta.item.todo.cancelled punctuation.definition.bullet.cancelled.todo",
    ".tag": "text.todo meta.item.todo.pending meta.tag.todo",
    ".tag-done": "text.todo meta.item.todo.completed meta.tag.todo.completed",
    ".tag-cancelled": "text.todo meta.item.todo.cancelled meta.tag.todo.cancelled",
    ".tag-today": "text.todo meta.item.todo.pending string.other.tag.todo.today",
    ".tag-critical": "text.todo meta.item.todo.pending string.other.tag.todo.critical",
    ".tag-high": "text.todo meta.item.todo.pending string.other.tag.todo.high",
    ".tag-low": "text.todo meta.item.todo.pending string.other.tag.todo.low",
    ".sep": "text.todo meta.punctuation.separator.todo",
    ".sep-archive": "text.todo meta.punctuation.archive.todo",
}
LINK_SCHEMES = {"http", "https", "ftp", "ftps", "mailto", "file"}
_export_directory = None


def plugin_unloaded():
    """Keep browser exports available during this session, then remove them."""
    global _export_directory
    if _export_directory is not None:
        _export_directory.cleanup()
        _export_directory = None


class PlainTasksConvertToHtml(PlainTasksEnabled):
    def run(self, edit, ask=False):
        regions = self.view.split_by_newlines(sublime.Region(0, self.view.size()))
        title = Path(self.view.file_name()).name if self.view.file_name() else "Export"
        document = self.produce_html_from_template(title, [self.render_line(r) for r in regions])

        if ask:
            window = self.view.window()
            if window is None:
                return
            output = window.new_file()
            output.assign_syntax("Packages/HTML/HTML.sublime-syntax")
            output.set_name(title + ".html")
            output.run_command("append", {"characters": document})
            window.run_command("save_as")
            return

        global _export_directory
        if _export_directory is None:
            _export_directory = tempfile.TemporaryDirectory(prefix="plaintasks-export-")
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".html", dir=_export_directory.name, delete=False
        ) as output:
            output.write(document)
        path = Path(output.name)
        try:
            opened = webbrowser.open_new_tab(path.as_uri())
        except OSError, webbrowser.Error:
            opened = False
        if not opened:
            sublime.error_message(f"Unable to open a browser. The HTML export is saved at:\n{path}")

    def render_line(self, region):
        scopes = self.view.scope_name(region.begin()).split()
        css_class = next(
            (value for key, value in LINE_CLASSES.items() if key in scopes), "empty-line"
        )
        if css_class not in ("open", "done", "cancelled", "note") or region.empty():
            content = escape(self.view.substr(region))
        else:
            # Sublime returns disjoint syntax tokens with their complete scope
            # stacks. One call replaces an IPC round trip for every character.
            parts = []
            point = region.begin()
            for token, scope in self.view.extract_tokens_with_scopes(region):
                start, end = max(point, token.begin()), min(region.end(), token.end())
                if start >= end:
                    continue
                if point < start:
                    parts.append(escape(self.view.substr(sublime.Region(point, start))))
                parts.append(self.render_scope(sublime.Region(start, end), css_class, scope))
                point = end
            if point < region.end():
                parts.append(escape(self.view.substr(sublime.Region(point, region.end()))))
            content = "".join(parts)
        return f'<span class="{css_class}">{content}</span>'

    def render_scope(self, region, line_class, scope=None):
        scopes = (self.view.scope_name(region.begin()) if scope is None else scope).split()
        text = self.view.substr(region)
        escaped = escape(text)
        if line_class != "note":
            state = {"open": "pending", "done": "completed", "cancelled": "cancelled"}.get(
                line_class
            )
            if state and f"punctuation.definition.bullet.{state}.todo" in scopes:
                css_state = "done" if state == "completed" else state
                return f'<span class="bullet-{css_state}">{escaped}</span>'
            css_class = next((value for key, value in TAG_CLASSES.items() if key in scopes), None)
            if css_class:
                return f'<span class="{css_class}">{escaped}</span>'
        if line_class in ("open", "note"):
            if "punctuation.definition.italic" in scopes or "punctuation.definition.bold" in scopes:
                return ""
            if "todo.italic" in scopes:
                return f"<i>{escaped}</i>"
            if "todo.bold" in scopes:
                return f"<b>{escaped}</b>"
            if "todo.url" in scopes:
                url = text.removeprefix("<").removesuffix(">")
                if not url:
                    return ""
                try:
                    scheme = urlsplit(url).scheme.lower()
                except ValueError:
                    return escaped
                if scheme and scheme not in LINK_SCHEMES:
                    return escaped
                href = url if scheme else "https://" + url
                return f'<a href="{escape(href, quote=True)}">{escape(url)}</a>'
        return escaped

    def produce_html_from_template(self, title, html_doc):
        template = sublime.load_resource("Packages/PlainTasks/templates/template.html")
        # Substitute once so placeholders in user text remain literal.
        return Template(template).substitute(
            title=escape(title), content="\n".join(html_doc), css="\n".join(self.export_css())
        )

    def export_css(self):
        """Use the same resolved styles for tmTheme and modern color schemes."""
        css = []
        for selector, scope in CSS_SCOPES.items():
            style = self.view.style() if selector == "body" else self.view.style_for_scope(scope)
            props = [
                f"{key}: {style[value]};"
                for key, value in (("color", "foreground"), ("background-color", "background"))
                if style.get(value)
            ]
            props.append("font-weight: bold;" if style.get("bold") else "font-weight: normal;")
            props.append("font-style: italic;" if style.get("italic") else "font-style: normal;")
            props.append(
                "text-decoration: underline;"
                if style.get("underline")
                else "text-decoration: none;"
            )
            css.append(f"{selector} {{ {' '.join(props)} }}")
        return css
