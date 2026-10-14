"""Small editor API double for standalone tests, with strict edit/size checks.

This models the exercised API contracts, not Sublime's syntax engine or UI.
It is never installed when the suite runs inside Sublime Text.
"""

from pathlib import Path
import sys
import types


class Region:
    def __init__(self, a, b=None):
        self.a = a
        self.b = a if b is None else b

    def begin(self):
        return min(self.a, self.b)

    def end(self):
        return max(self.a, self.b)

    def empty(self):
        return self.a == self.b

    def intersects(self, other):
        return self.begin() < other.end() and other.begin() < self.end()

    def contains(self, other):
        return self.begin() <= other.begin() and other.end() <= self.end()

    def __eq__(self, other):
        return isinstance(other, Region) and (self.a, self.b) == (other.a, other.b)

    def __lt__(self, other):
        return (self.a, self.b) < (other.a, other.b)


class Selection(list):
    def add(self, region):
        self.append(region if isinstance(region, Region) else Region(region))

    def add_all(self, regions):
        self.extend(regions)

    def subtract(self, region):
        self.remove(region)


class Settings(dict):
    def set(self, key, value):
        self[key] = value

    def add_on_change(self, key, callback):
        pass

    def clear_on_change(self, key):
        pass


class View:
    def __init__(self, text='', settings=None):
        self.text = text
        self._settings = Settings(settings or {})
        self._selection = Selection([Region(0)])
        self.edit = object()
        self.commands = []
        self._window = None
        self._name = None
        self._filename = None
        self.scope = None
        self.popup = None

    def settings(self):
        return self._settings

    def sel(self):
        return self._selection

    def size(self):
        return len(self.text)

    def substr(self, region):
        if isinstance(region, int):
            return self.text[region] if 0 <= region < self.size() else ''
        return self.text[region.begin():region.end()]

    def line(self, point):
        point = point.begin() if isinstance(point, Region) else point
        start = self.text.rfind('\n', 0, point) + 1
        end = self.text.find('\n', point)
        return Region(start, self.size() if end < 0 else end)

    def lines(self, region):
        return self.split_by_newlines(region)

    def split_by_newlines(self, region):
        return [self.line(region.a + sum(len(s) + 1 for s in self.text[region.a:region.b].split('\n')[:i]))
                for i, _ in enumerate(self.text[region.a:region.b].split('\n'))]

    def scope_name(self, point):
        if self.scope:
            return self.scope
        text = self.substr(self.line(point)).lstrip()
        state = {'☐': 'pending', '✔': 'completed', '✘': 'cancelled'}.get(text[:1])
        if state:
            return f'text.todo meta.item.todo.{state} '
        return 'text.todo keyword.control.header.todo ' if text.endswith(':') else 'text.todo notes.todo '

    def extract_scope(self, point):
        return self.line(point)

    def score_selector(self, *args):
        return 1

    def rowcol(self, point):
        return self.text[:point].count('\n'), point - self.line(point).a

    def insert(self, edit, point, text):
        assert edit is self.edit, 'Edit token belongs to another view'
        self.text = self.text[:point] + text + self.text[point:]
        return len(text)

    def replace(self, edit, region, text):
        assert edit is self.edit
        self.text = self.text[:region.begin()] + text + self.text[region.end():]

    def run_command(self, command, args=None):
        self.commands.append((command, args))
        if command == 'append':
            self.insert(self.edit, self.size(), args['characters'])

    def window(self):
        return self._window

    def file_name(self):
        return self._filename

    def set_name(self, name):
        self._name = name

    def assign_syntax(self, syntax):
        self._settings.set('syntax', syntax)

    def style_for_scope(self, scope):
        return {'foreground': '#112233', 'background': '#ffffff'}

    def style(self):
        return {'foreground': '#112233', 'background': '#ffffff'}

    def viewport_extent(self):
        return 901.5, 601.5

    def hide_popup(self):
        pass

    def show_popup(self, content, flags, location, max_width, max_height, on_navigate):
        assert type(location) is int
        assert type(max_width) is int
        assert type(max_height) is int
        self.popup = content, location, max_width, max_height

    def update_popup(self, content):
        self.popup = content


class Window:
    def __init__(self):
        self.created = []
        self.commands = []

    def new_file(self):
        view = View()
        view._window = self
        self.created.append(view)
        return view

    def run_command(self, command, args=None):
        self.commands.append((command, args))


class TextCommand:
    def __init__(self, view):
        self.view = view


class WindowCommand:
    def __init__(self, window):
        self.window = window


def install():
    sublime = types.ModuleType('sublime')
    sublime._plaintasks_test_stub = True
    sublime.version = lambda: '4215'
    sublime.platform = lambda: 'linux'
    sublime.Region = Region
    for index, name in enumerate(('DRAW_NO_FILL', 'DRAW_NO_OUTLINE', 'DRAW_SQUIGGLY_UNDERLINE',
                                  'HOVER_TEXT', 'LITERAL', 'COOPERATE_WITH_AUTO_COMPLETE',
                                  'LAYOUT_INLINE', 'LAYOUT_BELOW', 'ENCODED_POSITION')):
        setattr(sublime, name, 1 << index)
    sublime.error_message = lambda message: None
    sublime.status_message = lambda message: None
    root = Path(__file__).resolve().parents[2]
    sublime.load_resource = lambda path: (root / path.removeprefix('Packages/PlainTasks/')).read_text(encoding='utf-8')
    plugin = types.ModuleType('sublime_plugin')
    plugin.TextCommand = TextCommand
    plugin.WindowCommand = WindowCommand
    plugin.EventListener = type('EventListener', (), {})
    plugin.ViewEventListener = TextCommand
    sys.modules['sublime'] = sublime
    sys.modules['sublime_plugin'] = plugin
