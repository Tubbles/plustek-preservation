# Design

## Decided: the driver is pyopticfilm (2026-10-13)

OpticFilm 120 support is built inside a fork of [pyopticfilm](https://github.com/jboneng/pyopticfilm) ([Tubbles/pyopticfilm](https://github.com/Tubbles/pyopticfilm)), included here as the `pyopticfilm/` submodule. Reasons: pyopticfilm already drives the same GL128 ASIC on three hardware-tested OpticFilm models, so the 120 needs mostly model data and identity handling, and the work can go upstream as an ordinary pull request (`PLAN.md` phase 7). Consequences: the driver is Python and follows pyopticfilm's conventions (`pyopticfilm/CONTRIBUTING.md`: model-specific constants on the model's own class, model-lock tests only for hardware-validated models, hardware sign-off before `scan_ready`). This repository keeps the research, protocol documentation, capture tools and the USB identity and flash work. A SANE backend port is a later, separate step.

Branches in the submodule: `main` follows upstream; OpticFilm 120 work happens on feature branches that become upstream pull requests.

## Constraints known so far

- The scanner is a USB 2.0 high-speed device that enumerates as `05e3:0103` (Genesys Logic), see `doc/hardware/usb.md`.
- No kernel driver claims it, so a user-space driver over libusb needs no kernel work for access. A kernel driver is only on the table if libusb turns out to be insufficient (for example isochronous timing), which nothing points to yet.
- The test host is a Raspberry Pi 3 (aarch64, 1 GB RAM). The driver must run there, and must not assume a fast machine: a 6x12 frame at the advertised 5300 dpi is about 12500 x 25000 pixels, which at 16 bit for each of R, G, B and infrared is about 2.5 GB.

## Decided: the driver matches the Genesys default identity (2026-10-15)

A unit with the Genesys default identity (`05e3:0103`) is matched explicitly, only together with bcdDevice `0x0702`, so that other Genesys devices are not claimed (`doc/work/0015-pyopticfilm-opticfilm-120.md`). Restoring the Plustek identity on the unit (`doc/work/0007-identity-and-flash.md`) is not a prerequisite for the driver and stays a separate question.

## Open decisions

None at the moment.
