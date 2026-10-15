# Instructions for agents

## Sensitive data

- Serial numbers (SilverFast license serials, the scanner's hardware serial), the owner's registration email, and the scans of the DVD case and sticky note are sensitive. They live only in `work/sensitive.md` and outside the repository. Never write them into tracked files, commit messages, logs or captures that get committed.
- USB captures may contain the hardware serial or license data. Keep raw captures in `work/captures/`. Only commit captures or excerpts after checking them for such data.
- Downloaded vendor binaries stay in `work/downloads/` (untracked, see `work/downloads/MANIFEST.md`). They are for analysis only: never run them on the host outside a VM or Wine prefix set up for that purpose, and never commit them.
- Decompiled and disassembled output of the vendor engines stays in `work/re/` and `work/re-win/` (untracked, regenerated with `tools/ghidra/README.md`). Owner's decision 2026-10-15: not checked in. Commit the scripts and the findings, with function names and addresses as the references.

## Hosts

Host names, access details and machine specific notes live in `CLAUDE.local.md` (untracked). The scanner is attached to a Raspberry Pi 3 (Debian 13, aarch64); development happens on a separate, slow workstation.

## Talking to the scanner

- Until the protocol is understood, only send requests whose effect is known from the vendor driver or from captures. A wrong write could move a motor against an end stop or change the firmware configuration. Reads of descriptors and documented status requests are fine.
- The vendor engine is the playbook (owner, 2026-10-15, `doc/work/0012-driver-playbook.md`): derive a sequence from the engine's code (`doc/vendor-driver/`, Ghidra), confirm it against the capture, and map it onto the pyopticfilm function that does the same job, so that findings land as pyopticfilm support and not only as replay tools.
- The scanner leaves the bus about 5 minutes after a wake, even with read-only polling, unless the vendor's open sequence has been sent (`tools/pi/vendor_open.py`, `doc/hardware/usb.md`, "Standby"); after it the unit stayed up for hours. The owner wakes it with the power button and has agreed (2026-10-15) that the open sequence runs on every wake without a further go-ahead: the watcher on the Pi sends it itself when its `open-enabled` flag exists (`tools/pi/watch-scanner.sh`). Every other write still needs a go-ahead per run.
- The unit was reassembled on 2026-10-15 and the carrier drive was checked under motor power the same day: it runs free and sounds right (`doc/hardware/board.md`, "Reassembly"). The loader drive (`0x33` bit 5, `doc/protocol/playbook.md`, "Moves and homing") is still unchecked. Every motor run needs the owner's go-ahead and the owner at the unit; the film holder goes in only for the loader test the owner agreed to.

## Driver code (submodule)

- `pyopticfilm/` is a submodule pointing at the fork `Tubbles/pyopticfilm` (remote `origin`, pushes go over SSH; `upstream` is `jboneng/pyopticfilm`). Follow `pyopticfilm/CONTRIBUTING.md` there, not the conventions of this repository.
- Work on feature branches in the submodule. Commit the updated submodule pointer here only after the submodule commits are pushed to the fork, or the pointer breaks for everyone else.

## Reconstructed engine source (private submodule)

- `engine/` is the submodule `Tubbles/plustek-scanapi`, a private repository (owner's decision 2026-10-15) for the reconstructed source of Plustek's engine (`doc/work/0014-decompiled-code-cleanup.md`). It is derived from the vendor binaries, so it never becomes public and nothing from it is copied into this repository beyond function names and addresses. Cloners of this repository without access to it get an error for this submodule only.
- Its own `CLAUDE.md` holds the rules for editing it. Commit the updated pointer here only after the submodule commit is pushed.

## Documentation

- Facts about the hardware go in `doc/hardware/`, protocol knowledge in `doc/protocol/`, research summaries in `doc/research.md`. Each claim carries its source (URL, file and offset in a vendor binary, capture name).
- Decisions go into `doc/log/<date>.md`, work items into `doc/work/`.
