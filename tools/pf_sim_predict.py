#!/usr/bin/env python3
"""
pf_sim_predict.py  —  Mode B: predict a trajectory from a scenario, and draw it.

VALIDATION/PREDICTION TOOL (separate from the Field Trip game). Given a SCENARIO
(robot start pose, light position(s), obstacle geometry, sensor config), it
predicts the robot's trajectory by stepping this loop forward in time:

    idealized sensor models  ->  readings
    readings  ->  [VALIDATED field math from Mode A]  ->  Vx,Vy  ->  L,R wheels
    L,R  ->  differential-drive kinematics  ->  next pose
    repeat

The field math (compute_net_vector / vector_to_differential / proximity_strength /
light_strength) is IMPORTED from pf_sim_replay.py — the SAME code validated
against hardware in Mode A. So only the SENSOR/LIGHT/OBSTACLE models and the
DRIVETRAIN integration are new here, and those are the honest approximations.

PHILOSOPHY (per project decision): start IDEALIZED (clean physics), then use real
captures to add nuance. All model parameters live in the MODELS block below and
are meant to be tuned to fit hardware readings later.

Output: a PNG path plot (arena, light, obstacles, robot trajectory + heading
ticks) AND a trajectory CSV in the SAME column format as hardware captures, so
predictions and real runs can be diffed by the same tools.

Usage:
    python pf_sim_predict.py --scenario single_light
    python pf_sim_predict.py --scenario blindspot_headon --out blindspot.png
    python pf_sim_predict.py --list
"""

import argparse
import math
import os
import sys

# Reuse the VALIDATED field math from Mode A (same directory).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pf_sim_replay import compute_net_vector, vector_to_differential, \
    proximity_strength, light_strength

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle


# ============================================================================
#  MODELS  (idealized; tunable — this is where hardware nuance gets added later)
# ============================================================================

# ---- Geometry / units ----
# World frame: metres, +X world-east, +Y world-north. The robot has its own body
# frame (+Y forward, +X right) at pose (x, y, heading). heading = robot's forward
# direction as a world angle (radians, 0 = +X world, CCW positive).

# ---- Drivetrain model (differential drive) ----
WHEEL_BASE_M    = 0.10     # distance between wheels (tune to real robot)
MAX_WHEEL_MPS   = 0.18     # robot speed at wheel proportion = 100 (tune)
DT_S            = 0.05     # integration step = firmware TICK_MS (50 ms)

# ---- Collision model (simplest approximation: STOP on contact) ----
# The robot is treated as a disc of this radius. If a step would bring its centre
# within ROBOT_RADIUS_M of any obstacle segment, the robot is halted at the last
# safe pose for the rest of the run (no slip modelled — deliberately, since real
# slip was intermittent/messy). This is the "come to a stop" approximation.
ROBOT_RADIUS_M  = 0.06

# ---- IR sensor model (CALIBRATED to hardware, dev8) ----
# Fitted to readings vs matte-black tower: reading = 60 - IR_A*exp(-d_cm/IR_TAU),
# saturating to 60 (nothing) far, dropping toward 18 near. Real usable range is
# short (~<30cm) against matte black. (Was idealized linear [18,60]@0.42m.)
IR_A            = 70.0      # amplitude of the near-field dip
IR_TAU_M        = 0.12      # decay length in metres (12 cm)
IR_HALF_FOV_DEG = 12.0      # sensor cone half-angle for ray hit-testing (tune)

# ---- LDR sensor model (CALIBRATED to hardware, dev8) ----
# The calibration showed the LDR reading is NON-monotonic with distance because
# the torch is ELEVATED: closest (10cm horiz) is nearly overhead (52deg incidence)
# and reads DIMMER than 20cm. So the model computes the TRUE 3D geometry (light at
# height, sensor pointing horizontal) and applies both distance falloff and a
# measured directional response to the incidence angle.
LDR_AMBIENT     = 33.0      # dark floor (from earlier runs)
LDR_PEAK_VAL    = 90.0      # peak reading measured (at ~24cm slant, 33deg incid)
LDR_REF_SLANT_M = 0.24      # slant distance of the peak
LDR_FALLOFF     = 1.2       # distance falloff exponent (fit; >1 = faster than linear)
# Directional response vs off-axis angle (measured): 0deg=100%, 45deg=60%, 90deg=57%.
# Modelled as cos-like: resp = LDR_DIR_FLOOR + (1-LDR_DIR_FLOOR)*max(0,cos(off))^LDR_DIR_POW
LDR_DIR_FLOOR   = 0.20      # floor (never below ~55% even at 90deg, from data)
LDR_DIR_POW     = 4.0
# Fraction of a light that still reaches an LDR when the line of sight is
# BLOCKED by an obstacle (edge-spill / scatter / ambient bounce, not direct beam).
LDR_OCCLUSION_LEAK = 0.15
# Fraction of light re-emitted from an obstacle EDGE/corner when the direct
# ray is blocked (edge diffraction/spill). Larger than the raw scatter leak
# because a real edge channels a real gradient the robot can round.
LDR_EDGE_SPILL = 0.55


# ============================================================================
#  Sensor simulation
# ============================================================================

def _sensor_world_pose(robot, sensor):
    """Return (sx, sy, saim_world) for a sensor given robot pose and its config.
    sensor mount: x_m lateral(+right), y_m forward; angle deg CCW from +Y (fwd)."""
    x, y, h = robot['x'], robot['y'], robot['heading']
    # body -> world: body +Y is 'forward' = world heading h; body +X is 'right' =
    # heading - 90deg.
    fwd = h
    right = h - math.pi / 2
    lat = sensor.get('x_m', 0.0)
    fwd_off = sensor.get('y_m', 0.0)
    sx = x + math.cos(fwd) * fwd_off + math.cos(right) * lat
    sy = y + math.sin(fwd) * fwd_off + math.sin(right) * lat
    # aim: mount angle is CCW from +Y(forward). world aim = heading + angle.
    saim = h + math.radians(sensor['angle'])
    return sx, sy, saim


def _ray_segment_dist(px, py, ang, seg):
    """Distance from (px,py) along direction ang to intersection with segment
    seg=((x1,y1),(x2,y2)); None if no forward hit."""
    dx, dy = math.cos(ang), math.sin(ang)
    (x1, y1), (x2, y2) = seg
    ex, ey = x2 - x1, y2 - y1
    denom = dx * ey - dy * ex
    if abs(denom) < 1e-9:
        return None
    t = ((x1 - px) * ey - (y1 - py) * ex) / denom     # along ray
    u = ((x1 - px) * dy - (y1 - py) * dx) / denom      # along segment
    if t >= 0 and 0 <= u <= 1:
        return t
    return None


def _segments_cross(p1, p2, p3, p4):
    """True if segment p1-p2 intersects segment p3-p4."""
    def ccw(a, b, c):
        return (c[1]-a[1])*(b[0]-a[0]) - (b[1]-a[1])*(c[0]-a[0])
    d1 = ccw(p3, p4, p1); d2 = ccw(p3, p4, p2)
    d3 = ccw(p1, p2, p3); d4 = ccw(p1, p2, p4)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return True
    return False


def _light_occluded(sx, sy, lx, ly, segs):
    """True if the sensor->light line of sight crosses any obstacle segment."""
    for seg in segs:
        if _segments_cross((sx, sy), (lx, ly), seg[0], seg[1]):
            return True
    return False


def _point_segment_dist(px, py, seg):
    """Shortest distance from point (px,py) to segment seg=((x1,y1),(x2,y2))."""
    (x1, y1), (x2, y2) = seg
    ex, ey = x2 - x1, y2 - y1
    L2 = ex * ex + ey * ey
    if L2 < 1e-12:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * ex + (py - y1) * ey) / L2
    t = max(0.0, min(1.0, t))
    cx, cy = x1 + t * ex, y1 + t * ey
    return math.hypot(px - cx, py - cy)


def _would_collide(x, y, segs):
    for seg in segs:
        if _point_segment_dist(x, y, seg) < ROBOT_RADIUS_M:
            return True
    return False


def _obstacle_corners(obstacles):
    """Return the list of corner/endpoint POINTS of all obstacles. These act as
    secondary (diffraction) emitters when the direct light is occluded."""
    pts = []
    for ob in obstacles:
        if ob['type'] == 'rect':
            x0, y0, w, hh = ob['x'], ob['y'], ob['w'], ob['h']
            pts += [(x0, y0), (x0 + w, y0), (x0 + w, y0 + hh), (x0, y0 + hh)]
        elif ob['type'] == 'segment':
            pts += [tuple(ob['a']), tuple(ob['b'])]
    return pts


def _obstacle_segments(obstacles):
    segs = []
    for ob in obstacles:
        if ob['type'] == 'rect':
            x0, y0, w, hh = ob['x'], ob['y'], ob['w'], ob['h']
            c = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + hh), (x0, y0 + hh)]
            for i in range(4):
                segs.append((c[i], c[(i + 1) % 4]))
        elif ob['type'] == 'segment':
            segs.append((tuple(ob['a']), tuple(ob['b'])))
    return segs


def ir_reading(robot, sensor, segs):
    """Idealized IR getData() value from ray-casting the sensor's sight line."""
    sx, sy, saim = _sensor_world_pose(robot, sensor)
    best = None
    # sample a few rays within the cone, take nearest hit
    for da in (-IR_HALF_FOV_DEG, 0.0, IR_HALF_FOV_DEG):
        ang = saim + math.radians(da)
        for seg in segs:
            d = _ray_segment_dist(sx, sy, ang, seg)
            if d is not None and (best is None or d < best):
                best = d
    if best is None or best > (IR_TAU_M * 6):   # far beyond decay -> nothing
        return 60
    d_cm = best * 100.0
    # CALIBRATED curve: reading = 60 - IR_A*exp(-d_cm/(IR_TAU_M*100))
    val = 60.0 - IR_A * math.exp(-d_cm / (IR_TAU_M * 100.0))
    return int(round(max(18.0, min(60.0, val))))


def ldr_reading(robot, sensor, lights, segs=None, corners=None):
    """CALIBRATED LDR getData() [0..100] with EDGE-SPILL occlusion. When the direct
    sensor->light ray is blocked, light does not vanish — it wraps/diffracts around
    the obstacle's EDGES. We model each obstacle corner as a secondary emitter: if
    the direct light is occluded, the LDR instead sees light coming FROM the nearest
    corner that has clear line-of-sight to BOTH the true light and the sensor, at a
    reduced intensity (LDR_EDGE_SPILL). This creates a gradient strongest near the
    edge — the tangential cue that pulls the robot around the corner toward an
    occluded goal, matching real hardware behavior."""
    LDR_Z = 0.13
    sx, sy, saim = _sensor_world_pose(robot, sensor)
    total = LDR_AMBIENT

    def _contrib_from(px, py, pz, intensity_scale):
        """Light contribution as if a source of given intensity sat at (px,py,pz)."""
        dx, dy, dz = px - sx, py - sy, pz - LDR_Z
        slant = math.sqrt(dx*dx + dy*dy + dz*dz)
        if slant < 1e-4:
            slant = 1e-4
        falloff = (LDR_REF_SLANT_M / slant) ** LDR_FALLOFF
        aim3 = (math.cos(saim), math.sin(saim), 0.0)
        vhat = (dx/slant, dy/slant, dz/slant)
        cosang = max(0.0, aim3[0]*vhat[0] + aim3[1]*vhat[1] + aim3[2]*vhat[2])
        directional = LDR_DIR_FLOOR + (1.0 - LDR_DIR_FLOOR) * (cosang ** LDR_DIR_POW)
        return (LDR_PEAK_VAL - LDR_AMBIENT) * falloff * directional * intensity_scale

    for lt in lights:
        lx, ly = lt['x'], lt['y']
        lz = lt.get('z', 0.26)
        inten = lt.get('intensity', 1.0)
        direct_blocked = segs and _light_occluded(sx, sy, lx, ly, segs)
        if not direct_blocked:
            # clear line of sight: full direct contribution
            total += _contrib_from(lx, ly, lz, inten)
        else:
            # EDGE-SPILL: find the best corner that (a) the sensor can see and (b)
            # can see the light. That corner re-emits toward the sensor. Take the
            # strongest such corner (nearest to the sensor with a clear path).
            best = 0.0
            if corners:
                for (cxp, cyp) in corners:
                    # corner must be visible to the sensor (its own ray not blocked)
                    if _light_occluded(sx, sy, cxp, cyp, segs):
                        continue
                    # corner must have line-of-sight to the actual light
                    if _light_occluded(cxp, cyp, lx, ly, segs):
                        continue
                    # re-emit from the corner at reduced intensity (diffraction loss)
                    c = _contrib_from(cxp, cyp, lz, inten * LDR_EDGE_SPILL)
                    if c > best:
                        best = c
            # also allow a tiny uniform scatter floor even with no clear corner
            floor = _contrib_from(lx, ly, lz, inten) * LDR_OCCLUSION_LEAK
            total += max(best, floor)
    return int(round(max(0.0, min(100.0, total))))


# ============================================================================
#  Simulation loop
# ============================================================================

def simulate(scenario, max_steps=600, stop_on_stuck=True):
    sensors = scenario['sensors']
    tuning  = scenario['tuning']
    lights  = scenario.get('lights', [])
    obstacles = scenario.get('obstacles', [])
    segs = _obstacle_segments(obstacles)
    corners = _obstacle_corners(obstacles)

    robot = dict(scenario['start'])   # x, y, heading
    traj = [(robot['x'], robot['y'], robot['heading'])]
    log_rows = []
    stuck_count = 0
    collided = False

    for step in range(max_steps):
        # 1) sensor readings (idealized models)
        readings = []
        for s in sensors:
            if s['type'] == 'IR':
                readings.append(ir_reading(robot, s, segs))
            else:
                readings.append(ldr_reading(robot, s, lights, segs, corners))
        # 2) VALIDATED field math
        vx, vy = compute_net_vector(sensors, readings)
        L, R = vector_to_differential(vx, vy, tuning['base'], tuning['fGain'], tuning['tGain'])
        log_rows.append((step, list(readings), vx, vy, L, R))
        # 3) differential-drive kinematics
        vl = (L / 100.0) * MAX_WHEEL_MPS
        vr = (R / 100.0) * MAX_WHEEL_MPS
        v = (vl + vr) / 2.0
        omega = (vr - vl) / WHEEL_BASE_M        # +omega = CCW (left) ; matches sign of turn
        # NOTE: firmware turn convention verified in Mode A; here +Vx (right) gave
        # L>R -> vr<vl -> omega<0 -> clockwise = turn toward robot's right. Correct.
        robot['heading'] += omega * DT_S
        new_x = robot['x'] + math.cos(robot['heading']) * v * DT_S
        new_y = robot['y'] + math.sin(robot['heading']) * v * DT_S
        # Collision = STOP: if the new centre would contact an obstacle, halt at
        # the last safe pose (heading may still have updated, but no translation).
        if _would_collide(new_x, new_y, segs):
            traj.append((robot['x'], robot['y'], robot['heading']))
            collided = True
            break
        robot['x'], robot['y'] = new_x, new_y
        traj.append((robot['x'], robot['y'], robot['heading']))
        # stuck detection (near-zero motion)
        if abs(v) < 0.003 and abs(omega) < 0.05:
            stuck_count += 1
            if stop_on_stuck and stuck_count > 40:
                break
        else:
            stuck_count = 0
        # arrival at a light (stop if very close)
        for lt in lights:
            if math.hypot(lt['x'] - robot['x'], lt['y'] - robot['y']) < 0.05:
                stuck_count = 999  # flag arrival
        if stuck_count == 999:
            break

    return traj, log_rows, collided


# ============================================================================
#  Visualization
# ============================================================================

def draw(scenario, traj, out_png, collided=False):
    fig, ax = plt.subplots(figsize=(8, 8))
    arena = scenario.get('arena', (-0.2, -0.2, 1.0, 1.0))  # x0,y0,w,h
    ax.set_xlim(arena[0], arena[0] + arena[2])
    ax.set_ylim(arena[1], arena[1] + arena[3])
    ax.set_aspect('equal')
    ax.set_title(scenario.get('name', 'prediction'))
    ax.set_xlabel("world X (m)"); ax.set_ylabel("world Y (m)")
    ax.grid(True, alpha=0.2)

    # obstacles
    for ob in scenario.get('obstacles', []):
        if ob['type'] == 'rect':
            ax.add_patch(Rectangle((ob['x'], ob['y']), ob['w'], ob['h'],
                                    facecolor='#333', edgecolor='k', alpha=0.8))
        elif ob['type'] == 'segment':
            (x1, y1), (x2, y2) = ob['a'], ob['b']
            ax.plot([x1, x2], [y1, y2], 'k-', lw=3)
    # lights
    for lt in scenario.get('lights', []):
        ax.add_patch(Circle((lt['x'], lt['y']), 0.02, color='gold', zorder=5))
        ax.add_patch(Circle((lt['x'], lt['y']), 0.06, color='gold', alpha=0.25, zorder=4))

    # trajectory
    xs = [p[0] for p in traj]; ys = [p[1] for p in traj]
    ax.plot(xs, ys, '-', color='#1f77b4', lw=1.6, zorder=3, label='predicted path')
    # heading ticks every N steps
    for i in range(0, len(traj), 20):
        x, y, h = traj[i]
        ax.plot([x, x + 0.03 * math.cos(h)], [y, y + 0.03 * math.sin(h)],
                '-', color='#1f77b4', lw=0.8, alpha=0.6)
    # start + end markers
    ax.plot(xs[0], ys[0], 'go', ms=9, zorder=6, label='start')
    end_color = 'red' if collided else 'red'
    end_label = 'STOPPED (collision)' if collided else 'end'
    ax.plot(xs[-1], ys[-1], 'rs', ms=9, zorder=6, label=end_label)
    # show robot extent at the final pose
    ax.add_patch(Circle((xs[-1], ys[-1]), ROBOT_RADIUS_M, fill=False,
                        edgecolor='r', ls='--', lw=0.8, alpha=0.6, zorder=5))
    ax.legend(loc='upper right', fontsize=9)
    fig.savefig(out_png, dpi=110, bbox_inches='tight')
    plt.close(fig)


def write_traj_csv(scenario, log_rows, path):
    sensors = scenario['sensors']
    with open(path, 'w') as f:
        f.write(f"# PREDICTED trajectory: {scenario.get('name','')}\n")
        f.write("# convention: +Y=forward, +X=right (body); world path in .png\n")
        f.write("tick," + ",".join(s['id'] for s in sensors) + ",Vx,Vy,L,R\n")
        for (step, readings, vx, vy, L, R) in log_rows:
            f.write(f"{step}," + ",".join(str(r) for r in readings) +
                    f",{vx:.3f},{vy:.3f},{L},{R}\n")


# ============================================================================
#  Scenarios  (idealized; sensor config mirrors your hardware CONFIG rows)
# ============================================================================

def _std_sensors(ir_angle=22.5, ldr_angle=45.0, ir_policy='push', ldr_policy='pull',
                 include_ir=True, include_ldr=True):
    s = []
    if include_ir:
        s += [{'id': 'IR\u00b7L', 'type': 'IR', 'x_m': -0.040, 'y_m': 0.072, 'angle':  ir_angle, 'policy': ir_policy, 'gain': 1.0},
              {'id': 'IR\u00b7R', 'type': 'IR', 'x_m':  0.040, 'y_m': 0.072, 'angle': -ir_angle, 'policy': ir_policy, 'gain': 1.0}]
    if include_ldr:
        s += [{'id': 'LDR\u00b7L', 'type': 'LDR', 'x_m': -0.040, 'y_m': 0.056, 'angle':  ldr_angle, 'policy': ldr_policy, 'gain': 1.0},
              {'id': 'LDR\u00b7R', 'type': 'LDR', 'x_m':  0.040, 'y_m': 0.056, 'angle': -ldr_angle, 'policy': ldr_policy, 'gain': 1.0}]
    return s

TUNING = {'base': 45, 'fGain': 0.6, 'tGain': 1.2}

def scenario_single_light():
    return {
        'name': 'single_light — LDR pull, clean approach',
        'arena': (-0.1, -0.1, 1.0, 1.0),
        'start': {'x': 0.1, 'y': 0.1, 'heading': math.radians(60)},
        'sensors': _std_sensors(include_ir=False, ldr_policy='pull'),
        'lights': [{'x': 0.7, 'y': 0.8, 'intensity': 1.0}],
        'obstacles': [],
        'tuning': TUNING,
    }

def scenario_blindspot_headon():
    # IRs at +/-90 (side-pointing), obstacle DEAD AHEAD -> predicted blind spot.
    return {
        'name': 'blindspot_headon — IR push @±90, wall dead ahead',
        'arena': (-0.1, -0.1, 1.0, 1.0),
        'start': {'x': 0.4, 'y': 0.1, 'heading': math.radians(90)},
        'sensors': _std_sensors(ir_angle=90.0, ir_policy='push', include_ldr=True, ldr_policy='pull'),
        'lights': [{'x': 0.4, 'y': 0.9, 'intensity': 1.0}],   # light beyond the wall
        'obstacles': [{'type': 'rect', 'x': 0.30, 'y': 0.45, 'w': 0.20, 'h': 0.05}],  # wall across the path
        'tuning': TUNING,
    }

def scenario_corner_freeze():
    # IR push into a corner -> predicted symmetric local minimum. Start CLOSE so
    # the stall (not the travel) dominates the frame.
    return {
        'name': 'corner_freeze — IR push @±22.5 into a corner',
        'arena': (0.0, 0.0, 0.8, 0.8),
        'start': {'x': 0.45, 'y': 0.40, 'heading': math.radians(90)},
        'sensors': _std_sensors(ir_angle=22.5, ir_policy='push', include_ldr=False),
        'lights': [],
        'obstacles': [
            {'type': 'segment', 'a': (0.2, 0.7), 'b': (0.7, 0.7)},   # back wall
            {'type': 'segment', 'a': (0.2, 0.7), 'b': (0.2, 0.25)},  # left wall (corner)
        ],
        'tuning': TUNING,
    }

def scenario_wall_alongside():
    # HYPOTHESIS RENDER (matches user's DESCRIPTION of the tower+torch run, not a
    # capture — that's Option 2, to come). Physical setup: a computer tower stood
    # on its long edge (a long wall), robot starting roughly PARALLEL to it on a
    # near-collision course, and the LIGHT is a torch magnetically stuck to the
    # tower's FAR/TOP-END corner casting down — so the light is CO-LOCATED with the
    # far END of the wall, not a distant independent goal. Observed real behavior:
    # arc OUT (IR push from the wall side) then BACK IN (LDR pull toward the end
    # light), ending driving perpendicular to the tower's end, under the torch.
    return {
        'name': 'wall_alongside (tower+end-torch, HYPOTHESIS from description)',
        'arena': (-0.2, -0.1, 1.1, 1.1),
        # robot starts parallel to the tower, slightly toward it (near-collision),
        # facing along the wall (up, +Y).
        'start': {'x': 0.34, 'y': 0.10, 'heading': math.radians(90)},
        'sensors': _std_sensors(ir_angle=90.0, ir_policy='push', include_ldr=True, ldr_policy='pull'),
        # LIGHT at the tower's FAR END corner (top of the wall), co-located w/ obstacle end.
        'lights': [{'x': 0.45, 'y': 0.78, 'intensity': 1.0}],
        # tower = long vertical wall to the robot's right; its far end is at y=0.78
        # where the torch sits.
        'obstacles': [{'type': 'segment', 'a': (0.45, 0.20), 'b': (0.45, 0.78)}],
        'tuning': TUNING,
    }

SCENARIOS = {
    'single_light': scenario_single_light,
    'blindspot_headon': scenario_blindspot_headon,
    'corner_freeze': scenario_corner_freeze,
    'wall_alongside': scenario_wall_alongside,
}


def main():
    ap = argparse.ArgumentParser(description="Predict + visualize a potential-field trajectory (Mode B).")
    ap.add_argument("--scenario", default="single_light", help="scenario name (see --list)")
    ap.add_argument("--out", default=None, help="output PNG path")
    ap.add_argument("--csv", default=None, help="also write predicted trajectory CSV")
    ap.add_argument("--steps", type=int, default=600, help="max simulation steps")
    ap.add_argument("--list", action="store_true", help="list scenarios")
    args = ap.parse_args()

    if args.list:
        print("scenarios:")
        for k in SCENARIOS: print("  ", k)
        return

    if args.scenario not in SCENARIOS:
        print(f"unknown scenario '{args.scenario}'. --list to see options."); sys.exit(1)

    sc = SCENARIOS[args.scenario]()
    traj, log_rows, collided = simulate(sc, max_steps=args.steps)
    out = args.out or f"predict_{args.scenario}.png"
    draw(sc, traj, out, collided)
    print(f"scenario: {sc['name']}")
    print(f"  steps simulated: {len(traj)-1}")
    print(f"  start: ({traj[0][0]:.3f},{traj[0][1]:.3f})  end: ({traj[-1][0]:.3f},{traj[-1][1]:.3f})")
    print(f"  outcome: {'COLLIDED (stopped at obstacle)' if collided else 'no collision'}")
    print(f"  path plot -> {out}")
    if args.csv:
        write_traj_csv(sc, log_rows, args.csv)
        print(f"  trajectory csv -> {args.csv}")


if __name__ == "__main__":
    main()
