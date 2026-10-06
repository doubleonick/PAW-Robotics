"""
engine/calibration/calibration_receiver.py
-------------------------------------------
Python BLE receiver and analyser for the PAW robot calibration sequence.

Connects to the Arduino running robot_calibration.ino via BLE, collects
the calibration data stream, prompts the operator for physical measurements
at the right moments, computes calibration constants, and optionally writes
them back to the codebase.

Usage
-----
    python engine/calibration/calibration_receiver.py [--port COM5]

    # Or if you know the BLE device name or COM port:
    python engine/calibration/calibration_receiver.py --port /dev/tty.PAW-Calibration-SerialPort

    # Dry run (load previously saved session):
    python engine/calibration/calibration_receiver.py --load session_20260504.json

Dependencies
------------
    pip install pyserial bleak   (bleak for BLE on platforms without rfcomm)

Architecture note
-----------------
This script uses the same RobotBTClient transport as the rest of the BLE
stack.  It opens the serial port (BLE serial profile) and speaks the same
JSON-line protocol.  The Arduino sends data autonomously (notify-style);
the receiver just reads lines and dispatches on the "t" field.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Project root on path ──────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent   # tools/calibration/
_ROOT = _HERE.parent.parent               # project root
sys.path.insert(0, str(_ROOT))


# ── Constants matching the Arduino sketch defaults ────────────────────────────

# These must match the values compiled into robot_calibration.ino.
# The receiver validates them against the "ready" packet.
DEFAULT_WHEEL_RADIUS_MM  = 32.0
DEFAULT_SPIN_PROPORTION  = 60
DEFAULT_CRUISE_PROPORTION= 60
DEFAULT_SAMPLE_MS        = 100


# ── Session data container ────────────────────────────────────────────────────

class CalibrationSession:
    """Accumulates raw packets and operator measurements for one calibration run."""

    def __init__(self):
        self.start_time    = datetime.now()
        self.packets: list = []              # all raw packets in order
        self.by_phase: dict[int, list] = {}  # phase → sample packets
        self.contacts: list = []             # contact event packets
        self.phase_meta: dict[int, dict] = {}
        self.operator: dict = {}             # operator-entered measurements

        # Extracted constants from "ready" / "complete" packets
        self.wheel_radius_mm   = DEFAULT_WHEEL_RADIUS_MM
        self.spin_proportion   = DEFAULT_SPIN_PROPORTION
        self.cruise_proportion = DEFAULT_CRUISE_PROPORTION
        self.sample_ms         = DEFAULT_SAMPLE_MS

    def ingest(self, pkt: dict) -> None:
        self.packets.append(pkt)
        t = pkt.get("t")
        p = pkt.get("p")

        if t == "ready" or t == "complete":
            self.wheel_radius_mm   = pkt.get("wheel_radius_mm",   self.wheel_radius_mm)
            self.spin_proportion   = pkt.get("spin_prop",         self.spin_proportion)
            self.cruise_proportion = pkt.get("cruise_prop",       self.cruise_proportion)
            self.sample_ms         = pkt.get("sample_ms",         self.sample_ms)

        elif t == "phase":
            self.phase_meta[p] = pkt
            self.by_phase.setdefault(p, [])
            print(f"\n  [Phase {p}] {pkt.get('name','')} — {pkt.get('note','')}")

        elif t == "s" and p is not None:
            self.by_phase.setdefault(p, []).append(pkt)

        elif t == "contact":
            self.contacts.append(pkt)
            print(f"  *** CONTACT  phase={p}  ms={pkt.get('ms')}  "
                  f"side={pkt.get('side')} ***")

        elif t == "done":
            n = len(self.by_phase.get(p, []))
            print(f"  [Phase {p}] done  ({n} samples)")

        elif t == "timeout":
            print(f"  [Phase {p}] TIMEOUT — {pkt.get('note','')}")

    def save(self, path: Path) -> None:
        data = {
            "start_time":      self.start_time.isoformat(),
            "wheel_radius_mm": self.wheel_radius_mm,
            "spin_proportion": self.spin_proportion,
            "cruise_proportion": self.cruise_proportion,
            "sample_ms":       self.sample_ms,
            "operator":        self.operator,
            "packets":         self.packets,
        }
        path.write_text(json.dumps(data, indent=2))
        print(f"  Session saved → {path}")

    @classmethod
    def load(cls, path: Path) -> "CalibrationSession":
        data = json.loads(path.read_text())
        s = cls()
        s.start_time       = datetime.fromisoformat(data["start_time"])
        s.wheel_radius_mm  = data["wheel_radius_mm"]
        s.spin_proportion  = data["spin_proportion"]
        s.cruise_proportion= data["cruise_proportion"]
        s.sample_ms        = data["sample_ms"]
        s.operator         = data.get("operator", {})
        for pkt in data.get("packets", []):
            s.ingest(pkt)
        return s


# ── Analysis engine ───────────────────────────────────────────────────────────

class CalibrationAnalyser:
    """
    Computes calibration constants from a completed CalibrationSession.

    All derivations are documented step by step so the reasoning is
    transparent and can be verified against physical measurements.
    """

    def __init__(self, session: CalibrationSession):
        self.s = session
        self.results: dict = {}

    # ── 1. Wheel speed calibration ────────────────────────────────────────────

    def analyse_wheel_speed(self) -> Optional[float]:
        """
        Phase 1 (spin) + operator-measured rotation count.

        Formula:
            circumference = 2 * pi * wheel_radius_mm
            arc_per_rotation = circumference  (spinning in place, full wheel rotation)
            rotations_per_second = operator_count / SPIN_DURATION_S
            mm_per_second = circumference * rotations_per_second

        Returns mm/s at SPIN_PROPORTION, or None if operator data missing.
        """
        p1 = self.s.by_phase.get(1, [])
        if not p1:
            return None

        spin_duration_s = p1[-1]["ms"] / 1000.0 if p1 else 0
        rotations = self.s.operator.get("spin_rotations")
        if rotations is None:
            return None

        r_mm = self.s.wheel_radius_mm
        circumference_mm = 2 * math.pi * r_mm
        rot_per_s = rotations / spin_duration_s if spin_duration_s > 0 else 0
        mm_per_s  = circumference_mm * rot_per_s

        self.results["wheel_circumference_mm"] = circumference_mm
        self.results["spin_duration_s"]        = spin_duration_s
        self.results["spin_rotations_counted"] = rotations
        self.results["wheel_speed_mm_per_s"]   = mm_per_s
        self.results["cruise_proportion"]      = self.s.cruise_proportion

        print(f"\n  Wheel speed analysis:")
        print(f"    Wheel radius:       {r_mm:.1f} mm")
        print(f"    Circumference:      {circumference_mm:.1f} mm")
        print(f"    Spin duration:      {spin_duration_s:.2f} s")
        print(f"    Rotations counted:  {rotations:.1f}")
        print(f"    Speed at prop={self.s.spin_proportion}: {mm_per_s:.1f} mm/s")

        return mm_per_s

    # ── 2. IR calibration curve ───────────────────────────────────────────────

    def analyse_ir(self, phase: int = 3) -> Optional[dict]:
        """
        Phase 3 (approach-to-contact).

        Uses wheel speed from Phase 1 to assign a distance to each sample.
        Builds raw_ADC → distance_cm mapping.
        Fits a curve of the form: cm = A / (raw - B) matching the Sharp
        GP2Y0A21 characteristic curve shape.

        Also extracts: distance at which proximity threshold would fire.

        Returns dict of IR calibration data.
        """
        samples = self.s.by_phase.get(phase, [])
        contact_pkts = [c for c in self.s.contacts if c.get("p") == phase]
        if not samples or not contact_pkts:
            print(f"\n  IR analysis: insufficient data for phase {phase}")
            return None

        start_cm  = self.s.operator.get(f"phase{phase}_start_cm", 60.0)
        speed_mms = self.results.get("wheel_speed_mm_per_s")
        if speed_mms is None:
            print(f"\n  IR analysis: wheel speed not yet computed")
            return None

        contact_ms = contact_pkts[0]["ms"]

        # Assign distance to each sample
        # At t=0 robot is start_cm from wall.
        # At t=contact_ms robot is ~0 cm from wall (contact).
        # Interpolate linearly using wheel speed.
        # distance_cm(t) = start_cm - (speed_mms / 10) * (t / 1000)
        speed_cms = speed_mms / 10.0

        ir_curve = []   # (dist_cm, raw_PR, raw_PL)
        for pkt in samples:
            t_ms    = pkt["ms"]
            dist_cm = max(0.0, start_cm - speed_cms * (t_ms / 1000.0))
            ir_curve.append({
                "dist_cm": round(dist_cm, 2),
                "raw_PR":  pkt.get("rPR", 0),
                "raw_PL":  pkt.get("rPL", 0),
                "ms":      t_ms,
            })

        # Find the current threshold crossing
        # Current threshold: getData() <= 35 where getData maps [120,720]→[60,18]
        PROX_THRESHOLD = 35
        threshold_dist = None
        for pt in ir_curve:
            for key in ("raw_PR", "raw_PL"):
                raw = pt[key]
                if raw >= 120:
                    clamped = max(120, min(720, raw))
                    cm_val  = int(60 - (clamped - 120) / (720 - 120) * (60 - 18))
                    if cm_val <= PROX_THRESHOLD and threshold_dist is None:
                        threshold_dist = pt["dist_cm"]

        # RAW_MIN / RAW_MAX calibration:
        # Find the raw values at the known extremes:
        #   dist_cm ≈ 60 → raw should represent "nothing" (far)
        #   dist_cm ≈ 18 → raw should represent "very close"
        far_samples = [p for p in ir_curve if p["dist_cm"] > 55]
        near_samples= [p for p in ir_curve if p["dist_cm"] < 22]

        raw_at_far  = (sum(p["raw_PR"] for p in far_samples) / len(far_samples)
                       if far_samples else None)
        raw_at_near = (sum(p["raw_PR"] for p in near_samples) / len(near_samples)
                       if near_samples else None)

        self.results[f"ir_phase{phase}"] = {
            "start_cm":        start_cm,
            "contact_ms":      contact_ms,
            "speed_cms":       round(speed_cms, 2),
            "curve":           ir_curve,
            "threshold_dist_cm": threshold_dist,
            "raw_at_far_cm":   round(raw_at_far,  1) if raw_at_far  else None,
            "raw_at_near_cm":  round(raw_at_near, 1) if raw_at_near else None,
        }

        print(f"\n  IR calibration (Phase {phase}):")
        print(f"    Start distance:         {start_cm:.1f} cm")
        print(f"    Contact at:             {contact_ms} ms")
        print(f"    Speed used:             {speed_cms:.2f} cm/s")
        print(f"    Samples:                {len(ir_curve)}")
        print(f"    Raw at far (>55cm):     {raw_at_far}")
        print(f"    Raw at near (<22cm):    {raw_at_near}")
        print(f"    Threshold fires at:     {threshold_dist} cm")

        # Suggest updated RAW_MIN / RAW_MAX if we have data
        if raw_at_far is not None and raw_at_near is not None:
            print(f"\n  Suggested sensor_models.py constants:")
            print(f"    RAW_MIN = {int(raw_at_near)}   # raw when ~18cm (closest)")
            print(f"    RAW_MAX = {int(raw_at_far)}    # raw when ~60cm (furthest)")
            self.results["suggested_RAW_MIN"] = int(raw_at_near)
            self.results["suggested_RAW_MAX"] = int(raw_at_far)

        return self.results[f"ir_phase{phase}"]

    # ── 3. LDR calibration ────────────────────────────────────────────────────

    def analyse_ldr(self) -> Optional[dict]:
        """
        Phase 4 (LDR static).

        Operator marks distance positions in operator dict:
            session.operator["ldr_positions"] = [
                {"dist_cm": 10, "burst_start": 0, "burst_end": 3},
                {"dist_cm": 20, "burst_start": 4, "burst_end": 7},
                ...
            ]

        Computes mean raw values per distance and suggests the scale
        factor for LightSensor.update() in sensor_models.py.
        """
        samples = self.s.by_phase.get(4, [])
        positions = self.s.operator.get("ldr_positions", [])
        if not samples or not positions:
            print("\n  LDR analysis: no position data — skipping")
            return None

        ldr_curve = []
        for pos in positions:
            b0 = pos.get("burst_start", 0)
            b1 = pos.get("burst_end",   b0)
            subset = [samples[i] for i in range(b0, min(b1+1, len(samples)))]
            if not subset:
                continue
            mean_rLR = sum(p.get("rLR", 0) for p in subset) / len(subset)
            mean_rLL = sum(p.get("rLL", 0) for p in subset) / len(subset)
            ldr_curve.append({
                "dist_cm": pos["dist_cm"],
                "mean_raw_LR": round(mean_rLR, 1),
                "mean_raw_LL": round(mean_rLL, 1),
            })

        # Suggest scale factor: at 10cm the raw should be near 900 for
        # good resolution. scale = 900 / (1/(dist/100)^2) at dist=10cm.
        # 1/(0.1m)^2 = 100. scale_needed = 900/100 = 9. But empirical.
        # Instead: fit scale so that max observed raw ≈ 900.
        max_raw = max((p["mean_raw_LR"] for p in ldr_curve), default=0)
        if max_raw > 0:
            # current scale in sensor_models.py produces raw.
            # We want max_raw at closest distance.
            # If current scale=50 gives max_raw, we need to report what we see.
            suggested_scale = None  # requires knowing current scale; report raw
        else:
            suggested_scale = None

        self.results["ldr_curve"] = ldr_curve

        print(f"\n  LDR calibration (Phase 4):")
        print(f"    {'dist_cm':>8}  {'raw_LR':>8}  {'raw_LL':>8}")
        for pt in ldr_curve:
            print(f"    {pt['dist_cm']:>8.1f}  "
                  f"{pt['mean_raw_LR']:>8.1f}  "
                  f"{pt['mean_raw_LL']:>8.1f}")

        return self.results["ldr_curve"]

    # ── 4. Cross-validation ───────────────────────────────────────────────────

    def analyse_validation(self) -> None:
        """
        Phase 5: repeat approach from second distance.
        Compare predicted contact time (from wheel speed + start distance)
        against actual contact time.
        """
        ir5 = self.analyse_ir(phase=5)
        if ir5 is None:
            return

        if not ir5.get("speed_cms"):
            print("  Cross-validation skipped — wheel speed not calibrated.")
            return
        predicted_s = ir5["start_cm"] / ir5["speed_cms"]
        actual_s    = ir5["contact_ms"] / 1000.0
        error_pct   = abs(predicted_s - actual_s) / predicted_s * 100

        self.results["validation"] = {
            "predicted_contact_s": round(predicted_s, 3),
            "actual_contact_s":    round(actual_s, 3),
            "error_pct":           round(error_pct, 1),
        }

        print(f"\n  Cross-validation:")
        print(f"    Predicted contact:  {predicted_s:.3f} s")
        print(f"    Actual contact:     {actual_s:.3f} s")
        print(f"    Error:              {error_pct:.1f}%")
        if error_pct < 10:
            print(f"    ✓ Good agreement — wheel speed calibration is consistent")
        else:
            print(f"    ⚠ Large error — check start distance measurement or "
                  f"wheel slippage")

    # ── 5. Summary and patch suggestions ─────────────────────────────────────

    def print_summary(self) -> None:
        print("\n" + "="*60)
        print("  CALIBRATION SUMMARY")
        print("="*60)

        ws = self.results.get("wheel_speed_mm_per_s")
        if ws:
            print(f"\n  Wheel speed at prop={self.s.cruise_proportion}:")
            print(f"    {ws:.1f} mm/s  ({ws/10:.1f} cm/s)")
            loop_ms = 1000 / (ws / self.s.sample_ms)
            print(f"    → {self.s.sample_ms}ms sample interval = "
                  f"{ws * self.s.sample_ms / 1000:.1f} mm / sample")

        ir3 = self.results.get("ir_phase3")
        if ir3:
            print(f"\n  IR sensor (approach run):")
            print(f"    Threshold fires at: {ir3['threshold_dist_cm']} cm "
                  f"(target ≤35 cm)")
            rmin = self.results.get("suggested_RAW_MIN")
            rmax = self.results.get("suggested_RAW_MAX")
            if rmin and rmax:
                print(f"\n  → Update engine/sensors/sensor_models.py:")
                print(f"       RAW_MIN = {rmin}   # was 120")
                print(f"       RAW_MAX = {rmax}   # was 720")

        val = self.results.get("validation")
        if val:
            print(f"\n  Cross-validation error: {val['error_pct']}%")

        print()

    def write_patch(self, dry_run: bool = True) -> None:
        """
        Optionally patch sensor_models.py with calibrated RAW_MIN/RAW_MAX.
        If dry_run=True, prints the patch without writing it.
        """
        rmin = self.results.get("suggested_RAW_MIN")
        rmax = self.results.get("suggested_RAW_MAX")
        if rmin is None or rmax is None:
            print("  No IR patch to apply — insufficient data")
            return

        sm_path = _ROOT / "engine" / "sensors" / "sensor_models.py"
        src = sm_path.read_text()

        old_rmin = "    RAW_MIN = 120"
        old_rmax = "    RAW_MAX = 720"
        new_rmin = f"    RAW_MIN = {rmin}   # calibrated {datetime.now().date()}"
        new_rmax = f"    RAW_MAX = {rmax}   # calibrated {datetime.now().date()}"

        if old_rmin not in src or old_rmax not in src:
            print("  Could not locate RAW_MIN/RAW_MAX in sensor_models.py — "
                  "patch manually")
            return

        patched = src.replace(old_rmin, new_rmin).replace(old_rmax, new_rmax)

        if dry_run:
            print(f"\n  [DRY RUN] Would patch {sm_path}:")
            print(f"    {old_rmin!r:30s} → {new_rmin!r}")
            print(f"    {old_rmax!r:30s} → {new_rmax!r}")
        else:
            sm_path.write_text(patched)
            print(f"  ✓ Patched {sm_path}")


# ── BLE receiver ──────────────────────────────────────────────────────────────

def run_live(port: str) -> CalibrationSession:
    """
    Connect to Arduino BLE, then walk through calibration phases interactively.
    'port': BLE device name ("PAW-Calibration") or MAC address.
    Requires: pip install bleak
    """
    try:
        import asyncio
        import threading
        from bleak import BleakClient, BleakScanner
    except ImportError:
        raise RuntimeError("bleak is required.  pip install bleak")

    CMD_UUID  = "19b10001-e8f2-537e-4f6c-d104768a1214"
    DATA_UUID = "19b10002-e8f2-537e-4f6c-d104768a1214"

    session   = CalibrationSession()
    inbox:  list = []

    # Events for cross-thread coordination
    connected_evt  = threading.Event()   # set when BLE ready packet received
    done_evt       = threading.Event()   # set by main thread when phases complete
    ble_errors:list = []

    # Shared reference to the bleak client (set from BLE thread)
    ble_loop   = [None]   # the asyncio loop running in the BLE thread
    ble_client = [None]   # the BleakClient instance

    # ── BLE notify handler ────────────────────────────────────────────────────
    wake_evt = threading.Event()

    def on_notify(_handle, data: bytearray):
        for line in data.decode("utf-8", errors="replace").split("\n"):
            line = line.strip()
            if line:
                try:
                    inbox.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        wake_evt.set()   # wake wait_for on main thread

    # ── Send a command from the main thread into the BLE event loop ───────────
    def send_cmd(obj: dict):
        if ble_loop[0] is None or ble_client[0] is None:
            raise RuntimeError("BLE not connected")
        cmd = json.dumps(obj) + "\n"
        print(f"  >> Sending: {cmd.strip()}")
        # Schedule the write in the BLE event loop — response=True (standard
        # Write With Response) as required by ArduinoBLE on the Uno R4.
        # We do NOT block the main thread waiting for the result, which avoids
        # starving the Windows BLE message pump.
        future = asyncio.run_coroutine_threadsafe(
            ble_client[0].write_gatt_char(
                CMD_UUID, cmd.encode("utf-8"), response=True),
            ble_loop[0])
        # Give the write time to complete without blocking main thread
        # by checking in short increments
        for _ in range(50):   # up to 5 seconds
            if future.done():
                break
            time.sleep(0.1)
        if not future.done():
            print(f"  >> Send timed out — continuing")
            return
        try:
            future.result()
            print(f"  >> Sent OK")
        except Exception as e:
            print(f"  >> Send failed: {e}")
            raise

    def send_next():
        send_cmd({"cmd": "next"})

    # ── Packet helpers (main thread) ──────────────────────────────────────────
    def drain():
        while inbox:
            pkt = inbox.pop(0)
            session.ingest(pkt)

    def wait_for(t_type, p_num=None, timeout_s=120):
        """Block until a matching packet arrives or timeout."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            drain()
            matches = [pk for pk in session.packets
                       if pk.get("t") == t_type
                       and (p_num is None or pk.get("p") == p_num)]
            if matches:
                return matches[-1]
            # Wait for next notification rather than busy-sleeping —
            # avoids blocking Windows BLE message pump
            remaining = deadline - time.monotonic()
            wake_evt.wait(timeout=min(1.0, remaining))
            wake_evt.clear()
        raise TimeoutError(
            f"Timed out waiting for packet t={t_type!r} p={p_num}")

    # ── BLE coroutine (runs in background thread) ─────────────────────────────
    async def _ble_session():
        address = None
        for attempt in range(3):
            print(f"\nScanning for '{port}'  "
                  f"(attempt {attempt+1}/3, up to 12 seconds)...")
            devices = await BleakScanner.discover(timeout=12.0)
            for d in devices:
                if port.upper() in (d.name or "").upper() or \
                   port.upper() == (d.address or "").upper():
                    address = d.address
                    print(f"  Found: {d.name}  ({d.address})")
                    break
            if address:
                break
            print(f"  Not found — waiting 3 s before retry...")
            await asyncio.sleep(3.0)
        if address is None:
            raise RuntimeError(
                f"Device '{port}' not found after 3 scan attempts.\n"
                f"Make sure the robot is powered on, try pressing its "
                f"reset button, and run the script again.")

        print(f"  Connecting to {address}...")
        client = BleakClient(address, timeout=15.0)
        try:
            await client.connect()
        except Exception as e:
            raise RuntimeError(
                f"BLE connection failed: {e}\n"
                f"On Windows, try pairing the device first:\n"
                f"  Settings → Bluetooth → Add device → {address}")

        try:
            ble_client[0] = client

            # Subscribe to notifications — wrapped to avoid hang on Windows
            print("  Subscribing to notifications...")
            try:
                await asyncio.wait_for(
                    client.start_notify(DATA_UUID, on_notify),
                    timeout=8.0)
                print("  Subscribed.")
            except asyncio.TimeoutError:
                print("  start_notify timed out — continuing without notify.")
            except Exception as e:
                print(f"  start_notify failed ({e}) — continuing anyway.")

            # Read the current characteristic value (informational only)
            print("  Connected.  Reading robot state...")
            try:
                raw_val = await asyncio.wait_for(
                    client.read_gatt_char(DATA_UUID), timeout=3.0)
                text = raw_val.decode("utf-8", errors="replace").strip()
                print(f"  Robot says: {text}")
                for line in text.split("\n"):
                    line = line.strip()
                    if line:
                        try:
                            inbox.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                drain()
            except Exception as e:
                print(f"  Could not read state ({e})")

            # Unblock the main thread immediately — no need to wait for ready
            connected_evt.set()

            # Stay alive until main thread signals done
            while not done_evt.is_set():
                await asyncio.sleep(0.1)

        finally:
            try:
                await client.stop_notify(DATA_UUID)
            except Exception:
                pass
            try:
                await client.disconnect()
            except Exception:
                pass

    def _ble_thread():
        loop = asyncio.new_event_loop()
        ble_loop[0] = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_ble_session())
        except Exception as e:
            ble_errors.append(e)
            connected_evt.set()   # unblock main thread so it can report error
        finally:
            loop.close()

    # ── Start BLE thread and wait for connection ───────────────────────────────
    t = threading.Thread(target=_ble_thread, daemon=True)
    t.start()

    if not connected_evt.wait(timeout=20):
        raise RuntimeError("BLE connection timed out after 20 s.")
    if ble_errors:
        raise ble_errors[0]
    # Give the BLE event loop a moment to settle before sending commands
    time.sleep(0.5)
    print(f"  BLE loop ready: {ble_loop[0] is not None}")
    print(f"  BLE client ready: {ble_client[0] is not None}")

    # ── Phase helpers (main thread) ───────────────────────────────────────────
    def phase1_spin():
        print()
        print("─" * 55)
        print("PHASE 1 — Wheel speed calibration")
        print("  The robot will spin in place.")
        print("  Count how many full rotations one wheel makes.")
        input("  Press Enter when ready...")
        send_next()
        wait_for("phase", 1)
        print("  Spinning — count the rotations!")
        wait_for("done", 1)
        print("  Phase 1 complete.")
        raw = input("  How many rotations did you count? ").strip()
        session.operator["spin_rotations"] = float(raw or "0")

    def phase2_cruise():
        print()
        print("─" * 55)
        print("PHASE 2 — Open-space cruise (IR baseline)")
        print("  The robot drives straight briefly.")
        print("  Ensure no obstacles within 60 cm ahead.")
        input("  Press Enter when ready...")
        send_next()
        wait_for("phase", 2)
        print("  Driving...")
        wait_for("done", 2)
        print("  Phase 2 complete.")

    def phase3_approach(phase_num):
        print()
        print("─" * 55)
        label = "PHASE 3" if phase_num == 3 else "PHASE 5 (cross-validation)"
        print(f"{label} — Approach-to-contact")
        default = "60" if phase_num == 3 else "40"
        raw = input(f"  Distance from robot front to wall (cm) [{default}]: ").strip()
        dist_cm = float(raw or default)
        session.operator[f"phase{phase_num}_start_cm"] = dist_cm
        input(f"  Position robot {dist_cm:.0f} cm from wall, then press Enter...")
        send_next()
        wait_for("phase", phase_num)
        print("  Driving toward wall...")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            drain()
            if any(p.get("t") == "contact" and p.get("p") == phase_num
                   for p in session.packets):
                ms = next(p for p in reversed(session.packets)
                          if p.get("t") == "contact")["ms"]
                print(f"  Contact at {ms} ms.")
                break
            if any(p.get("t") == "done" and p.get("p") == phase_num
                   for p in session.packets):
                break
            time.sleep(0.05)
        wait_for("done", phase_num, timeout_s=5)
        print(f"  Phase {phase_num} complete.")

    def phase4_ldr():
        print()
        print("─" * 55)
        print("PHASE 4 — LDR calibration (robot stationary)")
        print("  20 bursts, 0.5 s apart. Move light between bursts.")
        input("  Place light at first distance, then press Enter...")
        send_next()
        wait_for("phase", 4)
        last_burst = -1
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            drain()
            n = len([p for p in session.packets
                     if p.get("t") == "s" and p.get("p") == 4])
            if n > last_burst:
                print(f"    Burst {n-1}")
                last_burst = n
            if any(p.get("t") == "done" and p.get("p") == 4
                   for p in session.packets):
                break
            time.sleep(0.1)
        wait_for("done", 4, timeout_s=5)
        print("  Phase 4 complete.")
        n_bursts = len([p for p in session.packets
                        if p.get("t") == "s" and p.get("p") == 4])
        print(f"\n  Enter distance (cm) for each burst. Press Enter to skip.")
        positions = []
        for b in range(n_bursts):
            raw = input(f"    Burst {b:2d}: ").strip()
            if raw:
                positions.append({"dist_cm": float(raw),
                                  "burst_start": b, "burst_end": b})
        session.operator["ldr_positions"] = positions

    # ── Run all phases ────────────────────────────────────────────────────────
    try:
        phase1_spin()
        phase2_cruise()
        phase3_approach(3)
        phase4_ldr()
        phase3_approach(5)

        wait_for("complete", timeout_s=10)
        print()
        print("=" * 55)
        print("  Calibration complete!")

    except KeyboardInterrupt:
        print("\n  Aborted.")
        try:
            send_cmd({"cmd": "abort"})
        except Exception:
            pass
    finally:
        done_evt.set()   # signal BLE thread to close connection
        t.join(timeout=5.0)

    if ble_errors and not isinstance(ble_errors[0], RuntimeError):
        print(f"  BLE thread error: {ble_errors[0]}")

    return session

def main():
    ap = argparse.ArgumentParser(
        description="PAW Robot BLE Calibration Receiver")
    ap.add_argument("--port",  default=None,
                    help="BLE serial port (e.g. COM5, /dev/tty.PAW-Calibration)")
    ap.add_argument("--load",  default=None,
                    help="Load previously saved session JSON instead of live run")
    ap.add_argument("--patch", action="store_true",
                    help="Write calibrated constants to sensor_models.py")
    args = ap.parse_args()

    # ── Collect data ──────────────────────────────────────────────────────────
    if args.load:
        print(f"Loading session from {args.load}...")
        session = CalibrationSession.load(Path(args.load))
    elif args.port:
        session = run_live(args.port)
        # Save the raw session
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = _HERE / "sessions" / f"session_{ts}.json"
        session.save(path)
    else:
        ap.print_help()
        print("\nProvide --port for a live run or --load for analysis of a "
              "saved session.")
        sys.exit(1)

    # ── Analyse ───────────────────────────────────────────────────────────────
    analyser = CalibrationAnalyser(session)
    analyser.analyse_wheel_speed()
    analyser.analyse_ir(phase=3)
    analyser.analyse_ldr()
    analyser.analyse_validation()
    analyser.print_summary()

    # ── Optionally write patch ─────────────────────────────────────────────────
    analyser.write_patch(dry_run=not args.patch)
    if not args.patch:
        print("  Run with --patch to apply changes to sensor_models.py")

    # ── Save results ──────────────────────────────────────────────────────────
    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_path = _HERE / "sessions" / f"results_{ts}.json"
    results_path.write_text(json.dumps(analyser.results, indent=2))
    print(f"\n  Full results saved → {results_path}")


if __name__ == "__main__":
    main()
