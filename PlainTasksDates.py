"""Date parsing, due highlighting, and calendar commands."""

import calendar
import re
from calendar import monthrange
from datetime import datetime, timedelta
from html import escape

import sublime
import sublime_plugin

from .APlainTasksCommon import PlainTasksBase, PlainTasksEnabled, PlainTasksFold

MARK_SOON = sublime.DRAW_NO_FILL
MARK_INVALID = sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE | sublime.DRAW_SQUIGGLY_UNDERLINE

try:
    from dateutil import parser as dateutil_parser
except ImportError:
    dateutil_parser = None

DATE_FORMAT = "(%y-%m-%d %H:%M)"
REMAIN_SETTING = "plain_tasks_remain_time_phantoms"
_LIFECYCLE = object()
SHORT_DATE = re.compile(
    r"(?:(?P<date>(?:--)?\d+(?:[-.]\d+){0,2})(?:\s+(?P<time>\d*:\d*))?|(?P<time_only>\d*:\d*))?"
)
RELATIVE_DATE = re.compile(
    r"""
    \+\+?\s*
    (?:(?P<days>(?>\d*))\s*(?P<unit>[dw])?\s*(?![:.]))?
    (?:(?P<hours>\d*)[:.](?P<minutes>\d*))?
""",
    re.I | re.X,
)
CREATED_TAG = re.compile(r"@created\(([^()\n]*)\)")
DUE_TAG = re.compile(r"@due\(([^()\n]*)\)")
DURATION_TAG = re.compile(r"(?<!\S)@(lasted|wasted|total)\(([^()\n]*)\)")
DURATION = re.compile(
    r"\s*(?:(?P<days>\d+)\s+days?\s*,?\s*)?(?:(?P<hours>\d+):(?P<minutes>\d+)(?::(?P<seconds>\d+))?|(?P<decimal>\d+\.\d+))?\s*"
)


def _date_error(error, date=None):
    fields = (date.year, date.month, date.day, date.hour, date.minute) if date else (None,) * 5
    return None, (error, *fields)


def _normalize_timezone(date, default):
    """Compare explicit offsets in the local/default timezone used by commands."""
    if date.tzinfo is not None:
        if default.tzinfo is None:
            return date.astimezone().replace(tzinfo=None)
        return date.astimezone(default.tzinfo)
    return date.replace(tzinfo=default.tzinfo)


def _bare_date(text):
    text = text.strip()
    if text.startswith("(") and text.endswith(")"):
        return text[1:-1].strip()
    return text


def is_yearfirst(date_format: str) -> bool:
    return date_format.strip("(  )").startswith(("%y", "%Y"))


def is_dayfirst(date_format: str) -> bool:
    return date_format.strip("(  )").startswith("%d")


def _convert_date(matchstr: str, now: datetime) -> tuple[int, int, int, int, int]:
    match = SHORT_DATE.fullmatch(matchstr.strip())
    if match is None:
        raise ValueError("Use a date, day, month-day, or hour:minute")
    year, month, day = now.year, now.month, now.day
    date_text = match["date"]
    if date_text:
        current_month = date_text.startswith("--")
        parts = [int(part) for part in re.split(r"[-.]", date_text.removeprefix("--"))]
        if current_month and len(parts) != 1:
            raise ValueError("-- must be followed by a day of this month")
        if len(parts) == 3:
            year, month, day = parts
            if year < 100:
                year += 2000
        elif len(parts) == 2:
            month, day = parts
            if month < now.month:
                year += 1
        else:
            day = parts[0] or now.day
            if parts[0] and not current_month and day <= now.day:
                year, month = divmod(year * 12 + month, 12)
                month += 1
    hour, minute = now.hour, now.minute
    time_text = match["time"] or match["time_only"]
    if time_text:
        hour_text, minute_text = time_text.split(":")
        hour = int(hour_text) if hour_text else hour
        minute = int(minute_text) if minute_text else minute
    return year, month, day, hour, minute


def convert_date(matchstr: str, now: datetime) -> tuple[datetime | None, tuple | None]:
    year = month = day = hour = minute = None
    try:
        year, month, day, hour, minute = _convert_date(matchstr, now)
        date = datetime(year, month, day, hour, minute, tzinfo=now.tzinfo)
    except (ValueError, OverflowError) as e:
        return None, (e, year, month, day, hour, minute)
    else:
        return date, None


def increase_date(view, region, text, now, date_format):
    text = _bare_date(text)
    match = RELATIVE_DATE.fullmatch(text)
    if match is None:
        return None, (ValueError("Use +days, +weeksw, or +hours:minutes"), 0, 0, 0)
    # ++ is relative to creation; an invalid creation tag must not change the base silently.
    if text.startswith("++") and view is not None:
        created = CREATED_TAG.search(view.substr(view.line(region)))
        if created:
            created_date, error = parse_date(
                created.group(1),
                date_format=date_format,
                yearfirst=is_yearfirst(date_format),
                dayfirst=is_dayfirst(date_format),
                default=now,
            )
            if error:
                return None, (ValueError(f"Invalid @created date: {created.group(1)}"), 0, 0, 0)
            else:
                now = created_date
    amount = hour = minute = 0
    try:
        number = int(match["days"] or 0)
        hour = int(match["hours"] or 0)
        minute = int(match["minutes"] or 0)
        if not (number or hour or minute) or (not number and match["unit"]):
            number = 1
        amount = number * 7 if (match["unit"] or "").lower() == "w" else number
        return now + timedelta(days=amount, hours=hour, minutes=minute), None
    except (ValueError, OverflowError) as e:
        return None, (e, amount, hour, minute)


def expand_short_date(view, start, end, now, date_format):
    line = view.line(start)
    while start >= line.a and view.substr(start) != "(":
        start -= 1
    while end < line.b and view.substr(end) != ")":
        end += 1
    if start < line.a or view.substr(end) != ")":
        error = (
            ValueError("Date tag must contain matching parentheses"),
            None,
            None,
            None,
            None,
            None,
        )
        return None, error, line
    region = sublime.Region(start + 1, end)
    text = view.substr(region)
    if text.strip().startswith("+"):
        date, error = increase_date(view, region, text, now, date_format)
    else:
        date, error = parse_date(
            text,
            date_format,
            yearfirst=is_yearfirst(date_format),
            dayfirst=is_dayfirst(date_format),
            default=now,
        )

    return date, error, sublime.Region(start, end + 1)


def parse_date(
    date_string: str,
    date_format: str = DATE_FORMAT,
    yearfirst: bool | None = None,
    dayfirst: bool | None = None,
    default: datetime | None = None,
) -> tuple[datetime | None, tuple | None]:
    """Parse a date while preserving PlainTasks' forward-looking short dates."""
    default = default if default is not None else datetime.now().replace(second=0, microsecond=0)
    yearfirst = is_yearfirst(date_format) if yearfirst is None else yearfirst
    dayfirst = is_dayfirst(date_format) if dayfirst is None else dayfirst
    try:
        date = datetime.strptime(date_string, date_format)
    except ValueError:
        bare_date_string = _bare_date(date_string)
        if bare_date_string.startswith("-") and not bare_date_string.startswith("--"):
            return _date_error(ValueError("Use --day for a day of the current month"))
        short_match = SHORT_DATE.fullmatch(bare_date_string)
        if short_match:
            date_part = short_match["date"] or ""
            if (
                not date_part
                or date_part.startswith("--")
                or (
                    len(re.split(r"[-.]", date_part)) < 3
                    and len(date_part.split("-")[0].split(".")[0]) <= 2
                )
            ):
                return convert_date(bare_date_string, default)
        if dateutil_parser is None:
            return convert_date(bare_date_string, default)
        try:
            date = dateutil_parser.parse(
                bare_date_string, yearfirst=yearfirst, dayfirst=dayfirst, default=default
            )
        except (ValueError, OverflowError) as error:
            return _date_error(error)
    if date.year < 1000 and "%y" in date_format:
        return None, (
            "Years before 1000 require %Y to avoid losing the century",
            date.year,
            date.month,
            date.day,
            date.hour,
            date.minute,
        )
    return _normalize_timezone(date, default), None


def format_delta(view, delta):
    seconds = int(delta.total_seconds())
    sign = "-" if seconds < 0 else ""
    days, seconds = divmod(abs(seconds), 86400)
    parts = [f"{days} day" + ("s" if days != 1 else "")] if days else []
    if view.settings().get("decimal_minutes", False):
        if seconds:
            parts.append(f"{seconds / 3600:.2f}")
    else:
        if seconds:
            hours, seconds = divmod(seconds, 3600)
            minutes, seconds = divmod(seconds, 60)
            parts.append(f"{hours}:{minutes:02}" + (f":{seconds:02}" if seconds else ""))
    return sign + ", ".join(parts) if parts else ""


class PlainTasksViewEventListener(sublime_plugin.ViewEventListener):
    def __init__(self, view):
        super().__init__(view)
        self.lifecycle = _LIFECYCLE

    @classmethod
    def is_applicable(cls, settings):
        return settings.get("syntax") == "Packages/PlainTasks/PlainTasks.sublime-syntax"

    def is_current(self):
        return (
            self.lifecycle is _LIFECYCLE
            and self.view.is_valid()
            and self.is_applicable(self.view.settings())
        )


class PlainTasksToggleHighlightPastDue(PlainTasksEnabled):
    def run(self, edit):
        highlight_on = self.view.settings().get("highlight_past_due", True)
        self.view.erase_regions("past_due")
        self.view.erase_regions("due_soon")
        self.view.erase_regions("misformatted")
        if not highlight_on:
            self.view.settings().set(REMAIN_SETTING, [])
            return

        pattern = r"@due(\([^()\n]*\))"
        dates_strings = []
        dates_regions = self.view.find_all(pattern, 0, "\\1", dates_strings)
        if not dates_regions:
            self.view.settings().set(REMAIN_SETTING, [])
            return

        past_due, due_soon, misformatted, phantoms = self.group_due_tags(
            dates_strings, dates_regions
        )

        scope_past_due = self.view.settings().get(
            "scope_past_due", "string.other.tag.todo.critical"
        )
        scope_due_soon = self.view.settings().get("scope_due_soon", "string.other.tag.todo.high")
        scope_misformatted = self.view.settings().get(
            "scope_misformatted", "string.other.tag.todo.low"
        )
        icon_past_due = self.view.settings().get("icon_past_due", "circle")
        icon_due_soon = self.view.settings().get("icon_due_soon", "dot")
        icon_misformatted = self.view.settings().get("icon_misformatted", "")
        self.view.add_regions("past_due", past_due, scope_past_due, icon_past_due)
        self.view.add_regions("due_soon", due_soon, scope_due_soon, icon_due_soon, MARK_SOON)
        self.view.add_regions(
            "misformatted", misformatted, scope_misformatted, icon_misformatted, MARK_INVALID
        )

        if self.view.settings().get("show_remain_due", False):
            self.view.settings().set(REMAIN_SETTING, phantoms)
        else:
            self.view.settings().set(REMAIN_SETTING, [])

    def group_due_tags(self, dates_strings, dates_regions):
        past_due, due_soon, misformatted, phantoms = [], [], [], []
        date_format = self.view.settings().get("date_format", DATE_FORMAT)
        yearfirst = is_yearfirst(date_format)
        dayfirst = is_dayfirst(date_format)
        now = datetime.now()
        default = now.replace(second=0, microsecond=0)
        due_soon_threshold = self.view.settings().get("highlight_due_soon", 24) * 60 * 60
        show_remain = self.view.settings().get("show_remain_due", False)

        for text, region in zip(dates_strings, dates_regions, strict=True):
            if any(s in self.view.scope_name(region.a) for s in ("completed", "cancelled")):
                continue
            if _bare_date(text).startswith("+"):
                date, error = increase_date(self.view, region, text, default, date_format)
            else:
                date, error = parse_date(
                    text,
                    date_format=date_format,
                    yearfirst=yearfirst,
                    dayfirst=dayfirst,
                    default=default,
                )
            if error:
                misformatted.append(region)
            else:
                if now >= date:
                    past_due.append(region)
                    if show_remain:
                        phantoms.append((region.a, "-" + format_delta(self.view, now - date)))
                else:
                    if show_remain:
                        phantoms.append((region.a, format_delta(self.view, date - now)))
                    if due_soon_threshold:
                        td = date - now
                        time_left = td.total_seconds()
                        if time_left < due_soon_threshold:
                            due_soon.append(region)
        return past_due, due_soon, misformatted, phantoms


class PlainTasksDueEvents(PlainTasksViewEventListener):
    def __init__(self, view):
        super().__init__(view)
        self.generation = 0

    def refresh(self):
        self.generation += 1
        if self.is_current():
            self.view.run_command("plain_tasks_toggle_highlight_past_due")

    on_activated = refresh
    on_post_save = refresh
    on_load = refresh

    def on_modified_async(self):
        self.generation += 1
        if not self.is_current():
            return
        generation = self.generation
        sublime.set_timeout(lambda: self.update_if_current(generation), 300)

    def update_if_current(self, generation):
        if generation == self.generation and self.is_current():
            self.refresh()

    def on_close(self):
        self.generation += 1


class PlainTasksFoldToDueTags(PlainTasksFold):
    def run(self, edit):
        if not self.view.settings().get("highlight_past_due", True):
            return sublime.message_dialog("highlight_past_due setting must be true")
        self.view.run_command("plain_tasks_toggle_highlight_past_due")
        dues = sorted(
            self.view.line(r)
            for r in (self.view.get_regions("past_due") + self.view.get_regions("due_soon"))
        )
        if not dues:
            return sublime.message_dialog("No overdue tasks.\nCongrats!")
        self.exec_folding(self.add_projects_and_notes(dues))


class PlainTasksCalculateTotalTimeForProject(PlainTasksEnabled):
    def run(self, edit, start):
        line = self.view.line(int(start))
        total, eol = self.calc_total_time_for_project(line)
        if total:
            self.view.insert(edit, eol, f" @total({format_delta(self.view, total)})")

    def calc_total_time_for_project(self, line):
        eol = line.end()
        if eol >= self.view.size():
            return timedelta(), eol
        project_block = self.view.indented_region(eol + 1)
        project_text = self.view.substr(project_block)
        total = timedelta()
        # Subproject @total tags summarize the same children; count only source durations.
        for match in DURATION_TAG.finditer(project_text):
            if match[1] != "total":
                duration = parse_duration(match[2])
                if duration is not None:
                    total += duration
        return total, eol


def parse_duration(text):
    """Parse the clock and decimal-hour formats emitted by format_delta."""
    match = DURATION.fullmatch(text)
    if not match or not any(match.groupdict().values()):
        return None
    try:
        minutes, seconds = int(match["minutes"] or 0), int(match["seconds"] or 0)
        if minutes >= 60 or seconds >= 60:
            return None
        return timedelta(
            days=int(match["days"] or 0),
            hours=float(match["decimal"]) if match["decimal"] else int(match["hours"] or 0),
            minutes=minutes,
            seconds=seconds,
        )
    except ValueError, OverflowError:
        return None


def calculate_elapsed(started, toggles, ended, date_format):
    times = [datetime.strptime(text, date_format) for text in (started, *toggles, ended)]
    try:
        if any(following < current for current, following in zip(times, times[1:], strict=False)):
            raise ValueError("Time tracking dates must be in chronological order")
        return sum(
            (stop - start for start, stop in zip(times[::2], times[1::2], strict=False)),
            timedelta(),
        )
    except TypeError as error:
        raise ValueError("Time tracking dates must use consistent timezones") from error


def _elapsed_tag(view, duration, tag, date_format):
    text = format_delta(view, duration) or ("a bit" if "%H" in date_format else "less than day")
    return f" @{tag}({text})"


class PlainTasksCalculateTimeForTask(PlainTasksEnabled):
    def run(self, edit, started_matches, toggle_matches, now, eol, tag="lasted"):
        if not started_matches:
            return
        date_format = self.view.settings().get("date_format", DATE_FORMAT)
        try:
            duration = calculate_elapsed(started_matches[0], toggle_matches, now, date_format)
        except ValueError as error:
            sublime.status_message(f"PlainTasks: invalid time tracking date: {error}")
            return
        eol = int(eol)
        if self.view.substr(sublime.Region(eol - 2, eol)) == "  ":
            eol -= 2  # keep double whitespace at eol
        self.view.insert(edit, eol, _elapsed_tag(self.view, duration, tag, date_format))


class PlainTasksReCalculateTimeForTasks(PlainTasksEnabled):
    def run(self, edit):
        date_format = self.view.settings().get("date_format", DATE_FORMAT)
        default_now = datetime.now().astimezone().strftime(date_format)
        # Process each selected line once and from the end so replacements preserve offsets.
        lines = {line.a: line for region in self.view.sel() for line in self.view.lines(region)}
        for _, line in sorted(lines.items(), reverse=True):
            current_scope = self.view.scope_name(line.a)
            if not any(s in current_scope for s in ("completed", "cancelled")):
                continue

            line_contents = self.view.substr(line)

            started = re.search(r"@started(\([^()\n]*\))", line_contents)
            if not started:
                continue
            done = re.search(r"@(?:done|cancelled|canceled)\s*(\([^()\n]*\))", line_contents)
            toggles = re.findall(r"@toggle(\([^()\n]*\))", line_contents)
            try:
                duration = calculate_elapsed(
                    started[1], toggles, done[1] if done else default_now, date_format
                )
            except ValueError as error:
                sublime.status_message(f"PlainTasks: invalid time tracking date: {error}")
                continue
            line_contents = re.sub(r"[ \t]@(?:lasted|wasted)\([^()\n]*\)", "", line_contents)
            tag = "lasted" if "completed" in current_scope else "wasted"
            suffix = "  " if line_contents.endswith("  ") else ""
            if suffix:
                line_contents = line_contents[:-2]
            self.view.replace(
                edit,
                line,
                line_contents + _elapsed_tag(self.view, duration, tag, date_format) + suffix,
            )


class PlainTaskInsertDate(PlainTasksBase):
    def run_command(self, edit, region=None, date=None):
        if region is not None:
            y, m, d, H, M = date
            region = sublime.Region(*region)
            stamp = datetime(y, m, d, H, M).astimezone().strftime(self.date_format)
            self.view.replace(edit, region, stamp + " ")
            self.view.sel().clear()
            self.view.sel().add(sublime.Region(self.view.line(region).b))
            return

        stamp = datetime.now().astimezone().strftime(self.date_format)
        for selection in reversed(list(self.view.sel())):
            self.view.insert(edit, selection.b, stamp)


class PlainTasksReplaceShortDate(PlainTasksBase):
    def run_command(self, edit):
        if not self.view.sel():
            return
        s = self.view.sel()[0]
        date, error, region = expand_short_date(
            self.view, s.a, s.b, datetime.now(), self.date_format
        )

        if not date:
            sublime.error_message(f"PlainTasks: {_date_error_text(error)}")
            return

        date = date.astimezone().strftime(self.date_format)
        self.view.replace(edit, region, date)
        offset = region.a + len(date)
        self.view.sel().clear()
        self.view.sel().add(sublime.Region(offset, offset))


def _due_text(view, delta):
    setting = "due_overdue_format" if delta.startswith("-") else "due_remain_format"
    default = "{time} overdue" if delta.startswith("-") else "{time} remaining"
    template = view.settings().get(setting, default)
    try:
        return template.format(time=delta.removeprefix("-") or "a little bit")
    except KeyError, ValueError:
        return default.format(time=delta.removeprefix("-") or "a little bit")


def _date_error_text(error):
    return str(error[0])


class PlainTasksPreviewShortDate(PlainTasksViewEventListener):
    def __init__(self, view):
        super().__init__(view)
        self.phantoms = sublime.PhantomSet(view, "plain_tasks_preview_short_date")

    def on_selection_modified_async(self):
        if not self.is_current():
            self.phantoms.update([])
            return
        selections = self.view.sel()
        if len(selections) != 1 or not (
            selections[0].empty() and "meta.tag.todo" in self.view.scope_name(selections[0].a)
        ):
            self.phantoms.update([])
            return
        rgn = self.view.extract_scope(selections[0].a)
        text = self.view.substr(rgn)
        match = DUE_TAG.match(text)
        if not match:
            self.phantoms.update([])
            return
        preview_offset = self.view.settings().get("due_preview_offset", 0)
        date_format = self.view.settings().get("date_format", DATE_FORMAT)
        start = rgn.a + 5  # within parenthesis
        now = datetime.now().replace(second=0, microsecond=0)
        date, error, region = expand_short_date(self.view, start, start, now, date_format)

        upd = []
        if not error:
            if now >= date:
                delta = "-" + format_delta(self.view, now - date)
            else:
                delta = format_delta(self.view, date - now)
            content = _due_text(self.view, delta)
            if content:
                if self.view.settings().get("show_remain_due", False):
                    # replace existing remain/overdue phantom
                    phantoms = list(self.view.settings().get(REMAIN_SETTING, []))
                    for index, (point, _) in enumerate(phantoms):
                        if point == region.a - 4:
                            phantoms[index] = [point, str(delta)]
                            self.view.settings().set(REMAIN_SETTING, phantoms)
                            break
                else:
                    upd.append(
                        sublime.Phantom(sublime.Region(region.a - 4), content, sublime.LAYOUT_BELOW)
                    )
            date = _bare_date(date.astimezone().strftime(date_format))
        if date == match.group(1).strip():
            self.phantoms.update(upd)
            return

        upd.append(
            sublime.Phantom(
                sublime.Region(max(region.a, region.b - preview_offset)),
                escape(date or _date_error_text(error)),
                sublime.LAYOUT_INLINE,
            )
        )
        self.phantoms.update(upd)


class PlainTasksChooseDate(PlainTasksViewEventListener):
    @classmethod
    def is_applicable(cls, settings):
        return PlainTasksViewEventListener.is_applicable(settings) and settings.get(
            "show_calendar_on_tags", False
        )

    def on_selection_modified_async(self):
        if not self.is_current():
            return
        selections = self.view.sel()
        if len(selections) != 1:
            return
        s = selections[0]
        if not (
            s.empty()
            and any("meta.tag.todo" in self.view.scope_name(n) for n in (s.a, max(0, s.a - 1)))
        ):
            return
        self.view.run_command("plain_tasks_calendar", {"point": s.a})


class PlainTasksCalendar(PlainTasksEnabled):
    def run(self, edit, point=None):
        if point is None:
            if not self.view.sel():
                return
            point = self.view.sel()[0].a
        self.region, _ = self.extract_tag(point)
        content = self.generate_calendar()
        self.view.show_popup(
            content, sublime.COOPERATE_WITH_AUTO_COMPLETE, self.region.a, 555, 555, self.action
        )

    def extract_tag(self, point):
        """Find the tag's date region, or insert at the cursor when outside a tag."""
        start = end = point
        tag_pattern = r"(?<!\S)(@[^()\s,.]+)(\([^()\n]*\))?"
        line = self.view.line(point)
        matches = re.finditer(tag_pattern, self.view.substr(line))
        for match in matches:
            m_start = line.a + match.start(1)
            m_end = line.a + match.end()
            if m_start <= point <= m_end:
                start = line.a + match.end(1)
                end = m_end
                break
        else:
            match = None
        tag = match.group(0) if match else ""
        return sublime.Region(start, end), tag

    @staticmethod
    def link(action, date, label):
        stamp = f"{date.year}-{date.month}-{date.day}-{date.hour}-{date.minute}"
        return f'<a href="{action}:{stamp}">{escape(str(label))}</a>'

    @staticmethod
    def grid(cells, columns):
        return "<br><br>".join(
            "  ".join(cells[index : index + columns]) for index in range(0, len(cells), columns)
        )

    def generate_calendar(self, date=None):
        date = date or datetime.now()
        navigation = "  ".join(
            (
                self.link("prev_month", date, "←"),
                self.link("next_month", date, "→"),
                self.link("month", date, date.strftime("%B")),
                self.link("prev_year", date, "←"),
                self.link("next_year", date, "→"),
                self.link("year", date, date.year),
            )
        )
        cells = []
        for week in calendar.Calendar().monthdayscalendar(date.year, date.month):
            for day in week:
                if not day:
                    cells.append("  ")
                    continue
                link = self.link("day", date.replace(day=day), f"{day:2}")
                cells.append(f"<b>{link}</b>" if day == date.day else link)
        return (
            f"<br><center><big>{navigation}</big></center><br><br>"
            f"{self.grid(cells, 7)}<br><br>{self.link('time', date, date.strftime('%H:%M'))}"
            "<br><br><hr><p>Choose a day to insert its date.<br>"
            "Choose the month, year, or time to change it.</p>"
        )

    def month_picker(self, date):
        cells = []
        for month in range(1, 13):
            day = min(date.day, monthrange(date.year, month)[1])
            value = date.replace(month=month, day=day)
            cells.append(self.link("calendar", value, value.strftime("%b")))
        return f"<br>{self.link('year', date, date.year)}<br><br>{self.grid(cells, 4)}"

    def year_picker(self, date):
        cells = []
        for year in range(max(1, date.year - 6), min(10000, date.year + 6)):
            day = min(date.day, monthrange(year, date.month)[1])
            cells.append(self.link("month", date.replace(year=year, day=day), year))
        return f"<br>{self.grid(cells, 4)}"

    def time_picker(self, date):
        hours = [self.link("time", date.replace(hour=hour), f"{hour:02}") for hour in range(24)]
        minutes = [
            self.link("time", date.replace(minute=minute), f"{minute:02}") for minute in range(60)
        ]
        return (
            f"<br>Hours<br><br>{self.grid(hours, 8)}<br><br>"
            f"Minutes<br><br>{self.grid(minutes, 10)}<br><br>"
            f"{self.link('calendar', date, 'Confirm: ' + date.strftime('%H:%M'))}<br><br>"
        )

    def action(self, payload):
        try:
            action, stamp = payload.split(":", 1)
            year, month, day, hour, minute = map(int, stamp.split("-"))
            date = datetime(year, month, min(day, monthrange(year, month)[1]), hour, minute)
        except ValueError, OverflowError:
            return
        if action == "day":
            self.view.hide_popup()
            self.view.run_command(
                "plain_task_insert_date",
                {
                    "region": (self.region.a, self.region.b),
                    "date": (date.year, date.month, date.day, date.hour, date.minute),
                },
            )
            return
        shifts = {"prev_month": -1, "next_month": 1, "prev_year": -12, "next_year": 12}
        if action in shifts:
            year, month = divmod(date.year * 12 + date.month - 1 + shifts[action], 12)
            month += 1
            if not 1 <= year <= 9999:
                return
            date = date.replace(
                year=year, month=month, day=min(date.day, monthrange(year, month)[1])
            )
            action = "calendar"
        render = {
            "calendar": self.generate_calendar,
            "month": self.month_picker,
            "year": self.year_picker,
            "time": self.time_picker,
        }.get(action)
        if render is not None:
            self.view.update_popup(render(date))


class PlainTasksRemain(PlainTasksViewEventListener):
    def __init__(self, view):
        super().__init__(view)
        self.phantom_set = sublime.PhantomSet(view, "plain_tasks_remain_time")
        self.phantoms = None
        self.view.settings().add_on_change(REMAIN_SETTING, self.check_setting)
        self.update()

    def on_close(self):
        self.view.settings().clear_on_change(REMAIN_SETTING)
        self.view.settings().set(REMAIN_SETTING, [])
        self.phantom_set.update([])
        for key in ("past_due", "due_soon", "misformatted"):
            self.view.erase_regions(key)

    def check_setting(self):
        if not self.is_current():
            self.on_close()
            return
        # Settings callbacks fire for any setting, including formatting changes.
        new_value = (
            self.view.settings().get(REMAIN_SETTING, []),
            self.view.settings().get("due_remain_format"),
            self.view.settings().get("due_overdue_format"),
        )
        if self.phantoms == new_value:
            return
        self.update()

    def update(self):
        if not self.is_current():
            self.on_close()
            return
        values = self.view.settings().get(REMAIN_SETTING, [])
        self.phantoms = (
            list(values),
            self.view.settings().get("due_remain_format"),
            self.view.settings().get("due_overdue_format"),
        )
        if not values:
            self.phantom_set.update([])
            return
        upd = []
        for point, content in values:
            upd.append(
                sublime.Phantom(
                    sublime.Region(point), _due_text(self.view, content), sublime.LAYOUT_BELOW
                )
            )
        self.phantom_set.update(upd)


def plugin_unloaded():
    global _LIFECYCLE
    _LIFECYCLE = object()
    for window in sublime.windows():
        for view in window.views():
            view.settings().set(REMAIN_SETTING, [])
            view.settings().clear_on_change(REMAIN_SETTING)
            view.erase_phantoms("plain_tasks_preview_short_date")
            view.erase_phantoms("plain_tasks_remain_time")
            for key in ("past_due", "due_soon", "misformatted"):
                view.erase_regions(key)
