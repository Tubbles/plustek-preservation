"""Tests for pyopticfilm_run.py with the driver calls replaced, no USB needed.

Run: python3 -I -B -m unittest discover -s tools/pi
"""

import pathlib
import sys
import unittest

TOOLS_DIRECTORY = pathlib.Path(__file__).resolve().parent
PYOPTICFILM_SOURCE = TOOLS_DIRECTORY.parent.parent / "pyopticfilm" / "src"
if str(PYOPTICFILM_SOURCE) not in sys.path:
    sys.path.insert(0, str(PYOPTICFILM_SOURCE))

import pyopticfilm_run
from pyopticfilm.exceptions import AsicError, MotorTimeoutError, UsbError


class RecordedSteps:
    """A Steps whose calls are recorded; feed or home can be made to raise."""

    def __init__(self, feed_error=None, home_error=None):
        self.calls = []
        self.status_reads = 0
        self.feed_error = feed_error
        self.home_error = home_error

    def status(self) -> int:
        self.status_reads += 1
        return 0xDC

    def steps(self) -> pyopticfilm_run.Steps:
        def feed(steps, timeout_seconds):
            self.calls.append(("feed", steps, timeout_seconds))
            if self.feed_error is not None:
                raise self.feed_error

        def home(steps, timeout_seconds):
            self.calls.append(("home", steps, timeout_seconds))
            if self.home_error is not None:
                raise self.home_error

        return pyopticfilm_run.Steps(status=self.status, arm=lambda: self.calls.append(("arm",)),
                                     open=lambda: self.calls.append(("open",)), feed=feed, home=home)


def plan(feed_steps=None, home=False, home_steps=1000, timeout_seconds=10.0) -> pyopticfilm_run.Plan:
    return pyopticfilm_run.Plan(feed_steps=feed_steps, home=home, home_steps=home_steps,
                                timeout_seconds=timeout_seconds)


class RunTest(unittest.TestCase):
    def run_plan(self, the_plan, recorded):
        events = []
        exit_code = pyopticfilm_run.run(the_plan, recorded.steps(), events.append)
        return exit_code, events

    def test_feed_then_home_in_order(self):
        recorded = RecordedSteps()
        exit_code, events = self.run_plan(plan(feed_steps=97, home=True, home_steps=1000, timeout_seconds=20.0),
                                          recorded)
        self.assertEqual(exit_code, pyopticfilm_run.EXIT_GOOD)
        self.assertEqual(recorded.calls, [("arm",), ("open",), ("feed", 97, 20.0), ("home", 1000, 20.0)])
        self.assertEqual([(event["name"], event["when"]) for event in events if event["event"] == "step"],
                         [("arm", "before"), ("arm", "after"), ("open", "before"), ("open", "after"),
                          ("feed", "before"), ("feed", "after"), ("home", "before"), ("home", "after")])
        self.assertEqual(events[0], {"event": "status", "when": "start", "status": 0xDC})
        self.assertTrue(all(event["status"] == 0xDC for event in events))

    def test_home_alone_skips_the_feed(self):
        recorded = RecordedSteps()
        exit_code, _ = self.run_plan(plan(home=True), recorded)
        self.assertEqual(exit_code, pyopticfilm_run.EXIT_GOOD)
        self.assertEqual(recorded.calls, [("arm",), ("open",), ("home", 1000, 10.0)])

    def test_refused_feed_stops_the_run_before_home(self):
        recorded = RecordedSteps(feed_error=AsicError("gate"))
        exit_code, events = self.run_plan(plan(feed_steps=97, home=True), recorded)
        self.assertEqual(exit_code, pyopticfilm_run.EXIT_REFUSED)
        self.assertEqual(recorded.calls[-1], ("feed", 97, 10.0))
        self.assertEqual(events[-1]["when"], "refused")
        self.assertEqual(events[-1]["error"], "gate")

    def test_motor_timeout_and_usb_error_exit_codes(self):
        exit_code, events = self.run_plan(plan(home=True), RecordedSteps(home_error=MotorTimeoutError("late")))
        self.assertEqual(exit_code, pyopticfilm_run.EXIT_MOTOR_TIMEOUT)
        self.assertEqual(events[-1]["when"], "failed")
        exit_code, events = self.run_plan(plan(feed_steps=5), RecordedSteps(feed_error=UsbError("gone")))
        self.assertEqual(exit_code, pyopticfilm_run.EXIT_USB_ERROR)
        self.assertEqual(events[-1]["when"], "usb_error")
        self.assertNotIn("status", events[-1])


class ArgumentsTest(unittest.TestCase):
    def test_defaults_and_plan(self):
        arguments = pyopticfilm_run.argument_parser().parse_args(["logs", "--feed", "97", "--home"])
        the_plan = pyopticfilm_run.plan_from_arguments(arguments)
        self.assertEqual(the_plan, plan(feed_steps=97, home=True))
        self.assertEqual(arguments.log_directory, pathlib.Path("logs"))

    def test_home_steps_and_timeout(self):
        arguments = pyopticfilm_run.argument_parser().parse_args(
            ["logs", "--home", "--home-steps", "2000", "--timeout-seconds", "20"])
        self.assertEqual(pyopticfilm_run.plan_from_arguments(arguments),
                         plan(home=True, home_steps=2000, timeout_seconds=20.0))

    def test_step_list(self):
        self.assertEqual([name for name, _ in pyopticfilm_run.step_list(plan(feed_steps=1))], ["arm", "open", "feed"])
        self.assertEqual([name for name, _ in pyopticfilm_run.step_list(plan(home=True))], ["arm", "open", "home"])


class SourceTest(unittest.TestCase):
    def test_script_has_no_usb_transfer_of_its_own(self):
        source = (TOOLS_DIRECTORY / "pyopticfilm_run.py").read_text()
        for name in ("ctrl_transfer", "control_msg", "bulk_write", "write_register", "usb.core"):
            self.assertNotIn(name, source)


if __name__ == "__main__":
    unittest.main()
