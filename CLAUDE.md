# Instructions for agents

## Sensitive data

- Serial numbers (SilverFast license serials, the scanner's hardware serial), the owner's registration email, and the scans of the DVD case and sticky note are sensitive. They live only in `work/sensitive.md` and outside the repository. Never write them into tracked files, commit messages, logs or captures that get committed.
- USB captures may contain the hardware serial or license data. Keep raw captures in `work/captures/`. Only commit captures or excerpts after checking them for such data.
- Downloaded vendor binaries stay in `work/downloads/` (untracked, see `work/downloads/MANIFEST.md`). They are for analysis only: never run them on the host outside a VM or Wine prefix set up for that purpose, and never commit them.

## Hosts

Host names, access details and machine specific notes live in `CLAUDE.local.md` (untracked). The scanner is attached to a Raspberry Pi 3 (Debian 13, aarch64); development happens on a separate, slow workstation.

## Talking to the scanner

- Until the protocol is understood, only send requests whose effect is known from the vendor driver or from captures. A wrong write could move a motor against an end stop or change the firmware configuration. Reads of descriptors and documented status requests are fine.
- The vendor engine is the playbook (owner, 2026-10-15, `doc/work/0012-driver-playbook.md`): derive a sequence from the engine's code (`doc/vendor-driver/`, Ghidra), confirm it against the capture, and map it onto the pyopticfilm function that does the same job, so that findings land as pyopticfilm support and not only as replay tools.
- The scanner leaves the bus about 5 minutes after a wake, even with read-only polling, unless the vendor's open sequence has been sent (`tools/pi/vendor_open.py`, `doc/hardware/usb.md`, "Standby"); how long it stays after that is being measured. The owner wakes it with the power button, so a session with the scanner starts with one press and the open sequence, which needs the owner's go-ahead like every other write.
- The unit was reassembled on 2026-10-15 and its mechanics are unverified (`doc/hardware/board.md`, "Reassembly"). Until `doc/work/0010-mechanical-check.md` is done, send nothing that powers or moves the motor, and keep the film holder out of the unit.

## Driver code (submodule)

- `pyopticfilm/` is a submodule pointing at the fork `Tubbles/pyopticfilm` (remote `origin`, pushes go over SSH; `upstream` is `jboneng/pyopticfilm`). Follow `pyopticfilm/CONTRIBUTING.md` there, not the conventions of this repository.
- Work on feature branches in the submodule. Commit the updated submodule pointer here only after the submodule commits are pushed to the fork, or the pointer breaks for everyone else.

## Documentation

- Facts about the hardware go in `doc/hardware/`, protocol knowledge in `doc/protocol/`, research summaries in `doc/research.md`. Each claim carries its source (URL, file and offset in a vendor binary, capture name).
- Decisions go into `doc/log/<date>.md`, work items into `doc/work/`.
