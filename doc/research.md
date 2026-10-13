# Research summary

What public sources and vendor files say about the OpticFilm 120, as of 2026-10-13. The full raw report with every source is `work/research/01-online-research.md` (untracked). Facts marked "verified" were rechecked against the downloaded file or source in this session. Downloaded files are listed in `work/downloads/MANIFEST.md`.

## The unit reports the wrong USB identity

| | Working OpticFilm 120 | Owner's unit |
|---|---|---|
| VID:PID | `07b3:1406` (Plustek) | `05e3:0103` (Genesys Logic) |
| bcdDevice | `0x0702` | `0x0702` |
| Manufacturer / product string indices | 10 / 11 | 1 / 2 |
| Product string | `"Film Scanner  "` (two trailing spaces) | `"USB2.0 Scanner"` |
| Manufacturer string | not in the capture | `"Genesys"` |
| Class, configuration, endpoints | identical (vendor class, self powered, 10 mA, bulk `0x81`/`0x02` 512 B, interrupt `0x83` 1 B, bInterval 8) | identical |

Sources:
- Working unit: the device descriptor in the USB capture attached to [SANE issue #151](https://gitlab.com/sane-project/backends/-/issues/151) (verified: three copies of `12 01 00 02 ff ff ff 40 b3 07 06 14 02 07 0a 0b 00 01` in the file; the string descriptor `"Film Scanner  "` is in it too), and `lsusb` / `sane-find-scanner` output in the same issue.
- Every Plustek Windows driver package from 2013 to 2015 binds only `USB\VID_07B3&PID_1406` (verified in `A31U_x64.inf` of V5.0.2.0; device name "Film Scanner(A31)", A31 being Plustek's internal model code). VueScan lists the same ID ([hamrick.com](https://www.hamrick.com/vuescan/plustek_opticfilm_120.html)).
- `05e3:0103` appears in no public ID database, SANE source or VueScan model page the research checked.
- GL128 siblings (OpticFilm 8100 V2, 8200i SE) enumerate directly as `07b3:18xx` with bcdDevice `0x0702` on plug-in, with no loader stage in between (pyopticfilm capture notes, `01_enumerate/NOTES.md`). So `05e3:0103` is not a normal pre-firmware state of this chip family.

**Consequence:** the Plustek driver cannot bind to the unit on Windows, which on its own explains "scanner not found" there. The macOS driver's matching rules are not checked yet.

**Hypothesis (unverified):** the controller lost the configuration that holds the Plustek identity (an external EEPROM or flash, or a fault reading it) and fell back to Genesys defaults. The string index change (10/11 to 1/2) fits a different descriptor source, not a changed value in the same table. Where a GL128 board keeps its identity is not documented publicly. Whether the rest of the scanner works is the next thing to test (see `PLAN.md` phase 2).

## Controller: Genesys GL128

- bcdDevice `0x0702` maps to GL128 in SANE's chip probe (verified: `tools/check-usb-chip.c` lines 1913 to 1914 and 4043 to 4044 of the 2026-10-12 master). `sane-find-scanner` reported `chip=GL128` for the working unit in issue #151.
- The GL128 is described as a GL124-family ASIC ([SANE commit 288d813a](https://gitlab.com/sane-project/backends/-/commit/288d813af2169a6ac9860a86b632203cbd281b64)). No public GL124 or GL128 datasheet is known.
- Register access uses USB control transfers in the GL124 framing that SANE already implements (`backend/genesys/scanner_interface_usb.cpp`). The vendor driver in the issue #151 capture polls register `0x101` thousands of times this way.
- Same ASIC in other Plustek models: OpticFilm 8200i SE (`07b3:1825`), 8100 V2 (`07b3:1824`), 8300i SE (`07b3:181f`), 135i (`07b3:1436`).
- The Pacific Image, Reflecta and Braun film scanners that use VID `05e3` (for example `05e3:0146`) are a different design: a Genesys USB bridge in front of SCSI-style scanner logic (SANE `pieusb` backend). Sharing the vendor ID does not make them relatives of the OpticFilm 120.

## Optics and mechanics

- Sensor: Toshiba TCD2558DG-1 tri-linear colour CCD, 5340 pixels, 7 µm pitch ([closeuphotography](https://www.closeuphotography.com/plustek-opticfilm-120-scanner-lens-test)).
- LED light source including an infrared LED for dust removal; 50 mm f/3.92 lens; 5300 dpi optical, about 3450 dpi measured; 5.7 kg ([filmscanner.info](https://filmscanner.info/en/PlustekOpticFilm120.html)).
- Motorised holder transport. The current (2024) Quick Guide says the scanner will not pull in a holder without USB, and ejects an inserted holder "when connection with a computer has been established" ([Quick Guide 2024](https://d3b63i9tvm4mo6.cloudfront.net/downloads/english/user_guide/17-0703A1M00011_12L_V1.0.pdf), pp. 17 and 21).
- No teardown beyond lens access, no service manual, no board photos found.

## Software support

- Plustek: Windows driver V6.0.0.0 and macOS driver V3.1.0.0, both listed 2024-02-01; the Mac driver covers macOS 10.13 to 27 and is marked "M1 Chip compatible" ([support page](https://plustek.com/us/products/film-photo-scanners/opticfilm-120/support.php)). Older Windows drivers V5.0.0.2 to V5.0.2.0 (2013 to 2015) and a 2016 macOS patch were also downloaded. No Linux driver, no Plustek scanning application: SilverFast is the bundled front end.
- The Windows driver is a WIA micro driver on top of `usbscan.sys` (`WIAA3103.dll`, `PkWiaDrv20_A31.dll`, `MidrvA31.dll`), from the INF.
- SilverFast 9 supports the model on current Windows and macOS. Installers need a serial plus email or a MySilverFast login ([SilverFast model page](https://www.silverfast.com/models/plustek-opticfilm-120/)).
- VueScan supports it on Windows and macOS only, through the Plustek driver. There is no built-in driver on Linux ([hamrick.com](https://www.hamrick.com/vuescan/plustek_opticfilm_120.html)).
- SANE: unsupported (issues [#151](https://gitlab.com/sane-project/backends/-/issues/151) and [#401](https://gitlab.com/sane-project/backends/-/issues/401)). SANE master gained GL128 support for the OpticFilm 8200i SE on 2026-10-01 ([MR !1030](https://gitlab.com/sane-project/backends/-/merge_requests/1030)); not in a release yet.
- [pyopticfilm](https://github.com/jboneng/pyopticfilm) (Python, PyUSB, GPL-3.0-or-later) scans with three GL128 OpticFilms and documents the GL128 boot sequence, register map, AFE access, shading upload and image transfer. It is the closest existing driver to what this project needs.

## Known failure modes

- 2013 shipment stop over an unnamed component ([photographyblog](https://www.photographyblog.com/news/plustek_halts_shipments_of_opticfilm_120)); reports of quality problems and banding. No public report of the identity change seen on this unit, and no documented hardware reset or firmware recovery procedure.

## Licensing

SilverFast licenses are issued against the scanner's hardware serial ([activation page](https://www.silverfast.com/show/activation-plustek/en.html)). SilverFast 9 needs a MySilverFast account. The Plustek driver itself has no activation step (INF only installs WIA and STI components).
