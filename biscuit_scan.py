#!/usr/bin/env python3
"""
biscuit_scan.py - Drive a Biscuit (XIAO ESP32-C5 / Biscuit firmware) device over
Bluetooth LE from any computer, no phone app required.

Runs a Wi-Fi access-point scan and/or a Bluetooth scan and prints (and optionally
saves) the results. Works on Linux, macOS, and Windows via the cross-platform
`bleak` library.

Protocol reference (stable across the public Biscuit firmware line):
  Advertised service UUID : 4fafc201-1fb5-459e-8fcc-c5c9c331914b
  Advertised local name   : "Biscuit" (match on the service UUID, not the name)
  Command  char (write)   : beb5483e-36e1-4688-b7f5-ea07361b26a8
  Response char (notify)  : beb5483e-36e1-4688-b7f5-ea07361b26a9
  Status   char (read)    : beb5483e-36e1-4688-b7f5-ea07361b26aa  (JSON health)
  Settings char (rw/notify): beb5483e-36e1-4688-b7f5-ea07361b26ab (JSON config)

Commands are line-delimited text:  CMD:<command>:[param=value,...]
Responses stream back as lines:    RSP:  STATUS:  DATA:  ERROR:  TIME:

  Wi-Fi AP scan     : CMD:scanap:          -> DATA:AP:SSID,BSSID,Channel,RSSI,Security
  Wi-Fi AP+station  : CMD:scanall:
  Bluetooth scan    : CMD:sniffbt:type=all -> DATA:BT:Name,MAC,RSSI,Type[,PayloadHex]
  Stop any scan     : CMD:stopscan:

Notes:
  * You MUST subscribe to the Response characteristic (notifications) or the
    device sends nothing back.
  * Shortly after subscribing the device may emit TIME:REQUEST:. Reply with
    TIME:SYNC:<ISO-8601 with offset>: so scan timestamps are correct.
  * Only one BLE central can be connected at a time - close the phone app first.

Legal / ethical: scan only networks and devices you own or are authorized to
assess. This is a passive observation tool.
"""

import argparse
import asyncio
import datetime
import sys

try:
    from bleak import BleakScanner, BleakClient
except ImportError:
    sys.exit("bleak is required:  pip install bleak")

SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
CMD_CHAR = "beb5483e-36e1-4688-b7f5-ea07361b26a8"
RSP_CHAR = "beb5483e-36e1-4688-b7f5-ea07361b26a9"

# 5 GHz channels (used only to label dual-band APs in the summary)
FIVE_GHZ = set(range(32, 178))


def iso_local_now() -> str:
    """Current local time as ISO-8601 with a +HH:MM / -HH:MM offset."""
    s = datetime.datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    return s[:-2] + ":" + s[-2:]


class Biscuit:
    def __init__(self, client: BleakClient):
        self.client = client
        self.lines = []
        self._buf = ""

    def _on_notify(self, _handle, data: bytearray):
        self._buf += bytes(data).decode("utf-8", "replace")
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if line:
                self.lines.append(line)

    async def start(self):
        await self.client.start_notify(RSP_CHAR, self._on_notify)
        await asyncio.sleep(1.5)
        # Answer the time-sync request if (or before) it is asked.
        await self.send(f"TIME:SYNC:{iso_local_now()}:")
        await asyncio.sleep(0.3)

    async def send(self, cmd: str):
        await self.client.write_gatt_char(CMD_CHAR, cmd.encode(), response=False)

    async def run_scan(self, command: str, seconds: int):
        self.lines.clear()
        await self.send(command)
        await asyncio.sleep(seconds)
        await self.send("CMD:stopscan:")
        await asyncio.sleep(1.5)
        return list(self.lines)


async def find_device(timeout: float, address: str | None):
    if address:
        return address
    print(f"Scanning {timeout:.0f}s for a Biscuit (service {SERVICE_UUID})...")
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    for addr, (dev, adv) in found.items():
        uuids = [u.lower() for u in (adv.service_uuids or [])]
        if SERVICE_UUID in uuids:
            print(f"Found Biscuit: {addr}  rssi={adv.rssi}  name={dev.name!r}")
            return addr
    return None


def parse_aps(lines):
    aps = []
    for ln in lines:
        if ln.startswith("DATA:AP:"):
            parts = ln[len("DATA:AP:"):].rsplit(",", 4)
            if len(parts) == 5:
                ssid, bssid, chan, rssi, sec = parts
                aps.append(dict(ssid=ssid, bssid=bssid, channel=chan,
                                rssi=rssi, security=sec))
    return aps


def parse_bts(lines):
    seen = {}
    for ln in lines:
        if ln.startswith("DATA:BT:"):
            body = ln[len("DATA:BT:"):]
            parts = body.split(",")
            if len(parts) >= 4:
                name, mac, rssi, typ = parts[0], parts[1], parts[2], parts[3]
                # keep strongest sighting per MAC
                prev = seen.get(mac)
                try:
                    r = int(rssi)
                except ValueError:
                    r = -999
                if prev is None or r > prev["_rssi"]:
                    seen[mac] = dict(name=name, mac=mac, rssi=rssi,
                                     type=typ, _rssi=r)
    return list(seen.values())


def fmt_report(aps, bts):
    out = []
    out.append(f"# Biscuit scan - {iso_local_now()}")
    out.append("")
    out.append(f"## Wi-Fi access points ({len(aps)})")
    out.append("SSID, BSSID, Channel, RSSI, Security, Band")
    for a in sorted(aps, key=lambda x: x["ssid"].lower()):
        try:
            band = "5GHz" if int(a["channel"]) in FIVE_GHZ else "2.4GHz"
        except ValueError:
            band = "?"
        ssid = a["ssid"] or "(hidden)"
        out.append(f"{ssid}, {a['bssid']}, {a['channel']}, "
                   f"{a['rssi']}, {a['security']}, {band}")
    out.append("")
    out.append(f"## Bluetooth devices ({len(bts)} unique)")
    out.append("Name, MAC, RSSI, Type")
    for b in sorted(bts, key=lambda x: x["_rssi"], reverse=True):
        name = b["name"] or "(no name)"
        out.append(f"{name}, {b['mac']}, {b['rssi']}, {b['type']}")
    return "\n".join(out)


async def main_async(args):
    addr = await find_device(args.discover_timeout, args.address)
    if not addr:
        sys.exit("No Biscuit found. Make sure it is powered on and in range, "
                 "and that no phone app is connected.")

    async with BleakClient(addr, timeout=25) as client:
        print(f"Connected: {client.is_connected}")
        dev = Biscuit(client)
        await dev.start()

        aps, bts = [], []
        if args.mode in ("wifi", "both"):
            print(f"Wi-Fi AP scan for {args.duration}s...")
            aps = parse_aps(await dev.run_scan("CMD:scanap:", args.duration))
            print(f"  {len(aps)} access points")
        if args.mode in ("bt", "both"):
            print(f"Bluetooth scan for {args.duration}s...")
            bts = parse_bts(await dev.run_scan("CMD:sniffbt:type=all", args.duration))
            print(f"  {len(bts)} unique devices")

        report = fmt_report(aps, bts)
        print("\n" + report)
        if args.out:
            with open(args.out, "w") as f:
                f.write(report + "\n")
            print(f"\nSaved to {args.out}")

        try:
            await client.stop_notify(RSP_CHAR)
        except Exception:
            pass


def main():
    p = argparse.ArgumentParser(description="Drive a Biscuit device over BLE to "
                                            "run Wi-Fi and Bluetooth scans.")
    p.add_argument("--mode", choices=["wifi", "bt", "both"], default="both",
                   help="Which scan(s) to run (default: both)")
    p.add_argument("--duration", type=int, default=14,
                   help="Seconds to collect per scan (default: 14)")
    p.add_argument("--address", default=None,
                   help="BLE address/UUID of the Biscuit (skip discovery)")
    p.add_argument("--discover-timeout", type=float, default=8.0,
                   help="Seconds to scan for the device (default: 8)")
    p.add_argument("--out", default=None,
                   help="Write the report to this file as well as stdout")
    args = p.parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
