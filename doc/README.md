# Documentation index

- `research.md`: what is known about the OpticFilm 120 from public sources and vendor files (USB identity, GL126 controller, software support, related scanners, failure modes).
- `hardware/usb.md`: USB identity and behaviour of the owner's unit.
- `hardware/flash-dump.md`: chip and content of the owner's serial flash.
- `hardware/board.md`: the main board of the owner's unit, from photos: every chip identified, date codes, what that means for the USB identity and the board revision, and the state of the unit after reassembly.
- `protocol/of120-capture-151.md`: annotated walkthrough of the only public USB capture of a working OpticFilm 120 (boot sequence, serial flash read, interrupt endpoint, the read-only probe set).
- `protocol/serial-flash.md`: how Plustek's macOS engine reads, writes and erases the serial flash on the scanner board, and what it keeps there.
- `protocol/usb-requests.md`: encoding of every other vendor request in the macOS engine (registers, front end, bulk transfers, buttons, reset, standby).
- `protocol/gl128-registers.md`: register field map generated from the macOS engine's accessor methods.
- `vendor-driver/windows.md`: Plustek's Windows driver package (layers, the `Scanapi.dll` engine, firmware and flash strings).
- `vendor-driver/macos.md`: Plustek's macOS driver (`PLK_A120.framework` with C++ symbols, serial flash API, the OpticFilm 120 configuration plist).
- `manual/quick-guide.md`: facts from the printed Quick Guide, in our own words (buttons, LEDs, holders, installation).
- `log/`: dated decision logs, one file per day, tagged for grepping.
- `work/`: work items. Each file has a `Status:` line (`todo`, `in progress`, `blocked`, `implemented`, `done`).
