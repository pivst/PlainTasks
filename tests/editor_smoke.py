"""Real Sublime 4215 checks. Copy only this file to an isolated Packages/User.

Run plain_tasks_smoke_test with output_path, or create a sibling
plain-tasks-smoke-request.json before launch containing {"output_path": "..."}.
No API doubles are used. Scratch views are closed after testing.
"""
from datetime import datetime, timedelta
from html import unescape
import importlib
import json
from pathlib import Path
import re
import sys
import traceback

import sublime
import sublime_plugin


class PlainTasksSmokeSetTextCommand(sublime_plugin.TextCommand):
    def run(self, edit, text):
        self.view.replace(edit, sublime.Region(0, self.view.size()), text)


class PlainTasksSmokeTestCommand(sublime_plugin.WindowCommand):
    def run(self, output_path=None):
        self.output = Path(output_path or str(Path(sublime.packages_path()).parent / 'plaintasks-smoke.json'))
        self.checks = []
        self.views = []
        self.report = {
            'build': sublime.version(), 'python': sys.version,
            'platform': sublime.platform(), 'arch': sublime.arch(),
            'packages_path': sublime.packages_path(), 'sys_path': list(sys.path),
            'dont_write_bytecode': sys.dont_write_bytecode,
            'checks': self.checks,
            'manual_pending': ['Native keyboard shortcuts', 'Save As dialog',
                               'External browser launch', 'Visual popup layout'],
        }
        try:
            self.tasks = importlib.import_module('PlainTasks.PlainTasks')
            self.dates = importlib.import_module('PlainTasks.PlainTasksDates')
            self.export = importlib.import_module('PlainTasks.PlainTasksToHTML')
            self.report['plugin_file'] = self.tasks.__file__
            self.report['dateutil_available'] = self.dates.dateutil_parser is not None
            self.cases = [
                ('runtime_4215_python314', '', self.runtime),
                ('package_resources', '', self.resources),
                ('syntax_unicode', '项目:\n ☐ 中文任务\n ✔ 完成 @done(26-10-13 12:00)\n ✘ 取消 @cancelled(26-10-13 12:00)', self.syntax),
                ('new_task', '中文任务', self.new),
                ('complete_reopen', ' ☐ 中文任务', self.complete),
                ('cancel_reopen', ' ☐ 中文任务', self.cancel),
                ('multiple_selections', ' ☐ 第一项\n ☐ 第二项', self.multiple),
                ('archive', '项目:\n ☐ 保留\n ✔ 完成 @done(26-10-13 12:00)\n ✘ 取消 @cancelled(26-10-13 12:00)', self.archive),
                ('taskpaper', ' - 中文任务', self.taskpaper),
                ('due_short_relative', ' ☐ 任务 @due(+2w)', self.due),
                ('dateutil_named_month', '', self.named_date),
                ('calendar_leap_navigation', ' ☐ 任务 @due()', self.calendar),
                ('hover_at_zero', '☐ 中文任务', self.hover),
                ('html_bundled_theme', '项目:\n ☐ 中文 <任务>&\" **加粗** *倾斜* <https://example.com/?q=1&x=2> @high', self.html),
                ('html_modern_scheme', ' ☐ 中文任务 @high\n ✔ 完成 @done(26-10-13 12:00)\n ✘ 取消 @cancelled(26-10-13 12:00)', self.modern_html),
                ('html_literal_delimiters', ' ☐ **_literal_** *under_score*', self.delimiters),
                ('file_link_parsing', '', self.links),
                ('windows_keymap', '', self.keymap),
                ('crlf_unicode_file', '', self.crlf),
            ]
            self.next_case()
        except Exception:
            self.checks.append({'name': 'plugin_import', 'ok': False, 'error': traceback.format_exc()})
            self.finish()

    def next_case(self):
        if not self.cases:
            self.finish()
            return
        name, text, check = self.cases.pop(0)
        view = self.window.new_file()
        self.views.append(view)
        view.set_scratch(True)
        view.set_name('PlainTasks smoke: ' + name)
        view.assign_syntax('Packages/PlainTasks/PlainTasks.sublime-syntax')
        view.settings().set('translate_tabs_to_spaces', True)
        view.settings().set('done_date', False)
        view.run_command('plain_tasks_smoke_set_text', {'text': text})
        def execute():
            try:
                check(view)
                self.checks.append({'name': name, 'ok': True})
            except Exception:
                self.checks.append({'name': name, 'ok': False, 'error': traceback.format_exc(),
                                    'text': self.text(view)})
            view.hide_popup()
            sublime.set_timeout(self.next_case, 100)
        sublime.set_timeout(execute, 150)

    @staticmethod
    def text(view):
        return view.substr(sublime.Region(0, view.size()))

    @staticmethod
    def select(view, *positions):
        view.sel().clear()
        for position in positions:
            view.sel().add(sublime.Region(position))

    @staticmethod
    def require(condition, message):
        if not condition:
            raise AssertionError(message)

    def runtime(self, view):
        self.require(sublime.version() == '4215', 'Expected exact build 4215')
        self.require(sys.version_info[:2] == (3, 14), 'Expected embedded Python 3.14')

    def resources(self, view):
        for resource in ('templates/template.html', 'tasks.hidden-tmTheme',
                         'messages/Tutorial.todo', '.python-version'):
            self.require(bool(sublime.load_resource('Packages/PlainTasks/' + resource)), resource)
        for resource in ('messages/Tutorial.todo', 'PlainTasks (Windows).sublime-settings'):
            self.window.run_command('plain_tasks_open_resource', {'resource': resource})
            output = self.window.active_view()
            self.views.append(output)
            self.require(output.is_read_only() == (not resource.endswith('.todo')) and output.size() > 0,
                         'compressed package menu: ' + resource)
            self.require(self.text(output) == sublime.load_resource('Packages/PlainTasks/' + resource), 'resource text')

    def syntax(self, view):
        for token, selector in [('项目', 'keyword.control.header.todo'), ('中文', 'meta.item.todo.pending'),
                                ('完成', 'meta.item.todo.completed'), ('取消', 'meta.item.todo.cancelled')]:
            self.require(view.match_selector(self.text(view).index(token), selector), selector)

    def new(self, view):
        view.run_command('plain_tasks_new')
        self.require('☐' in self.text(view) and '中文任务' in self.text(view), 'new task command')

    def complete(self, view):
        view.run_command('plain_tasks_complete')
        self.require('✔ 中文任务 @done' in self.text(view), 'complete')
        view.run_command('plain_tasks_complete')
        self.require(self.text(view) == ' ☐ 中文任务', 'reopen')

    def cancel(self, view):
        view.run_command('plain_tasks_cancel')
        self.require('✘ 中文任务 @cancelled' in self.text(view), 'cancel')
        view.run_command('plain_tasks_cancel')
        self.require(self.text(view) == ' ☐ 中文任务', 'reopen cancelled')

    def multiple(self, view):
        self.select(view, 1, self.text(view).index('第二项'))
        view.run_command('plain_tasks_complete')
        self.require(self.text(view).count('✔') == 2, 'both selections complete')

    def archive(self, view):
        view.run_command('plain_tasks_archive')
        before, after = self.text(view).split('Archive:')
        self.require('☐ 保留' in before and '完成' not in before, 'active tasks retained')
        self.require('完成' in after and '取消' in after and '@project(项目)' in after, 'archived tasks')

    def taskpaper(self, view):
        view.settings().set('taskpaper_compatible', True)
        view.run_command('plain_tasks_complete')
        self.require(' - 中文任务 @done' == self.text(view), 'TaskPaper completed')
        view.run_command('plain_tasks_complete')
        self.require(self.text(view) == ' - 中文任务', 'TaskPaper reopened')

    def due(self, view):
        self.select(view, self.text(view).index('+2w'))
        view.run_command('plain_tasks_replace_short_date')
        self.require('@due(' in self.text(view) and '+2w' not in self.text(view), 'relative date expanded')
        stamp = re.search(r'@due(\([^)]*\))', self.text(view)).group(1)
        self.require(datetime.strptime(stamp, '(%y-%m-%d %H:%M)').date() ==
                     (datetime.now() + timedelta(days=14)).date(), 'relative date adds 14 days')
        view.run_command('plain_tasks_toggle_highlight_past_due')

    def named_date(self, view):
        date, error = self.dates.parse_date('2026-Oct-13', default=datetime(2026, 1, 1))
        self.require(error is None and date.date().isoformat() == '2026-10-13', 'dateutil must be installed for named months')

    def calendar(self, view):
        command = self.dates.PlainTasksCalendar(view)
        command.run(None, point=self.text(view).index('()') + 1)
        self.require(view.is_popup_visible(), 'calendar popup')
        generated = []
        original = command.generate_calendar
        def record(date=None):
            generated.append(date)
            return original(date)
        command.generate_calendar = record
        command.action('next_month:2028-1-31-12-0')
        self.require(generated[-1] == datetime(2028, 2, 29, 12), 'month end clamps to leap day')
        command.action('next_year:2028-2-29-12-0')
        self.require(generated[-1] == datetime(2029, 2, 28, 12), 'next year clamps leap day')
        command.action('calendar:2028-2-31-12-0')
        self.require(generated[-1] == datetime(2028, 2, 29, 12), 'calendar clamps invalid day')

    def hover(self, view):
        listener = self.tasks.PlainTasksHover(view)
        listener.on_hover(0, sublime.HOVER_TEXT)
        self.require(view.is_popup_visible(), 'hover at zero opens popup')
        listener.exec_action('complete\v0')
        self.require('✔ 中文任务' in self.text(view), 'hover action completes task')

    def render(self, view):
        command = self.export.PlainTasksConvertToHtml(view)
        return command.produce_html_from_template('中文<&"',
            [command.render_line(r) for r in view.split_by_newlines(sublime.Region(0, view.size()))])

    def html(self, view):
        view.settings().set('color_scheme', 'Packages/PlainTasks/tasks.hidden-tmTheme')
        document = self.render(view)
        self.require('&lt;任务&gt;&amp;&quot;' in document, 'escaped user content')
        self.require('<b>加粗</b>' in document and '<i>倾斜</i>' in document, 'real syntax markup')
        self.require('href="https://example.com/?q=1&amp;x=2"' in document, 'URL href')
        self.require('tag-high' in document and 'body {' in document, 'CSS')
        output = self.window.new_file()
        self.views.append(output)
        output.set_scratch(True)
        output.assign_syntax('Packages/HTML/HTML.sublime-syntax')
        output.run_command('append', {'characters': document})
        self.require(self.text(output) == document, 'output view append token')
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.with_suffix('.html').write_text(document, encoding='utf-8')

    def modern_html(self, view):
        view.settings().set('color_scheme', 'Packages/Color Scheme - Default/Mariana.sublime-color-scheme')
        document = self.render(view)
        self.require('background-color:' in document and '中文任务' in document, 'resolved modern scheme styles')
        css = self.export.PlainTasksConvertToHtml(view).export_css()
        for token, selector in [('完成', '.done'), ('@done', '.tag-done'), ('@cancelled', '.tag-cancelled')]:
            actual = view.style_for_scope(view.scope_name(self.text(view).index(token)))
            rule = next(line for line in css if line.startswith(selector + ' {'))
            self.require('color: ' + actual['foreground'] + ';' in rule, 'resolved scope color ' + selector)
            self.require(('font-style: italic;' if actual.get('italic') else 'font-style: normal;') in rule,
                         'resolved font style ' + selector)

    def delimiters(self, view):
        document = self.render(view)
        visible = unescape(re.sub('<[^>]+>', '', document.split('<pre')[1].split('</pre>')[0]))
        self.require('_literal_' in visible and 'under_score' in visible, 'literal underscores within markup preserved')

    def links(self, view):
        command = self.tasks.PlainTasksOpenLinkCommand(view)
        self.require(command.parse_link('no link')[0] is None, 'invalid link returns safely')
        for text in ('[文档](中文 目录/任务.txt ":12:3")', '[[中文 目录/任务.txt::12:3]]',
                     r'[doc](C:\中文 目录\任务.txt ":12:3")'):
            filename, _, line, column, _ = command.parse_link(text)
            self.require('任务.txt' in filename and (line, column) == ('12', '3'), text)

    def keymap(self, view):
        keys = sublime.decode_value(sublime.load_resource('Packages/PlainTasks/Default (Windows).sublime-keymap'))
        self.require(any(k['keys'] == ['ctrl+d'] and k['command'] == 'plain_tasks_complete' for k in keys), 'Windows ctrl+d')

    def crlf(self, view):
        path = self.output.parent / '中文 空格' / '验收.todo'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes('项目:\r\n ☐ 中文任务\r\n'.encode('utf-8'))
        view.run_command('plain_tasks_smoke_set_text', {'text': path.read_text(encoding='utf-8')})
        view.set_line_endings('Windows')
        self.select(view, self.text(view).index('中文任务'))
        view.run_command('plain_tasks_complete')
        self.require('✔ 中文任务' in self.text(view) and view.line_endings() == 'Windows', 'CRLF edit')
        view.retarget(str(path))
        view.run_command('save')
        data = path.read_bytes()
        self.require(b'\r\n' in data and '✔ 中文任务'.encode('utf-8') in data, 'CRLF Unicode save')

    def finish(self):
        self.report['passed'] = sum(c['ok'] for c in self.checks)
        self.report['failed'] = sum(not c['ok'] for c in self.checks)
        self.report['ok'] = self.report['failed'] == 0 and bool(self.checks)
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')
        for view in self.views:
            if view.is_valid():
                view.close()
        print('PlainTasks smoke:', self.output, 'PASS' if self.report['ok'] else 'FAIL',
              self.report['passed'], 'passed,', self.report['failed'], 'failed')


def plugin_loaded():
    request = Path(__file__).parent / 'plain-tasks-smoke-request.json'
    if request.exists():
        args = json.loads(request.read_text(encoding='utf-8'))
        request.unlink()
        sublime.set_timeout(lambda: sublime.active_window().run_command('plain_tasks_smoke_test', args), 1500)
