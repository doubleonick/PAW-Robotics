"""
games/valentinos/builder/robot_builder.py
------------------------------------------
Split-screen robot builder and wiring editor for Valentino's Vehicles.

Layout (60/40 horizontal split):
  Left 60%  — Robot canvas: top-down view, chassis + sensor/motor placement
  Right 40% — Wiring editor panel (embedded, not a subprocess)

Chassis options:
  rectangle  — 167 × 94 mm  (Ana BBot / physical VV robot)
  octagon    — 155 mm bounding square  (EthologyBot V2 proportions)
  triangle   — equilateral, circumscribed in octagon's bounding circle

Sensor placement:
  Lego-peg grid (8 mm spacing), 3 rows deep from each edge, 4 mm margin
  Sensors: IR (numbered IR1, IR2, …) and LDR (LDR1, LDR2, …)
  Right-click to remove a placed sensor

Motor placement:
  Snap points at edge midpoints (rectangle: long edges only in Phase 1)
  First motor placed mirrors automatically across the longitudinal axis
  Right-click to remove motors

Canvas labels:
  "Front" along top edge (horizontal, centred)
  "Back"  along bottom edge
  "Left"  along left edge  (rotated, R at top — reads top-to-bottom)
  "Right" along right edge (rotated, R at bottom — reads top-to-bottom)

Output:
  Returns a RobotConfig dict compatible with the VV simulation engine.
  Wiring config (VehicleConfig) embedded in the result.
"""

from __future__ import annotations
import math
import os
import sys

import pygame

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import engine.theme as _T

def _t(): return _T

BG          = lambda: _t().BG
PANEL       = lambda: _t().PANEL
PANEL_DEEP  = lambda: _t().PANEL_DEEP
BORDER      = lambda: _t().BORDER
BORDER_DIM  = lambda: _t().BORDER_DIM
PHOSPHOR    = lambda: _t().PHOSPHOR
PHOSPHOR_MID= lambda: _t().PHOSPHOR_MID
PHOSPHOR_DIM= lambda: _t().PHOSPHOR_DIM
AMBER       = lambda: _t().AMBER
AMBER_DIM   = lambda: _t().AMBER_DIM
TEXT        = lambda: _t().TEXT
TEXT_DIM    = lambda: _t().TEXT_DIM

# ── Geometry constants (metres) ───────────────────────────────────────────────

def chassis_collision_radius(spec) -> float:
    """Collision-circle radius for a chassis spec, in metres.

    Returns the INSCRIBED radius — the largest circle that fits inside the
    drawn body — so the robot never stops short of a wall it visually clears.
    A circle is a poor model for the rectangle chassis (aspect 1.78): using the
    inscribed radius means the nose can overlap a head-on wall by up to
    (length-width)/2 = 3.6 cm. Proper polygon collision (PyBulletAdapter) is
    the real fix; this keeps the sides correct in the meantime, which is the
    visually dominant case in a corridor.

    Accepts a chassis_spec dict or a chassis key string.
    """
    if isinstance(spec, str):
        spec = CHASSIS.get(spec, {})
    spec = spec or {}
    t = spec.get("type", "octagon")
    if t == "rectangle":
        return min(spec.get("width_m", 0.094),
                   spec.get("length_m", 0.167)) / 2.0
    if t == "triangle":
        # inradius of an equilateral triangle is half its circumradius
        return spec.get("circum_r_m", 0.1550 * math.sqrt(2) / 2) / 2.0
    return spec.get("bsquare_m", 0.1550) / 2.0     # octagon inradius


CHASSIS = {
    "rectangle": {
        "label":   "Rectangle  (167 × 94 mm)",
        "type":    "rectangle",
        "width_m":  0.094,
        "length_m": 0.167,
    },
    "octagon": {
        "label":   "Octagon  (155 mm across)",
        "type":    "octagon",
        # 155 mm bounding square, from robots/ethology_v2.json
        # (chassis.bounding_square_mm = 155) — the CAD-derived source of truth,
        # and the figure this file's own header always claimed.
        # Was 0.1690 ("70 mm edges"), which is 9% too big and put the drawn
        # chassis out of register with RE's robot.json body_radius of 0.0775.
        # 0.155/2 = 0.0775 exactly: body_radius IS the octagon inradius.
        "bsquare_m": 0.1550,
    },
    "triangle": {
        "label":   "Triangle  (equilateral, inscribed)",
        "type":    "triangle",
        # circumradius matches the octagon's bounding circle (bsquare=155mm)
        "circum_r_m": 0.1550 * math.sqrt(2) / 2,  # bounding circle
    },
}

PLEG_SPACING_M = 0.008   # 8 mm
PLEG_MARGIN_M  = 0.004   # 4 mm from edge
PLEG_ROWS      = 3        # rows deep from each edge

WHEEL_DIAM_M   = 0.024   # 24 mm standard wheel diameter
SENSOR_RADIUS  = 0.006   # display radius for sensor dot (6 mm)
MOTOR_RADIUS   = 0.010   # display radius for motor snap point

# Sensor colours by type
MAX_SENSORS  = 6
SENSOR_TYPES = ["IR", "LDR"]
SENSOR_COLS  = {"IR": (255, 105, 180), "LDR": (255, 200, 60)}  # IR pink: distinct from LDR·G green
LDR_CH_COLS  = {"W": (255, 200, 60), "R": (220, 60, 60),
                "G": (60, 200, 60),  "B": (80, 140, 255)}

# ── Flow styles ────────────────────────────────────────────────────────────────
# How a sensor makes the robot flow relative to a source it senses. Each style
# is a fixed (policy, tangential) pair the engine already understands:
#   policy     = radial response  (+1 toward / -1 away / 0 none-but-slight)
#   tangential = circulation      (+ = one way around, - = the other)
# SWIRL is the standard circulation magnitude; 3.0 solves both C7 and C10 at
# either handedness. Orbit carries a small inward radial so the ring is stable
# (a pure-tangential orbit drifts outward); the player never sees the number.
SWIRL        = 3.0
ORBIT_INWARD = -0.3
# Ordered list drives the click-to-cycle order. (key, label, policy, tangential)
FLOW_STYLES = [
    ("seek",        "Seek (toward)",        "attract", 0.0),
    ("flee",        "Flee (away)",          "repel",   0.0),
    ("orbit_l",     "Orbit left",           "none",    +SWIRL),
    ("orbit_r",     "Orbit right",          "none",    -SWIRL),
    ("around_l",    "Flow-around left",     "repel",   +SWIRL),
    ("around_r",    "Flow-around right",    "repel",   -SWIRL),
]
FLOW_BY_KEY  = {k: (k, lbl, pol, tan) for (k, lbl, pol, tan) in FLOW_STYLES}

def _flow_radial(policy: str) -> str:
    """Map a flow policy token to the stored sensor policy."""
    return policy  # "attract" | "repel" | "none"

def _style_from_policy_tan(policy: str, tangential: float) -> str:
    """Recover a flow-style key from a stored (policy, tangential) pair, for
    loading older/saved robots. Falls back to nearest sensible style."""
    if abs(tangential) < 1e-6:
        return "seek" if policy == "attract" else "flee"
    side = "l" if tangential > 0 else "r"
    if policy == "repel":
        return f"around_{side}"
    return f"orbit_{side}"

# Physical proximity constraints (metres)
MIN_SEP = {
    ("IR",  "IR"):  0.016,
    ("IR",  "LDR"): 0.012,
    ("LDR", "IR"):  0.012,
    ("LDR", "LDR"): 0.016,
}

# ── Chassis geometry helpers ──────────────────────────────────────────────────

def chassis_polygon_m(cfg: dict) -> list[tuple[float,float]]:
    """
    Return polygon vertices in robot-local metres.
    x = right (+right, -left), y = forward (+front, -back).
    Origin = chassis centre.
    """
    t = cfg["type"]
    if t == "rectangle":
        w = cfg["width_m"]  / 2
        l = cfg["length_m"] / 2
        return [(-w, l), (w, l), (w, -l), (-w, -l)]

    elif t == "octagon":
        a   = cfg["bsquare_m"] / 2   # half bounding square = B/2
        # For regular octagon with equal sides s:
        #   bsquare B = s*(1+sqrt2),  cut = s/sqrt2 = a*sqrt2/(1+sqrt2)
        # Simplified: cut = a*(sqrt2-1) ... verify:
        #   a = s*(1+sqrt2)/2, cut=s/sqrt2, a-cut = s*(1+sqrt2)/2 - s/sqrt2
        #   = s*( (1+sqrt2)/2 - 1/sqrt2 ) = s*(sqrt2+2-sqrt2)/(2) ... 
        # Actually: cut = a - s/2 = a - a/(1+sqrt2) = a*sqrt2/(1+sqrt2)
        cut = a * math.sqrt(2) / (1 + math.sqrt(2))
        return [
            (-a + cut,  a), (a - cut,  a),
            ( a,  a - cut), (a, -(a - cut)),
            ( a - cut, -a), (-a + cut, -a),
            (-a, -(a - cut)), (-a,  a - cut),
        ]

    elif t == "triangle":
        R  = cfg["circum_r_m"]
        ir = R / 2   # inradius = R/2 for equilateral
        hs = R * math.sqrt(3) / 2  # half side length
        # Front edge flat, rear vertex pointing back
        # Front-left, Front-right, Rear
        return [(-hs, ir), (hs, ir), (0, -R)]

    return []


def chassis_edge_midpoints_m(cfg: dict) -> list[tuple[float,float]]:
    """Return midpoint of each polygon edge (motor snap points)."""
    poly = chassis_polygon_m(cfg)
    mids = []
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i+1) % n]
        mids.append(((ax+bx)/2, (ay+by)/2))
    return mids


def motor_snap_points_m(cfg: dict) -> list[tuple[float,float]]:
    """
    Return valid motor snap points for Phase 1.
    Rectangle: only long (side) edges (left and right midpoints).
    Octagon:   left and right side edge midpoints.
    Triangle:  front-edge vertices (two front corners).
    Motor placement mirrors: placing first point auto-places its mirror.
    Returns list of (x, y) in metres — includes only one of each mirror pair
    (the one with x > 0, i.e. the right-side point).
    """
    t = cfg["type"]
    if t == "rectangle":
        hw = cfg["width_m"] / 2
        return [(hw, 0.0), (-hw, 0.0)]

    elif t == "octagon":
        hw = cfg["bsquare_m"] / 2
        return [(hw, 0.0), (-hw, 0.0)]

    elif t == "triangle":
        R  = cfg["circum_r_m"]
        ir = R / 2
        hs = R * math.sqrt(3) / 2
        return [(hs, ir), (-hs, ir)]

    return []


def peg_holes_m(cfg: dict) -> list[tuple[float,float]]:
    """
    Generate Lego-peg hole positions for a chassis.
    Returns deduplicated set of (x, y) in metres, robot-local.
    """
    t    = cfg["type"]
    poly = chassis_polygon_m(cfg)
    n    = len(poly)
    seen = set()
    holes = []
    s    = PLEG_SPACING_M
    m    = PLEG_MARGIN_M

    def _add(x, y):
        key = (round(x/s)*s, round(y/s)*s)
        rx  = round(key[0], 6)
        ry  = round(key[1], 6)
        if (rx, ry) not in seen:
            seen.add((rx, ry))
            holes.append((rx, ry))

    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i+1) % n]
        ex, ey = bx - ax, by - ay
        length = math.hypot(ex, ey)
        if length < 1e-9:
            continue
        # Unit vectors along edge
        ux, uy = ex/length, ey/length
        # Inward normal: polygon vertices are CW so inward = rotate right
        # CW: inward normal = (+uy, -ux)
        nx, ny = uy, -ux

        # Rows perpendicular to edge (inward)
        for row in range(PLEG_ROWS):
            d     = m + row * s   # distance from edge
            ox    = ax + nx * d
            oy    = ay + ny * d
            # Columns along edge
            steps = int(length / s) + 2
            for col in range(-1, steps + 1):
                px = ox + ux * (m + col * s)
                py = oy + uy * (m + col * s)
                # Check inside polygon
                if _point_in_poly(px, py, poly):
                    _add(px, py)

    return holes


def _point_in_poly(x, y, poly) -> bool:
    """Ray-casting point-in-polygon."""
    n      = len(poly)
    inside = False
    px, py = x, y
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py) and
                px < (xj - xi) * (py - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


# ── RobotBuilder ─────────────────────────────────────────────────────────────

class RobotBuilder:
    """
    Split-screen robot builder + embedded wiring editor.
    Call run() to launch.  Returns (robot_config, vehicle_config) or
    (None, None) if cancelled.
    """

    def __init__(self, initial_chassis: str = "rectangle",
                 initial_config=None,
                 existing_robot: dict | None = None,
                 window_size: tuple | None = None,
                 show_wiring: bool = True,
                 arena_preview: dict | None = None,
                 flow_styles: bool = False,
                 radial_only: bool = False):
        self._show_wiring    = show_wiring
        # Flow-style picker (Seek/Flee/Orbit/Flow-around) is FIELD TRIP ONLY —
        # it is FT's virtual-field vocabulary and its replacement for wiring.
        # Valentino's Vehicles is the Braitenberg/wiring game and must NEVER
        # show it. Defaults OFF so only a game that explicitly opts in (FT,
        # via flow_styles=True) gets it; the shared builder otherwise omits it.
        self._flow_styles    = flow_styles
        # Radial-only (Push/Pull) mode: the flow-style picker offers ONLY Seek
        # (Pull/toward) and Flee (Push/away) — the pure radial forces. The
        # tangential circulation styles (Orbit, Flow-around) are hidden until
        # they're hardware-validated. The engine still understands tangential, so
        # saved robots and challenge solutions using it remain loadable.
        self._radial_only    = radial_only
        self._arena_preview  = arena_preview
        from engine.builder.wiring_editor import (
            WiringEditor, VehicleConfig)
        self._VehicleConfig = VehicleConfig
        # Restore from existing robot.json if provided
        if existing_robot:
            initial_chassis = existing_robot.get("chassis", initial_chassis)
        self._chassis_key    = initial_chassis
        self._sel_sensor     = None
        self._sel_motor      = None
        self._dragging_angle = False
        self._chassis       = CHASSIS.get(initial_chassis, CHASSIS["rectangle"])
        self._sensors: list[dict] = []
        self._motors:  list[dict] = []

        self._editor = WiringEditor(initial_config,
                                     suppress_done=True)
        self._editor._sensor_names = []
        self._editor._motor_names  = []

        self._tool      = "place_IR"   # default: place IR sensor
        self._ldr_channel = "W"        # W/R/G/B — active for Place LDR
        self._window_size = window_size   # passed from hub
        self._sel_sensor:        int | None = None
        self._dragging_angle:    bool       = False
        self._angle_handle_rect  = None
        self._policy_toggle_rect = None
        self._flow_pick_rects = {}   # flow_key -> Rect, for the sidebar picker
        self._sel_motor:  int | None = None
        self._status    = "Choose a chassis, then place sensors and motors"
        self._confirmed = False
        self._cancelled = False

        # Precompute holes (recomputed when chassis changes)
        self._holes: list[tuple] = []
        self._snap_points: list[tuple] = []
        self._peg_radius_px = 0
        self._set_chassis(initial_chassis)

        # Restore sensors/motors from existing robot config
        if existing_robot:
            raw_sensors = existing_robot.get("sensors", {})
            if isinstance(raw_sensors, dict):
                for sid, pos in raw_sensors.items():
                    stype = pos.get("type",
                            "IR" if sid.startswith("IR") else "LDR")
                    # robot.json: x_m=forward, y_m=lateral
                    # canvas: x=lateral(right+), y=forward
                    _pol = pos.get("policy", "attract")
                    _tan = float(pos.get("tangential", 0.0))
                    self._sensors.append({
                        "id":        sid,
                        "type":      stype,
                        "channel":   pos.get("channel", "W"),
                        # robot.json: x_m=forward, y_m=lateral (LEFT-positive).
                        # Canvas x is RIGHT-positive, so negate y_m back on load —
                        # this undoes the negation _export_sensor applied on save.
                        # (Without the negation here, a right-placed sensor reloaded
                        # on the left — a mirror flip on every round-trip.)
                        "x":         -pos.get("y_m", 0.0),
                        "y":         pos.get("x_m", 0.0),
                        "angle_deg": pos.get("angle_deg", 0.0),
                        "policy":    _pol,
                        # flow style recovered from saved (policy, tangential)
                        "flow":      _style_from_policy_tan(_pol, _tan),
                    })
            raw_motors = existing_robot.get("motors", {})
            if isinstance(raw_motors, dict):
                for mid, pos in raw_motors.items():
                    self._motors.append({
                        "id": mid,
                        # negate y_m -> canvas x (right-positive), undoing the
                        # save-side negation, same as sensors above.
                        "x":  -pos.get("y_m", 0.0),
                        "y":  pos.get("x_m", 0.0),
                    })
            # Advance tool past already-placed sensors
            if len(self._sensors) >= MAX_SENSORS:
                self._tool = "motor"
            # else keep default place_IR
            self._update_editor_nodes()
            # Restore wiring connections AFTER chassis and nodes are set
            if initial_config and initial_config.connections:
                self._editor._connections = list(initial_config.connections)

        # Estimate canvas scale and origin before first draw so that
        # clicks register correctly immediately.
        # Assumes 1200x800 window, 18% panel, 42% canvas (60/40 split).
        _ww, _wh = 1200, 800
        _panel_w  = int(_ww * 0.18)
        _canvas_w = int(_ww * 0.42)
        _canvas_h = _wh
        poly   = chassis_polygon_m(self._chassis)
        all_x  = [p[0] for p in poly]
        all_y  = [p[1] for p in poly]
        span_x = max(all_x) - min(all_x)
        span_y = max(all_y) - min(all_y)
        _margin = 0.06
        scl_x  = (_canvas_w - 80) / (span_x + _margin * 2)
        scl_y  = (_canvas_h - 80) / (span_y + _margin * 2)
        self._scale  = min(scl_x, scl_y)
        self._origin = (_panel_w + _canvas_w // 2, _canvas_h // 2)

    def _draw_flow_glyph(self, surf, cx, cy, R, style, selected):
        """Draw one flow-style glyph centred at (cx,cy) within radius ~R.
        Rings (focal middle ring) + one arrow whose PATH encodes the motion:
        Seek=in, Flee=out, Orbit=3/4 arc on focal ring, Flow-around=stem in at
        6 o'clock, trace focal ring to 12, stem out. Used by the sidebar
        picker. Colours: toward=blue, away=red, around=amber."""
        import math as _m
        BLUE = (80, 160, 255); RED = (255, 80, 80); AMBER = (255, 200, 60)
        try:
            dim   = TEXT_DIM()
            focal = PHOSPHOR() if selected else BORDER()
            srcc  = PHOSPHOR() if selected else TEXT_DIM()
        except Exception:
            dim = (90, 90, 90); focal = (180, 180, 180); srcc = (150, 150, 150)
        r0 = int(R * 0.42); dr = int(R * 0.27)
        r_mid = r0 + dr; r_out = r0 + 2 * dr; stem = int(R * 1.02)
        w = 3 if selected else 2

        def pt(r, deg):
            a = _m.radians(deg)
            return (cx + r * _m.cos(a), cy - r * _m.sin(a))
        def head(x, y, ang, color):
            s = 8 if selected else 6
            a1 = ang + _m.radians(150); a2 = ang - _m.radians(150)
            pygame.draw.line(surf, color, (x, y),
                             (x + s*_m.cos(a1), y - s*_m.sin(a1)), w)
            pygame.draw.line(surf, color, (x, y),
                             (x + s*_m.cos(a2), y - s*_m.sin(a2)), w)
        def arc(r, d0, d1, color, with_head=True):
            steps = 40
            pts = [pt(r, d0 + (d1-d0)*i/steps) for i in range(steps+1)]
            if len(pts) > 1:
                pygame.draw.lines(surf, color, False, pts, w)
            if with_head:
                going = d1 > d0; d = _m.radians(d1)
                tx = -_m.sin(d)*(1 if going else -1)
                ty = -_m.cos(d)*(1 if going else -1)
                ex, ey = pt(r, d1); head(ex, ey, _m.atan2(-ty, tx), color)

        # rings (focal middle ring brighter/thicker)
        for i in range(3):
            rr = r0 + i*dr
            mid = (rr == r_mid)
            pygame.draw.circle(surf, focal if mid else dim, (cx, cy), rr,
                               2 if mid else 1)
        pygame.draw.circle(surf, srcc, (cx, cy), max(3, int(R*0.12)))

        if style == "seek":
            p0 = pt(stem, 90); p1 = pt(r_mid, 90)
            pygame.draw.line(surf, BLUE, p0, p1, w); head(*p1, _m.radians(-90), BLUE)
        elif style == "flee":
            p0 = pt(r_mid, 90); p1 = pt(stem, 90)
            pygame.draw.line(surf, RED, p0, p1, w); head(*p1, _m.radians(90), RED)
        elif style == "orbit_l":
            arc(r_mid, 180, 450, AMBER)
        elif style == "orbit_r":
            arc(r_mid, 0, -270, AMBER)
        elif style == "around_l":
            pygame.draw.line(surf, RED, pt(stem, 270), pt(r_mid, 270), w)
            arc(r_mid, 270, 90, RED, with_head=False)
            pygame.draw.line(surf, RED, pt(r_mid, 90), pt(stem, 90), w)
            head(*pt(stem, 90), _m.radians(90), RED)
        elif style == "around_r":
            pygame.draw.line(surf, RED, pt(stem, 270), pt(r_mid, 270), w)
            arc(r_mid, 270, 450, RED, with_head=False)
            pygame.draw.line(surf, RED, pt(r_mid, 90), pt(stem, 90), w)
            head(*pt(stem, 90), _m.radians(90), RED)

    def _export_sensor(self, s: dict) -> dict:
        """Build the export dict for one sensor, deriving policy + tangential
        from its flow style. y_m negated so lateral is LEFT-positive (canvas
        x is right-positive)."""
        flow = s.get("flow") or _style_from_policy_tan(
            s.get("policy", "attract"), 0.0)
        _, _, policy, tangential = FLOW_BY_KEY.get(
            flow, FLOW_BY_KEY["seek"])
        out = {"type": s["type"],
               "channel": s.get("channel", "W"),
               "x_m": round(s["y"], 4),
               "y_m": round(-s["x"], 4),
               "angle_deg": s.get("angle_deg", 0.0),
               "policy": policy}
        if abs(tangential) > 1e-6:
            out["tangential"] = round(tangential, 3)
        return out

    def _set_chassis(self, key: str):
        self._chassis_key = key
        self._chassis     = CHASSIS[key]
        self._holes       = peg_holes_m(self._chassis)
        self._snap_points = motor_snap_points_m(self._chassis)
        self._sensors.clear()
        self._motors.clear()
        # Clear wiring when chassis changes
        self._editor._connections = []
        self._editor._sel_source  = None
        self._tool = "place_IR"
        self._ldr_channel = "W"
        # Recalculate scale/origin for new chassis
        poly   = chassis_polygon_m(self._chassis)
        all_x  = [p[0] for p in poly]
        all_y  = [p[1] for p in poly]
        span_x = max(all_x) - min(all_x)
        span_y = max(all_y) - min(all_y)
        _margin = 0.06
        _canvas_w = int(getattr(self, "_canvas_w_px", 1200 * 42 // 100))
        _canvas_h = int(getattr(self, "_canvas_h_px", 800))
        _panel_w  = int(getattr(self, "_panel_w_px",  1200 * 18 // 100))
        scl_x  = (_canvas_w - 80) / (span_x + _margin * 2)
        scl_y  = (_canvas_h - 80) / (span_y + _margin * 2)
        self._scale  = min(scl_x, scl_y)
        self._origin = (_panel_w + _canvas_w // 2, _canvas_h // 2)
        self._update_editor_nodes()

    def _make_zone_id(self, stype: str, canvas_x: float) -> str:
        """
        Assign a zone-qualified ID to a sensor placed at canvas_x.
        Zone: L if canvas_x < -PLEG_SPACING_M (screen left),
              R if canvas_x >  PLEG_SPACING_M (screen right),
              C otherwise (within one peg of centre).
        Numbered within zone if multiple sensors share it.
        """
        if canvas_x < -PLEG_SPACING_M:
            zone = "L"   # screen left = robot left
        elif canvas_x > PLEG_SPACING_M:
            zone = "R"   # screen right = robot right
        else:
            zone = "C"
        # Count existing sensors of same type+zone
        existing = [s for s in self._sensors
                    if s["type"] == stype and
                    self._zone_of(s["x"]) == zone]
        n = len(existing) + 1   # 1-based index for new sensor
        # Count ALL sensors of same type+zone after placement to decide numbering
        # We number only if there will be >1; for now use index and renumber later
        return f"{stype}\u00b7{zone}{n}"

    def _zone_of(self, canvas_x: float) -> str:
        if canvas_x < -PLEG_SPACING_M:
            return "L"   # screen-left
        elif canvas_x > PLEG_SPACING_M:
            return "R"   # screen-right
        return "C"

    def _update_editor_nodes(self):
        """Renumber zone IDs and push names to wiring editor."""
        # Bucket sensors L→C→R, front-to-back within each zone
        buckets: dict[str, list] = {"L": [], "C": [], "R": []}
        for s in self._sensors:
            buckets[self._zone_of(s["x"])].append(s)
        for z in buckets:
            buckets[z].sort(key=lambda s: -s["y"])  # front first

        # Renumber IDs: single sensor in zone → "IR·L", multiple → "IR·L1"
        # Output order: L→C→R matches screen left→right (top-down view)
        s_names: list[str] = []
        for z in ("L", "C", "R"):
            group = buckets[z]
            # Sub-bucket by type within zone for numbering
            type_counts: dict[str, int] = {}
            for s in group:
                type_counts[s["type"]] = type_counts.get(s["type"], 0) + 1
            type_idx: dict[str, int] = {}
            for s in group:
                t   = s["type"]
                idx = type_idx.get(t, 0) + 1
                type_idx[t] = idx
                if type_counts[t] == 1:
                    new_id = f"{t}\u00b7{z}"
                else:
                    new_id = f"{t}\u00b7{z}{idx}"
                s["id"] = new_id
                s_names.append(new_id)

        # Motors: left (positive canvas x) → FL, right → FR
        m_sorted = sorted(self._motors, key=lambda m: -m["x"])
        m_names  = ["FL", "FR"][:len(m_sorted)] if m_sorted else []

        # Build channel map {sensor_id: channel} for wiring editor colors
        ch_map = {s["id"]: s.get("channel", "W") for s in self._sensors}
        self._editor._sensor_names     = s_names
        self._editor._sensor_channels  = ch_map
        self._editor._sensor_positions = None
        self._editor._motor_names      = m_names
        # Purge connections referencing sensors or motors no longer present
        valid_sources = set(s_names)
        valid_dests   = set(m_names) | {
            f"E{i}" for i in range(1, 7)} | {
            f"I{i}" for i in range(1, 7)}
        self._editor._connections = [
            c for c in self._editor._connections
            if c.source in valid_sources
        ]
        if self._editor._rect:
            self._editor.set_panel(self._editor._rect)

    # ── World ↔ screen coordinate conversion ─────────────────────────────

    def _w2s(self, wx, wy) -> tuple[int,int]:
        ox, oy = self._origin
        # Top-down view: Forward = up
        # wx = lateral offset, wy = forward offset
        return (int(ox + wx * self._scale),
                int(oy - wy * self._scale))

    def _s2w(self, sx, sy) -> tuple[float,float]:
        ox, oy = self._origin
        return ((sx - ox) / self._scale,
                (oy - sy) / self._scale)

    def _nearest_hole(self, wx, wy) -> tuple[float,float] | None:
        best_d = float("inf")
        best   = None
        tol    = PLEG_SPACING_M * 0.7   # 5.6mm — just under half-spacing
        for hx, hy in self._holes:
            d = math.hypot(wx - hx, wy - hy)
            if d < best_d and d < tol:
                best_d = d
                best   = (hx, hy)
        return best

    def _nearest_snap(self, wx, wy) -> tuple[float,float] | None:
        best_d = float("inf")
        best   = None
        tol    = PLEG_SPACING_M * 1.5
        for sx, sy in self._snap_points:
            d = math.hypot(wx - sx, wy - sy)
            if d < best_d and d < tol:
                best_d = d
                best   = (sx, sy)
        return best

    # ── Drawing ───────────────────────────────────────────────────────────

    def _draw_canvas(self, surf, canvas_rect, font_sm, font_md):
        """Draw the robot top-down view into canvas_rect."""
        pygame.draw.rect(surf, PANEL_DEEP(), canvas_rect)
        pygame.draw.rect(surf, BORDER(), canvas_rect, 1)

        # Compute scale to fit chassis in canvas with margin
        poly = chassis_polygon_m(self._chassis)
        all_x = [p[0] for p in poly]
        all_y = [p[1] for p in poly]
        span_x = max(all_x) - min(all_x)
        span_y = max(all_y) - min(all_y)
        margin = 0.06  # 6cm margin
        scl_x  = (canvas_rect.width  - 80) / (span_x + margin * 2)
        scl_y  = (canvas_rect.height - 80) / (span_y + margin * 2)
        self._scale  = min(scl_x, scl_y)
        self._origin = (canvas_rect.centerx, canvas_rect.centery)
        # Store for chassis-change recalculation
        self._canvas_w_px = canvas_rect.width
        self._canvas_h_px = canvas_rect.height
        self._panel_w_px  = canvas_rect.left

        # Chassis polygon
        pts = [self._w2s(x, y) for x, y in poly]
        pygame.draw.polygon(surf, (30, 55, 30), pts)
        pygame.draw.polygon(surf, PHOSPHOR_DIM(), pts, 2)

        # Peg holes — drawn as small filled circles in a visible green
        pr = max(2, int(PLEG_SPACING_M * self._scale * 0.30))
        self._peg_radius_px = pr
        try:
            hole_col = PHOSPHOR_DIM()
        except Exception:
            hole_col = (51, 140, 60)
        for hx, hy in self._holes:
            sx, sy = self._w2s(hx, hy)
            if canvas_rect.collidepoint(sx, sy):
                pygame.draw.circle(surf, hole_col, (sx, sy), pr)

        # Motor snap points
        for mpx, mpy in self._snap_points:
            sx, sy = self._w2s(mpx, mpy)
            sr = max(4, int(MOTOR_RADIUS * self._scale))
            pygame.draw.circle(surf, AMBER_DIM(), (sx, sy), sr, 1)

        # Placed motors
        for mi, m in enumerate(self._motors):
            sx, sy = self._w2s(m["x"], m["y"])
            mr = max(5, int(WHEEL_DIAM_M/2 * self._scale))
            sel = (mi == self._sel_motor)
            col = AMBER() if sel else AMBER_DIM()
            pygame.draw.circle(surf, col, (sx, sy), mr)
            pygame.draw.circle(surf, AMBER(), (sx, sy), mr, 2)
            t = font_sm.render(m["id"], True, (10, 18, 10))
            surf.blit(t, (sx - t.get_width()//2, sy - t.get_height()//2))

        # Placed sensors
        self._angle_handle_rect = None   # rebuilt for the selected sensor below
        for si, s in enumerate(self._sensors):
            sx2, sy2 = self._w2s(s["x"], s["y"])
            sr2 = max(4, int(SENSOR_RADIUS * self._scale))
            sel = (si == self._sel_sensor)
            stype2 = s.get("type", "IR")
            if stype2 == "LDR":
                col = LDR_CH_COLS.get(s.get("channel", "W"),
                                      SENSOR_COLS["LDR"])
            else:
                col = SENSOR_COLS.get(stype2, PHOSPHOR())
            # Draw filled circle with dark border for definition. The dark
            # border also gives separation so a same-colour selection ring
            # still reads (e.g. green ring around a green IR dot).
            pygame.draw.circle(surf, (10, 18, 10), (sx2, sy2), sr2 + 2)
            pygame.draw.circle(surf, col, (sx2, sy2), sr2)
            # Angle indicator: small triangle on the rim, always visible.
            # Coloured by sensor type/channel (same as the dot) — the canvas
            # conveys only PHYSICAL facts (type, position, facing). Behaviour
            # (flow style) lives in the sidebar, not on the robot.
            # robot.json: 0°=forward; screen: 0°=right, 90°=up
            ang_rad  = math.radians(s.get("angle_deg", 0.0) + 90.0)
            tri_col  = col
            tri_dist = sr2 + 3          # triangle tip on rim
            tri_size = max(4, sr2 // 2) # half-base of triangle
            # Tip of triangle (pointing outward)
            tip_x = sx2 + math.cos(ang_rad) * (tri_dist + tri_size)
            tip_y = sy2 - math.sin(ang_rad) * (tri_dist + tri_size)
            # Two base points perpendicular to the direction
            perp  = ang_rad + math.pi / 2
            b1x   = sx2 + math.cos(ang_rad) * tri_dist \
                        + math.cos(perp) * tri_size
            b1y   = sy2 - math.sin(ang_rad) * tri_dist \
                        - math.sin(perp) * tri_size
            b2x   = sx2 + math.cos(ang_rad) * tri_dist \
                        - math.cos(perp) * tri_size
            b2y   = sy2 - math.sin(ang_rad) * tri_dist \
                        + math.sin(perp) * tri_size
            pygame.draw.polygon(surf, tri_col,
                                [(int(tip_x), int(tip_y)),
                                 (int(b1x),   int(b1y)),
                                 (int(b2x),   int(b2y))])
            # Selection cue: a ring around the dot in the triangle/type colour.
            # Sits outside the dark border so it pops against the infill.
            # (No policy colour any more — behaviour is shown in the sidebar.)
            if sel:
                pygame.draw.circle(surf, tri_col, (sx2, sy2), sr2 + 4, 2)
            # The triangle itself is the angle drag target (no separate blob).
            if sel:
                self._angle_handle_rect = pygame.Rect(
                    int(tip_x) - tri_size - 2, int(tip_y) - tri_size - 2,
                    (tri_size + 2) * 2, (tri_size + 2) * 2)
            # Label: dark outline then white text for max contrast
            label = s["id"]
            t = font_sm.render(label, True, (255, 255, 255))
            ts = font_sm.render(label, True, (10, 18, 10))
            tx = sx2 - t.get_width()//2
            ty = sy2 - t.get_height()//2
            # Shadow in each direction for outline effect
            for dx, dy in ((-1,0),(1,0),(0,-1),(0,1)):
                surf.blit(ts, (tx+dx, ty+dy))
            surf.blit(t, (tx, ty))

        # Direction indicator (arrow pointing forward = up)
        arr_x, arr_y = canvas_rect.centerx, canvas_rect.top + 20
        pygame.draw.polygon(surf, PHOSPHOR_MID(), [
            (arr_x, arr_y), (arr_x - 6, arr_y + 10), (arr_x + 6, arr_y + 10)])

        # Edge labels
        self._draw_edge_labels(surf, canvas_rect, font_sm)

    def _draw_edge_labels(self, surf, r, font):
        """Draw Front/Back/Left/Right labels along canvas edges."""
        # Front — top edge, horizontal
        ft = font.render("Front", True, TEXT_DIM())
        surf.blit(ft, (r.centerx - ft.get_width()//2, r.top + 4))
        # Back — bottom edge, horizontal
        bt = font.render("Back", True, TEXT_DIM())
        surf.blit(bt, (r.centerx - bt.get_width()//2, r.bottom - bt.get_height() - 4))

        # Left — left edge, rotated so L is at top (reads top-to-bottom)
        lt = font.render("Left", True, TEXT_DIM())
        lt_rot = pygame.transform.rotate(lt, -90)  # -90 = top-to-bottom
        surf.blit(lt_rot, (r.left + 4,
                            r.centery - lt_rot.get_height()//2))

        # Right — right edge, rotated so R is at top (reads top-to-bottom)  
        rt = font.render("Right", True, TEXT_DIM())
        rt_rot = pygame.transform.rotate(rt, 90)  # 90 = bottom-to-top, R at bottom
        # Wait — spec says "R in Right should face TOP of canvas"
        # reads top-to-bottom means first letter R is at top
        # rotate(lt, 90) puts left side of text at top → R at top for "Right"
        rt_rot = pygame.transform.rotate(rt, -90)
        surf.blit(rt_rot, (r.right - rt_rot.get_width() - 4,
                            r.centery - rt_rot.get_height()//2))

    def _draw_panel(self, surf, panel_rect, font_sm, font_md, font_hd):
        """Draw the left control panel (chassis selector + tools + status)."""
        pygame.draw.rect(surf, PANEL(), panel_rect)
        pygame.draw.rect(surf, BORDER(), panel_rect, 1)

        y = panel_rect.top + 10
        x = panel_rect.left + 10
        w = panel_rect.width - 20

        # Title
        tt = font_hd.render("Robot Builder", True, PHOSPHOR())
        surf.blit(tt, (x, y)); y += tt.get_height() + 12

        # Chassis selector
        t = font_sm.render("Chassis:", True, TEXT_DIM())
        surf.blit(t, (x, y)); y += t.get_height() + 4
        self._chassis_btns = {}
        for key, info in CHASSIS.items():
            br = pygame.Rect(x, y, w, 28)
            active = (key == self._chassis_key)
            pygame.draw.rect(surf, PHOSPHOR_MID() if active else PANEL_DEEP(),
                             br, border_radius=4)
            pygame.draw.rect(surf, PHOSPHOR() if active else BORDER(),
                             br, 1, border_radius=4)
            lt2 = font_sm.render(info["label"], True,
                                 (10,18,10) if active else TEXT())
            surf.blit(lt2, (br.x + 6, br.centery - lt2.get_height()//2))
            self._chassis_btns[key] = br
            y += 34

        y += 8

        # Tool selector
        t = font_sm.render("Place:", True, TEXT_DIM())
        surf.blit(t, (x, y)); y += t.get_height() + 4
        self._tool_btns = {}
        n_placed  = len(self._sensors)
        can_place = n_placed < MAX_SENSORS
        ct = font_sm.render(
            f"Sensors: {n_placed}/{MAX_SENSORS}", True,
            PHOSPHOR() if can_place else TEXT_DIM())
        surf.blit(ct, (x, y)); y += ct.get_height() + 6
        type_tools = []
        for stype in SENSOR_TYPES:
            col = SENSOR_COLS[stype]
            type_tools.append((f"place_{stype}", f"Place {stype}",
                               col, not can_place))
        type_tools.append(("motor", "Place Motors", AMBER(), False))
        for tid, tlabel, tcol, dimmed in type_tools:
            br     = pygame.Rect(x, y, w, 28)
            active = (self._tool == tid)
            bg     = PANEL_DEEP()
            bc     = tcol if active else (BORDER_DIM() if dimmed else BORDER())
            bw     = 2 if active else 1
            tc     = tcol if active else (TEXT_DIM() if dimmed else TEXT())
            pygame.draw.rect(surf, bg, br, border_radius=4)
            pygame.draw.rect(surf, bc, br, bw, border_radius=4)
            lt2 = font_sm.render(tlabel, True, tc)
            surf.blit(lt2, (br.x + 6, br.centery - lt2.get_height()//2))
            self._tool_btns[tid] = br
            y += 34

        # Channel toggle — shown when Place LDR is active
        # Show channel selector when placing LDR or when an LDR sensor is selected
        _sel_ldr = (self._sel_sensor is not None and
                    self._sel_sensor < len(self._sensors) and
                    self._sensors[self._sel_sensor].get("type") == "LDR")
        if self._tool == "place_LDR" or _sel_ldr:
            # Active channel: use selected sensor's channel if one is selected
            if _sel_ldr:
                _active_ch = self._sensors[self._sel_sensor].get("channel", "W")
                _ch_label  = "Sensor Channel:"
            else:
                _active_ch = self._ldr_channel
                _ch_label  = "Channel:"
            lbl = font_sm.render(_ch_label, True, TEXT_DIM())
            surf.blit(lbl, (x, y)); y += lbl.get_height() + 2
            bw2 = (w - 6) // 4
            for ci, ch in enumerate(("W", "R", "G", "B")):
                br2  = pygame.Rect(x + ci * (bw2 + 2), y, bw2, 26)
                col2 = LDR_CH_COLS[ch]
                act2 = (ch == _active_ch)
                # Filled background when active, dark when not
                fill_col = col2 if act2 else PANEL_DEEP()
                text_col = (255, 255, 255) if act2 else col2
                pygame.draw.rect(surf, fill_col, br2, border_radius=3)
                pygame.draw.rect(surf, col2, br2, 1, border_radius=3)
                lt3 = font_sm.render(ch, True, text_col)
                surf.blit(lt3, (br2.centerx - lt3.get_width()//2,
                                br2.centery - lt3.get_height()//2))
                self._tool_btns[f"ch_{ch}"] = br2
            y += 32

        y += 8
        # Select tool
        br = pygame.Rect(x, y, w, 28)
        active = (self._tool == "select")
        pygame.draw.rect(surf, PANEL_DEEP(), br, border_radius=4)
        pygame.draw.rect(surf, PHOSPHOR() if active else BORDER(), br,
                         2 if active else 1, border_radius=4)
        lt2 = font_sm.render("Select / Delete (right-click)", True,
                             PHOSPHOR() if active else TEXT_DIM())
        surf.blit(lt2, (br.x + 6, br.centery - lt2.get_height()//2))
        self._tool_btns["select"] = br
        y += 40

        # Sensor/motor list
        t = font_sm.render(f"Sensors: {len(self._sensors)}  "
                           f"Motors: {len(self._motors)}", True, TEXT_DIM())
        surf.blit(t, (x, y)); y += t.get_height() + 8
        for si, s in enumerate(self._sensors):
            sel_s = (si == self._sel_sensor)
            sc = PHOSPHOR() if sel_s else TEXT_DIM()
            st = font_sm.render(f"  {s['id']}  ({s['x']*1000:.0f},"
                                f"{s['y']*1000:.0f}) mm", True, sc)
            surf.blit(st, (x, y)); y += st.get_height() + 2
            if sel_s:
                ang    = s.get("angle_deg", 0.0)
                flow   = s.get("flow", "seek")
                at = font_sm.render(
                    f"    Angle: {ang:.0f}\u00b0  (drag \u25b2)",
                    True, TEXT_DIM())
                surf.blit(at, (x, y)); y += at.get_height() + 4
                # Flow-style picker: FIELD TRIP ONLY. Skip entirely for VV
                # (and any non-flow game), which sets behaviour via wiring.
                if self._flow_styles:
                    _pick_hdr = ("    Push / Pull (tap):" if self._radial_only
                                 else "    Flow style (tap):")
                    fl = font_sm.render(_pick_hdr, True, PHOSPHOR())
                    surf.blit(fl, (x, y)); y += fl.get_height() + 4

                    # 2x3 glyph grid. Pairs per row: Seek/Flee, Orbit L/R,
                    # Flow-around L/R. Selected glyph highlighted; each tappable.
                    self._flow_pick_rects = {}
                    if self._radial_only:
                        # Push/Pull only: Seek (Pull) and Flee (Push).
                        rows = [("seek", "flee")]
                    else:
                        rows = [("seek", "flee"), ("orbit_l", "orbit_r"),
                                ("around_l", "around_r")]
                    gx0 = x + 8
                    avail = (w - gx0 - 6)
                    cell = min(58, avail // 2)
                    gR = cell // 2 - 6
                    for (lkey, rkey) in rows:
                        for ci, key in enumerate((lkey, rkey)):
                            gx = gx0 + ci * cell
                            sel_g = (key == flow)
                            gcx = gx + cell // 2
                            gcy = y + cell // 2
                            if sel_g:
                                pygame.draw.rect(
                                    surf, PHOSPHOR(),
                                    pygame.Rect(gx + 2, y + 2, cell - 4, cell - 4),
                                    1, border_radius=4)
                            self._draw_flow_glyph(surf, gcx, gcy, gR, key, sel_g)
                            self._flow_pick_rects[key] = pygame.Rect(
                                gx, y, cell, cell)
                        y += cell
                    # label of current style under the grid
                    _, flow_lbl, _p, _t = FLOW_BY_KEY.get(flow, FLOW_BY_KEY["seek"])
                    lt = font_sm.render(f"    {flow_lbl}", True, PHOSPHOR())
                    surf.blit(lt, (x, y)); y += lt.get_height() + 6
                else:
                    # Non-flow games never have an active flow picker; ensure no
                    # stale hit-rects linger from a previous (flow) game.
                    self._flow_pick_rects = {}
        for m in self._motors:
            mt = font_sm.render(f"  {m['id']}  ({m['x']*1000:.0f},"
                                f"{m['y']*1000:.0f}) mm", True, AMBER_DIM())
            surf.blit(mt, (x, y)); y += mt.get_height() + 2

        # Status
        n_remaining = MAX_SENSORS - len(self._sensors)
        if len(self._motors) < 2 and len(self._sensors) < 1:
            hint = "Place sensors and motors"
        elif len(self._motors) < 2:
            hint = "Place motors to finish"
        elif n_remaining > 0:
            hint = f"{self._status[:32]}"
        else:
            hint = self._status[:40]
        st = font_sm.render(hint, True, PHOSPHOR_DIM())
        surf.blit(st, (x, panel_rect.bottom - 60))

        # Done / Cancel buttons
        bw = (w - 8) // 2
        can_done = len(self._motors) >= 2 and len(self._sensors) >= 1
        self._done_btn   = pygame.Rect(x, panel_rect.bottom - 38, bw, 30)
        self._cancel_btn = pygame.Rect(x + bw + 8, panel_rect.bottom - 38,
                                        bw, 30)
        pygame.draw.rect(surf, PHOSPHOR_MID() if can_done else PANEL_DEEP(),
                         self._done_btn, border_radius=4)
        dt = font_md.render("Done", True, (10,18,10) if can_done else TEXT_DIM())
        surf.blit(dt, (self._done_btn.centerx - dt.get_width()//2,
                        self._done_btn.centery - dt.get_height()//2))
        pygame.draw.rect(surf, PANEL_DEEP(), self._cancel_btn, border_radius=4)
        pygame.draw.rect(surf, BORDER(), self._cancel_btn, 1, border_radius=4)
        ct = font_md.render("Cancel", True, TEXT_DIM())
        surf.blit(ct, (self._cancel_btn.centerx - ct.get_width()//2,
                        self._cancel_btn.centery - ct.get_height()//2))

    # ── Event handling ────────────────────────────────────────────────────

    def _handle_canvas_click(self, pos, button, canvas_rect):
        wx, wy = self._s2w(*pos)

        if button == 3:  # right-click = delete
            # Check sensors
            for i, s in enumerate(self._sensors):
                sx2, sy2 = self._w2s(s["x"], s["y"])
                if math.hypot(pos[0]-sx2, pos[1]-sy2) <= max(8, int(
                        SENSOR_RADIUS * self._scale) + 4):
                    removed_id    = s["id"]
                    removed_stype = s.get("type", "IR")
                    self._sensors.pop(i)
                    # Remove all wiring connections for this sensor
                    self._editor._connections = [
                        c for c in self._editor._connections
                        if c.source != removed_id and c.dest != removed_id
                    ]
                    self._update_editor_nodes()
                    self._status = f"Removed {removed_id}"
                    if self._sel_sensor == i:
                        self._sel_sensor = None
                    if len(self._sensors) < MAX_SENSORS:
                        self._tool = f"place_{removed_stype}"
                    return
            # Check motors
            for i, m in enumerate(self._motors):
                sx2, sy2 = self._w2s(m["x"], m["y"])
                if math.hypot(pos[0]-sx2, pos[1]-sy2) <= max(8, int(
                        WHEEL_DIAM_M/2 * self._scale) + 4):
                    # Remove both motors (mirror pair)
                    self._motors.clear()
                    self._update_editor_nodes()
                    self._status = "Motors removed"
                    self._sel_motor = None
                    return
            return

        # Left click — angle handle check works in ANY tool mode
        if (self._angle_handle_rect and
                self._angle_handle_rect.collidepoint(pos) and
                self._sel_sensor is not None):
            self._dragging_angle = True
            return

        # Click on any placed sensor selects it, regardless of active tool
        sensor_r = max(8, int(SENSOR_RADIUS * self._scale) + 4)
        for i, s in enumerate(self._sensors):
            sx2, sy2 = self._w2s(s["x"], s["y"])
            if math.hypot(pos[0]-sx2, pos[1]-sy2) <= sensor_r:
                self._sel_sensor = i
                self._sel_motor  = None
                self._dragging_angle = False
                return

        # Click on any placed motor selects it
        motor_r = max(8, int(WHEEL_DIAM_M/2 * self._scale) + 4)
        for i, m in enumerate(self._motors):
            sx2, sy2 = self._w2s(m["x"], m["y"])
            if math.hypot(pos[0]-sx2, pos[1]-sy2) <= motor_r:
                self._sel_motor  = i
                self._sel_sensor = None
                self._dragging_angle = False
                return

        # Click on empty space — deselect
        if self._tool == "select":
            self._sel_sensor = None
            self._sel_motor  = None
            self._dragging_angle = False

        if self._tool.startswith("place_") and self._tool[6:] in SENSOR_TYPES:
            stype = self._tool[6:]
            if len(self._sensors) >= MAX_SENSORS:
                self._status = f"Maximum {MAX_SENSORS} sensors reached"
                return
            snap = self._nearest_hole(wx, wy)
            if snap is None:
                self._status = "Click on a peg hole (green dots)"
                return
            for s in self._sensors:
                if math.hypot(s["x"]-snap[0], s["y"]-snap[1]) < 0.001:
                    self._status = "A sensor is already at that position"
                    return
            for s in self._sensors:
                min_sep = MIN_SEP.get((stype, s["type"]), 0.012)
                if math.hypot(s["x"]-snap[0], s["y"]-snap[1]) < min_sep:
                    self._status = (f"Too close to {s['id']} — "
                                    f"min {min_sep*1000:.0f}mm apart")
                    return
            zone_id = self._make_zone_id(stype, snap[0])
            channel = self._ldr_channel if stype == "LDR" else "W"
            self._sensors.append({"type": stype, "channel": channel,
                                   "x": snap[0], "y": snap[1],
                                   "id": zone_id, "angle_deg": 0.0,
                                   "policy": "attract", "flow": "seek"})
            self._sel_sensor = len(self._sensors) - 1  # select immediately
            self._sel_motor  = None
            self._update_editor_nodes()
            self._status = f"Placed {zone_id} at ({snap[0]*1000:.0f},{snap[1]*1000:.0f})mm"
            if len(self._sensors) >= MAX_SENSORS:
                self._tool = "motor"

        elif self._tool == "motor":
            if len(self._motors) >= 2:
                self._status = "Remove existing motors first (right-click)"
                return
            snap = self._nearest_snap(wx, wy)
            if snap is None:
                self._status = "Click near a motor snap point (amber ring)"
                return
            mx2, my2 = snap
            # Mirror across the longitudinal (y) axis.
            #
            # The canvas is a TOP-DOWN view with forward = up, and _w2s maps +x
            # to the RIGHT of the screen with no flip. Looking down at the robot
            # from above, screen-right IS the robot's right, so the motor at
            # +mx2 is the LEFT one only if you are facing the robot — which you
            # are not. These two labels were reversed: the motor drawn on the
            # left read "MR" and vice versa.
            #
            # Labels only. The exported data was always correct (y_m = -canvas x
            # puts MR at y_m<0 = robot right), and Field Trip never reads the
            # ids at all — force_to_motors() derives left/right from the force
            # vector and the code only ever COUNTS the motor entries. So this
            # was a display bug with no behavioural effect, as observed.
            self._motors = [
                {"x": -mx2, "y": my2, "id": "ML"},
                {"x":  mx2, "y": my2, "id": "MR"},
            ]
            self._update_editor_nodes()
            self._status = f"Motors placed at ±{mx2*1000:.0f}mm"

    def _handle_panel_click(self, pos):
        # Flow-style picker — tap a glyph to set that style directly.
        # FIELD TRIP ONLY; never active for VV (flow_styles is False there, so
        # _flow_pick_rects is empty, but gate explicitly for clarity).
        if (self._flow_styles and self._sel_sensor is not None
                and self._flow_pick_rects):
            for key, rect in self._flow_pick_rects.items():
                if rect.collidepoint(pos):
                    s = self._sensors[self._sel_sensor]
                    s["flow"] = key
                    s["policy"] = FLOW_BY_KEY[key][2]  # keep legacy in sync
                    return
        for key, br in self._chassis_btns.items():
            if br.collidepoint(pos):
                self._set_chassis(key)
                self._status = f"Chassis: {key}"
                return
        for tid, br in self._tool_btns.items():
            if br.collidepoint(pos):
                if tid.startswith("ch_"):
                    new_ch = tid[3:]
                    # Apply to selected sensor if it's an LDR
                    if (self._sel_sensor is not None and
                            self._sel_sensor < len(self._sensors) and
                            self._sensors[self._sel_sensor].get("type") == "LDR"):
                        self._sensors[self._sel_sensor]["channel"] = new_ch
                        self._update_editor_nodes()
                        self._status = f"Sensor channel: {new_ch}"
                    else:
                        self._ldr_channel = new_ch
                        self._status = f"LDR channel: {new_ch}"
                else:
                    self._tool = tid
                    lbl = (f"Place {tid[6:]}"
                           if tid.startswith("place_") else tid)
                    self._status = f"Placing: {lbl}"
                return
        can_done = len(self._motors) >= 2 and len(self._sensors) >= 1
        if can_done and self._done_btn.collidepoint(pos):
            self._confirmed = True
        elif self._cancel_btn.collidepoint(pos):
            self._cancelled = True

    # ── Main loop ─────────────────────────────────────────────────────────

    def run(self) -> tuple:
        """
        Run the robot builder.
        Returns (robot_config_dict, VehicleConfig) or (None, None).
        """
        pygame.init()
        _T.apply(_T.load_saved_theme())
        if self._window_size:
            ww, wh = self._window_size
        else:
            info = pygame.display.Info()
            ww   = min(1400, info.current_w - 20)
            wh   = min(900,  info.current_h - 60)
        screen = pygame.display.set_mode((ww, wh))
        pygame.display.set_caption("Build Your Own Vehicle — Robot Builder")
        clock = pygame.time.Clock()

        font_sm = pygame.font.SysFont("Courier New", 12)
        font_md = pygame.font.SysFont("Courier New", 14)
        font_hd = pygame.font.SysFont("Courier New", 18, bold=True)

        # 60/40 split: left panel + canvas, right wiring editor
        panel_w  = int(ww * 0.18)
        if self._show_wiring:
            canvas_w = int(ww * 0.42)
            editor_w = ww - panel_w - canvas_w
        else:
            # Split right half: robot canvas | arena preview
            right_w  = ww - panel_w
            canvas_w = right_w // 2
            editor_w = right_w - canvas_w

        panel_rect  = pygame.Rect(0, 0, panel_w, wh)
        canvas_rect = pygame.Rect(panel_w, 0, canvas_w, wh)
        editor_rect = pygame.Rect(panel_w + canvas_w, 0, editor_w, wh)

        if self._show_wiring:
            self._editor.set_panel(editor_rect)

        while True:
            screen.fill(BG())

            # Draw left panel
            self._draw_panel(screen, panel_rect, font_sm, font_md, font_hd)
            # Draw canvas
            self._draw_canvas(screen, canvas_rect, font_sm, font_md)
            # Draw wiring editor or arena preview
            if self._show_wiring:
                self._editor.draw(screen, editor_rect, font_sm, font_md, font_hd)
            elif self._arena_preview and editor_rect.width > 0:
                # Arena preview in place of wiring editor
                pygame.draw.rect(screen, PANEL_DEEP(), editor_rect)
                pygame.draw.rect(screen, BORDER(), editor_rect, 1)
                try:
                    from engine.arena import draw_arena
                    # Aspect-ratio-correct sub-rect
                    aw   = self._arena_preview["width"]
                    ah   = self._arena_preview["height"]
                    avail_w = editor_rect.width  - 16
                    avail_h = editor_rect.height - 32
                    scl  = min(avail_w / aw, avail_h / ah) * 0.92
                    pw   = int(aw * scl)
                    ph   = int(ah * scl)
                    ox   = editor_rect.x + (editor_rect.width  - pw) // 2
                    oy   = editor_rect.y + (editor_rect.height - ph) // 2
                    pad  = pygame.Rect(ox, oy, pw, ph)
                    draw_arena(screen, pad, self._arena_preview,
                               font_sm=font_sm)
                    lbl = font_sm.render("Arena Preview", True, TEXT_DIM())
                    screen.blit(lbl, (editor_rect.x + 8,
                                     editor_rect.bottom - 24))
                except Exception as e:
                    lbl = font_sm.render(f"Preview: {e}", True, TEXT_DIM())
                    screen.blit(lbl, (editor_rect.x + 8, editor_rect.y + 8))

            pygame.display.flip()
            clock.tick(60)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._cancelled = True
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self._cancelled = True

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    pos = event.pos
                    if panel_rect.collidepoint(pos):
                        self._handle_panel_click(pos)
                    elif canvas_rect.collidepoint(pos):
                        self._handle_canvas_click(pos, event.button, canvas_rect)
                    elif self._show_wiring and editor_rect.collidepoint(pos):
                        self._editor.handle_event(event, editor_rect)

                elif event.type == pygame.MOUSEMOTION:
                    if self._dragging_angle and self._sel_sensor is not None:
                        s = self._sensors[self._sel_sensor]
                        sx_c, sy_c = self._w2s(s["x"], s["y"])
                        dx = event.pos[0] - sx_c
                        dy = -(event.pos[1] - sy_c)
                        raw     = math.degrees(math.atan2(dy, dx))
                        snapped = round(raw / 15) * 15
                        # Convert screen angle back to robot frame (0°=forward)
                        s["angle_deg"] = float((snapped - 90) % 360)
                    elif editor_rect.collidepoint(event.pos):
                        self._editor.handle_event(event, editor_rect)

                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button == 1:
                        self._dragging_angle = False
                    if self._show_wiring and editor_rect.collidepoint(event.pos):
                        self._editor.handle_event(event, editor_rect)

            if self._confirmed:
                robot_cfg = self._build_robot_config()
                vehicle_cfg = self._editor.get_config()
                return robot_cfg, vehicle_cfg

            if self._cancelled:
                return None, None

    def _build_robot_config(self) -> dict:
        """Assemble robot description — sensors keyed by slot name."""
        return {
            "chassis":      self._chassis_key,
            "chassis_spec": self._chassis,
            # canvas: x=lateral(right+), y=forward -> json: x_m=forward, y_m=lateral
            # sensor IDs are zone-qualified: "IR·L", "LDR·C1" etc.
            # x_m=forward (canvas y); y_m=lateral, LEFT positive (canvas x is
            # right-positive, so negate). policy+tangential come from the
            # sensor's flow style (single source of truth).
            "sensors": {
                s["id"]: self._export_sensor(s)
                for s in self._sensors
            },
            "motors": {
                # Match the sensor mapping above: y_m is lateral with
                # LEFT positive, canvas x is right-positive, so negate.
                # Without this, motors exported mirror-flipped (ML/MR swapped)
                # relative to sensors and the y_m=left+ convention.
                m["id"]: {"x_m": round(m["y"], 4),
                           "y_m": round(-m["x"], 4)}
                for m in self._motors
            },
        }


# ── Standalone entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    robot_cfg, vehicle_cfg = RobotBuilder().run()
    if robot_cfg:
        import json
        print(json.dumps(robot_cfg, indent=2))
    pygame.quit()
