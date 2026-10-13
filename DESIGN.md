# Design

Nothing is decided yet. The architecture is chosen once phase 2 of `PLAN.md` shows what the scanner speaks.

## Constraints known so far

- The scanner is a USB 2.0 high-speed device that enumerates as `05e3:0103` (Genesys Logic), see `doc/hardware/usb.md`.
- No kernel driver claims it, so a user-space driver over libusb needs no kernel work for access. A kernel driver is only on the table if libusb turns out to be insufficient (for example isochronous timing), which nothing points to yet.
- The test host is a Raspberry Pi 3 (aarch64, 1 GB RAM). The driver must run there, and must not assume a fast machine: a 6x12 frame at the advertised 5300 dpi is about 12500 x 25000 pixels, which at 16 bit for each of R, G, B and infrared is about 2.5 GB.

## Open decisions

- Implementation language.
- Front end: SANE backend (works with existing scanning applications) versus a standalone tool (freedom to expose film specific features such as multi-exposure and the infrared channel).
- Where image processing happens: in the driver, or in a separate post-processing stage operating on raw scans.
