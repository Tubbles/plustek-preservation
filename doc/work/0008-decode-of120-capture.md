# 0008 Decode the public OpticFilm 120 USB capture

Status: done (reviewed)

The only public capture of a working OpticFilm 120 (attached to SANE issue #151, a VueScan preview through Plustek's driver). Deliverables: a reusable USBPcap decoder in `tools/usbpcap/`, an annotated walkthrough in `doc/protocol/of120-capture-151.md`, and a "safe probe set" of read-only requests with the values a working unit returns, to replay on the owner's unit.
