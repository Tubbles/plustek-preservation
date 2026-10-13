# plustek-preservation

Bringing a Plustek OpticFilm 120 medium-format film scanner (2012) back to life, with the goal of a Linux user-space driver.

The owner's unit no longer works with the vendor software on Windows or macOS. Whether that is lost software support or a hardware fault is the first thing this project has to find out.

## Status

Research phase. See `PLAN.md` for the roadmap and `doc/work/` for individual work items.

## Layout

| Path | Contents |
|---|---|
| `PLAN.md` | Goals and phases |
| `DESIGN.md` | Driver architecture (filled in as it is decided) |
| `doc/` | Documentation, start at `doc/README.md` |
| `doc/log/` | Dated decision logs |
| `doc/work/` | Work items with status |
| `tools/` | Helper scripts (for example the USB watcher that runs on the test Raspberry Pi) |
| `pyopticfilm/` | Submodule: our fork of [pyopticfilm](https://github.com/jboneng/pyopticfilm), where the OpticFilm 120 driver support is built (see `DESIGN.md`) |
| `TODO.md` | Owner's inbox of new requests |
| `SUGGESTIONS.md` | Ideas that came up during the work |

`work/` and `tmp/` are untracked: downloaded vendor packages, captures, and anything that carries serial numbers or personal data live there.

## Test setup

The scanner is attached to a Raspberry Pi 3 (Debian 13, aarch64) on the local network.

## License

GNU Affero General Public License v3.0 or later (`AGPL-3.0-or-later`), see `LICENSE`.
