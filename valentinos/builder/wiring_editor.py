"""
valentinos/builder/wiring_editor.py
------------------------------------
Interactive wiring diagram editor for Valentino's Vehicles.

Layout (left → right = signal flow):
  Column 0 : Sensor banks      (RL, RR, PL, PR)  — 2 pins each
  Column 1 : Meter banks       (M1-M4)            — 1 pin each
  Column 2 : Neuron E/I inputs (E1-E6, I1-I6)    — 4 pins each
  Column 3 : Neuron bodies     (bias trimpot)
  Column 4 : Neuron N/T outputs(N1-N6, T1-T4)    — 1 pin each
  Column 5 : Motor banks       (FL/BL, FR/BR)     — 4 pins each

Works in any pygame.Rect — standalone (full window) or embedded (panel).
All layout is computed as fractions of the given rect; no absolute coords.

Interaction:
  Left-click a source bank  → select it (highlighted border)
  Left-click a dest bank    → create wire if source selected
  Left-click a wire         → cycle color: blue→green→red→blue
  Right-click a wire        → remove it
  Drag neuron trimpot       → adjust bias -4..+4
  Done button / Enter       → confirm
  Escape                    → cancel
"""

from __future__ import annotations
import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import pygame
from valentinos.engine.signals import Connection
from valentinos.engine.vehicle import VehicleConfig

# ── Palette ────────────────────────────────────────────────────────────────────

def _T():
    try:
        import engine.theme as _t
        return _t
    except Exception:
        pass
    class _F:
        BG=(10,12,10); PANEL=(14,18,14); PANEL_DEEP=(8,10,8)
        BORDER=(30,58,30); TEXT=(160,220,160); TEXT_DIM=(70,110,70)
        WHITE_GREEN=(220,255,220); PHOSPHOR=(51,255,87)
        PHOSPHOR_MID=(30,160,50); AMBER=(255,149,0); AMBER_DIM=(80,46,0)
        PHOSPHOR_DIM=(20,90,30); RED_PH=(255,60,60)
    return _F()

def BG():          return _T().BG
def PANEL():       return _T().PANEL
def PANEL_DEEP():  return _T().PANEL_DEEP
def BORDER():      return _T().BORDER
def BORDER_DIM():  return _T().BORDER_DIM
def TEXT():        return _T().TEXT
def TEXT_DIM():    return _T().TEXT_DIM
def TEXT_BRIGHT(): return getattr(_T(), "WHITE_GREEN", _T().PHOSPHOR)
def PHOSPHOR():    return _T().PHOSPHOR
def PHOSPHOR_MID():return _T().PHOSPHOR_MID
def PHOSPHOR_DIM():return _T().PHOSPHOR_DIM
def AMBER():       return _T().AMBER
def AMBER_DIM():   return _T().AMBER_DIM

CYAN       = ( 60, 230, 230)
YELLOW     = (255, 230,  60)
WHITE      = (240, 240, 240)
GREY       = (100, 110, 100)
RED_NODE   = (220,  60,  60)
GREEN_NODE = ( 60, 200,  80)

WIRE_COLORS = {"blue":  ( 80, 140, 255),
               "green": ( 60, 210,  80),
               "red":   (220,  60,  60)}
WIRE_WIDTHS = {"blue": 2, "green": 3, "red": 4}
WIRE_CYCLE  = ["blue", "green", "red"]

BANK_COLOR = {
    "sensor":   AMBER(),
    "ldr":      AMBER(),
    "neuron_E": GREEN_NODE,
    "neuron_I": RED_NODE,
    "neuron_N": CYAN,
    "neuron_T": YELLOW,
    "motor":    WHITE,
    "meter":    GREY,
}
PIN_COLOR = {
    "sensor":   (180, 100,   0),
    "ldr":      (180, 100,   0),
    "neuron_E": ( 30, 130,  40),
    "neuron_I": (140,  30,  30),
    "neuron_N": ( 30, 160, 160),
    "neuron_T": (180, 160,  20),
    "motor":    (160, 160, 160),
    "meter":    ( 70,  80,  70),
}

# ── Bank geometry ──────────────────────────────────────────────────────────────

PIN_R    = 3
PIN_STEP = 9
PAD      = 5

def _bank_rect(pins: int, cx: int, cy: int,
               horizontal: bool = False) -> pygame.Rect:
    if horizontal:
        w = pins * PIN_STEP + PAD * 2
        h = PIN_R * 2 + PAD * 2
    else:
        w = PIN_R * 2 + PAD * 2
        h = pins * PIN_STEP + PAD * 2
    return pygame.Rect(cx - w // 2, cy - h // 2, w, h)


def _pin_positions(rect: pygame.Rect, pins: int,
                   horizontal: bool = False) -> list[tuple[int,int]]:
    pts = []
    if horizontal:
        y  = rect.centery
        x0 = rect.x + PAD + PIN_R
        for i in range(pins):
            pts.append((x0 + i * PIN_STEP, y))
    else:
        x  = rect.centerx
        y0 = rect.y + PAD + PIN_R
        for i in range(pins):
            pts.append((x, y0 + i * PIN_STEP))
    return pts


# ── Layout fractions ───────────────────────────────────────────────────────────
# All positions expressed as fractions of rect dimensions.
# Orientation: TOP→BOTTOM signal flow.
#   Sensors at top, neurons in middle, motors at bottom.
#   Sensor/motor LANES run left→right.

# Row Y fractions (signal flow top→bottom)
_FY_SENSOR = 0.10   # sensor bank row
_FY_METER  = 0.18   # meter row
_FY_EI     = 0.29   # neuron E/I input row
_FY_NEURON = 0.50   # neuron body row
_FY_NT     = 0.70   # neuron N/T output row
_FY_MF     = 0.83   # motor Forward row
_FY_MB     = 0.93   # motor Backward row

# Lane X fractions (left→right within usable area)
_FX_LEFT  = 0.08
_FX_RIGHT = 0.95
_FX_MID   = (_FX_LEFT + _FX_RIGHT) / 2

# Default 4 sensor lanes (evenly spread left→right)
_FX_SENSOR_LANES = [
    _FX_LEFT,
    _FX_LEFT + (_FX_RIGHT - _FX_LEFT) * 0.33,
    _FX_LEFT + (_FX_RIGHT - _FX_LEFT) * 0.67,
    _FX_RIGHT,
]
# Default 2 motor lanes
_FX_MOTOR_LANES = [
    _FX_LEFT + (_FX_RIGHT - _FX_LEFT) * 0.33,
    _FX_LEFT + (_FX_RIGHT - _FX_LEFT) * 0.67,
]

# Neuron lanes: 6 spread across full width
def _neuron_fx(i: int) -> float:  # i in 1..6
    spacing = (_FX_RIGHT - _FX_LEFT) / 7
    return _FX_LEFT + spacing * i


def _build_banks_for_rect(rect: pygame.Rect,
                           sensor_names: list[str] | None = None,
                           motor_names:  list[str] | None = None
                           ) -> list[dict]:
    """
    Build the complete bank list within rect.
    Orientation: TOP→BOTTOM signal flow.
      Sensors top row, neurons middle, motors bottom row.
      Sensor/motor lanes spread left→right.
    sensor_names: e.g. ["RL","RR","PL","PR"]
    motor_names:  e.g. ["FL","FR"]  (full node names)
    """
    if sensor_names is None:
        sensor_names = ["RL", "RR", "PL", "PR"]
    if motor_names is None:
        motor_names  = ["FL", "FR"]

    ox, oy, pw, ph = rect.x, rect.y, rect.width, rect.height
    def fx(f): return ox + int(pw * f)
    def fy(f): return oy + int(ph * f)

    banks = []
    def add(name, kind, role, pins, cx, cy, horiz=False):
        r = _bank_rect(pins, cx, cy, horiz)
        banks.append({"name": name, "kind": kind, "role": role,
                      "pins": pins, "cx": cx, "cy": cy,
                      "rect": r, "horiz": horiz})

    # ── Sensors — top row, lanes left→right ───────────────────────────────
    n_s = len(sensor_names)
    lanes = (list(_FX_SENSOR_LANES) if n_s <= 4
             else [_FX_LEFT + (_FX_RIGHT - _FX_LEFT)*i/max(1,n_s-1)
                   for i in range(n_s)])
    for i, name in enumerate(sensor_names):
        cx = fx(lanes[i] if i < len(lanes) else _FX_RIGHT)
        stype = "ldr" if name.startswith("P") else "sensor"
        add(name, stype, "source", 2, cx, fy(_FY_SENSOR))

    # ── Meters — row below sensors, same lanes ────────────────────────────
    for i in range(1, 5):
        cx = fx(lanes[i-1] if i-1 < len(lanes) else _FX_RIGHT)
        add(f"M{i}", "meter", "dest", 1, cx, fy(_FY_METER), horiz=True)

    # ── Neuron inputs (E/I) — fixed Y row, 6 lanes ───────────────────────
    for i in range(1, 7):
        cx = fx(_neuron_fx(i))
        add(f"E{i}", "neuron_E", "dest", 4, cx - 17, fy(_FY_EI), horiz=True)
        add(f"I{i}", "neuron_I", "dest", 4, cx + 17, fy(_FY_EI), horiz=True)

    # ── Neuron outputs (N/T) ──────────────────────────────────────────────
    for i in range(1, 7):
        cx = fx(_neuron_fx(i))
        add(f"N{i}", "neuron_N", "source", 1, cx - 17, fy(_FY_NT))
        if i <= 4:
            add(f"T{i}", "neuron_T", "source", 1, cx + 17, fy(_FY_NT))

    # ── Motors — bottom rows, lanes left→right ────────────────────────────
    n_m = len(motor_names)
    mlanes = (list(_FX_MOTOR_LANES) if n_m <= 2
              else [_FX_LEFT + (_FX_RIGHT-_FX_LEFT)*i/max(1,n_m-1)
                    for i in range(n_m)])
    for i, name in enumerate(motor_names):
        cx   = fx(mlanes[i] if i < len(mlanes) else _FX_RIGHT)
        back = "B" + name[1:] if len(name) >= 2 else "B" + name
        add(name, "motor", "dest", 4, cx, fy(_FY_MF))
        add(back, "motor", "dest", 4, cx, fy(_FY_MB))

    return banks


# ── WiringEditor ───────────────────────────────────────────────────────────────

class WiringEditor:
    """
    Wiring editor that works in any pygame.Rect.

    Standalone use:   result = WiringEditor(cfg).run()
    Embedded use:     editor.set_panel(rect)
                      editor.draw(surf, rect, font_sm, font_md, font_hd)
                      editor.handle_event(event, rect)
    """

    def __init__(self, initial_config: VehicleConfig | None = None,
                 title: str = "Vehicle Wiring — Valentino's Vehicles",
                 sensor_names: list | None = None,
                 motor_names:  list | None = None,
                 suppress_done: bool = False):
        self._title = title
        self._suppress_done = suppress_done

        cfg = initial_config or VehicleConfig()
        self._connections: list[Connection] = list(cfg.connections)
        self._biases: dict[str, float]      = dict(cfg.neuron_biases)
        self._gain:   float                 = cfg.gain

        self._sensor_names: list = (list(sensor_names) if sensor_names
                                    else ["RL", "RR", "PL", "PR"])
        self._motor_names:  list = (list(motor_names)  if motor_names
                                    else ["FL", "FR"])

        self._rect: pygame.Rect | None = None
        self._banks: list[dict]        = []
        self._bmap:  dict[str, dict]   = {}

        self._sel_source:      str | None = None
        self._hover_wire:      int | None = None
        self._dragging_neuron: int | None = None
        self._drag_start_pos:  int        = 0
        self._drag_start_bias: float      = 0.0
        self._confirmed: bool = False
        self._cancelled: bool = False
        self._done_btn:  pygame.Rect | None = None
        self._gain_bar:  pygame.Rect | None = None
        self._status = "Click a source bank to begin wiring"

    # ── Public API ────────────────────────────────────────────────────────

    def set_panel(self, rect: pygame.Rect) -> None:
        """Set/update the rect this editor draws and responds in."""
        self._rect  = rect
        self._banks = _build_banks_for_rect(
            rect, self._sensor_names, self._motor_names)
        self._bmap  = {b["name"]: b for b in self._banks}

    def draw(self, surf: pygame.Surface, rect: pygame.Rect,
             font_sm=None, font_md=None, font_hd=None) -> None:
        if rect != self._rect:
            self.set_panel(rect)
        fs = font_sm or self._font(11)
        fm = font_md or self._font(13)
        fh = font_hd or self._font(16)
        mx, my = pygame.mouse.get_pos()
        self._hover_wire = self._wire_near(mx, my)
        surf.set_clip(rect)
        pygame.draw.rect(surf, BG(), rect)
        self._draw_columns(surf, fs, rect)
        self._draw_neuron_bodies(surf, fs, rect)
        self._draw_wires(surf)
        self._draw_banks(surf, fs, rect)
        self._draw_pending(surf, mx, my)
        self._draw_ui(surf, fm, fh, rect)
        surf.set_clip(None)

    def handle_event(self, event: pygame.event.Event,
                     rect: pygame.Rect) -> bool:
        if rect != self._rect:
            self.set_panel(rect)
        if event.type == pygame.MOUSEBUTTONDOWN:
            if not rect.collidepoint(event.pos):
                return False
            if event.button == 1:
                self._left_click(event.pos, rect)
            elif event.button == 3:
                self._right_click(event.pos)
            return True
        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self._dragging_neuron = None
            return False
        elif event.type == pygame.MOUSEMOTION:
            if self._dragging_neuron is not None:
                # Drag horizontally for horizontal trimpot
                delta = event.pos[0] - self._drag_start_pos
                key   = f"N{self._dragging_neuron}"
                new   = self._drag_start_bias + delta * 0.06
                self._biases[key] = max(-4.0, min(4.0, new))
                return True
            return False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._sel_source = None
            elif event.key == pygame.K_RETURN:
                if not self._suppress_done:
                    self._confirmed = True
            return False
        return False

    @property
    def is_confirmed(self) -> bool:
        return self._confirmed

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def get_config(self) -> VehicleConfig:
        return self._build_config()

    def current_text(self) -> str:
        return ""

    @property
    def is_done(self) -> bool:
        return self._confirmed

    @property
    def is_last_page(self) -> bool:
        return False

    def update_sensors(self, sensor_names: list[str]) -> None:
        self._sensor_names = sensor_names
        if self._rect:
            self.set_panel(self._rect)

    def update_motors(self, motor_names: list[str]) -> None:
        self._motor_names = motor_names
        if self._rect:
            self.set_panel(self._rect)

    # ── Standalone run() ──────────────────────────────────────────────────

    def run(self) -> VehicleConfig | None:
        pygame.init()
        import engine.theme as _Te; _Te.apply(_Te.load_saved_theme())
        info = pygame.display.Info()
        taskbar = {"win32": 48, "darwin": 50}.get(sys.platform, 52)
        ww = max(900, info.current_w - 16)
        wh = max(600, info.current_h - taskbar - 16)
        screen = pygame.display.set_mode((ww, wh))
        pygame.display.set_caption(self._title)
        clock   = pygame.time.Clock()
        fs = self._font(13); fm = self._font(15); fh = self._font(19)
        rect = pygame.Rect(0, 0, ww, wh)
        self.set_panel(rect)
        result = None

        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._cancelled = True
                else:
                    self.handle_event(event, rect)

            if self._confirmed:
                result = self._build_config(); break
            if self._cancelled:
                break

            self.draw(screen, rect, fs, fm, fh)
            pygame.display.flip()
            clock.tick(60)

        return result

    # ── Font ──────────────────────────────────────────────────────────────

    def _font(self, size: int) -> pygame.font.Font:
        for name in ("Courier New", "Courier", "monospace"):
            try:
                f = pygame.font.SysFont(name, size)
                if f: return f
            except Exception:
                pass
        return pygame.font.Font(None, size)

    # ── Drawing — all use rect for coordinates ────────────────────────────

    def _draw_columns(self, surf, font, rect):
        """Row headers (left edge) and lane labels (above sensor row)."""
        ox, oy, pw, ph = rect.x, rect.y, rect.width, rect.height
        def fx(f): return ox + int(pw * f)
        def fy(f): return oy + int(ph * f)

        # Row labels on left edge
        row_labels = [
            (_FY_SENSOR, "SENSORS"),
            (_FY_METER,  "METERS"),
            (_FY_EI,     "INPUTS"),
            (_FY_NEURON, "NEURONS"),
            (_FY_NT,     "OUTPUTS"),
            (_FY_MF,     "MOTORS"),
        ]
        for yf, lbl in row_labels:
            t = font.render(lbl, True, TEXT_DIM())
            surf.blit(t, (ox + 2, fy(yf) - t.get_height()//2))

        # Horizontal separators between neuron sections
        for yf in (_FY_EI - 0.03, _FY_NT - 0.03):
            pygame.draw.line(surf, BORDER(),
                             (ox + 55, fy(yf)), (ox + pw - 4, fy(yf)), 1)

        # Sensor lane labels above sensor row
        n_s = len(self._sensor_names)
        lanes = (list(_FX_SENSOR_LANES) if n_s <= 4
                 else [_FX_LEFT+(_FX_RIGHT-_FX_LEFT)*i/max(1,n_s-1)
                       for i in range(n_s)])
        bank_h = PIN_R * 2 + PAD * 2
        for i, name in enumerate(self._sensor_names):
            cx = fx(lanes[i] if i < len(lanes) else _FX_RIGHT)
            t  = font.render(name, True, AMBER())
            # Above the bank, above any wires that exit from the top
            surf.blit(t, (cx - t.get_width()//2,
                          fy(_FY_SENSOR) - bank_h//2 - t.get_height() - 8))

        # Motor lane labels and Fwd/Bwd row labels
        n_m = len(self._motor_names)
        mlanes = (list(_FX_MOTOR_LANES) if n_m <= 2
                  else [_FX_LEFT+(_FX_RIGHT-_FX_LEFT)*i/max(1,n_m-1)
                        for i in range(n_m)])
        for i, name in enumerate(self._motor_names):
            cx = fx(mlanes[i] if i < len(mlanes) else _FX_RIGHT)
            t  = font.render(name, True, BORDER())
            surf.blit(t, (cx - t.get_width()//2,
                          fy(_FY_MF) - t.get_height() - 2))
        for yf, lbl in [(_FY_MF, "Fwd"), (_FY_MB, "Bwd")]:
            t = font.render(lbl, True, BORDER_DIM())
            surf.blit(t, (ox + pw - font.size(lbl)[0] - 4,
                          fy(yf) - font.size(lbl)[1]//2))

    def _draw_neuron_bodies(self, surf, font, rect):
        """Neuron triangles spread horizontally at _FY_NEURON row."""
        ox, oy, pw, ph = rect.x, rect.y, rect.width, rect.height
        def fx(f): return ox + int(pw * f)
        def fy(f): return oy + int(ph * f)

        cy_n = fy(_FY_NEURON)
        hh   = max(14, int(ph * 0.028))   # half-height of triangle

        for i in range(1, 7):
            cx = fx(_neuron_fx(i))
            # Triangle pointing downward (source = bottom)
            pts = [(cx - hh, cy_n - hh),
                   (cx + hh, cy_n - hh),
                   (cx,      cy_n + hh)]
            pygame.draw.polygon(surf, PANEL_DEEP(), pts)
            pygame.draw.polygon(surf, BORDER(), pts, 1)
            lbl = font.render(f"N{i}", True, TEXT())
            surf.blit(lbl, (cx - lbl.get_width()//2,
                            cy_n - lbl.get_height()//2))

            # Bias trimpot — vertical bar beside triangle
            bias = self._biases.get(f"N{i}", 0.0)
            th   = max(30, int(ph * 0.05))
            tw   = 8
            tr   = pygame.Rect(cx + hh + 3, cy_n - th//2, tw, th)
            pygame.draw.rect(surf, PANEL_DEEP(), tr, border_radius=3)
            pygame.draw.rect(surf, BORDER(), tr, 1, border_radius=3)
            centre = tr.y + tr.height // 2
            frac   = bias / 4.0
            bh     = int(abs(frac) * tr.height // 2)
            if bh > 0:
                col = PHOSPHOR_MID() if bias >= 0 else AMBER_DIM()
                by  = centre if bias >= 0 else centre - bh
                pygame.draw.rect(surf, col,
                                 pygame.Rect(tr.x, by, tw, bh),
                                 border_radius=2)
            pygame.draw.line(surf, BORDER(),
                             (tr.x, centre), (tr.right, centre), 1)
            bv = font.render(f"{bias:+.1f}", True, TEXT_DIM())
            surf.blit(bv, (tr.right + 2, centre - bv.get_height()//2))

    def _draw_banks(self, surf, font, rect):
        for bank in self._banks:
            name  = bank["name"]
            kind  = bank["kind"]
            role  = bank["role"]
            brect = bank["rect"]
            horiz = bank["horiz"]
            pins  = bank["pins"]
            sel   = (name == self._sel_source)

            bc = BANK_COLOR.get(kind, BANK_COLOR["sensor"])
            pc = PIN_COLOR.get(kind,  PIN_COLOR["sensor"])

            if sel:
                glow = pygame.Rect(brect.x-3, brect.y-3,
                                   brect.width+6, brect.height+6)
                pygame.draw.rect(surf, TEXT_BRIGHT(), glow, 2, border_radius=5)

            pygame.draw.rect(surf, PANEL_DEEP(), brect, border_radius=3)
            pygame.draw.rect(surf, bc, brect, 1, border_radius=3)

            for px, py in _pin_positions(brect, pins, horiz):
                pygame.draw.circle(surf, pc, (px, py), PIN_R)

            # Label: dest banks above, source banks below
            # (sensors are labelled in _draw_columns; neuron outputs here)
            lbl = font.render(name, True, bc if not sel else TEXT_BRIGHT())
            if role == "source" and kind in ("neuron_N", "neuron_T"):
                surf.blit(lbl, (brect.centerx - lbl.get_width()//2,
                                brect.bottom + 2))
            elif role == "dest":
                surf.blit(lbl, (brect.centerx - lbl.get_width()//2,
                                brect.y - lbl.get_height() - 2))

    def _draw_wires(self, surf):
        for idx, conn in enumerate(self._connections):
            sb = self._bmap.get(conn.source)
            db = self._bmap.get(conn.dest)
            if not sb or not db:
                continue
            p1  = self._exit(sb, "source")
            p2  = self._exit(db, "dest")
            col = WIRE_COLORS[conn.color]
            wid = WIRE_WIDTHS[conn.color]
            if idx == self._hover_wire:
                col = tuple(min(255, c + 60) for c in col)
                wid += 2
            self._bezier(surf, p1, p2, col, wid)

    def _draw_pending(self, surf, mx, my):
        if self._sel_source is None:
            return
        b = self._bmap.get(self._sel_source)
        if b:
            self._bezier(surf, self._exit(b, "source"),
                         (mx, my), WIRE_COLORS["blue"], 1)

    def _draw_ui(self, surf, font_md, font_hd, rect):
        """Header bar, status, Done button, Gain bar."""
        ox, oy, pw, ph = rect.x, rect.y, rect.width, rect.height

        # Header strip
        header_h = max(22, int(ph * 0.04))
        pygame.draw.rect(surf, PANEL(), (ox, oy, pw, header_h))
        pygame.draw.line(surf, BORDER(),
                         (ox, oy + header_h), (ox + pw, oy + header_h))
        t = font_hd.render("Wiring Editor", True, TEXT_BRIGHT())
        surf.blit(t, (ox + 8, oy + 3))

        # Bottom bar
        bar_h  = max(36, int(ph * 0.07))
        bar_y  = oy + ph - bar_h
        pygame.draw.rect(surf, PANEL(), (ox, bar_y, pw, bar_h))
        pygame.draw.line(surf, BORDER(), (ox, bar_y), (ox + pw, bar_y))

        # Status
        st = font_md.render(self._status[:55], True, TEXT_DIM())
        surf.blit(st, (ox + 8, bar_y + 4))

        # Gain bar
        gw = max(80, int(pw * 0.14))
        gh = 12
        gain_x = ox + pw - gw - 110
        gain_y = bar_y + (bar_h - gh) // 2
        gain_r = pygame.Rect(gain_x, gain_y, gw, gh)
        pygame.draw.rect(surf, PANEL_DEEP(), gain_r, border_radius=3)
        pygame.draw.rect(surf, BORDER(), gain_r, 1, border_radius=3)
        fw = int(gain_r.width * (self._gain / 3.0))
        if fw > 0:
            pygame.draw.rect(surf, PHOSPHOR_MID(),
                             pygame.Rect(gain_r.x, gain_r.y, fw, gh),
                             border_radius=3)
        gl = font_md.render(f"Gain:{self._gain:.1f}", True, TEXT_DIM())
        surf.blit(gl, (gain_r.x - gl.get_width() - 4,
                       gain_r.y + (gh - gl.get_height())//2))
        self._gain_bar = gain_r

        # Done button
        dw, dh = max(70, int(pw * 0.09)), bar_h - 8
        done_r  = pygame.Rect(ox + pw - dw - 4, bar_y + 4, dw, dh)
        self._done_btn = done_r
        if not self._suppress_done:
            mx2, my2 = pygame.mouse.get_pos()
            hov = done_r.collidepoint(mx2, my2)
            pygame.draw.rect(surf,
                             PHOSPHOR_MID() if hov else PANEL_DEEP(),
                             done_r, border_radius=4)
            pygame.draw.rect(surf, PHOSPHOR(), done_r, 1, border_radius=4)
            dl = font_md.render("Done", True, TEXT_BRIGHT())
            surf.blit(dl, (done_r.centerx - dl.get_width()//2,
                           done_r.centery - dl.get_height()//2))

    # ── Wire geometry ─────────────────────────────────────────────────────

    def _exit(self, bank: dict, role: str) -> tuple[int,int]:
        """Sources exit bottom; dests enter top (top→bottom flow)."""
        r = bank["rect"]
        if role == "source":
            return (r.centerx, r.bottom)
        else:
            return (r.centerx, r.top)

    def _bezier(self, surf, p1, p2, color, width):
        x1, y1 = p1;  x2, y2 = p2
        dy    = max(40, abs(y2 - y1) * 0.45)
        ctrl1 = (x1, y1 + dy)
        ctrl2 = (x2, y2 - dy)
        steps = max(24, int(abs(y2 - y1) / 4))
        pts   = []
        for i in range(steps + 1):
            t  = i / steps;  u = 1 - t
            bx = u**3*x1 + 3*u**2*t*ctrl1[0] + 3*u*t**2*ctrl2[0] + t**3*x2
            by = u**3*y1 + 3*u**2*t*ctrl1[1] + 3*u*t**2*ctrl2[1] + t**3*y2
            pts.append((int(bx), int(by)))
        if len(pts) >= 2:
            pygame.draw.lines(surf, color, False, pts, width)

    def _near_bezier(self, px, py, p1, p2, thr) -> bool:
        x1, y1 = p1;  x2, y2 = p2
        dy    = max(40, abs(y2 - y1) * 0.45)
        ctrl1 = (x1, y1 + dy)
        ctrl2 = (x2, y2 - dy)
        steps = max(24, int(abs(y2 - y1) / 4))
        for i in range(steps + 1):
            t  = i / steps;  u = 1 - t
            bx = u**3*x1 + 3*u**2*t*ctrl1[0] + 3*u*t**2*ctrl2[0] + t**3*x2
            by = u**3*y1 + 3*u**2*t*ctrl1[1] + 3*u*t**2*ctrl2[1] + t**3*y2
            if math.hypot(px - bx, py - by) < thr:
                return True
        return False

    # ── Interaction ───────────────────────────────────────────────────────

    def _bank_at(self, pos) -> dict | None:
        for b in self._banks:
            if b["rect"].collidepoint(pos):
                return b
        return None

    def _wire_near(self, mx, my, threshold=8) -> int | None:
        for idx, conn in enumerate(self._connections):
            sb = self._bmap.get(conn.source)
            db = self._bmap.get(conn.dest)
            if not sb or not db:
                continue
            if self._near_bezier(mx, my,
                                  self._exit(sb, "source"),
                                  self._exit(db, "dest"), threshold):
                return idx
        return None

    def _left_click(self, pos, rect: pygame.Rect | None = None):
        # Done button
        if (not self._suppress_done and
                self._done_btn and self._done_btn.collidepoint(pos)):
            self._confirmed = True
            return

        # Gain bar
        if self._gain_bar and self._gain_bar.collidepoint(pos):
            frac = (pos[0] - self._gain_bar.x) / self._gain_bar.width
            self._gain = round(max(0.1, min(3.0, frac * 3.0)), 2)
            return

        # Neuron trimpot hit test
        if self._rect:
            ox, oy, pw, ph = (self._rect.x, self._rect.y,
                               self._rect.width, self._rect.height)
            cy_n = oy + int(ph * _FY_NEURON)
            hh   = max(14, int(ph * 0.028))
            tw   = 8
            th   = max(30, int(ph * 0.05))
            for i in range(1, 7):
                cx = ox + int(pw * _neuron_fx(i))
                tr = pygame.Rect(cx + hh + 3, cy_n - th//2, tw + 8, th)
                if tr.collidepoint(pos):
                    self._dragging_neuron = i
                    self._drag_start_pos  = pos[0]
                    self._drag_start_bias = self._biases.get(f"N{i}", 0.0)
                    return

        # Wire left-click → cycle color
        if self._sel_source is None:
            w = self._wire_near(*pos)
            if w is not None:
                conn = self._connections[w]
                idx  = WIRE_CYCLE.index(conn.color)
                self._connections[w] = Connection(
                    conn.source, conn.dest,
                    WIRE_CYCLE[(idx + 1) % 3])
                self._status = (f"{conn.source}→{conn.dest} "
                                f"now {self._connections[w].color}")
                return

        # Bank click
        bank = self._bank_at(pos)
        if bank is None:
            self._sel_source = None
            return

        name = bank["name"]
        role = bank["role"]

        if self._sel_source is None:
            if role == "source":
                self._sel_source = name
                self._status = f"Wiring from {name} — click a destination"
        else:
            if name == self._sel_source:
                self._sel_source = None
                self._status = "Deselected"
            elif role == "dest":
                self._add_wire(self._sel_source, name)
                self._sel_source = None
            elif role == "source":
                self._sel_source = name
                self._status = f"Wiring from {name} — click a destination"

    def _right_click(self, pos):
        w = self._wire_near(*pos, threshold=10)
        if w is not None:
            removed = self._connections.pop(w)
            self._status = f"Removed {removed.source}→{removed.dest}"

    def _add_wire(self, source: str, dest: str):
        for i, c in enumerate(self._connections):
            if c.source == source and c.dest == dest:
                idx = WIRE_CYCLE.index(c.color)
                self._connections[i] = Connection(
                    source, dest, WIRE_CYCLE[(idx + 1) % 3])
                self._status = (f"{source}→{dest} "
                                f"now {self._connections[i].color}")
                return
        self._connections.append(Connection(source, dest, "blue"))
        self._status = f"Connected {source} → {dest}  (blue = 1×)"

    def _build_config(self) -> VehicleConfig:
        return VehicleConfig(
            connections=list(self._connections),
            neuron_biases={k: v for k, v in self._biases.items()
                           if abs(v) > 0.01},
            gain=self._gain)


# ── Standalone ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    example = VehicleConfig(
        connections=[
            Connection("PL", "FL", "blue"),
            Connection("PR", "FR", "blue"),
        ],
        name="Example: Vehicle 2a Cowardice",
    )
    ed = WiringEditor(initial_config=example)
    result = ed.run()
    if result:
        print(f"\nVehicle ({len(result.connections)} connections):")
        for c in result.connections:
            print(f"  {c}")
        print(f"  Biases: {result.neuron_biases}")
        print(f"  GAIN:   {result.gain}")
    else:
        print("\nCancelled.")
