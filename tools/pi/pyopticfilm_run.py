"""Run pyopticfilm's OpticFilm 120 open, feed and home on the unit, with a transfer log.

The driver code lives in the pyopticfilm fork (submodule pyopticfilm/,
doc/work/0015-pyopticfilm-opticfilm-120.md). This script only wires it
up for a run on the Pi: it opens the unit with pyopticfilm, records
every USB transfer through pyopticfilm's RecordingTransport, arms the
motor (the model is not scan_ready, so Scanner.arm_bringup_motor() is
the explicit arming step), sends the open (Gl126.init, a warm re-run on
a unit the watcher holds), then the moves asked for on the command line,
in this order: --feed N (move 1 of the capture, N steps away from home),
then --home (the same move with MTRREV, bounded by --home-steps). Every
register write comes from pyopticfilm; this script sends nothing itself.

Every run writes LOG_DIRECTORY/<UTC stamp>/usb.jsonl (one line per USB
transfer, pyopticfilm's UsbTransaction.to_json: request fields, data,
response, host timestamps) and driver.log (pyopticfilm's logger at
DEBUG). The status register 0x101 is read before and after each step and
logged.

Exit codes: 0 every step done; 10 no device; 11 the driver refused a step
(AsicError: gate, arming, home sensor not reached); 12 a move timed out
(MotorTimeoutError, the cut has been sent); 13 USB error; 2 bad
arguments.

Run (owner's go-ahead per run, owner at the unit):
    sudo plustek-preservation/venv/bin/python plustek-preservation/pyopticfilm_run.py \
        scanner-log/pyopticfilm --feed 97 --home
"""

import argparse
import dataclasses
import datetime
import json
import logging
import pathlib
import sys
import typing

EXIT_GOOD = 0
EXIT_NO_DEVICE = 10
EXIT_REFUSED = 11
EXIT_MOTOR_TIMEOUT = 12
EXIT_USB_ERROR = 13
EXIT_BAD_ARGUMENTS = 2

DEFAULT_HOME_STEPS = 1000
DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclasses.dataclass
class Plan:
    feed_steps: typing.Optional[int]
    home: bool
    home_steps: int
    timeout_seconds: float


@dataclasses.dataclass
class Steps:
    """The driver calls a run makes, in order, so that run() can be tested without hardware."""
    status: typing.Callable[[], int]
    arm: typing.Callable[[], None]
    open: typing.Callable[[], None]
    feed: typing.Callable[[int, float], None]
    home: typing.Callable[[int, float], None]


def utc_stamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def make_run_directory(log_directory: pathlib.Path) -> pathlib.Path:
    run_directory = log_directory / utc_stamp()
    run_directory.mkdir(parents=True, exist_ok=False)
    return run_directory


def step_list(plan: Plan) -> list:
    """(name, call) pairs in the order a run makes them."""
    steps = [("arm", "arm"), ("open", "open")]
    if plan.feed_steps is not None:
        steps.append(("feed", "feed"))
    if plan.home:
        steps.append(("home", "home"))
    return steps


def run(plan: Plan, steps: Steps, event_log: typing.Callable[[dict], None]) -> int:
    """Make the calls of the plan in order, logging 0x101 around each, and map errors to exit codes."""
    from pyopticfilm.exceptions import AsicError, MotorTimeoutError, UsbError
    event_log({"event": "status", "when": "start", "status": steps.status()})
    for name, _ in step_list(plan):
        event_log({"event": "step", "name": name, "when": "before", "status": steps.status()})
        try:
            if name == "arm":
                steps.arm()
            elif name == "open":
                steps.open()
            elif name == "feed" and plan.feed_steps is not None:
                steps.feed(plan.feed_steps, plan.timeout_seconds)
            else:
                steps.home(plan.home_steps, plan.timeout_seconds)
        except MotorTimeoutError as error:
            event_log({"event": "step", "name": name, "when": "failed", "error": str(error), "status": steps.status()})
            return EXIT_MOTOR_TIMEOUT
        except AsicError as error:
            event_log({"event": "step", "name": name, "when": "refused", "error": str(error), "status": steps.status()})
            return EXIT_REFUSED
        except UsbError as error:
            event_log({"event": "step", "name": name, "when": "usb_error", "error": str(error)})
            return EXIT_USB_ERROR
        event_log({"event": "step", "name": name, "when": "after", "status": steps.status()})
    return EXIT_GOOD


def hardware_steps(scanner) -> Steps:
    return Steps(
        status=lambda: scanner.asic.read_status().raw,
        arm=scanner.arm_bringup_motor,
        open=scanner.asic.init,
        feed=lambda steps, timeout_seconds: scanner.asic.feed(steps, timeout_s=timeout_seconds),
        home=lambda steps, timeout_seconds: scanner.asic.home(steps=steps, timeout_s=timeout_seconds),
    )


def open_scanner(sink: typing.Callable[[dict], None]):
    """Open the unit with pyopticfilm, every transfer recorded through sink."""
    from pyopticfilm.scanner import Scanner
    from pyopticfilm.usb.device import UsbDeviceHandle
    from pyopticfilm.usb.protocol import GenesysUsbProtocol
    from pyopticfilm.usb.trace import RecordingTransport
    handle = UsbDeviceHandle.open()
    recording = RecordingTransport(inner=handle, sink=lambda transaction: sink(transaction.to_json()),
                                   keep_in_memory=False)
    return Scanner(handle, protocol=GenesysUsbProtocol(recording))


def driver_logging(run_directory: pathlib.Path) -> None:
    from pyopticfilm.logging import get_logger
    logger = get_logger()
    logger.setLevel(logging.DEBUG)
    file_handler = logging.FileHandler(run_directory / "driver.log")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(file_handler)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(console)


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("log_directory", type=pathlib.Path)
    parser.add_argument("--feed", type=int, default=None, metavar="STEPS", help="FEEDL of a move away from home")
    parser.add_argument("--home", action="store_true", help="return to the home sensor after the feed")
    parser.add_argument("--home-steps", type=int, default=DEFAULT_HOME_STEPS, metavar="STEPS",
                        help="FEEDL bound of the return (default %(default)s)")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS,
                        help="poll limit of each move (default %(default)s; a return from an inch out needs 20)")
    return parser


def plan_from_arguments(arguments: argparse.Namespace) -> Plan:
    return Plan(feed_steps=arguments.feed, home=arguments.home, home_steps=arguments.home_steps,
                timeout_seconds=arguments.timeout_seconds)


def main() -> int:
    parser = argument_parser()
    arguments = parser.parse_args()
    plan = plan_from_arguments(arguments)
    if plan.feed_steps is None and not plan.home:
        parser.error("nothing to do: give --feed STEPS, --home or both")
    run_directory = make_run_directory(arguments.log_directory)
    driver_logging(run_directory)
    print(f"log: {run_directory}")
    with (run_directory / "usb.jsonl").open("a") as usb_log, (run_directory / "events.jsonl").open("a") as events:
        def usb_sink(record: dict) -> None:
            usb_log.write(json.dumps(record) + "\n")
            usb_log.flush()

        def event_log(record: dict) -> None:
            record["time"] = utc_stamp()
            events.write(json.dumps(record) + "\n")
            events.flush()
            print(json.dumps(record))

        from pyopticfilm.exceptions import DeviceNotFoundError, PlustekError
        try:
            scanner = open_scanner(usb_sink)
        except DeviceNotFoundError as error:
            event_log({"event": "no_device", "error": str(error)})
            return EXIT_NO_DEVICE
        except PlustekError as error:
            event_log({"event": "open_failed", "error": str(error)})
            return EXIT_USB_ERROR
        try:
            return run(plan, hardware_steps(scanner), event_log)
        finally:
            scanner._handle.close()


if __name__ == "__main__":
    sys.exit(main())
