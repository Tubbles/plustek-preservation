# Documentation index

- `research.md`: what is known about the OpticFilm 120 from public sources and vendor files (USB identity, GL128 controller, software support, related scanners, failure modes).
- `hardware/usb.md`: USB identity and behaviour of the owner's unit.
- `protocol/of120-capture-151.md`: annotated walkthrough of the only public USB capture of a working OpticFilm 120 (boot sequence, serial flash read, interrupt endpoint, the read-only probe set).
- `vendor-driver/windows.md`: Plustek's Windows driver package (layers, the `Scanapi.dll` engine, firmware and flash strings).
- `vendor-driver/macos.md`: Plustek's macOS driver (`PLK_A120.framework` with C++ symbols, serial flash API, the OpticFilm 120 configuration plist).
- `manual/quick-guide.md`: facts from the printed Quick Guide, in our own words (buttons, LEDs, holders, installation).
- `log/`: dated decision logs, one file per day, tagged for grepping.
- `work/`: work items. Each file has a `Status:` line (`todo`, `in progress`, `blocked`, `implemented`, `done`).
