# Serial EEPROM read over USB

One run of `tools/pi/eeprom_read.py` on 2026-10-14 22:08 UTC over words 0 to 7, with the owner's go-ahead, on the first wake after a 24 V power cycle (the unit had been unplugged since the board photos, `board.md`). Requests and the decision rule for the result: `../protocol/serial-eeprom.md`, "Clocking of the 0x8b byte" and "Reading the EEPROM over USB". Run log: `probes/20261014T220845Z-eeprom-read.jsonl`.

## Result

- Registers before any write: `0x31 = bc`, `0x34 = 00`, `0x4f = 00`, `0x8e = 00`, `0x8f = 00`. The same `0x31` and `0x34` as before the flash dump (`flash-dump.md`).
- `0x0a` read `0x80` at power-on, `EPROMSEL` (bit 3) clear. The tool wrote `0x88`, read `0x88` back, and restored `0x80` at the end. So `0x0a` returns the written latch, at least for bit 3, unlike `0x31`. The vendor's register blast writes `0x48` here (`../protocol/serial-eeprom.md`, "EPROMSEL").
- The busy bit (`0x4f` bit 4) was never seen set.
- Both passes returned sixteen `00` bytes (SHA-256 `374708ff…37bb`, the hash of 16 zero bytes). Every word is `0000`: `0x8f` and `0x8e` returned `00` for every READ command, as they did before the first command. Exit code 15, 3.5 s.

## Reading

By the rule in `../protocol/serial-eeprom.md`: every word equal and not `ffff` means the data registers do not follow the address. The run cannot separate the two readings it was designed to leave open, and neither gives a USB path to the chip:

- `0x8b`, `0x8e` and `0x8f` are the exposure fields `EXPR` and `EXPG` on this chip (`CGL126`, and SANE's GL124), and the READ commands landed in an exposure register. `00` is the power-on value and what SANE writes there. This is the reading the document predicted.
- The registers are a Microwire interface and its data line sits low. An AT93C46D with nothing programmed reads ones, not zeros (ERASE and ERAL program every bit to logic 1, [AT93C46D datasheet](https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-5193-SEEPROM-AT93C46D-Datasheet.pdf), instruction descriptions), and under the clockings that form almost no READ in words 0 to 7 the data registers keep what they held before, which was `00` too.

A third reading, that the interface works and words 0 to 7 really hold `0000`, is not excluded, but a 64-word run is only safe once the clocking is known to be the expected one, and this result says nothing about the clocking. The tool also ran without the open's register blast and clock set-up (`../protocol/serial-eeprom.md`, "Caveats"). So the USB route to U19 stops here, as the document's rule says.

## Consequence

- The content of U19 needs a read in circuit: an SOIC-8 test clip on the chip, driven from the Pi's GPIO pins (`../work/0007-identity-and-flash.md`). The same clip lets a logic analyser or the Pi watch the four Microwire lines while the unit powers up, which shows whether the ASIC reads the chip at all and what it gets.
- `keep-awake-enabled` was created on the Pi right after this run, as planned (`usb.md`, "Standby"): from the next wake on, the watcher runs `tools/pi/keep_awake.py`. Remove the flag before any further `eeprom_read.py` run, which wants the power-on value of `0x34`.
