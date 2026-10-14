# Serial flash of the owner's unit

Full read of the serial flash over USB on 2026-10-14 06:17 UTC, with `tools/pi/flash_dump.py` (requests in `../protocol/serial-flash.md`, "Reading the whole flash over USB"). Run log: `probes/20261014T061716Z-flash-dump.jsonl`. The image itself stays in `work/flash/` (untracked); its whole content is described below.

## Chip

The JEDEC ID read returned `1c 31 13`: EON EN25F40, 4 Mbit (512 KiB). Source: flashrom `include/flashchips.h` (`EON_EN25F40 0x3113`, EON manufacturer code `0x1c`). The working unit in the issue #151 capture returned `c2 20 13` (Macronix, MX25L4005 class, also 512 KiB), so Plustek fitted parts from different makers. The engine never looks at the ID (`../protocol/serial-flash.md`, notes on `SFlash_RDID`).

## Result

- Both passes (ascending, then descending) are identical, SHA-256 `d8a31ba9d2e07b95260e49a4cc6a11c3941546014c33cd314f1320f945bf81b1`. The address check passed (`consistent`), and no address bit aliases.
- 28 of the 524288 bytes are not `0xff`, all at `0x00` to `0x1b`. The rest of the chip is blank.
- Those 28 bytes are the infrared scaling record (`../protocol/serial-flash.md`, "Infrared scaling record"), seven LE32 words:

| Word | Owner's unit | Working unit (capture) |
|---|---|---|
| 0 | 5300 | 5300 |
| 1 | 551 | 541 |
| 2 | 10511 | 10495 |
| 3 | 674 | 580 |
| 4 | 591 | 586 |
| 5 | 10467 | 10461 |
| 6 | 698 | 600 |

Same layout, word 0 equal, the others close: per-unit calibration values *(inference)*.

## What it rules out

- `apiCounterControl` never reset a counter on this unit after the record was written: that path erases `0x00000` to `0x0ffff` and leaves `00000000` and a total at address 0 (`../protocol/serial-flash.md`, "Usage counters").
- The flash holds no USB identity, no descriptor, no strings and no firmware. Either the identity never lived in this flash, or it lived in a part that something other than the engine code read so far has erased. A full dump of a working unit would tell the two apart.

## Other readings from the same run

- Registers before any write: `0x31 = bc`, `0x34 = 00`, `0x36 = 00`. `GPOE8` (`0x34` bit 7) is clear, which fits the standby reading in `../vendor-driver/macos.md`, "Standby" *(inference)*.
- The link check returned `55` after each SPI init write, the value a working unit gives. Before any write it returns `aa` (`usb.md`, "Read-only probe").
