# 0010 Check the mechanics after the reassembly

Status: todo

The owner disassembled the unit for the board photos (2026-10-14) and reassembled it on 2026-10-15 with doubts about the spring-loaded gear train around the moving holder carrier and with one stripped screw hole (`doc/hardware/board.md`, "Reassembly"). Before the first request that powers the motor, make sure the mechanism runs free, so that a jam does not strip a gear or stall the motor against an end stop.

Steps:
- [ ] Agree with the owner on a check that needs no motor command: by hand and by eye with the lid off, or by listening while the unit powers up with the holder out.
- [ ] Keep the film holder out of the unit until the check is done. The Quick Guide says the scanner ejects an inserted holder once a computer is connected (`doc/research.md`), a move the host does not control.
- [ ] Define the first motor command as the shortest, slowest move in the working capture (`doc/protocol/of120-capture-151.md`, positioning moves), with the owner at the power switch and an explicit go-ahead for that run.
- [ ] Record the outcome in `doc/hardware/board.md` and the log.

Until this item is done, no motor-driving request goes to the unit (`CLAUDE.md`, "Talking to the scanner").
