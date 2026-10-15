# 0013 Debugging facilities: status, flags, self tests, resets

Status: todo

Owner's direction (2026-10-15, after two host-driven moves ran the step engine with the working unit's timing and moved nothing, `0011-first-motor-move.md`): before more blind moves, inventory what the unit and the engine offer for debugging. Flags to read out, status to query, built-in self tests, and whether a soft reset brings the unit into a known, deterministic state. Each facility is derived from the engine's code first (`0012-driver-playbook.md` method), checked against the capture where it appears, and classed as read-only, write without motion, or motion.

Known so far, from the decompiled macOS engine (`work/re/decomp-x86_64/`, untracked):
- `CIOUSB::AsicSelfTest` (`0x0f83e0`) returns 0 and `CIOUSB::FlashSelfTest` (`0x0f8410`) returns 1 without touching the device: stubs. `CIOUSB::SdramSelfTest` (`0x0f8430`) is a real test: it writes a fill byte to a memory range with `WriteData`, reads it back with `ReadData` and compares. No decompiled function calls any of the three, so the engine does not run self tests on its own.
- `CIOUSB::HardwareResetScanner` (`0x0f8370`) sends one control write, wValue `0x8b`, wIndex `1`, four zero bytes, under the USB lock. No decompiled function calls it either. What the firmware does on it is not known.
- `CScanApi::SoftwareResetScanner` (`0x0338a0`) is what `Register` runs at open: `SCANRESET` (`0x0e = 0x00`), the settings read, the full register blast, clocks, DRAM refresh, flash ID (`doc/protocol/playbook.md`, "Standby", row 2). `apiReset` (`0x033820`) is its API entry.
- Status readers: `apiGetDeviceStatus` (`0x023180`), `CScanApi::GetModuleStatus` (`0x023a90`), `GetPaperStatus`, `GetLampStatus`, `GetButtonStatus`, `CScan::GetMyLastError` (`0x0401c0`), `CScan::DumpAllRegFromAsic` (`0x0bde50`) and `CIOUSB::DumpAllRegistersToConsole` (`0x0f8790`), `CIOUSB::ReadInterrupt` and `GetInterruptVal`, `ReadButtonID`. Register-level flags already known: `0x101` status bits (`doc/protocol/of120-moves.md`, "Status values"), `0x100` flags (`COVERSNR`, `CHKVER`, `DATAENB`, `MOTMFLG`, `HISPDFLG`), the GPIO data registers, `VALIDWORD` (`0x102` to `0x105`).
- Resets available in principle, from least to most invasive: `SCANRESET`; the `0x8b` wIndex `1` request; a USB port reset from the host (libusb `reset_device`, standard USB, effect on this firmware unknown); the 24 V power cycle, which is the firmware's own reset and runs its homing move (`doc/hardware/usb.md`, "Power").

Steps:
- [ ] Read the status readers and the dump functions: which registers and requests each one sends, what the returned bits mean per the engine, and which of them the capture shows. Deliverable: a section "Status and flags" in `doc/protocol/playbook.md` and a read-only register dump added to `tools/pi/probe_readonly.py` or a new read-only tool, so that a full snapshot of the unit can be taken at any time (every register the engine reads, `0x100` to `0x105`, the GPIO registers, the interrupt endpoint with a short timeout).
- [ ] Read `SoftwareResetScanner`, `HardwareResetScanner` and the firmware side of `0x8b` wIndex `1` (`doc/protocol/usb-requests.md`, `serial-flash.md`), and what pyopticfilm does for a reset (`is_cold_boot`, `asic_boot`). Deliverable: a section "Resets" with what each reset does to the ASIC state, the motor and the standby timer, and which one gives a deterministic state that a tool can verify by reading the dump afterwards.
- [ ] `SdramSelfTest` and any other test the engine could run: what it sends, whether it touches the motor or the flash, and whether it is worth running here. Deliverable: a section "Self tests".
- [ ] Decide with the owner which of these to run, then run them with the snapshot before and after.

Related: `0011-first-motor-move.md` (the moves that produced no motion), `0012-driver-playbook.md` (method and the standby section), `0007-identity-and-flash.md`.
