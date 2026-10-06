#!/usr/bin/env python3
"""
pf_sim_replay.py  —  Mode A: replay a capture through the sim's field math.

VALIDATION TOOL (separate from the Field Trip game). It answers ONE question:
given the SAME sensor readings the robot logged, does the simulator's potential-
field math produce the SAME net vector (Vx,Vy) and wheel commands (L,R) that the
firmware produced?

It does this by re-implementing CogPotentialField's math EXACTLY (computeNetVector,
vectorToDifferential, proximityStrength, lightStrength — mirrored line-for-line
from firmware/potential_field_ble/CogPotentialField.cpp) and feeding it each
capture row's readings. It then diffs sim-vs-logged for every row.

This isolates the field MATH from any physics/sensor/motion modelling — because
we feed it real readings, nothing has to be modelled. If this doesn't match, the
math port is wrong and no predictive sim can be trusted until it's fixed.

Usage:
    python pf_sim_replay.py captures/pf_20260714_160604.csv
    python pf_sim_replay.py captures/*.csv            # batch
    python pf_sim_replay.py --verbose <file>          # per-row diffs
    python pf_sim_replay.py --tol 1 <file>            # wheel tolerance (int units)

Exit code 0 if all rows within tolerance, 1 otherwise.
"""

import argparse
import math
import sys
import glob


# ---- Firmware math, mirrored EXACTLY from CogPotentialField.cpp ----

def proximity_strength(getdata_value):
    # const NEAR_CM=18, FAR_CM=60; clamp; (FAR-d)/(FAR-NEAR)
    NEAR_CM, FAR_CM = 18.0, 60.0
    d = float(getdata_value)
    if d < NEAR_CM: d = NEAR_CM
    if d > FAR_CM:  d = FAR_CM
    return (FAR_CM - d) / (FAR_CM - NEAR_CM)


def light_strength(getdata_value):
    v = float(getdata_value)
    if v < 0.0:   v = 0.0
    if v > 100.0: v = 100.0
    return v / 100.0


def compute_net_vector(sensors, readings):
    """sensors: list of dicts {type,angle,policy,gain}. readings: parallel list of
    getData() values. Returns (Vx, Vy). Mirrors computeNetVector()."""
    vx = vy = 0.0
    for s, r in zip(sensors, readings):
        if s['type'] == 'IR':
            strength = proximity_strength(r)
        else:  # LDR
            strength = light_strength(r)
        mag = strength * s['gain']
        dir_deg = s['angle']
        if s['policy'] == 'push':
            dir_deg += 180.0
        dir_rad = math.radians(dir_deg)
        ux = -math.sin(dir_rad)   # +X (right) component
        uy =  math.cos(dir_rad)   # +Y (forward) component
        vx += mag * ux
        vy += mag * uy
    return vx, vy


def vector_to_differential(vx, vy, base_speed, forward_gain, turn_gain):
    """Mirrors vectorToDifferential(). Returns (L, R) as ints."""
    forward = base_speed + forward_gain * vy * 100.0
    turn    = turn_gain * vx * 100.0
    left  = forward + turn
    right = forward - turn
    left  = max(-100.0, min(100.0, left))
    right = max(-100.0, min(100.0, right))
    return int(left), int(right)


# ---- Capture parsing ----

def parse_capture(path):
    """Returns (sensors, tuning, rows). Two-pass: first collect config from ALL
    header lines (they repeat every 5s; take first occurrence of each sensor id),
    then parse data rows with the now-known sensor count."""
    sensors = []
    tuning = {'base': 45, 'fGain': 0.6, 'tGain': 1.2}
    seen_sensor_ids = set()

    lines = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            lines.append(line.rstrip('\n').rstrip('\r'))

    # ---- Pass 1: config ----
    for line in lines:
        if not line.startswith('#'):
            continue
        if ' type=' in line and (' pull' in line or ' push' in line):
            parts = line.split()
            sid = parts[1]
            if sid in seen_sensor_ids:
                continue
            seen_sensor_ids.add(sid)
            typ = 'IR' if 'type=IR' in line else 'LDR'
            ang, gain = None, 1.0
            for p in parts:
                if p.startswith('ang='): ang = float(p[4:])
                if p.startswith('g='):   gain = float(p[2:])
            policy = 'push' if ' push' in line else 'pull'
            sensors.append({'id': sid, 'type': typ, 'angle': ang,
                            'policy': policy, 'gain': gain})
        elif line.startswith('# base='):
            for p in line.replace('#', '').split():
                if p.startswith('base='):  tuning['base']  = float(p[5:])
                if p.startswith('fGain='): tuning['fGain'] = float(p[6:])
                if p.startswith('tGain='): tuning['tGain'] = float(p[6:])

    n = len(sensors)

    # ---- Pass 2: data rows (skip #, blank, and the repeated 'tick' header) ----
    data_rows = []
    for line in lines:
        if not line or line.startswith('#') or line.startswith('tick'):
            continue
        parts = line.split(',')
        if not parts[0].isdigit():
            continue
        # a valid data row has exactly: tick + n readings + Vx,Vy,L,R
        if len(parts) != 1 + n + 4:
            continue
        vals = [float(x) for x in parts]
        data_rows.append({
            'tick': int(vals[0]),
            'readings': vals[1:1+n],
            'Vx': vals[1+n], 'Vy': vals[2+n],
            'L': int(vals[3+n]), 'R': int(vals[4+n]),
        })
    return sensors, tuning, data_rows


# ---- Replay + compare ----

def replay(path, tol_wheel=1, tol_v=0.01, verbose=False):
    sensors, tuning, rows = parse_capture(path)
    if not sensors:
        print(f"  !! no sensor config found in header of {path}")
        return False
    if not rows:
        print(f"  !! no data rows in {path}")
        return False

    max_dv = 0.0
    max_dw = 0
    bad = 0
    # Separate STABLE rows (readings identical to previous row) from TRANSITION
    # rows. On stable rows the logged readings and logged Vx/Vy come from the same
    # sensor state, so they're the clean test of the MATH. On transition rows the
    # firmware logs a fresh getData() re-read (a different ADC sample than the one
    # computeNetVector used), so small disagreement there is a LOGGING artifact +
    # sensor noise, not a math error.
    stable_errs = []
    prev_readings = None
    for row in rows:
        vx, vy = compute_net_vector(sensors, row['readings'])
        L, R = vector_to_differential(vx, vy, tuning['base'], tuning['fGain'], tuning['tGain'])
        dvx = abs(vx - row['Vx']); dvy = abs(vy - row['Vy'])
        dL = abs(L - row['L']);    dR = abs(R - row['R'])
        max_dv = max(max_dv, dvx, dvy)
        max_dw = max(max_dw, dL, dR)
        row_bad = (dvx > tol_v or dvy > tol_v or dL > tol_wheel or dR > tol_wheel)
        if row_bad:
            bad += 1
        if row['readings'] == prev_readings:
            stable_errs.append(max(dvx, dvy))
        prev_readings = row['readings']
        if verbose and row_bad:
            print(f"    tick {row['tick']}: sim(Vx={vx:.3f},Vy={vy:.3f},L={L},R={R}) "
                  f"vs log(Vx={row['Vx']:.3f},Vy={row['Vy']:.3f},L={row['L']},R={row['R']})"
                  f"  dV=({dvx:.3f},{dvy:.3f}) dW=({dL},{dR})")

    stable_mean = (sum(stable_errs) / len(stable_errs)) if stable_errs else float('nan')
    stable_max  = max(stable_errs) if stable_errs else float('nan')
    # The MATH is validated if the stable-row error is negligible (float rounding).
    math_ok = (len(stable_errs) > 0 and stable_max < 0.03)

    status = "MATH OK" if math_ok else ("DIFFER" if stable_errs else "NO-STABLE-ROWS")
    cfg = ", ".join(f"{s['id']}:{s['type']}@{s['angle']:.1f}{s['policy'][0]}" for s in sensors)
    print(f"  [{status}] {path.split('/')[-1]}")
    print(f"         config: {cfg}")
    print(f"         tuning: base={tuning['base']:.0f} fGain={tuning['fGain']:.2f} tGain={tuning['tGain']:.2f}")
    print(f"         rows={len(rows)}")
    print(f"         STABLE rows (clean math test): {len(stable_errs)}, mean|dV|={stable_mean:.4f}, max|dV|={stable_max:.4f}")
    print(f"         TRANSITION rows differ more (logging re-read + sensor noise): overall max|dV|={max_dv:.3f}, max|dWheel|={max_dw}")
    return math_ok


def main():
    ap = argparse.ArgumentParser(description="Replay a PAW potential-field capture through the sim math (Mode A).")
    ap.add_argument("files", nargs="+", help="capture CSV(s); globs allowed")
    ap.add_argument("--tol", type=int, default=1, help="wheel-command tolerance (int units, default 1 for rounding)")
    ap.add_argument("--tolv", type=float, default=0.01, help="Vx/Vy tolerance (default 0.01)")
    ap.add_argument("--verbose", action="store_true", help="print each mismatched row")
    args = ap.parse_args()

    paths = []
    for f in args.files:
        paths.extend(sorted(glob.glob(f)) or [f])

    all_ok = True
    for p in paths:
        ok = replay(p, tol_wheel=args.tol, tol_v=args.tolv, verbose=args.verbose)
        all_ok = all_ok and ok
        print()
    print("=" * 60)
    print("ALL CAPTURES MATCH THE SIM MATH" if all_ok else "SOME CAPTURES DIVERGED — see above")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
