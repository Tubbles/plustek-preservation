# Instructions for agents

## Sensitive data

- Serial numbers (SilverFast license serials, the scanner's hardware serial), the owner's registration email, and the scans of the DVD case and sticky note are sensitive. They live only in `work/sensitive.md` and outside the repository. Never write them into tracked files, commit messages, logs or captures that get committed.
- USB captures may contain the hardware serial or license data. Keep raw captures in `work/captures/`. Only commit captures or excerpts after checking them for such data.
- Downloaded vendor binaries stay in `work/downloads/` (untracked, see `work/downloads/MANIFEST.md`). They are for analysis only: never run them on the host outside a VM or Wine prefix set up for that purpose, and never commit them.

## Hosts

Host names, access details and machine specific notes live in `CLAUDE.local.md` (untracked). The scanner is attached to a Raspberry Pi 3 (Debian 13, aarch64); development happens on a separate, slow workstation.

## Talking to the scanner

- Until the protocol is understood, only send requests whose effect is known from the vendor driver or from captures. A wrong write could move a motor against an end stop or change the firmware configuration. Reads of descriptors and documented status requests are fine.
- The scanner drops off the bus after about 5 minutes without host activity (standby, not yet confirmed). The owner wakes it with the power button.

## Documentation

- Facts about the hardware go in `doc/hardware/`, protocol knowledge in `doc/protocol/`, research summaries in `doc/research.md`. Each claim carries its source (URL, file and offset in a vendor binary, capture name).
- Decisions go into `doc/log/<date>.md`, work items into `doc/work/`.
