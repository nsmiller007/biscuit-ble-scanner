# biscuit-ble-scanner

Drive a **Biscuit** (Seeed **XIAO ESP32-C5** running Biscuit firmware) over
**Bluetooth LE from your computer** — no phone app required — to run dual-band
Wi-Fi access-point scans and Bluetooth device scans, and save the results.

The Biscuit's official companion app (Biscuit Manager) talks to the device over
a simple, documented BLE GATT protocol. This project talks to that same protocol
directly from Python using [`bleak`](https://github.com/hbldh/bleak), so it runs
headless on a Linux box, a Raspberry Pi, a laptop, or anything with a Bluetooth
adapter. Handy for a small always-on RF/Wi-Fi monitoring node.

## Features

- Wi-Fi access-point scan (`scanap`) with SSID, BSSID, channel, RSSI, security
- Bluetooth scan (`sniffbt`) with name, MAC, RSSI, and type (BLE/Classic)
- Dual-band aware — labels 5 GHz vs 2.4 GHz access points
- Cross-platform via `bleak` (Linux / macOS / Windows)
- Optional report file output
- No companion app, no cloud, no account

## Hardware

- A Biscuit device: Pro, Ultra, Crumb, Nyan, or a **DIY XIAO ESP32-C5** build.
- A computer with a working Bluetooth LE adapter.
  On Linux, confirm with `hciconfig` (look for an `UP RUNNING` adapter).

> The XIAO ESP32-C5 is a thumbnail-sized dual-band (2.4/5 GHz) board. If yours
> has an external antenna with a protective sticker on it, peel the sticker off
> before serious scanning — it hurts range.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
# Run both scans (default), discover the device automatically:
python3 biscuit_scan.py

# Only Wi-Fi, 20 seconds, and save a report:
python3 biscuit_scan.py --mode wifi --duration 20 --out scan.txt

# Only Bluetooth:
python3 biscuit_scan.py --mode bt

# Skip discovery by giving the BLE address (faster, more reliable):
python3 biscuit_scan.py --address AA:BB:CC:DD:EE:FF
```

### Options

| Flag | Default | Meaning |
| --- | --- | --- |
| `--mode {wifi,bt,both}` | `both` | Which scan(s) to run |
| `--duration N` | `14` | Seconds to collect per scan |
| `--address ADDR` | (discover) | BLE address/UUID of the Biscuit |
| `--discover-timeout N` | `8` | Seconds to scan for the device |
| `--out FILE` | (none) | Also write the report to a file |

### Example output

```
## Wi-Fi access points (3)
SSID, BSSID, Channel, RSSI, Security, Band
ExampleNet, AA:BB:CC:00:11:22, 149, -43, [WPA2_WPA3_PSK], 5GHz
ExampleNet, AA:BB:CC:00:11:23, 6, -41, [WPA2_PSK], 2.4GHz
(hidden), AA:BB:CC:00:11:24, 11, -72, [WPA2_PSK], 2.4GHz
...

## Bluetooth devices (2 unique)
Name, MAC, RSSI, Type
ExampleTag, 11:22:33:44:55:66, -58, BLE
(no name), 77:88:99:AA:BB:CC, -74, BLE
...
```

## How it works (BLE protocol)

Biscuit exposes a stable, line-delimited text protocol over GATT. The minimum
flow this tool uses:

1. Scan for a peripheral advertising service UUID
   `4fafc201-1fb5-459e-8fcc-c5c9c331914b` (the advertised local name is literally
   `Biscuit` on every device, so match on the UUID).
2. Connect and **subscribe to notifications** on the Response characteristic
   `beb5483e-36e1-4688-b7f5-ea07361b26a9` — until you do, the device sends
   nothing back.
3. Optionally answer the `TIME:REQUEST:` prompt with
   `TIME:SYNC:<ISO-8601 with offset>:`.
4. Write commands to the Command characteristic
   `beb5483e-36e1-4688-b7f5-ea07361b26a8` and read the streamed response lines.

| Characteristic | UUID | Direction |
| --- | --- | --- |
| Command | `...26a8` | write |
| Response | `...26a9` | notify |
| Status (JSON) | `...26aa` | read |
| Settings (JSON) | `...26ab` | read/write/notify |

Commands follow `CMD:<command>:[param=value,...]`. Common ones:

| Command | Purpose | Data lines |
| --- | --- | --- |
| `CMD:scanap:` | Wi-Fi AP scan | `DATA:AP:SSID,BSSID,Channel,RSSI,Security` |
| `CMD:scanall:` | Wi-Fi AP + stations | `DATA:AP:...` and `DATA:STA:...` |
| `CMD:sniffbt:type=all` | Bluetooth scan | `DATA:BT:Name,MAC,RSSI,Type[,Payload]` |
| `CMD:stopscan:` | Stop current scan | — |

Only one BLE central can be connected at a time, so close the phone app first.

## Legal and ethical use

This is a **passive** observation tool. Scan only networks and devices you own
or are explicitly authorized to assess. You are responsible for complying with
all applicable laws and policies.

## License

MIT — see [LICENSE](LICENSE).

## Credits

Biscuit firmware and the Biscuit Manager app are made by the Biscuit Shop. The
GATT protocol used here is their publicly documented 3rd-party integration
surface. This project is an independent, unofficial client.
