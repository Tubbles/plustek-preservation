# Main board of the owner's unit

The owner opened the scanner on 2026-10-14 (warranty seals broken) and photographed the main board in place. The seven photos are in `work/board-photos/20261014/` (untracked, phone camera, partly blurred); they show no serial numbers. Markings were read from enlarged crops of the photos, and the parts were identified by searching the markings. Each identification names its source. *(inference)* marks readings that go beyond what the photo or the source states. Reference designators are the board's silkscreen.

## Parts

| Ref | Marking on the part | Part | Source |
|---|---|---|---|
| U1 | Genesys logo, `GL126`, `MY10A02G01`, `216SM7681` | Genesys Logic GL126 USB 2.0 scanner controller. LQFP with silkscreen pin numbers `10` to `40` along one edge and `90` to `130` along the opposite one, so 44 pins per side, 176 pins *(inference)*. | [GL126 product page](https://www.genesyslogic.com.tw/en/product-detail/PC-based_Scanner/GL126) |
| U2, U3 | `ESMT`, `M12L2561616A-6T`, `AZA1P12E8`, `1218` | ESMT 256 Mbit SDRAM, 16M×16, 166 MHz, 54-pin TSOP II. Two chips, 64 MiB together. | [Suntsu listing](https://suntsu.com/product/integrated-circuits/memory/m12l2561616a-6t-2t/); the GL126 page lists 16M×16 SDRAM and "two SDRAM" |
| U4 | `cFeon`, `F40-100HIP`, `09C117A`, `P014CDA` | EON EN25F40, 4 Mbit serial flash, SOIC-8. Its JEDEC ID `1c 31 13` was read over USB (`flash-dump.md`). cFeon is EON's top marking brand since 2009. | `flash-dump.md`; [EN25F32 datasheet note on cFeon marking](https://pdf.jiepei.com/en25f32-17047831.html) |
| U5 | TI logo, `66A993M`, `ACT157M`, `G4` | Texas Instruments CD74ACT157M, quad 2-input multiplexer, SOIC-16 (orderable as CD74ACT157M and CD74ACT157M96). Role on this board unknown. | [TI product page](https://www.ti.com/product/CD74ACT157), [Arrow listing](https://www.arrow.com/en/products/cd74act157m96/texas-instruments?region=nac) |
| U11 | Megawin logo, `MPC82E54AS3`, `1242GGCA`, `C4N000.00C`, a pink paint dot | Megawin MPC82E54A, 1T 8051 microcontroller: 15.5 KB flash, 256 B RAM plus 256 B XRAM, crystal up to 25 MHz, UART, SPI, 10-channel 8-bit ADC, PCA and PWM, watchdog, ISP and IAP. 28-pin SSOP (14 pins per side in the photo; Elnec lists an SSOP28 variant). | [Keil device database](https://www.keil.com/dd/chip/4130.htm), [Elnec device list](https://www.elnec.com/en/search/device-list/27/megawin) |
| U14, U15 | `N2Y22AD`, `DS90LV`, `048AT` | National Semiconductor (now TI) DS90LV048A, quad LVDS receiver, TSSOP-16. Two chips, eight LVDS lanes. | [TI datasheet SNLS045](https://www.ti.com/lit/gpn/DS90LV048A) |
| U19 | `ATMLH032`, `46D 1`, the rest under blue paint | Atmel (now Microchip) AT93C46D, 1 Kbit three-wire (Microwire) serial EEPROM, 1.8 V to 5.5 V, SOIC-8. The datasheet's marking scheme for the 8-lead SOIC is `ATMLHYWW` over `### %`: `ATML` Atmel, `H` industrial grade with NiPdAu finish, `Y` year digit, `WW` work week of assembly, `###` the truncation code `46D`, `%` the minimum voltage code (`1` = 1.8 V). So: AT93C46D, assembled week 32 of a year ending in 0, which on a 2012 board is 2010 *(inference: the datasheet's year table lists one decade)*. | [AT93C46D datasheet, Atmel-5193H, section 9 "Part Markings"](https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-5193-SEEPROM-AT93C46D-Datasheet.pdf) |
| U20 | SOT-23-6, marking not readable | | |
| U22 | SOT-23-5, marking not readable, next to Y2 | | |
| Y2 | `N12.000`, `4D30PB` | 12.000 MHz crystal in a metal can, with R63 (`105`, 1 MΩ) and C73, C74 beside it. Which chip it clocks is not visible: the GL126 takes a 12 MHz clock input (product page) and the MCU needs a crystal too. | |

Passive parts worth noting (SMD codes: `330` is 33 Ω, `470` 47 Ω, `101` 100 Ω, `103` 10 kΩ, `105` 1 MΩ, `000` a link):

- RP18, a four-resistor pack marked `470` (47 Ω), sits between U1 and U19, with R70 (`103`, 10 kΩ) on U19's other side. A 93C46 has four signal lines (CS, SK, DI, DO) on pins 1 to 4 and the organisation pin ORG on pin 6, which selects x16 when tied high. Four series resistors plus one pull-up is what a Microwire EEPROM on the ASIC's EEPROM pins needs *(inference: the traces were not followed)*.
- RP16 and RP17 (`101`, 100 Ω) sit at the inputs of U14 and U15: LVDS terminations *(inference)*.
- Ten or more four-resistor packs marked `330` (33 Ω) surround U1, U2 and U3 (RP1, RP4 to RP8, RP10, RP13, RP19, RP20): series termination of the SDRAM bus *(inference)*.

Other things on the board: a long FFC connector on the edge next to U14 and U15 (the sensor board, where the analogue front end would sit *(inference)*), the pin header CN5 and the FFC connector CN7 on the opposite edge (flat cable printed `VW-1 60V 80C`), several electrolytic capacitors near the FFC connector, and a round yellow "QC OK" sticker.

## Board markings

Silkscreen on the component side, partly hidden under a cable: `…4-1.6` (read as the laminate and thickness, FR4 1.6 mm *(inference)*), `38F2-D`, `2012`, the laminate maker's UL mark `P-Y 88 94V-0`, and a four-glyph code near it read as `1304` (uncertain, photo 06).

## Date codes and the board revision

| Part | Code | Date |
|---|---|---|
| U19 EEPROM | `H032` | 2010, week 32 (datasheet scheme above) |
| U2, U3 SDRAM | `1218` | 2012, week 18 *(inference: YYWW)* |
| U11 MCU | `1242` | 2012, week 42 *(inference: YYWW)* |
| PCB | `2012` | 2012 |

The newest part was made in week 42 of 2012, so the board was assembled in late 2012 or later, which fits a unit bought before 2022 from the first production years. The `-new1440` configuration of Plustek's macOS driver, which describes a changed board, was added on 2022-11-18 (`../vendor-driver/macos.md`). This board is therefore the original revision *(inference: assumes the changed board is not older than the driver support for it)*. The film holder test in `tools/pi/probe_readonly.py --gpio` remains a direct check.

## What the parts say about the fault

- The serial flash (U4) holds no USB identity (`flash-dump.md`). U19 is a 93C46-class EEPROM next to the ASIC, which is the part family Plustek's `CAsic::ReadFromNVRAM` is written for: 16-bit words, 6-bit addresses, the EWEN, READ and EWDS commands (`../protocol/serial-eeprom.md`). So the USB identity most likely lives in U19, and the Genesys default identity means the GL126 did not get valid data from it at power-up: blank, corrupted, or not readable because of a connection fault *(inference)*.
- Two ways to read it: over USB with `tools/pi/eeprom_read.py` (no hardware, but it is open whether the registers reach the chip on this ASIC, `../protocol/serial-eeprom.md`, "Conflict with the exposure registers"), or in circuit with an SOIC-8 test clip on the Pi's GPIO pins (hardware purchase).
- The GL126's embedded CPU does the USB protocol, so the identity does not need a microcontroller.

## Reassembly (2026-10-15)

The owner put the unit back together on 2026-10-15 and reports that the spring-loaded gear train around the moving holder carrier was hard to reassemble, that something there may not be seated as it was, and that one screw hole lost its thread (the screw stays in). The electronics are not affected by any of this as far as is known. The mechanics were checked under motor power on 2026-10-15 (`../work/0010-mechanical-check.md`): the carrier left the home sensor on a 97-step replay of the vendor's move 1 and ran 754 steps on a 500-step replay, and the owner reports the motor sounded smooth, as remembered from when the unit worked. A full-length replay (10158 steps, about one inch) and, on 13:20 UTC, the first reverse move (`move_carrier.py --home`, move 1 with `MTRREV`, `probes/20261015T132025Z-move-carrier-home.jsonl`) ran the same way: the carrier came back onto the home sensor from 754 steps out in 0.69 s and the owner heard nothing scrapey in either direction. The firmware's own power-on homing, the one move the host does not drive, sounds a little scratchy to the owner (`usb.md`, "Power"), so that sound belongs to the firmware's motion profile rather than to the gear train at the host's speed *(inference)*. The loader drive, the path that `0x33` bit 5 selects (`../protocol/playbook.md`, "Moves and homing"), is not checked yet: its two replays were silent with nothing in the slot. The EEPROM read and the keep-awake tool write only `0x0a`, `0x8b`, `0x31` and `0x34`, none of which touch the motor. The film holder stays out of the unit meanwhile: the Quick Guide says the scanner ejects an inserted holder once a computer is connected (`../research.md`), which would be a motor move outside our control. What the 8051 (U11) does is unknown; the GL126 "supports external MCU with SPI interface" (product page). The front panel button, the LEDs and the standby timer are things an ASIC-only design would have trouble with and a small MCU next to the panel connector would do *(inference, untested)*. If so, the vendor's `StandbyReg` line (`GPIO8`, `../vendor-driver/macos.md`, "Standby") is the ASIC telling the MCU that a host is active.
