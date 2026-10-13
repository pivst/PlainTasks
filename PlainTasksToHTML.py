"""Export task documents as UTF-8 HTML using Sublime package resources."""

from html import escape
import os
from pathlib import Path
import re
from string import Template
import tempfile
import webbrowser

import sublime

from .APlainTasksCommon import PlainTasksBase
from .plist_parser import parse_file, parse_string


def hex_to_rgba(value: str) -> list[str]:
    value = value.lstrip('#')
    length = len(value)
    if length in (3, 4):
        value = ''.join(v * 2 for v in value)
    if len(value) not in (6, 8):
        raise ValueError('Expected an RGB or RGBA hex color')
    alpha = [str(round(int(value[6:], 16)/255., 2) if len(value) == 8 else 1.)]
    return [str(int(value[i:i+2], 16)) for i in range(0, 6, 2)] + alpha


def convert_to_rgba_css(word: str) -> str:
    rgba = hex_to_rgba(word)
    rgba_css = 'rgb%s(%s)' % ('a' if len(rgba) > 3 else '', ','.join(rgba))
    return rgba_css


default_ccsl = [  # hand-made repr of tasks.hidden-tmTheme
    'body { background-color: #efe9b7; }',
    'a { color: rgba(0, 62, 114, .55); font-weight: bold; }',
    '.bullet-pending { font-style: normal; font-weight: bold; color: rgba(0,0,0,.6); }',
    '.bullet-done { font-style: normal; font-weight: bold; color: #00723e; }',
    '.bullet-cancelled { font-style: normal; font-weight: bold; color: #b60101; }',
    '.sep { font-style: normal; color: rgba(0,0,0,.44); }',
    '.sep-archive { font-style: normal; color: rgba(0,0,0,.44); }',
    '.header { font-weight: bold; font-style: normal; color: #bc644a; background-color: rgba(0,0,0,.05); width: 100%; }',
    '.tag { font-weight: bold; font-style: normal; color: #C37763; }',
    '.tag-done, .tag-cancelled { font-style: normal; color:#A49F85; }',
    '.tag-today, .tag-critical, .tag-high, .tag-low { font-weight: bold; font-style: normal; color: #000000; }',
    '.tag-today { background: #EADD4E; } .tag-critical{ background: #FF0000; }',
    '.tag-high { background: #FF7F00; }',
    '.tag-low { background: #222222; color: #ffffff; }',
    '.done, .cancelled { color: #66654F; }',
    '.note { font-style: normal; color: #858266; }'
]

scope_to_tag = {  # key is name of regex group, value is regex expression
    'body': r'^body$',
    'a':    r'(?:todo\.)?url(?!\.)',
    # PENDING
    '__open':           r'(?:^|\b)meta(?!\.)',
    '__bullet_pending': r'bullet\.pending(?!\.)',
    # COMPLETED
    '__done':        r'comment(?!\.)',
    '__bullet_done': r'bullet\.completed(?!\.)',
    '__tag_done':    r'tag\.todo\.completed(?!\.)',
    # CANCELLED
    '__cancelled':        r'item\.todo\.cancelled(?!\.)',
    '__bullet_cancelled': r'bullet\.cancelled(?!\.)',
    '__tag_cancelled':    r'tag\.todo\.cancelled(?!\.)',
    # PROJECT & NOTE
    '__header': r'keyword(?!\.)',
    '__note':   r'notes(?:\.todo(?!\.))?',
    # TAGS
    '__tag':          r'(?:^|meta\.)tag(?:\.todo)?(?!\.)',
    '__tag_today':    r'(?:tag\.todo\.)?today(?!\.)',
    '__tag_critical': r'(?:tag\.todo\.)?critical(?!\.)',
    '__tag_high':     r'(?:tag\.todo\.)?high(?!\.)',
    '__tag_low':      r'(?:tag\.todo\.)?low(?!\.)',
    # SEPARATORS
    '__sep':         r'separator(?:\.todo(?!\.))?',
    '__sep_archive': r'archive(?:\.todo(?!\.))?'
}
allrxinone = r'|'.join([('(?P<%s>%s)' % (t, r)) for t, r in scope_to_tag.items()])
SCOPES_REGEX = re.compile(allrxinone)


def convert_tmtheme_to_css(theme_file):
    '''return list of css lines ready to be pasted'''
    if not theme_file:
        return default_ccsl

    theme_as_dict = parse_file(theme_file)
    return theme_to_css(theme_as_dict)


def theme_to_css(theme_as_dict):
    """Convert an already decoded TextMate theme to CSS."""
    cssl = []

    # make default color pink, easy to see in case of bugs
    default_color = 'rgb(236,9,140)'
    for i in theme_as_dict.get('settings', []):
        s = i.get('settings', {})
        if 'caret' in s:
            default_color = convert_to_rgba_css(s['caret'])

    for item in theme_as_dict.get('settings', []):
        scope = item.get('scope', 'body')
        props = item.get('settings', {})
        props_str = ''
        if props:
            for k, v in props.items():
                k = k.replace('foreground', 'color')
                if v:
                    if any(k == w for w in ('background', 'color')):
                        props_str += '%s: %s; ' % (k, convert_to_rgba_css(v) or v)
                    elif k == 'fontStyle':
                        if 'bold' in v:
                            props_str += 'font-weight: bold; font-style: normal; '
                        elif 'italic' in v:
                            props_str += 'font-weight: normal; font-style: italic; '
            if not props.get('fontStyle'):
                props_str += 'font-weight: normal; font-style: normal; '
            if not props.get('foreground'):
                props_str += 'color: %s; ' % default_color
        else:
            props_str += 'color: %s; font-weight: normal; font-style: normal; ' % default_color
        if scope == 'keyword':
            props_str += 'width: 100%; '

        mo = re.search(SCOPES_REGEX, scope)
        tag = mo.lastgroup.replace('__', '.').replace('_', '-') if mo else ''
        if tag:
            cssl.append('%s { %s}' % (tag, props_str))
    return cssl


class PlainTasksConvertToHtml(PlainTasksBase):
    def is_enabled(self):
        return self.view.score_selector(0, "text.todo") > 0

    def runCommand(self, edit, ask=False):
        regions = self.view.split_by_newlines(sublime.Region(0, self.view.size()))
        html_doc = [self.render_line(region) for region in regions]
        title = os.path.basename(self.view.file_name()) if self.view.file_name() else 'Export'
        document = self.produce_html_from_template(title, html_doc)

        if ask:
            window = self.view.window() or sublime.active_window()
            output = window.new_file()
            output.assign_syntax('Packages/HTML/HTML.sublime-syntax')
            output.set_name(title + '.html')
            # An edit token belongs to its source view; append obtains a new token.
            output.run_command('append', {'characters': document})
            window.run_command('save_as')
            return

        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False, suffix='.html') as output:
            output.write(document)
        webbrowser.open_new_tab(Path(output.name).as_uri())

    def render_line(self, region):
        """Render a line with one shared path for task text and inline markup."""
        scope = self.view.scope_name(region.a)
        line_classes = {
            'keyword.control.header.todo': 'header',
            'meta.item.todo.pending': 'open',
            'meta.item.todo.completed': 'done',
            'meta.item.todo.cancelled': 'cancelled',
            'meta.punctuation.separator.todo': 'sep',
            'meta.punctuation.archive.todo': 'sep-archive',
            'notes.todo': 'note',
        }
        css_class = next((value for key, value in line_classes.items() if key in scope), 'empty-line')
        if css_class not in ('open', 'done', 'cancelled', 'note'):
            return f'<span class="{css_class}">{escape(self.view.substr(region))}</span>'

        scopes = self.extracting_scopes(region)
        if not scopes:
            return f'<span class="{css_class}">{escape(self.view.substr(region))}</span>'
        indent = escape(self.view.substr(sublime.Region(region.a, scopes[0].a)))
        content = ''.join(self.render_scope(part, css_class) for part in scopes)
        return f'<span class="{css_class}">{indent}{content}</span>'

    def render_scope(self, region, line_class):
        scope = self.view.scope_name(region.a)
        text = self.view.substr(region)
        escaped = escape(text)
        if 'bullet' in scope and line_class != 'note':
            state = {'open': 'pending', 'done': 'done', 'cancelled': 'cancelled'}[line_class]
            return f'<span class="bullet-{state}">{escaped}</span>'
        tags = {
            'tag.todo.completed': 'tag-done',
            'tag.todo.cancelled': 'tag-cancelled',
            'tag.todo.today': 'tag-today',
            'tag.todo.critical': 'tag-critical',
            'tag.todo.high': 'tag-high',
            'tag.todo.low': 'tag-low',
            'meta.tag': 'tag',
        }
        css_class = next((value for key, value in tags.items() if key in scope), None)
        if css_class and line_class != 'note':
            return f'<span class="{css_class}">{escaped}</span>'
        if line_class in ('open', 'note'):
            if 'italic' in scope:
                content = escape(text.strip('_*'))
                return f'<i>{content}</i>' if content else ''
            if 'bold' in scope:
                content = escape(text.strip('_*'))
                return f'<b>{content}</b>' if content else ''
            if 'url' in scope:
                url = escape(text.strip('<>'), quote=True)
                return f'<a href="{url}">{url}</a>' if url else ''
        return escaped

    def produce_html_from_template(self, title, html_doc):
        css = self.export_css()
        template = sublime.load_resource('Packages/PlainTasks/templates/template.html')
        # Substitute once so placeholders in user text remain literal.
        return Template(template).substitute(title=escape(title), content='\n'.join(html_doc), css='\n'.join(css))

    def export_css(self):
        scheme = self.view.settings().get('color_scheme', '')
        if scheme.endswith('tmTheme'):
            try:
                return theme_to_css(parse_string(sublime.load_resource(scheme)))
            except (OSError, ValueError):
                return default_ccsl
        # Sublime resolves modern color schemes, variables, and inherited rules.
        selectors = {
            'body': 'text.todo',
            'a': 'text.todo todo.url',
            '.header': 'text.todo keyword.control.header.todo',
            '.note': 'text.todo notes.todo',
            '.open': 'text.todo meta.item.todo.pending',
            '.done': 'text.todo meta.item.todo.completed',
            '.cancelled': 'text.todo meta.item.todo.cancelled',
            '.bullet-pending': 'text.todo punctuation.definition.bullet.pending.todo',
            '.bullet-done': 'text.todo punctuation.definition.bullet.completed.todo',
            '.bullet-cancelled': 'text.todo punctuation.definition.bullet.cancelled.todo',
            '.tag': 'text.todo meta.tag.todo',
            '.tag-done': 'text.todo string.other.tag.todo.completed',
            '.tag-cancelled': 'text.todo string.other.tag.todo.cancelled',
            '.tag-today': 'text.todo string.other.tag.todo.today',
            '.tag-critical': 'text.todo string.other.tag.todo.critical',
            '.tag-high': 'text.todo string.other.tag.todo.high',
            '.tag-low': 'text.todo string.other.tag.todo.low',
            '.sep': 'text.todo meta.punctuation.separator.todo',
            '.sep-archive': 'text.todo meta.punctuation.archive.todo',
        }
        css = []
        for selector, scope in selectors.items():
            style = self.view.style_for_scope(scope)
            props = [f'{key}: {style[value]};' for key, value in
                     (('color', 'foreground'), ('background-color', 'background')) if style.get(value)]
            if style.get('bold'):
                props.append('font-weight: bold;')
            if style.get('italic'):
                props.append('font-style: italic;')
            css.append(f'{selector} {{ {" ".join(props)} }}')
        return css

    def extracting_scopes(self, region):
        """Return disjoint inline scopes clipped to this line, in text order."""
        if region.empty():
            return []
        scopes = []
        start = region.a
        previous = self.view.scope_name(start)
        for point in range(start + 1, region.b):
            current = self.view.scope_name(point)
            if current != previous:
                scopes.append(sublime.Region(start, point))
                start, previous = point, current
        scopes.append(sublime.Region(start, region.b))
        return scopes
