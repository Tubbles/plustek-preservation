# 0012 The vendor engine as the playbook, mapped onto pyopticfilm

Status: todo

Owner's direction (2026-10-15): read the official drivers as playbooks. The open sequence held the unit on the bus (`doc/hardware/usb.md`, "Standby"), and the engine's code says why it should: `StandbyModeSel` keeps bit 7 of `0x31` set and `Register` pulses it at open (`doc/vendor-driver/macos.md`, "Standby"). Setting the bit alone did not hold the owner's unit, so the open does something more that makes the line effective, and the engine's `Register` is where that is written down. From here on every sequence sent to the unit is derived from the engine first, confirmed against the issue #151 capture second, and mapped onto pyopticfilm third, so that the OpticFilm 120 support lands as a model configuration in pyopticfilm rather than as a replay tool.

Sources: the macOS engine keeps its symbols (`doc/vendor-driver/macos.md`, "Symbols"; Ghidra project per `tools/ghidra/README.md`), the Windows engine is the same code base (`doc/vendor-driver/windows.md`, "Disassembly"), the capture is decoded in `doc/protocol/of120-capture-151.md` and `of120-moves.md`, and pyopticfilm's GL128 code is `pyopticfilm/src/pyopticfilm/asic/gl128.py` (`asic_boot`, `init`, `feed`, `home`, `park`, `_upload_fast_slopes`, `wait_until_at_home`, `stop_motor`).

Steps, one topic at a time, each a section in `doc/protocol/playbook.md` with the engine function names and addresses, the capture frames that confirm the sequence, the pyopticfilm function that does the same job for the 8200i SE, and what differs:
- [ ] Standby: what `Register` writes before and after the pulse that makes the standby line effective (GPIO direction and output-enable registers `0x30` to `0x3c`, the plist register patches `31.80` and `34.80`), what `SetStandbyOffTime` reads on each tick, and what pyopticfilm does about standby on the SE (nothing found by a search for standby, sleep, wake or keep-alive in `pyopticfilm/src`). Outcome: the smallest write set that should hold the unit, to be tested on a later wake, and whether pyopticfilm needs a standby hook for this model.
- [ ] Open: `Register` end to end against `vendor_open.py`'s table and pyopticfilm's `asic_boot` and `init`. Which blast values come from the plist blob `0` and the register patches, which are computed.
- [ ] Moves and homing: the engine's feed, go-home and park functions against `of120-moves.md` and pyopticfilm's `feed`, `home`, `park` and `_upload_fast_slopes`. Settles how the engine homes (AGOHOME after a scan versus a BACKSCAN move), whether FEEDL counts the ramp, and what `0x33` bit 5 is.
- [ ] Scan: the image scan set-up and the data path, against pyopticfilm's shading and strip functions. Needed for phase 5 of `PLAN.md`.
- [ ] Keep `doc/research.md` and the pyopticfilm feature branch in step: every section ends with the pyopticfilm change it implies (model table entry, new hook, or nothing).

Related: `0005-vendor-driver-analysis.md` (the static analysis this builds on), `0011-first-motor-move.md` (the move tool replays the capture; its sequence is checked against the engine in the moves step), `0009-upstream.md`.
