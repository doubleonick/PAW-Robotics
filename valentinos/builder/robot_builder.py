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

CHASSIS = {
    "rectangle": {
        "label":   "Rectangle  (167 × 94 mm)",
        "type":    "rectangle",
        "width_m":  0.094,
        "length_m": 0.167,
    },
    "octagon": {
        "label":   "Octagon  (70 mm edges)",
        "type":    "octagon",
        "bsquare_m": 0.1690,   # regular octagon, 70mm edges
    },
    "triangle": {
        "label":   "Triangle  (equilateral, inscribed)",
        "type":    "triangle",
        # circumradius matches octagon bounding circle (bsquare=169mm)
        "circum_r_m": 0.1690 * math.sqrt(2) / 2,  # bounding circle
    },
}

PLEG_SPACING_M = 0.008   # 8 mm
PLEG_MARGIN_M  = 0.004   # 4 mm from edge
PLEG_ROWS      = 3        # rows deep from each edge

WHEEL_DIAM_M   = 0.024   # 24 mm standard wheel diameter
SENSOR_RADIUS  = 0.006   # display radius for sensor dot (6 mm)
MOTOR_RADIUS   = 0.010   # display radius for motor snap point

# Sensor colours by type
# Fixed sensor slots matching BraitenBot physical labels
SENSOR_SLOTS = ["RL", "RR", "PL", "PR"]
SENSOR_TYPE  = {"RL": "IR", "RR": "IR", "PL": "LDR", "PR": "LDR"}
SENSOR_COLS  = {"IR": (80, 220, 120), "LDR": (255, 200, 60)}

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
                 window_size: tuple | None = None):
        from games.valentinos.builder.wiring_editor import (
            WiringEditor, VehicleConfig)
        self._VehicleConfig = VehicleConfig
        # Restore from existing robot.json if provided
        if existing_robot:
            initial_chassis = existing_robot.get("chassis", initial_chassis)
        self._chassis_key   = initial_chassis
        self._chassis       = CHASSIS.get(initial_chassis, CHASSIS["rectangle"])
        self._sensors: list[dict] = []
        self._motors:  list[dict] = []

        self._editor = WiringEditor(initial_config,
                                     suppress_done=True)
        self._editor._sensor_names = []
        self._editor._motor_names  = []

        self._tool      = f"place_{SENSOR_SLOTS[0]}"   # start at RL
        self._window_size = window_size   # passed from hub
        self._sel_sensor: int | None = None
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
                for slot, pos in raw_sensors.items():
                    if slot in SENSOR_SLOTS:
                        # robot.json: x_m=forward, y_m=lateral
                        # canvas convention: x=lateral(right+), y=forward
                        self._sensors.append({
                            "id":   slot,
                            "type": SENSOR_TYPE[slot],
                            "x":    pos.get("y_m", 0.0),
                            "y":    pos.get("x_m", 0.0),
                        })
            raw_motors = existing_robot.get("motors", {})
            if isinstance(raw_motors, dict):
                for mid, pos in raw_motors.items():
                    self._motors.append({
                        "id": mid,
                        "x":  pos.get("y_m", 0.0),
                        "y":  pos.get("x_m", 0.0),
                    })
            # Advance tool past already-placed sensors
            placed = {s["id"] for s in self._sensors}
            for slot in SENSOR_SLOTS:
                if slot not in placed:
                    self._tool = f"place_{slot}"
                    break
            else:
                self._tool = "motor"
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
        self._tool = f"place_{SENSOR_SLOTS[0]}"
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

    def _update_editor_nodes(self):
        placed  = {s["id"] for s in self._sensors}
        s_names = [sl for sl in SENSOR_SLOTS if sl in placed]
        m_names = ["FL", "FR"] if self._motors else []
        self._editor._sensor_names = s_names
        self._editor._motor_names  = m_names
        if self._editor._rect:
            self._editor.set_panel(self._editor._rect)

    # ── World ↔ screen coordinate conversion ─────────────────────────────

    def _w2s(self, wx, wy) -> tuple[int,int]:
        ox, oy = self._origin
        # y-axis: world +y = forward = up on screen
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
        for si, s in enumerate(self._sensors):
            sx2, sy2 = self._w2s(s["x"], s["y"])
            sr2 = max(4, int(SENSOR_RADIUS * self._scale))
            sel = (si == self._sel_sensor)
            col = SENSOR_COLS.get(s.get("type","IR"), PHOSPHOR())
            if sel:
                pygame.draw.circle(surf, col, (sx2, sy2), sr2 + 3, 2)
            pygame.draw.circle(surf, col, (sx2, sy2), sr2)
            t = font_sm.render(s["id"], True, (10, 18, 10))
            surf.blit(t, (sx2 - t.get_width()//2, sy2 - t.get_height()//2))

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
        placed_ids = {s["id"] for s in self._sensors}
        # Always show all slot buttons — placed ones shown dimmer
        slot_tools = []
        for slot in SENSOR_SLOTS:
            stype     = SENSOR_TYPE[slot]
            is_placed = slot in placed_ids
            prefix    = "[+]" if not is_placed else "[ ]"
            slot_tools.append((f"place_{slot}",
                                f"{prefix} {slot} ({stype})",
                                SENSOR_COLS[stype], is_placed))
        slot_tools.append(("motor", "Place Motors", AMBER(), False))
        for tid, tlabel, tcol, is_placed in slot_tools:
            br     = pygame.Rect(x, y, w, 28)
            active = (self._tool == tid)
            bg     = PANEL_DEEP()
            bc     = tcol if active else (BORDER_DIM() if is_placed else BORDER())
            bw     = 2 if active else 1
            tc     = (tcol if active
                      else TEXT_DIM() if is_placed else TEXT())
            pygame.draw.rect(surf, bg, br, border_radius=4)
            pygame.draw.rect(surf, bc, br, bw, border_radius=4)
            lt2 = font_sm.render(tlabel, True, tc)
            surf.blit(lt2, (br.x + 6, br.centery - lt2.get_height()//2))
            self._tool_btns[tid] = br
            y += 34

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
        for s in self._sensors:
            st = font_sm.render(f"  {s['id']}  ({s['x']*1000:.0f},"
                                f"{s['y']*1000:.0f}) mm", True, TEXT_DIM())
            surf.blit(st, (x, y)); y += st.get_height() + 2
        for m in self._motors:
            mt = font_sm.render(f"  {m['id']}  ({m['x']*1000:.0f},"
                                f"{m['y']*1000:.0f}) mm", True, AMBER_DIM())
            surf.blit(mt, (x, y)); y += mt.get_height() + 2

        # Status
        placed = {s["id"] for s in self._sensors}
        remaining = [sl for sl in SENSOR_SLOTS if sl not in placed]
        if remaining:
            hint = f"Still needed: {', '.join(remaining)}"
        elif len(self._motors) < 2:
            hint = "Place motors to finish"
        else:
            hint = self._status[:40]
        st = font_sm.render(hint, True, PHOSPHOR_DIM())
        surf.blit(st, (x, panel_rect.bottom - 60))

        # Done / Cancel buttons
        bw = (w - 8) // 2
        can_done = len(self._motors) >= 2
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
                    removed_id = s["id"]
                    self._sensors.pop(i)
                    self._update_editor_nodes()
                    self._status = f"Removed {removed_id}"
                    if self._sel_sensor == i:
                        self._sel_sensor = None
                    self._tool = f"place_{removed_id}"
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

        # Left click
        if self._tool == "select":
            self._sel_sensor = None
            self._sel_motor  = None
            for i, s in enumerate(self._sensors):
                sx2, sy2 = self._w2s(s["x"], s["y"])
                if math.hypot(pos[0]-sx2, pos[1]-sy2) <= max(8, int(
                        SENSOR_RADIUS * self._scale) + 4):
                    self._sel_sensor = i
                    return
            for i, m in enumerate(self._motors):
                sx2, sy2 = self._w2s(m["x"], m["y"])
                if math.hypot(pos[0]-sx2, pos[1]-sy2) <= max(8, int(
                        WHEEL_DIAM_M/2 * self._scale) + 4):
                    self._sel_motor = i
                    return


        elif self._tool.startswith("place_"):
            slot  = self._tool[6:]
            stype = SENSOR_TYPE.get(slot, "IR")
            snap  = self._nearest_hole(wx, wy)
            if snap is None:
                self._status = "Click on a peg hole (green dots)"
                return
            if any(s["id"] == slot for s in self._sensors):
                self._status = f"{slot} already placed — remove it first"
                return
            for s in self._sensors:
                if math.hypot(s["x"]-snap[0], s["y"]-snap[1]) < 0.001:
                    self._status = "A sensor is already at that position"
                    return
            for s in self._sensors:
                min_sep = MIN_SEP.get(
                    (stype, SENSOR_TYPE.get(s["id"], "IR")), 0.012)
                if math.hypot(s["x"]-snap[0], s["y"]-snap[1]) < min_sep:
                    self._status = (f"Too close to {s['id']} — "
                                    f"min {min_sep*1000:.0f}mm apart")
                    return
            self._sensors.append({"type": stype, "x": snap[0],
                                   "y": snap[1], "id": slot})
            self._update_editor_nodes()
            self._status = (f"Placed {slot} at "
                            f"({snap[0]*1000:.0f},{snap[1]*1000:.0f})mm")
            placed = {s["id"] for s in self._sensors}
            for next_slot in SENSOR_SLOTS:
                if next_slot not in placed:
                    self._tool = f"place_{next_slot}"
                    break
            else:
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
            # Mirror across longitudinal (y) axis
            self._motors = [
                {"x":  mx2, "y": my2, "id": "MR"},
                {"x": -mx2, "y": my2, "id": "ML"},
            ]
            self._update_editor_nodes()
            self._status = f"Motors placed at ±{mx2*1000:.0f}mm"

    def _handle_panel_click(self, pos):
        for key, br in self._chassis_btns.items():
            if br.collidepoint(pos):
                self._set_chassis(key)
                self._status = f"Chassis: {key}"
                return
        for tid, br in self._tool_btns.items():
            if br.collidepoint(pos):
                self._tool = tid
                lbl = (tid[6:] + " sensor"
                       if tid.startswith("place_") else tid)
                self._status = f"Placing: {lbl}"
                return
        can_done = len(self._motors) >= 2
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
        canvas_w = int(ww * 0.42)
        editor_w = ww - panel_w - canvas_w

        panel_rect  = pygame.Rect(0, 0, panel_w, wh)
        canvas_rect = pygame.Rect(panel_w, 0, canvas_w, wh)
        editor_rect = pygame.Rect(panel_w + canvas_w, 0, editor_w, wh)

        self._editor.set_panel(editor_rect)

        while True:
            screen.fill(BG())

            # Draw left panel
            self._draw_panel(screen, panel_rect, font_sm, font_md, font_hd)
            # Draw canvas
            self._draw_canvas(screen, canvas_rect, font_sm, font_md)
            # Draw wiring editor
            self._editor.draw(screen, editor_rect, font_sm, font_md, font_hd)

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
                    elif editor_rect.collidepoint(pos):
                        self._editor.handle_event(event, editor_rect)

                elif event.type in (pygame.MOUSEBUTTONUP,
                                    pygame.MOUSEMOTION):
                    if editor_rect.collidepoint(event.pos):
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
            "sensors": {
                s["id"]: {"x_m": round(s["y"], 4),
                           "y_m": round(s["x"], 4),
                           "angle_deg": 0.0}
                for s in self._sensors
            },
            "motors": {
                m["id"]: {"x_m": round(m["y"], 4),
                           "y_m": round(m["x"], 4)}
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
