# Slope tables from the issue #151 capture

The four distinct 512-byte payloads that the OpticFilm 120 driver uploads before its carrier moves in the SANE issue #151 capture, as hex dumps. Each file is named after the first frame that sent its payload. How the tables are used and what they contain is in `../of120-moves.md`, "Slope tables".

| File | Frame | Address | SHA-256 of the 512 bytes | Also sent at frames |
|---|---|---|---|---|
| `slope-6267.hex` | 6267 | `0x1000c000` | `47a4f0bc51c2a53ed0298d2b2e5e4bfdb0af3a40c5d812cacb470d2934b2d7a2` | 6275, 13735, 13743 |
| `slope-6353.hex` | 6353 | `0x1000c000` | `6c5dcd0eb8f251e3e03957e89eb1506b2b9e479dcba9ffc0b0124a5895692bd4` | 6361, 6471, 6479, 13819, 13827, 13935, 13943, 15573, 15581 |
| `slope-6653.hex` | 6653 | `0x1000c000` | `838b1154f780d8d8550ae565bbb143170e0caa17acd8ceb35b9dceca45402c92` | 6661, 14147, 14155 |
| `slope-7419.hex` | 7419 | `0x1000c000` | `a73cbf604e186370e5113abc8343bbd1f7a13ca4d3a94f22b31b798a8b537a76` | 7427 |

Every upload goes first to `0x1000c000`, then the same bytes to `0x10010000`, so the second frame of each pair is the `0x10010000` copy. The 97-step move (move 3) sends `slope-6353.hex` at frames 6471 and 6479.

The capture holds each payload in full: the USBPcap records declare 512 bytes and contain 512. For all 20 uploads, the SHA-256 of the full payload from `decode.py --full-data` equals the `captured_sha256` that the default decode records for the same frame in `work/captures/151/transfers.jsonl` (checked 2026-10-15), and each dump turns back into those bytes with `xxd -r` (same SHA-256).

The files are `xxd` output: offset, eight 16-bit groups in wire order, ASCII column. One file is made like this, with the frame number of the table:

```
python3 -I tools/usbpcap/decode.py work/downloads/gitlab-sane-project/issue-151-optifilm120-usb-capture/Optifilm120 --full-data > work/captures/151/transfers-full.jsonl
grep '"frame": 6267,' work/captures/151/transfers-full.jsonl | python3 -I -c "import json, sys; sys.stdout.write(json.load(sys.stdin)['data_hex'])" | xxd -r -p | xxd > doc/protocol/tables/slope-6267.hex
```

To get the bytes back: `xxd -r doc/protocol/tables/slope-6267.hex > slope-6267.bin`.
