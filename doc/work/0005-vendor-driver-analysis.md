# 0005 Static analysis of vendor driver packages

Status: implemented

Unpack the Windows and macOS driver packages. Find the USB IDs they match (INF files, Info.plist), the user-space and kernel components, any firmware or calibration blobs, and the command layer that talks to the scanner.

Results: `doc/vendor-driver/windows.md`, `doc/vendor-driver/macos.md` and, from the macOS engine's symbols, `doc/protocol/serial-flash.md`, `usb-requests.md` and `gl128-registers.md`. The Windows `Scanapi.dll` was not disassembled: the macOS engine carries C++ symbol names and was enough.
