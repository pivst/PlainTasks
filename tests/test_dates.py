"""Dates, elapsed-time accounting, calendar boundaries, and phantom lifecycle."""

import re
from datetime import UTC, datetime, timedelta, timezone
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

import sublime
from PlainTasks.tests.support.sublime_stub import Region, View

from PlainTasks import PlainTasksDates as dates


def task_view(text="", settings=None):
    view = View(text, settings)
    view.settings().set("syntax", "Packages/PlainTasks/PlainTasks.sublime-syntax")
    view.is_valid = Mock(return_value=True)
    view.erase_regions = Mock()
    return view


class TestDateParsing(TestCase):
    now = datetime(2026, 12, 31, 23, 15)

    def test_invalid_text_is_never_today(self):
        for parser in (dates.dateutil_parser, None):
            with patch.object(dates, "dateutil_parser", parser):
                for text in ("yo", "not a date", "-1", "99", "2026-02-30", "1-1 trailing text"):
                    with self.subTest(text=text, dateutil=parser is not None):
                        date, error = dates.parse_date(text, default=self.now)
                        self.assertIsNone(date)
                        self.assertIsNotNone(error)

    def test_short_dates_roll_forward_and_explicit_current_month_does_not(self):
        for text, expected in (
            ("", self.now),
            ("0", self.now),
            ("--1", self.now.replace(day=1)),
            ("1", datetime(2027, 1, 1, 23, 15)),
            ("1-1", datetime(2027, 1, 1, 23, 15)),
            ("1 0:00", datetime(2027, 1, 1)),
            ("0:", self.now.replace(hour=0)),
            (":0", self.now.replace(minute=0)),
        ):
            with self.subTest(text=text):
                actual, error = dates.parse_date(text, default=self.now)
                self.assertIsNone(error)
                self.assertEqual(actual, expected)

    def test_explicit_timezone_is_compared_in_the_default_timezone(self):
        stamp = datetime(2026, 10, 14, 12, 30, tzinfo=timezone(timedelta(hours=8)))
        for default, expected in (
            (self.now, stamp.astimezone().replace(tzinfo=None)),
            (self.now.replace(tzinfo=UTC), stamp.astimezone(UTC)),
        ):
            with self.subTest(default=default):
                date, error = dates.parse_date("2026-10-14 12:30 +0800", default=default)
                self.assertIsNone(error)
                self.assertEqual(date, expected)
                self.assertIsInstance(date < default, bool)

    def test_custom_date_format_with_timezone(self):
        date, error = dates.parse_date(
            "(2026-10-14 12:30 +0800)",
            date_format="(%Y-%m-%d %H:%M %z)",
            default=self.now.replace(tzinfo=UTC),
        )
        self.assertIsNone(error)
        self.assertEqual(date, datetime(2026, 10, 14, 4, 30, tzinfo=UTC))

    def test_custom_date_format_determines_ambiguous_date_order(self):
        date, error = dates.parse_date(
            "01/11/2026", date_format="(%d/%m/%Y %H:%M)", default=self.now
        )
        self.assertIsNone(error)
        self.assertEqual(date, datetime(2026, 11, 1, 23, 15))

    def test_short_dates_keep_an_aware_default(self):
        now = self.now.replace(tzinfo=UTC)
        date, error = dates.parse_date("1-1", default=now)
        self.assertIsNone(error)
        self.assertEqual(date, datetime(2027, 1, 1, 23, 15, tzinfo=UTC))

    def test_relative_units_and_hours_do_not_backtrack_into_days(self):
        for text, delta in (
            ("+", timedelta(days=1)),
            ("+w", timedelta(weeks=1)),
            ("+3W", timedelta(weeks=3)),
            ("+2d 12:", timedelta(days=2, hours=12)),
            ("+33.", timedelta(hours=33)),
            ("+33.55", timedelta(hours=33, minutes=55)),
            ("+:555", timedelta(minutes=555)),
            ("+0:0", timedelta(days=1)),
        ):
            with self.subTest(text=text):
                date, error = dates.increase_date(None, None, text, self.now, dates.DATE_FORMAT)
                self.assertIsNone(error)
                self.assertEqual(date, self.now + delta)

    def test_relative_garbage_and_overflow_return_errors(self):
        for text in ("+hey", "++garbage", "+1w junk", "+-1", "+" + "9" * 5000):
            with self.subTest(text=text[:32]):
                date, error = dates.increase_date(None, None, text, self.now, dates.DATE_FORMAT)
                self.assertIsNone(date)
                self.assertIsNotNone(error)

    def test_relative_creation_tag_is_validated(self):
        view = View(" ☐ Task @created(26-12-01 09:30) @due(++4w)")
        date, error = dates.increase_date(view, Region(0), "++4w", self.now, dates.DATE_FORMAT)
        self.assertIsNone(error)
        self.assertEqual(date, datetime(2026, 12, 29, 9, 30))
        view.text = " ☐ Task @created(garbage) @due(++4w)"
        date, error = dates.increase_date(view, Region(0), "++4w", self.now, dates.DATE_FORMAT)
        self.assertIsNone(date)
        self.assertIn("@created", str(error[0]))


class TestDurations(TestCase):
    def test_decimal_hours_and_clock_times(self):
        for text, expected in (
            ("1.50", timedelta(hours=1, minutes=30)),
            ("2 days, 1.50", timedelta(days=2, hours=1, minutes=30)),
            ("1 day", timedelta(days=1)),
            ("26:30", timedelta(hours=26, minutes=30)),
            ("0:00:15", timedelta(seconds=15)),
        ):
            with self.subTest(text=text):
                self.assertEqual(dates.parse_duration(text), expected)

    def test_invalid_or_overflowing_durations_are_ignored(self):
        for text in ("", "a bit", "1:99", "1:01:99", "1.5 garbage", "9" * 5000 + " days"):
            with self.subTest(text=text[:32]):
                self.assertIsNone(dates.parse_duration(text))

    def test_negative_durations_have_a_single_sign(self):
        for decimal, expected in ((False, "-1:30"), (True, "-1.50")):
            self.assertEqual(
                dates.format_delta(
                    View(settings={"decimal_minutes": decimal}), -timedelta(hours=1, minutes=30)
                ),
                expected,
            )
        self.assertEqual(dates.format_delta(View(), timedelta()), "")

    def test_tracking_sums_active_intervals_and_excludes_pauses(self):
        elapsed = dates.calculate_elapsed(
            "(26-10-14 09:00)",
            ["(26-10-14 10:00)", "(26-10-14 11:00)"],
            "(26-10-14 12:30)",
            dates.DATE_FORMAT,
        )
        self.assertEqual(elapsed, timedelta(hours=2, minutes=30))
        elapsed = dates.calculate_elapsed(
            "(26-10-14 09:00)", ["(26-10-14 10:00)"], "(26-10-14 12:30)", dates.DATE_FORMAT
        )
        self.assertEqual(elapsed, timedelta(hours=1))

    def test_tracking_rejects_nonchronological_or_invalid_stamps(self):
        for started, toggles, ended in (
            ("(26-10-14 10:00)", [], "(26-10-14 09:00)"),
            ("(26-10-14 09:00)", ["(26-10-14 08:00)"], "(26-10-14 10:00)"),
            ("garbage", [], "(26-10-14 10:00)"),
        ):
            with self.subTest(started=started, toggles=toggles):
                with self.assertRaises(ValueError):
                    dates.calculate_elapsed(started, toggles, ended, dates.DATE_FORMAT)


@skipUnless(getattr(sublime, "_plaintasks_test_stub", False), "Standalone editor API contracts")
class TestDateCommands(TestCase):
    def test_project_totals_scan_only_children_and_do_not_double_count_subtotals(self):
        text = (
            "Outside @lasted(20:00)\nProject:\n"
            "  ✔ One @lasted(1.50)\n  Subproject: @total(2:00)\n"
            "    ✘ Two @wasted(2:00)\nNext:\n  ✔ Three @lasted(10:00)"
        )
        view = View(text)
        children = Region(text.index("  ✔ One"), text.index("Next:"))
        view.indented_region = Mock(return_value=children)
        view.find_all = Mock(side_effect=AssertionError("Must not scan unrelated projects"))
        total, eol = dates.PlainTasksCalculateTotalTimeForProject(view).calc_total_time_for_project(
            view.line(text.index("Project:"))
        )
        self.assertEqual(total, timedelta(hours=3, minutes=30))
        self.assertEqual(eol, text.index("\n  ✔ One"))
        view.indented_region.assert_called_once_with(eol + 1)

    def test_invalid_recalculation_preserves_existing_duration(self):
        text = " ✔ Task @started(garbage) @done(26-10-14 12:00) @lasted(1:30)"
        view = View(text)
        with patch.object(sublime, "status_message") as status:
            dates.PlainTasksReCalculateTimeForTasks(view).run(view.edit)
        self.assertEqual(view.text, text)
        self.assertIn("invalid time tracking", status.call_args.args[0])

    def test_recalculation_is_idempotent_and_preserves_trailing_spaces(self):
        view = View(" ✔ Task @started(26-10-14 09:00) @done(26-10-14 10:30) @lasted(9:00)  ")
        view.sel().add(Region(3))
        command = dates.PlainTasksReCalculateTimeForTasks(view)
        command.run(view.edit)
        self.assertTrue(view.text.endswith("@lasted(1:30)  "))
        self.assertEqual(view.text.count("@lasted"), 1)
        first = view.text
        command.run(view.edit)
        self.assertEqual(view.text, first)

    def test_invalid_tracking_adds_no_duration_tag(self):
        view = View(" ✔ Task")
        dates.PlainTasksCalculateTimeForTask(view).run(
            view.edit, ["garbage"], [], "(26-10-14 12:00)", view.size()
        )
        self.assertEqual(view.text, " ✔ Task")

    def test_disabled_highlighting_clears_remaining_time(self):
        view = View(settings={"highlight_past_due": False, dates.REMAIN_SETTING: [[0, "1:00"]]})
        view.erase_regions = Mock()
        dates.PlainTasksToggleHighlightPastDue(view).run(view.edit)
        self.assertEqual(view.settings()[dates.REMAIN_SETTING], [])
        self.assertEqual(view.erase_regions.call_count, 3)

    def test_garbage_due_tags_are_marked_invalid_and_completed_tasks_ignored(self):
        view = View(" ☐ Task @due(garbage)\n ✔ Done @due(garbage)")
        points = [text.start() for text in re.finditer("@due", view.text)]
        regions = [Region(point, point + len("@due(garbage)")) for point in points]
        groups = dates.PlainTasksToggleHighlightPastDue(view).group_due_tags(
            ["(garbage)", "(garbage)"], regions
        )
        self.assertEqual(groups, ([], [], [regions[0]], []))

    def test_due_highlighting_debounces_edits_and_ignores_closed_views(self):
        view = task_view()
        callbacks = []
        with patch.object(
            sublime,
            "set_timeout",
            side_effect=lambda callback, delay: callbacks.append(callback),
            create=True,
        ):
            listener = dates.PlainTasksDueEvents(view)
            listener.on_modified_async()
            listener.on_modified_async()
            callbacks[0]()
            self.assertEqual(view.commands, [])
            callbacks[1]()
            self.assertEqual(view.commands, [("plain_tasks_toggle_highlight_past_due", None)])
            listener.on_modified_async()
            listener.on_close()
            callbacks[-1]()
            self.assertEqual(len(view.commands), 1)

    def test_queued_due_update_does_not_survive_syntax_change_or_unload(self):
        for reason in ("syntax", "unload"):
            with self.subTest(reason=reason):
                view = task_view()
                callbacks = []
                with patch.object(
                    sublime,
                    "set_timeout",
                    side_effect=lambda callback, delay, callbacks=callbacks: callbacks.append(
                        callback
                    ),
                    create=True,
                ):
                    listener = dates.PlainTasksDueEvents(view)
                    listener.on_modified_async()
                    if reason == "syntax":
                        view.settings().set("syntax", "Packages/Python/Python.sublime-syntax")
                    else:
                        with patch.object(sublime, "windows", return_value=[], create=True):
                            dates.plugin_unloaded()
                    callbacks[0]()
                    self.assertEqual(view.commands, [])

    def test_calendar_start_of_file_and_tag_replacement_do_not_consume_notes(self):
        view = View("@due(26-10-14 12:00) note after tag")
        command = dates.PlainTasksCalendar(view)
        region, tag = command.extract_tag(4)
        self.assertEqual(view.substr(region), "(26-10-14 12:00)")
        self.assertEqual(tag, "@due(26-10-14 12:00)")
        view.sel().clear()
        view.sel().add(Region(20))
        command.run(view.edit, point=0)
        self.assertEqual(command.region, region)

    def test_calendar_bounds_and_unknown_payloads_do_not_crash(self):
        view = View()
        command = dates.PlainTasksCalendar(view)
        for payload in (
            "prev_year:1-1-1-12-0",
            "next_month:9999-12-31-12-0",
            "year:1-1-1-12-0",
            "year:9999-1-1-12-0",
            "unknown:2026-1-1-12-0",
            "bad",
            "calendar:2026-99-99-12-0",
        ):
            with self.subTest(payload=payload):
                command.action(payload)
        self.assertNotIn("month:10000-", view.popup)

    def test_date_picker_insertion_does_not_move_selection_again(self):
        view = View(" ☐ Task @due(1)")
        command = dates.PlainTasksCalendar(view)
        command.region = Region(12, 15)
        view.sel().clear()
        view.sel().add(Region(2))
        command.action("day:2026-10-14-12-0")
        self.assertEqual(view.sel(), [Region(2)])
        self.assertEqual(view.commands[-1][0], "plain_task_insert_date")


@skipUnless(getattr(sublime, "_plaintasks_test_stub", False), "Standalone phantom API contracts")
class TestDatePhantoms(TestCase):
    def setUp(self):
        self.phantom_set = Mock()
        patcher = patch.object(sublime, "PhantomSet", return_value=self.phantom_set, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(sublime, "Phantom", side_effect=lambda *args: args, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_remaining_time_renders_existing_values_and_cleans_up_callback(self):
        view = task_view(settings={dates.REMAIN_SETTING: [[0, "-1:30"]]})
        view.settings().clear_on_change = Mock()
        listener = dates.PlainTasksRemain(view)
        self.assertEqual(self.phantom_set.update.call_args.args[0][0][1], "1:30 overdue")
        view.settings().set("due_overdue_format", "Overdue by {time}")
        listener.check_setting()
        self.assertEqual(self.phantom_set.update.call_args.args[0][0][1], "Overdue by 1:30")
        listener.on_close()
        view.settings().clear_on_change.assert_called_once_with(dates.REMAIN_SETTING)

    def test_preview_handles_no_selection_and_escapes_errors(self):
        view = task_view("@due(<script>alert</script>)")
        view.scope = "text.todo meta.tag.todo "
        view.sel().clear()
        listener = dates.PlainTasksPreviewShortDate(view)
        listener.on_selection_modified_async()
        self.phantom_set.update.assert_called_with([])
        view.sel().add(Region(7))
        listener.on_selection_modified_async()
        content = self.phantom_set.update.call_args.args[0][0][1]
        self.assertNotIn("<script>", content)
        self.assertIn("&lt;script&gt;", content)

    def test_preview_settings_copy_does_not_mutate_cached_phantom_values(self):
        previous = [[0, "old"]]
        view = task_view(
            "@due(+2w)", settings={"show_remain_due": True, dates.REMAIN_SETTING: previous}
        )
        view.scope = "text.todo meta.tag.todo "
        view.sel().clear()
        view.sel().add(Region(6))
        dates.PlainTasksPreviewShortDate(view).on_selection_modified_async()
        self.assertEqual(previous, [[0, "old"]])
        self.assertNotEqual(view.settings()[dates.REMAIN_SETTING], previous)

    def test_syntax_change_detaches_remaining_time_callback_and_clears_phantoms(self):
        view = task_view(settings={dates.REMAIN_SETTING: [[0, "-1:30"]]})
        view.settings().clear_on_change = Mock()
        listener = dates.PlainTasksRemain(view)
        view.settings().set("syntax", "Packages/Python/Python.sublime-syntax")
        listener.check_setting()
        view.settings().clear_on_change.assert_called_once_with(dates.REMAIN_SETTING)
        self.phantom_set.update.assert_called_with([])
        self.assertEqual(view.settings()[dates.REMAIN_SETTING], [])

    def test_preview_callback_after_syntax_change_clears_instead_of_rendering(self):
        view = task_view("@due(+2w)")
        listener = dates.PlainTasksPreviewShortDate(view)
        view.settings().set("syntax", "Packages/Python/Python.sublime-syntax")
        listener.on_selection_modified_async()
        self.phantom_set.update.assert_called_with([])

    def test_bad_remaining_time_template_has_a_readable_fallback(self):
        view = View(settings={"due_remain_format": "{undefined}"})
        self.assertEqual(dates._due_text(view, "1:30"), "1:30 remaining")
