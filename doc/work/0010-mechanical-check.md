# 0010 Check the mechanics after the reassembly

Status: done for the carrier drive (2026-10-15); the loader drive is checked by the holder test in `0013-debugging-facilities.md`

The owner disassembled the unit for the board photos (2026-10-14) and reassembled it on 2026-10-15 with doubts about the spring-loaded gear train around the moving holder carrier and with one stripped screw hole (`doc/hardware/board.md`, "Reassembly"). Before the first request that powers the motor, make sure the mechanism runs free, so that a jam does not strip a gear or stall the motor against an end stop.

Steps:
- [x] Agree with the owner on the check (2026-10-15): the owner prefers to move the carrier under motor power rather than open the unit again. The read-only part is the home and holder sensor bits at the next wake; the moves are `0011-first-motor-move.md`.
- [x] Keep the film holder out of the unit until the check is done. The Quick Guide says the scanner ejects an inserted holder once a computer is connected (`doc/research.md`), a move the host does not control. Kept out through all runs of 2026-10-15; the holder goes in next, as the test of the loader drive.
- [x] Define the first motor command as the shortest, slowest move in the working capture (`doc/protocol/of120-capture-151.md`, positioning moves), with the owner at the power switch and an explicit go-ahead for that run. Done as `0011-first-motor-move.md`: two replays of the vendor's move 3 (97 steps, loader drive as it turned out, nothing heard), then the vendor's move 1 with 97 steps (the carrier left the home sensor, motion heard) and with 500 steps (754 steps with the ramps, 0.80 s). The owner on the 500-step run: the motor sounded smooth, "like how I want to remember it sounding all those years ago".
- [x] Record the outcome in `doc/hardware/board.md` ("Reassembly") and the log (`doc/log/2026-10-15.md`, "The carrier moved").

The carrier drive and its gear train run free after the reassembly. Motor runs still need the owner's go-ahead per run (`CLAUDE.md`, "Talking to the scanner").
