# 0011 First motor move after the reassembly

Status: todo

The owner wants to test the mechanics by moving the holder carrier (`0010-mechanical-check.md`). This item is the tool and the procedure for the first motor command, built so that each run is bounded and replays only what the working unit in the issue #151 capture received (`doc/protocol/of120-capture-151.md`).

What the vendor does, as far as the capture shows:
- Every move comes after the open sequence (register blast, clock set-up, AFE defaults, GPIO set-up) and is preceded by a pair of slope tables to `0x1000c000` and `0x10010000`.
- A positioning move is `0x02 = 0x18` (MTRPWR, FASTFED), FEEDL (`0x3d` to `0x3f`) in steps, `0x0f = 0x01` to start, then either an interrupt read or polling of `0x101` until the motor stops, then `0x02 = 0x08`.
- The shortest positioning move in the capture is 97 steps (the third move of each cycle). Moves out use `0x09 = 0x08` (BACKSCAN) with `0x02 = 0x30`.
- Position is counted from the home sensor (`HOMESNR`, `0x101` bit 3) and the holder sensor (`0x31` bit 2, `LoaderReadyReg`); the frame positions and `FilmLoaderOrigin 0,980` are constants in the driver configuration, and the flash holds only the infrared record. No stored position calibration was found anywhere, so a carrier moved by hand needs no recalibration *(inference: as far as the engine and the flash show)*.

Steps:
- [ ] Read-only first: at the next wake, log `0x101` (home sensor) and `0x31` (holder sensor) and compare with the values before the opening (`0x4c` and `0xbc`, `doc/hardware/usb.md`). The firmware moves the motor briefly at every power-on (owner, 2026-10-15), so the mechanism has already run since the reassembly; the owner thinks the carrier now sits near the middle of its travel. If `HOMESNR` is clear after a power-on, the power-on move is not a homing or the sensor no longer trips, and that has to be understood before any move.
- [ ] Extract from the capture the exact bytes of the open sequence and of the 97-step move (registers, both slope tables, the `0x101` values polled until the motor stopped) into `doc/protocol/`.
- [ ] Build `tools/pi/first_move.py`: open sequence as captured, one move of a chosen length (default the capture's 97 steps) in a chosen direction, bounded by a poll limit, `0x02 = 0x08` afterwards, every register logged. Refuse any other write. Unit tests, review by a second agent.
- [ ] Decide the direction with the owner from where the carrier sits now, then one run with the owner at the power switch and an explicit go-ahead. Listen for a stall.
- [ ] If the short move runs clean: a homing run (`0x02 = 0x30`, AGOHOME) with a poll limit, which finds the sensor, then record the outcome in `doc/hardware/board.md` and close `0010`.

Risks, for the owner's decision: a move into an end stop or a mis-seated gear stalls the stepper. Whether a stall can damage the gear train in this unit is not known. The vendor's own first move is 10158 steps blind, so the mechanism is built to take ordinary stalls, but a mis-seated gear is not an ordinary case. The shortest, slowest move the vendor uses is the least that can be sent and still move the carrier.
