"""
valentinos/builder/wiring_inspector.py
---------------------------------------
Read-only wiring inspector for the VV intro demo sequence.

Renders inside the hub's controls panel — NOT a separate window.
The arena continues running on the right while this is displayed.

Layout (controls panel, top to bottom):
  ┌─────────────────────────────┐
  │  Vehicle title + canonical  │   ~40px
  │  name                       │
  ├─────────────────────────────┤
  │                             │
  │   Wiring diagram            │   ~60% of remaining height
  │   (full board, greyed out   │
  │    unused nodes, live       │
  │    meter bars)              │
  │                             │
  └─────────────────────────────┘

The narrative panel (lower half) is drawn by the hub as normal
and carries PAW-Bot's signal-flow commentary.
"""

from __future__ import annotations
import math
import pygame
from typing import Optional

from valentinos.engine.vehicle import VehicleConfig
from valentinos.engine.signals import WIRE_WEIGHT, Connection


# ── Colour helpers ────────────────────────────────────────────────────────────

def _T():
    import engine.theme as _t
    return _t


def _tc(attr, fallback):
    try:
        return getattr(_T(), attr)
    except Exception:
        return fallback


# ── Node definitions (mirrors wiring_editor layout, scaled to panel) ──────────

# All coordinates are in a normalised 0..1 space, then scaled to the
# available rect at draw time.  This makes the inspector resolution-independent.

# X positions (0=left/front of board, 1=right/rear)
_X_SENSOR  = 0.08
_X_METER   = 0.20
_X_EI      = 0.38
_X_NEURON  = 0.55
_X_NT      = 0.70
_X_MOTOR_F = 0.88
_X_MOTOR_B = 0.94

# Y positions (0=top, 1=bottom)
_Y_TOP  = 0.04
_Y_BOT  = 0.96
_Y_MID  = 0.50

# Sensor Y positions — mirrors wiring editor layout exactly:
#   top    = right side of robot (PR, RR)
#   bottom = left  side of robot (PL, RL)
_PR_Y  = _Y_TOP + 0.04          # PR — top corner  (right side of robot)
_RR_Y  = _Y_TOP + 0.22          # RR — inboard from PR
_RL_Y  = _Y_BOT - 0.22          # RL — inboard from PL
_PL_Y  = _Y_BOT - 0.04          # PL — bottom corner (left side of robot)

# Motor Y positions — same convention: FR top, FL bottom
_FR_Y  = _Y_TOP + 0.22          # FR/BR — top-right (right side of robot)
_FL_Y  = _Y_BOT - 0.22          # FL/BL — bottom-right (left side of robot)

# Neuron Y positions — 6 neurons evenly spaced
def _neuron_y(idx: int) -> float:
    span = _Y_BOT - _Y_TOP - 0.04
    step = span / 7
    return _Y_TOP + 0.02 + step * idx


_NODE_DEFS: list[dict] = []

def _build_nodes():
    global _NODE_DEFS
    nodes = []

    def add(name, role, kind, nx, ny):
        nodes.append({"name": name, "role": role, "kind": kind,
                       "nx": nx, "ny": ny})

    # Sensors
    add("PL", "sensor", "source", _X_SENSOR, _PL_Y)
    add("RL", "sensor", "source", _X_SENSOR, _RL_Y)
    add("RR", "sensor", "source", _X_SENSOR, _RR_Y)
    add("PR", "sensor", "source", _X_SENSOR, _PR_Y)

    # Meters
    add("M3", "meter",  "dest",   _X_METER,  _Y_MID - 0.18)
    add("M2", "meter",  "dest",   _X_METER,  _Y_MID)
    add("M1", "meter",  "dest",   _X_METER,  _Y_MID + 0.18)

    # Neurons E inputs, body, N/T outputs
    for i in range(1, 7):
        ny = _neuron_y(i)
        add(f"E{i}", "neuron_E", "dest",   _X_EI,     ny - 0.04)
        add(f"I{i}", "neuron_I", "dest",   _X_EI,     ny + 0.04)
        add(f"N{i}", "neuron_N", "source", _X_NT,     ny - 0.04)
        if i <= 4:
            add(f"T{i}", "neuron_T", "source", _X_NT, ny + 0.04)

    # Motors
    add("FR", "motor", "dest", _X_MOTOR_F, _FR_Y)
    add("BR", "motor", "dest", _X_MOTOR_B, _FR_Y)
    add("FL", "motor", "dest", _X_MOTOR_F, _FL_Y)
    add("BL", "motor", "dest", _X_MOTOR_B, _FL_Y)

    _NODE_DEFS = nodes


_build_nodes()

# Wire colours matching wiring editor
_WIRE_COLS = {
    "blue":  (80,  130, 220),
    "green": (60,  200,  80),
    "red":   (220,  60,  60),
}

# Role colours (active / dimmed)
_ROLE_ACTIVE = {
    "sensor":   (255, 160,  40),
    "meter":    (160, 160, 160),
    "neuron_E": ( 60, 200,  80),
    "neuron_I": (200,  60,  60),
    "neuron_N": ( 60, 200, 200),
    "neuron_T": (220, 200,  40),
    "motor":    (200, 200, 200),
    "neuron_body": (60, 120, 160),
}
_ROLE_DIM = {k: tuple(c // 4 for c in v) for k, v in _ROLE_ACTIVE.items()}


class WiringInspector:
    """
    Stateless renderer — call draw() each frame.
    Does not own a pygame window or event loop.
    """

    def __init__(self, config: VehicleConfig, vehicle_name: str):
        self.config       = config
        self.vehicle_name = vehicle_name
        # Pre-compute which node names are used in this config
        self._used: set[str] = set()
        for c in config.connections:
            self._used.add(c.source)
            self._used.add(c.dest)

    def draw(self, surf: pygame.Surface, rect: pygame.Rect,
             signals: Optional[dict] = None,
             font_sm: Optional[pygame.font.Font] = None,
             font_md: Optional[pygame.font.Font] = None) -> None:
        """
        Draw the wiring inspector into `rect`.

        signals : dict mapping node name → float (from _Sim.signal_snapshot())
                  If None, meters stay dim.
        """
        T    = _T()
        sigs = signals or {}

        # Scale helpers
        def sx(nx): return int(rect.x + nx * rect.width)
        def sy(ny): return int(rect.y + ny * rect.height)

        # Node pixel positions
        node_pos: dict[str, tuple[int, int]] = {}
        for nd in _NODE_DEFS:
            node_pos[nd["name"]] = (sx(nd["nx"]), sy(nd["ny"]))

        # ── Draw wires ────────────────────────────────────────────────────
        for conn in self.config.connections:
            p1 = node_pos.get(conn.source)
            p2 = node_pos.get(conn.dest)
            if not p1 or not p2:
                continue
            col = _WIRE_COLS.get(conn.color, _WIRE_COLS["blue"])
            wid = {1: 1, 2: 2, 3: 3}.get(WIRE_WEIGHT[conn.color], 1)
            self._bezier(surf, p1, p2, col, wid)

        # ── Draw nodes ────────────────────────────────────────────────────
        for nd in _NODE_DEFS:
            name   = nd["name"]
            role   = nd["role"]
            px, py = node_pos[name]
            active = name in self._used
            col    = _ROLE_ACTIVE.get(role, (120,120,120)) if active \
                     else _ROLE_DIM.get(role, (30,30,30))

            # Node shape by role
            if role == "sensor":
                pygame.draw.rect(surf, col,
                                 pygame.Rect(px-6, py-4, 12, 8),
                                 border_radius=2)
            elif role in ("neuron_E", "neuron_I", "neuron_N", "neuron_T"):
                pygame.draw.circle(surf, col, (px, py), 5)
            elif role == "motor":
                pygame.draw.polygon(surf, col,
                                    [(px-7,py-5),(px+5,py),(px-7,py+5)])
            elif role == "meter":
                # Meter: draw 10-segment LED bar vertically
                self._draw_meter_bar(surf, px, py, name, sigs,
                                     active, col)
                # Label above
                if font_sm:
                    lt = font_sm.render(name, True, col)
                    surf.blit(lt, (px - lt.get_width()//2, py - 52))
                continue   # skip generic label below

            # Label
            if font_sm and role != "meter":
                lt = font_sm.render(name, True, col)
                surf.blit(lt, (px - lt.get_width()//2,
                               py - lt.get_height() - 3))

        # ── Neuron bodies (triangles in centre) ────────────────────────────
        for i in range(1, 7):
            ny   = _neuron_y(i)
            bx   = sx(_X_NEURON)
            by   = sy(ny)
            used = (f"E{i}" in self._used or f"I{i}" in self._used or
                    f"N{i}" in self._used or f"T{i}" in self._used)
            col  = _ROLE_ACTIVE["neuron_body"] if used \
                   else _ROLE_DIM["neuron_body"]
            pygame.draw.polygon(surf, col,
                                 [(bx-10, by-8), (bx+10, by), (bx-10, by+8)])
            pygame.draw.polygon(surf, tuple(min(255,c+40) for c in col),
                                 [(bx-10, by-8), (bx+10, by), (bx-10, by+8)],
                                 1)
            # N index label
            if font_sm:
                lbl = font_sm.render(f"N{i}", True, col)
                surf.blit(lbl, (bx - lbl.get_width()//2,
                                by - lbl.get_height() - 3))

            # Live N output value
            if used and sigs and font_sm:
                val = sigs.get(f"N{i}", 0.0)
                vt  = font_sm.render(f"{val:.2f}", True,
                                     _ROLE_ACTIVE["neuron_N"])
                surf.blit(vt, (bx - vt.get_width()//2, by + 10))

    def _draw_meter_bar(self, surf, px, py, name, sigs, active, col):
        """10-segment vertical LED bar for a meter node."""
        SEGMENTS = 10
        seg_w, seg_h, seg_gap = 8, 5, 1
        bar_h = SEGMENTS * (seg_h + seg_gap) - seg_gap
        bx    = px - seg_w // 2
        by    = py - bar_h // 2

        # Compute meter value from wired sources
        val = 0.0
        if sigs:
            for c in self.config.connections:
                if c.dest == name:
                    val += sigs.get(c.source, 0.0) * WIRE_WEIGHT[c.color]
        val = max(0.0, min(1.0, val))
        lit = int(val * SEGMENTS)

        LIT_COLS = {"M1": (220, 50, 50), "M2": (240,240,240), "M3": (220,50,50)}
        DIM_COLS = {"M1": (60, 10, 10),  "M2": (60, 60, 60),  "M3": (60,10,10)}
        lit_col  = LIT_COLS.get(name, (200,200,200)) if active else (30,30,30)
        dim_col  = DIM_COLS.get(name, (40, 40, 40))  if active else (15,15,15)

        for seg in range(SEGMENTS):
            sy_ = by + bar_h - seg * (seg_h + seg_gap) - seg_h
            c   = lit_col if seg < lit else dim_col
            pygame.draw.rect(surf, c,
                             pygame.Rect(bx, sy_, seg_w, seg_h),
                             border_radius=1)

    @staticmethod
    def _bezier(surf, p1, p2, col, width=1):
        """Draw a cubic bezier wire between p1 and p2."""
        dx   = abs(p2[0] - p1[0]) * 0.45
        cp1  = (p1[0] + dx, p1[1])
        cp2  = (p2[0] - dx, p2[1])
        pts  = []
        for t in range(21):
            tt  = t / 20
            mt  = 1 - tt
            x   = (mt**3*p1[0] + 3*mt**2*tt*cp1[0] +
                   3*mt*tt**2*cp2[0] + tt**3*p2[0])
            y   = (mt**3*p1[1] + 3*mt**2*tt*cp1[1] +
                   3*mt*tt**2*cp2[1] + tt**3*p2[1])
            pts.append((int(x), int(y)))
        if len(pts) > 1:
            pygame.draw.lines(surf, col, False, pts, width)
