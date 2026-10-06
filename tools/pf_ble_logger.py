#!/usr/bin/env python3
"""
pf_ble_logger.py
----------------
Receive the potential-field robot's BLE data stream and write it to a file.

Companion to firmware/potential_field_ble/. The robot (UNO R4 WiFi) advertises
as "PAW-PField" and notifies CSV log lines on a DATA characteristic. This script
connects, subscribes, echoes lines to the console, and appends them to a
timestamped capture file under ./captures/.

Usage:
    python pf_ble_logger.py                 # scan for "PAW-PField", auto-name file
    python pf_ble_logger.py --name PAW-PField
    python pf_ble_logger.py --out my_trial.csv
    python pf_ble_logger.py --address AA:BB:CC:DD:EE:FF   # skip scan

Requires: pip install bleak

Notes:
  * The robot runs its behavior whether or not this is connected — this only
    CAPTURES. Start it before or during a trial; lines already sent before you
    connect are not retro-captured (the robot resends the run-header on connect,
    so your file is self-describing from the first line).
  * Ctrl-C to stop; the file is flushed continuously so a kill won't lose data.
  * BLE throughput is limited; the sketch streams every few ticks. If lines look
    truncated, lower LOG_EVERY_N_TICKS's rate or shorten the CSV in the sketch.
"""

import argparse
import asyncio
import datetime
import os
import sys

# Must match firmware/potential_field_ble/CogBleLog.cpp
SERVICE_UUID = "19b21000-e8f2-537e-4f6c-d104768a1214"
DATA_UUID    = "19b21002-e8f2-537e-4f6c-d104768a1214"
DEFAULT_NAME = "PAW-PField"


async def scan_for(name: str, timeout: float = 8.0) -> str:
    from bleak import BleakScanner
    target = name.upper()
    print(f"Scanning for '{name}' ...")
    async with BleakScanner() as scanner:
        await asyncio.sleep(timeout)
        for d in scanner.discovered_devices:
            dn = (d.name or "").upper()
            if target in dn or target == (d.address or "").upper():
                print(f"  found {d.name} @ {d.address}")
                return d.address
    raise RuntimeError(f"Device '{name}' not found. Is the robot powered and advertising?")


async def run(address: str, out_path: str):
    from bleak import BleakClient

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    buf = ""          # accumulates partial lines across notifications
    line_count = 0

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        def on_notify(_handle, data: bytearray):
            nonlocal buf, line_count
            buf += data.decode("utf-8", errors="replace")
            # Split into complete lines; keep any trailing partial in buf.
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.rstrip("\r")
                if not line:
                    continue
                print(line)
                f.write(line + "\n")
                f.flush()
                line_count += 1

        print(f"Connecting to {address} ...")
        async with BleakClient(address, timeout=15.0) as client:
            print(f"Connected. Writing to: {out_path}")
            print("Ctrl-C to stop.\n")
            await client.start_notify(DATA_UUID, on_notify)
            try:
                while True:
                    await asyncio.sleep(0.2)
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
            finally:
                try:
                    await client.stop_notify(DATA_UUID)
                except Exception:
                    pass
    print(f"\nStopped. {line_count} lines written to {out_path}")


def main():
    ap = argparse.ArgumentParser(description="Capture the PAW potential-field robot's BLE log.")
    ap.add_argument("--name", default=DEFAULT_NAME, help="BLE device name to scan for")
    ap.add_argument("--address", default=None, help="BLE MAC/address (skips scan)")
    ap.add_argument("--out", default=None, help="output file path (default: captures/pf_<timestamp>.csv)")
    args = ap.parse_args()

    if args.out is None:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        args.out = os.path.join("captures", f"pf_{ts}.csv")

    try:
        address = args.address
        if address is None:
            address = asyncio.run(scan_for(args.name))
        asyncio.run(run(address, args.out))
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
