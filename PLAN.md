# Plan

## End goal

The owner can scan 35 mm and 120 film on Linux with the OpticFilm 120, at full quality (full resolution, 16-bit per channel, infrared channel for dust removal), through a maintained open source user-space driver. Secondary: the knowledge gathered (protocol, hardware, calibration) is documented well enough that someone else could maintain or port the driver.

Second goal (owner, 2026-10-15): SilverFast Ai Studio 8, the front end bundled with the scanner, working on Linux, through Wine, a Windows guest on the Linux desktop, or a replacement of Plustek's engine library on top of the open driver. The options and their state are in `doc/work/0016-silverfast-on-linux.md`.

## Phases

### 1. Research

Collect everything that exists: manuals, vendor drivers and applications for every OS and version, third-party support (SilverFast, VueScan), open source work on the same controller family, known failure modes. Write up the facts from the printed manual.

Exit: `doc/research.md` answers what controller the scanner uses, which software supported it until when, and whether anyone has documented its protocol.

### 2. Diagnosis: is the unit alive?

Capture the USB descriptors. Find out whether `05e3:0103` is the expected identity or a fallback mode. Fix the test host's power supply. Using knowledge from the vendor drivers, talk to the scanner from Linux with harmless requests (status and register reads) and see whether the firmware answers.

Exit: a clear verdict, "hardware works and only the software side is missing" or "the unit has a fault X", with evidence.

### 3. Reference behaviour

Get the vendor stack talking to the scanner somewhere we control (an older Windows or macOS release in a VM with USB passthrough, or old hardware), and record full USB traces of initialisation, calibration, preview, scan, eject and standby. If the unit has a fault, decide here whether repair (for example reflashing firmware) is in reach.

Exit: a library of annotated USB captures.

### 4. Protocol reverse engineering

Combine static analysis of the vendor driver binaries with the captures: command set, register map, motor and lamp control, calibration (dark and white shading), data format of the image stream, infrared channel, buttons and status. The engine's code is the playbook and the capture the check (`doc/work/0012-driver-playbook.md`); each sequence is mapped onto the pyopticfilm function that does the same job for the other GL128 OpticFilms, so phase 5 starts from a model configuration rather than from scratch.

Exit: `doc/protocol/` documents enough to write a driver from it.

### 5. User-space driver

A libusb based driver for Linux, first as a minimal command line tool that produces a raw scan, then calibrated output, then a front end (a SANE backend or a standalone tool, decided in `DESIGN.md`).

Exit: the owner scans a roll of film on Linux.

### 6. Image quality and polish

Shading correction, colour, infrared dust removal, multi-exposure, film holder handling, documentation for users.

### 7. Upstream

Once the unit scans again and the results are verified, contribute OpticFilm 120 support and the findings to the existing open source drivers for this chip: [pyopticfilm](https://github.com/jboneng/pyopticfilm) first (Python, already scans three GL128 OpticFilms), then SANE's `genesys` backend (`gl128.cpp`, in master since 2026-10-01). Includes the model configuration, the GL128 knowledge recovered from the vendor drivers (register field names, serial flash access), and how to handle a unit that lost its USB identity.

Exit: OpticFilm 120 support merged upstream, or offered as a pull/merge request with the evidence attached.
