# Register fields of Plustek's CGL128 and CGL126 classes

Register field map taken from the accessor methods of Plustek's macOS engine (`PLK_A120.framework/Versions/A/ScanApi`, version 1.4.27.4.0, x86_64 slice). Each field is a pair of methods named after the field: a getter `NAME(bool, int)` and a setter `NAME(int, bool, int)`. The tables are generated, not typed by hand (see "How the table was made").

## Which class the OpticFilm 120 uses

The engine picks the class from bcdDevice (`../vendor-driver/macos.md`, "Which chip class"): `CGL128` for ≥ `0x0704`, `CGL125` for `0x0703`, `CGL126` for `0x0702`, `CGL846` for `0x0600` to `0x0701`. **The OpticFilm 120 reports bcdDevice `0x0702` and so uses `CGL126`.** SANE names the chip with bcdDevice `0x0702` GL128 (`../research.md`), so "GL128" in SANE and pyopticfilm and `CGL126` in Plustek's engine are the same silicon *(inference from the bcdDevice values; Plustek's names may follow its own history)*.

The two classes differ in only 22 fields (second table). For the OpticFilm 120, use the `CGL128` table with the `CGL126` column of the difference table applied.

## How to read the tables

- Register numbers are ASIC register addresses as used by `CIOUSB::ReadRegs` and `CIOUSB::WriteRegs` (`usb-requests.md`). `0x100` and up are read with wValue `0x018e` and written with `0x0183`.
- "mask, bits" fields live in one register. The setter changes only those bits of the host's shadow copy and, when asked to, writes the whole register. The getter optionally re-reads the register from the device first, then shifts and masks.
- "N bytes, big-endian" fields span N consecutive registers, most significant byte first (`CRegister::SetRegs` and `GetRegs` with a byte count). No extra mask is applied.
- A mask of `0xff` on a single register means the accessor reads or writes the whole register (for example `SCANRESET` at `0x0e` and `MOVE` at `0x0f`).
- "not implemented": both accessors (or the only one) just return a constant without touching any register. Getters return 0, setters return 1 (success).
- Getter and setter columns give the method addresses in the x86_64 slice. An empty column means the class has no such method.
- Field names are Plustek's. Where SANE's GL124 header (`backend/genesys/gl124_registers.h`) defines the same name, the position agrees in the cases checked: `MTRPWR` at `0x02` mask `0x10`, `LAMPPWR` at `0x03` mask `0x10`, `DPIHW` at `0x05` mask `0xc0`, `CLKSET` at `0x0b` mask `0xe0`, and `DATAENB`, `MOTMFLG`, `DOCJAM`, `COVERSNR`, `ADFSNR` at `0x100`. SANE's GL124 header defines nothing for `0x101`. Meanings beyond the names are not established here.

Fields relevant to observations elsewhere:

- `GPIO8` is `0x31` bit 7, the bit named by plist key `StandbyReg = 0x31,0x80` (`../vendor-driver/macos.md`, "Standby"). The capture read `0x31 = 0xbb`, bit 7 set (`of120-capture-151.md`, frames 139 to 160).
- `GPIO18` is `0x33` bit 1, the bit named by plist key `LoaderEjectSwitch = 0x33,0x02,1`. Plist key `LoaderEjectSwitchIO = 0x36,1` names register `0x36`, where `GPOE18` is bit 1 *(inference that the `1` is the bit number)*. The capture sets `0x36` bit 1 (`0xfc` to `0xfe`) and clears `0x33` bit 1 (`0x0e` to `0x0c`, `0x1e` to `0x1c`) at frames 139 to 160 and 247 to 264.
- `MOTORENB` (`0x101` bit 0) is the bit `CAsic::WaitMotorStop` (`0x056d80`) polls until it clears. The capture's 3392 reads of `0x101` fit that pattern *(inference: the capture does not show which function issued them)*.
- `VALIDWORD` (`0x102` to `0x105`, 4 bytes) is read before buffer reads in the capture (`00 00 00 ea` at frames 385 to 538).
- `EPROMSEL` (`0x0a` bit 3) exists in `CGL126` only. It is set by `CAsic::ReadFromNVRAM`, which has no caller (`serial-flash.md`).
- `SPI_MOT` (`0x9f` bit 5) exists in `CGL126` only; its purpose is not known.
- `CGL126::ShadingAddr` (`0x0ea770`) returns `0x10014000`, the shading table address of the capture. `CGL126::ImageAddr` (`0x080db0`) and `CGL126::UserAddr` (`0x080b30`) compute memory addresses from `DPIHW` and `DRAMSEL`.

## CGL128 fields

| Field | Register | Layout | Getter | Setter | Note |
|---|---|---|---|---|---|
| `CISSET` | `0x01` | mask `0x80`, bits 7 | `0x0157a0` | `0x04fad0` |  |
| `DVDSET` | `0x01` | mask `0x20`, bits 5 | `0x04e840` | `0x00fe50` |  |
| `SCAN` | `0x01` | mask `0x01`, bits 0 | `0x04e640` | `0x0154e0` |  |
| `SHDAREA` | `0x01` | mask `0x02`, bits 1 | `0x0ea530` |  |  |
| `STAGGER` | `0x01` | mask `0x10`, bits 4 |  | `0x014170` |  |
| `ACDCDIS` | `0x02` | mask `0x40`, bits 6 | `0x06db60` | `0x010430` |  |
| `AGOHOME` | `0x02` | mask `0x20`, bits 5 | `0x04fdc0` | `0x010720` |  |
| `FASTFED` | `0x02` | mask `0x08`, bits 3 |  | `0x010ff0` |  |
| `MTRPWR` | `0x02` | mask `0x10`, bits 4 | `0x0e8f50` | `0x010d00` |  |
| `MTRREV` | `0x02` | mask `0x04`, bits 2 | `0x051a10` | `0x06e800` |  |
| `NOTHOME` | `0x02` | mask `0x80`, bits 7 |  | `0x010a10` |  |
| `AVEENB` | `0x03` | mask `0x40`, bits 6 |  | `0x0eaf10` |  |
| `LAMPDOG` | `0x03` | mask `0x80`, bits 7 |  | `0x013e80` |  |
| `LAMPPWR` | `0x03` | mask `0x10`, bits 4 | `0x04ef30` | `0x00f7f0` |  |
| `LAMPTIM` | `0x03` | mask `0x0f`, bits 3-0 |  | `0x0159a0` |  |
| `XPASEL` | `0x03` | mask `0x20`, bits 5 | `0x04cb50` | `0x04d3c0` |  |
| `BITSET` | `0x04` | mask `0x40`, bits 6 | `0x0513c0` | `0x013b90` |  |
| `FILTER` | `0x04` | mask `0x30`, bits 5-4 | `0x00e8e0` | `0x00dfd0` |  |
| `LINEART` | `0x04` | mask `0x80`, bits 7 | `0x051050` | `0x0e9e10` |  |
| `DPIHW` | `0x05` | mask `0xc0`, bits 7-6 | `0x00f0e0` |  |  |
| `GMMENB` | `0x05` | mask `0x08`, bits 3 | `0x0e85b0` | `0x010140` |  |
| `MTLLAMP` | `0x05` | mask `0x30`, bits 5-4 |  | `0x015c90` |  |
| `GAIN4` | `0x06` | mask `0x08`, bits 3 | `0x0e95c0` |  |  |
| `OPTEST` | `0x06` | mask `0x07`, bits 2-0 | `0x0e99f0` | `0x016e60` |  |
| `PWRBIT` | `0x06` | mask `0x10`, bits 4 | `0x04f8d0` |  |  |
| `SCANMOD` | `0x06` | mask `0xe0`, bits 7-5 | `0x06cdf0` |  |  |
| `CIS_LINE` | `0x08` | mask `0x10`, bits 4 |  | `0x0151f0` |  |
| `DRAM2X` | `0x08` | mask `0x80`, bits 7 | `0x06c9f0` |  |  |
| `BACKSCAN` | `0x09` | mask `0x08`, bits 3 |  | `0x04d0d0` |  |
| `MCNTSET` | `0x09` | mask `0xc0`, bits 7-6 | `0x0715f0` |  |  |
| `ADFSEL` | `0x0a` | mask `0x20`, bits 5 | `0x04ed30` | `0x04ea40` |  |
| `CLKSET` | `0x0b` | mask `0xe0`, bits 7-5 |  | `0x072270` |  |
| `DRAMSEL` | `0x0b` | mask `0x07`, bits 2-0 | `0x06cbf0` |  |  |
| `ENBDRAM` | `0x0b` | mask `0x08`, bits 3 | `0x04f3b0` | `0x04c570` |  |
| `CCDLMT` | `0x0c` | mask `0x0f`, bits 3-0 | `0x00f5f0` | `0x0e78e0` |  |
| `CLRDOCJM` | `0x0d` | mask `0x02`, bits 1 |  | `0x0e7ec0` |  |
| `CLRLNCNT` | `0x0d` | mask `0x01`, bits 0 |  | `0x0162c0` |  |
| `CLRMCNT` | `0x0d` | mask `0x04`, bits 2 |  | `0x0165b0` |  |
| `SCANRESET` | `0x0e` | mask `0xff`, bits 7-0 | `0x051db0` | `0x04f130` |  |
| `MOVE` | `0x0f` | mask `0xff`, bits 7-0 |  | `0x017980` |  |
| `RFHSET` | `0x13` | mask `0x1f`, bits 4-0 | `0x04f5b0` | `0x04c860` |  |
| `TGMODE` | `0x17` | mask `0xc0`, bits 7-6 | `0x0717f0` | `0x0e7bd0` |  |
| `CNT0_EN` | `0x19` | mask `0x08`, bits 3 |  | `0x0515c0` |  |
| `TBTIME` | `0x1c` | mask `0x07`, bits 2-0 | `0x06dfa0` | `0x00fc00` |  |
| `LINESEL` | `0x1d` | mask `0x1f`, bits 4-0 | `0x051810` | `0x0119d0` |  |
| `CIS_3CH` | `0x1e` | mask `0x04`, bits 2 | `0x00f450` |  |  |
| `TGW` | `0x1f` | 2 bytes, big-endian, `0x1f` to `0x20` | `0x00eae0` |  |  |
| `TGSHLD` | `0x21` | 2 bytes, big-endian, `0x21` to `0x22` | `0x00ed10` |  |  |
| `LINCNT` | `0x25` | 3 bytes, big-endian, `0x25` to `0x27` | `0x0ea7b0` | `0x015f80` |  |
| `MAXWD` | `0x28` | 3 bytes, big-endian, `0x28` to `0x2a` |  | `0x06cff0` |  |
| `BUFSEL` | `0x2b` | mask `0xff`, bits 7-0 |  | `0x06d630` |  |
| `DPISET` | `0x2c` | 2 bytes, big-endian, `0x2c` to `0x2d` | `0x050c40` | `0x013850` |  |
| `GPOM11` | `0x30` | mask `0x20`, bits 5 | `0x070180` |  |  |
| `GPOM12` | `0x30` | mask `0x40`, bits 6 | `0x070390` |  |  |
| `GPIO1` | `0x31` | mask `0x01`, bits 0 |  | `0x073770` |  |
| `GPIO2` | `0x31` | mask `0x02`, bits 1 |  | `0x073d50` |  |
| `GPIO3` | `0x31` | mask `0x04`, bits 2 |  | `0x074330` |  |
| `GPIO4` | `0x31` | mask `0x08`, bits 3 | `0x0ebc80` | `0x074910` |  |
| `GPIO5` | `0x31` | mask `0x10`, bits 4 |  | `0x074ef0` |  |
| `GPIO6` | `0x31` | mask `0x20`, bits 5 |  | `0x014a50` |  |
| `GPIO7` | `0x31` | mask `0x40`, bits 6 | `0x0501d0` | `0x014d40` |  |
| `GPIO8` | `0x31` | mask `0x80`, bits 7 |  | `0x075ab0` |  |
| `GPIO10` | `0x32` | mask `0x02`, bits 1 |  | `0x014760` |  |
| `GPIO11` | `0x32` | mask `0x04`, bits 2 | `0x0705a0` | `0x076960` |  |
| `GPIO12` | `0x32` | mask `0x08`, bits 3 | `0x0707b0` | `0x076f40` |  |
| `GPIO13` | `0x32` | mask `0x10`, bits 4 |  | `0x077520` |  |
| `GPIO14` | `0x32` | mask `0x20`, bits 5 |  | `0x077b00` |  |
| `GPIO15` | `0x32` | mask `0x40`, bits 6 | `0x0ebe90` | `0x0780e0` |  |
| `GPIO16` | `0x32` | mask `0x80`, bits 7 | `0x072b80` | `0x0786c0` |  |
| `GPIO9` | `0x32` | mask `0x01`, bits 0 |  | `0x076090` |  |
| `GPIO17` | `0x33` | mask `0x01`, bits 0 |  | `0x078ca0` |  |
| `GPIO18` | `0x33` | mask `0x02`, bits 1 |  | `0x079280` |  |
| `GPIO19` | `0x33` | mask `0x04`, bits 2 |  | `0x079860` |  |
| `GPIO20` | `0x33` | mask `0x08`, bits 3 |  | `0x079e40` |  |
| `GPIO21` | `0x33` | mask `0x10`, bits 4 |  | `0x07a130` |  |
| `GPOE1` | `0x34` | mask `0x01`, bits 0 |  | `0x073480` |  |
| `GPOE2` | `0x34` | mask `0x02`, bits 1 |  | `0x073a60` |  |
| `GPOE3` | `0x34` | mask `0x04`, bits 2 |  | `0x074040` |  |
| `GPOE4` | `0x34` | mask `0x08`, bits 3 |  | `0x074620` |  |
| `GPOE5` | `0x34` | mask `0x10`, bits 4 |  | `0x074c00` |  |
| `GPOE6` | `0x34` | mask `0x20`, bits 5 |  | `0x0751e0` |  |
| `GPOE7` | `0x34` | mask `0x40`, bits 6 |  | `0x0754d0` |  |
| `GPOE8` | `0x34` | mask `0x80`, bits 7 |  | `0x0757c0` |  |
| `GPOE10` | `0x35` | mask `0x02`, bits 1 |  | `0x076380` |  |
| `GPOE11` | `0x35` | mask `0x04`, bits 2 | `0x0711d0` | `0x076670` |  |
| `GPOE12` | `0x35` | mask `0x08`, bits 3 | `0x0713e0` | `0x076c50` |  |
| `GPOE13` | `0x35` | mask `0x10`, bits 4 |  | `0x077230` |  |
| `GPOE14` | `0x35` | mask `0x20`, bits 5 |  | `0x077810` |  |
| `GPOE15` | `0x35` | mask `0x40`, bits 6 | `0x0ec0a0` | `0x077df0` |  |
| `GPOE16` | `0x35` | mask `0x80`, bits 7 |  | `0x0783d0` |  |
| `GPOE9` | `0x35` | mask `0x01`, bits 0 |  | `0x075da0` |  |
| `GPOE17` | `0x36` | mask `0x01`, bits 0 |  | `0x0789b0` |  |
| `GPOE18` | `0x36` | mask `0x02`, bits 1 |  | `0x078f90` |  |
| `GPOE19` | `0x36` | mask `0x04`, bits 2 |  | `0x079570` |  |
| `GPOE20` | `0x36` | mask `0x08`, bits 3 |  | `0x079b50` |  |
| `GPOE21` | `0x36` | mask `0x10`, bits 4 |  | `0x017150` |  |
| `GPIO27` | `0x37` | mask `0x04`, bits 2 |  | `0x07ae10` |  |
| `GPIO28` | `0x37` | mask `0x08`, bits 3 |  | `0x07b350` |  |
| `GPIO29` | `0x37` | mask `0x10`, bits 4 |  | `0x07b760` |  |
| `GPIO30` | `0x37` | mask `0x20`, bits 5 |  | `0x07bae0` |  |
| `GPIO31` | `0x37` | mask `0x40`, bits 6 |  | `0x07bef0` |  |
| `GPIO32` | `0x37` | mask `0x80`, bits 7 |  | `0x07c390` |  |
| `GPOE27` | `0x38` | mask `0x04`, bits 2 |  | `0x07ab20` |  |
| `GPOE28` | `0x38` | mask `0x08`, bits 3 |  | `0x07b100` |  |
| `GPOE29` | `0x38` | mask `0x10`, bits 4 |  | `0x07b5a0` |  |
| `GPOE30` | `0x38` | mask `0x20`, bits 5 |  | `0x07b920` |  |
| `GPOE31` | `0x38` | mask `0x40`, bits 6 |  | `0x07bca0` |  |
| `GPOE32` | `0x38` | mask `0x80`, bits 7 |  | `0x07c140` |  |
| `GPO33` | `0x39` | mask `0x01`, bits 0 |  | `0x07c5e0` |  |
| `GPO34` | `0x39` | mask `0x02`, bits 1 |  | `0x07c8d0` |  |
| `GPO35` | `0x39` | mask `0x04`, bits 2 |  | `0x07cbc0` |  |
| `GPO36` | `0x39` | mask `0x08`, bits 3 |  | `0x07ceb0` |  |
| `GPO37` | `0x39` | mask `0x10`, bits 4 |  | `0x07d1a0` |  |
| `GPO38` | `0x39` | mask `0x20`, bits 5 |  | `0x07d3f0` |  |
| `GPOLED10` | `0x3a` | mask `0x04`, bits 2 |  | `0x07e670` |  |
| `GPOLED21` | `0x3a` | mask `0x08`, bits 3 |  | `0x07e960` |  |
| `GPOLED8` | `0x3a` | mask `0x01`, bits 0 |  | `0x07e090` |  |
| `GPOLED9` | `0x3a` | mask `0x02`, bits 1 |  | `0x07e380` |  |
| `VRMOVE` | `0x3b` | mask `0x30`, bits 5-4 | `0x0709c0` |  |  |
| `VRSCAN` | `0x3b` | mask `0x03`, bits 1-0 | `0x070bd0` | `0x0ea9f0` |  |
| `FEEDL` | `0x3d` | 3 bytes, big-endian, `0x3d` to `0x3f` | `0x06dd60` | `0x011690` |  |
| `PREFED` | `0x40` | 3 bytes, big-endian, `0x40` to `0x42` |  | `0x04dbc0` |  |
| `PSTFED` | `0x43` | 2 bytes, big-endian, `0x43` to `0x44` | `0x0e9380` | `0x04df40` |  |
| `SCANLEN` | `0x45` | 3 bytes, big-endian, `0x45` to `0x47` | `0x0e8370` | `0x04e2c0` |  |
| `LEDCNT` | `0x5f` | mask `0x0f`, bits 3-0 |  | `0x07dd90` |  |
| `AUTOCONF` | `0x60` | mask `0x01`, bits 0 | `0x0ea330` |  |  |
| `ENOFFSET` | `0x60` | mask `0x08`, bits 3 | `0x0ea100` |  |  |
| `LPERIOD` | `0x7d` | 3 bytes, big-endian, `0x7d` to `0x7f` | `0x00dd90` | `0x06eaf0` |  |
| `DUMMY` | `0x80` | 2 bytes, big-endian, `0x80` to `0x81` | `0x013080` | `0x0129d0` |  |
| `STRPIXEL` | `0x82` | 3 bytes, big-endian, `0x82` to `0x84` | `0x013610` | `0x012d10` |  |
| `ENDPIXEL` | `0x85` | 3 bytes, big-endian, `0x85` to `0x87` | `0x050a00` | `0x0132a0` |  |
| `EXPDMY` | `0x88` | 2 bytes, big-endian, `0x88` to `0x89` | `0x072560` |  |  |
| `EXPR` | `0x8a` | 3 bytes, big-endian, `0x8a` to `0x8c` | `0x06e140` | `0x06f2d0` |  |
| `EXPG` | `0x8d` | 3 bytes, big-endian, `0x8d` to `0x8f` | `0x06e380` | `0x06f640` |  |
| `EXPB` | `0x90` | 3 bytes, big-endian, `0x90` to `0x92` | `0x06e5c0` | `0x06f9b0` |  |
| `MTRPWM` | `0x9b` | mask `0x3f`, bits 5-0 | `0x070fd0` |  |  |
| `FASTPWM` | `0x9c` | mask `0x3f`, bits 5-0 | `0x070dd0` |  |  |
| `FULLPAGE` | `0x9f` | mask `0x01`, bits 0 | `0x04ffc0` | `0x0e8a10` |  |
| `FSTPSEL` | `0xa0` | mask `0x38`, bits 5-3 | `0x06ff50` | `0x072fc0` |  |
| `STEPSEL` | `0xa0` | mask `0x07`, bits 2-0 | `0x04d9b0` | `0x04d6b0` |  |
| `SCANFED` | `0xa2` | 2 bytes, big-endian, `0xa2` to `0xa3` |  | `0x0112e0` |  |
| `STEPNO` | `0xa4` | 2 bytes, big-endian, `0xa4` to `0xa5` | `0x071e20` | `0x011cc0` |  |
| `FWDSTEP` | `0xa6` | 2 bytes, big-endian, `0xa6` to `0xa7` | `0x06d330` | `0x012350` |  |
| `BWDSTEP` | `0xa8` | 2 bytes, big-endian, `0xa8` to `0xa9` | `0x0e9bf0` | `0x012690` |  |
| `FASTNO` | `0xaa` | 2 bytes, big-endian, `0xaa` to `0xab` |  | `0x071ae0` |  |
| `FSHDEC` | `0xac` | 2 bytes, big-endian, `0xac` to `0xad` | `0x0eace0` | `0x012000` |  |
| `FMOVNO` | `0xae` | 2 bytes, big-endian, `0xae` to `0xaf` |  | `0x06ee60` |  |
| `SW2_EN` | `0xb8` | mask `0x08`, bits 3 |  | `0x014460` |  |
| `BGMM_N` | `0xbd` | mask `0x04`, bits 2 |  | `0x087590` |  |
| `GGMM_N` | `0xbd` | mask `0x02`, bits 1 |  | `0x087290` |  |
| `RGMM_N` | `0xbd` | mask `0x01`, bits 0 |  | `0x086f90` |  |
| `BGMM_F` | `0xbe` | mask `0x04`, bits 2 |  | `0x087e90` |  |
| `GGMM_F` | `0xbe` | mask `0x02`, bits 1 |  | `0x087b90` |  |
| `RGMM_F` | `0xbe` | mask `0x01`, bits 0 |  | `0x087890` |  |
| `RGMM_Z` | `0xc5` | 2 bytes, big-endian, `0xc5` to `0xc6` |  | `0x086510` |  |
| `GGMM_Z` | `0xc7` | 2 bytes, big-endian, `0xc7` to `0xc8` |  | `0x086890` |  |
| `BGMM_Z` | `0xc9` | 2 bytes, big-endian, `0xc9` to `0xca` |  | `0x086c10` |  |
| `AUTO_O` | `0xfe` | mask `0x0f`, bits 3-0 |  | `0x0168a0` |  |
| `AUTO_S` | `0xff` | mask `0xff`, bits 7-0 |  | `0x016ba0` |  |
| `ADFSNR` | `0x100` | mask `0x40`, bits 6 | `0x051f70` |  |  |
| `COVERSNR` | `0x100` | mask `0x20`, bits 5 | `0x0e9150` |  |  |
| `DATAENB` | `0x100` | mask `0x01`, bits 0 | `0x072980` |  |  |
| `DOCJAM` | `0x100` | mask `0x08`, bits 3 | `0x072d90` |  |  |
| `MOTMFLG` | `0x100` | mask `0x02`, bits 1 | `0x04cea0` |  |  |
| `BUFEMPTY` | `0x101` | mask `0x40`, bits 6 | `0x017c00` |  |  |
| `HOMESNR` | `0x101` | mask `0x08`, bits 3 | `0x06fd20` |  |  |
| `LAMPSTS` | `0x101` | mask `0x04`, bits 2 | `0x072040` |  |  |
| `MOTORENB` | `0x101` | mask `0x01`, bits 0 | `0x072780` |  |  |
| `SCANFSH` | `0x101` | mask `0x10`, bits 4 | `0x0e97c0` |  |  |
| `VALIDWORD` | `0x102` | 4 bytes, big-endian, `0x102` to `0x105` | `0x017e30` |  |  |
| `SCANCNT` | `0x10b` | 3 bytes, big-endian, `0x10b` to `0x10d` | `0x0503e0` |  |  |
| `BWHI` | `0x114` | mask `0xff`, bits 7-0 | `0x0eb200` | `0x0eb5e0` |  |
| `BWLOW` | `0x115` | mask `0xff`, bits 7-0 | `0x0eb3f0` | `0x0eb890` |  |
| `AUTOADF` |  | not implemented | `0x0e81b0` | `0x0e87b0` | returns 0, returns 1 |
| `DRAM3X` |  | not implemented | `0x06c910` |  | returns 0 |
| `EPROMSEL` |  | not implemented |  | `0x0732c0` | returns 1 |
| `GPIO22` |  | not implemented | `0x00e2c0` | `0x00e560` | returns 0, returns 1 |
| `GPIO23` |  | not implemented | `0x00e410` | `0x00e720` | returns 0, returns 1 |
| `GPIO24` |  | not implemented |  | `0x07a420` | returns 1 |
| `GPIO25` |  | not implemented | `0x0ebb40` | `0x07a7a0` | returns 0, returns 1 |
| `GPIO26` |  | not implemented |  | `0x015030` | returns 1 |
| `GPO28` |  | not implemented |  | `0x07d7f0` | returns 1 |
| `GPO29` |  | not implemented |  | `0x07d910` | returns 1 |
| `GPO30` |  | not implemented |  | `0x07da30` | returns 1 |
| `GPO31` |  | not implemented |  | `0x07db50` | returns 1 |
| `GPO32` |  | not implemented |  | `0x07dc70` | returns 1 |
| `GPO39` |  | not implemented |  | `0x07d640` | returns 1 |
| `GPOADF` |  | not implemented |  | `0x04f7b0` | returns 1 |
| `GPOE22` |  | not implemented |  | `0x017440` | returns 1 |
| `GPOE23` |  | not implemented |  | `0x017600` | returns 1 |
| `GPOE24` |  | not implemented |  | `0x0177c0` | returns 1 |
| `GPOE25` |  | not implemented |  | `0x07a5e0` | returns 1 |
| `GPOE26` |  | not implemented |  | `0x07a960` | returns 1 |
| `GPOLED22` |  | not implemented |  | `0x07ec50` | returns 1 |
| `GPOLED23` |  | not implemented |  | `0x07ee10` | returns 1 |
| `GPOLED24` |  | not implemented |  | `0x07efd0` | returns 1 |
| `GPOLED25` |  | not implemented |  | `0x07f190` | returns 1 |
| `MASTER` |  | not implemented |  | `0x0e8d10` | returns 1 |
| `MULDMYLN` |  | not implemented | `0x0719f0` |  | returns 0 |
| `SC_NUM` |  | not implemented | `0x051c10` |  | returns 0 |
| `SLAVE` |  | not implemented |  | `0x0e8e30` | returns 1 |
| `SPI_MOT` |  | not implemented |  | `0x06d8b0` | returns 1 |
| `STEPTIM` |  | not implemented | `0x06da70` | `0x00fae0` | returns 0, returns 1 |
| `TGTIME` |  | not implemented | `0x06d550` | `0x06f1b0` | returns 0, returns 1 |

## Where CGL126 (the OpticFilm 120's class) differs

| Field | CGL126 | CGL128 |
|---|---|---|
| `AUTOADF` | `0x9f` mask `0x08`, bits 3 | not implemented |
| `DRAM3X` | `0x08` mask `0x02`, bits 1 | not implemented |
| `EPROMSEL` | `0x0a` mask `0x08`, bits 3 | not implemented |
| `GPIO22` | `0x33` mask `0x20`, bits 5 | not implemented |
| `GPIO23` | `0x33` mask `0x40`, bits 6 | not implemented |
| `GPIO24` | `0x33` mask `0x80`, bits 7 | not implemented |
| `GPIO25` | `0x37` mask `0x01`, bits 0 | not implemented |
| `GPIO26` | `0x37` mask `0x02`, bits 1 | not implemented |
| `GPO39` | `0x39` mask `0x40`, bits 6 | not implemented |
| `GPOE22` | `0x36` mask `0x20`, bits 5 | not implemented |
| `GPOE23` | `0x36` mask `0x40`, bits 6 | not implemented |
| `GPOE24` | `0x36` mask `0x80`, bits 7 | not implemented |
| `GPOE25` | `0x38` mask `0x01`, bits 0 | not implemented |
| `GPOE26` | `0x38` mask `0x02`, bits 1 | not implemented |
| `GPOLED22` | `0x3a` mask `0x10`, bits 4 | not implemented |
| `GPOLED23` | `0x3a` mask `0x20`, bits 5 | not implemented |
| `GPOLED24` | `0x3a` mask `0x40`, bits 6 | not implemented |
| `GPOLED25` | `0x3a` mask `0x80`, bits 7 | not implemented |
| `SC_NUM` | `0xbf` mask `0x3f`, bits 5-0 | not implemented |
| `SPI_MOT` | `0x9f` mask `0x20`, bits 5 | not implemented |
| `VRMOVE` | `0x3b` mask `0x0c`, bits 3-2 | `0x3b` mask `0x30`, bits 5-4 |
| `VRSCAN` | `0x3b` mask `0xc0`, bits 7-6 | `0x3b` mask `0x03`, bits 1-0 |

Every other field has the same register, mask or byte count in both classes.

## How the table was made

1. Ghidra 12.1.4 imported and auto-analysed the x86_64 slice (`../../tools/ghidra/README.md`).
2. `tools/ghidra/ExtractAccessorFacts.java` decompiled every method of `CGL128`, `CGL126`, `CGL125` and `CGL846` and recorded, from the decompiler's P-code: the calls with their constant arguments (register numbers and byte counts passed to `CIOUSB::ReadRegs`, `CIOUSB::WriteRegs`, `CRegister::SetLink`, `CRegister::SetRegs`, `CRegister::GetRegs`), the constants used in AND and shift operations, the constant offsets of 16-bit shadow loads and stores (offset = register × 2), and constant return values. Output: `work/re/accessor-facts-x86_64.jsonl`.
3. `tools/ghidra/register_fields.py` turned those facts into the tables: register from the call arguments (falling back to the shadow offset), mask from the setter's inverted AND mask and the getter's shift and mask, byte count from `SetRegs`/`GetRegs`. Where a field has both accessors the script compares them; no field produced a disagreement.
4. Spot checks against the decompiled C: `DPIHW`, `LAMPPWR`, `FEEDL`, `STRPIXEL`, `GPIO22`, `VRSCAN`, `VRMOVE` in both classes.

Commands:

```sh
python3 -I tools/ghidra/register_fields.py work/re/accessor-facts-x86_64.jsonl CGL128
python3 -I tools/ghidra/register_fields.py work/re/accessor-facts-x86_64.jsonl CGL126 --diff CGL128
```

`CGL125` and `CGL846` were extracted too (same facts file) but are not tabulated here.
