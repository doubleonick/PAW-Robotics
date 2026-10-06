"""
valentinos/builder/wiring_editor.py
------------------------------------
Interactive wiring diagram editor for Valentino's Vehicles.

Layout (left → right = signal flow):
  Column 0 : Sensor banks      (RL, RR, PL, PR)  — 2 pins each
  Column 1 : Meter banks       (M1-M3)            — 1 pin each
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
from engine.signals import Connection
from engine.vehicle import VehicleConfig

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

LDR_CH_COLS = {"W": (255, 200, 60), "R": (220, 60, 60),
               "G": ( 60, 200, 60), "B": ( 80, 140, 255)}

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


def _row_anchors(rect: pygame.Rect):
    """Compute the shared vertical anchors used by both bank-building and
    neuron-body drawing, so the triangle/pot row lines up with its pins."""
    ph = rect.height
    _bh = PIN_R * 2 + PAD * 2
    meter_y_px = rect.y + int(ph * _FY_METER) + _bh // 2
    row_step = max(36, int(ph * 0.075))
    ei_y = meter_y_px + row_step
    nt_y = meter_y_px + row_step * 3
    neuron_body_y = (ei_y + nt_y) // 2
    mf_y = nt_y + row_step * 2 + int(ph * 0.04)
    mb_y = mf_y + row_step
    return dict(meter=meter_y_px, step=row_step, ei=ei_y, nt=nt_y,
                neuron=neuron_body_y, mf=mf_y, mb=mb_y)


def _build_banks_for_rect(rect: pygame.Rect,
                           sensor_names:     list[str] | None = None,
                           motor_names:      list[str] | None = None,
                           ) -> list[dict]:
    """
    Build the complete bank list within rect.
    Orientation: TOP→BOTTOM signal flow.
      Sensors top row, neurons middle, motors bottom row.
      Sensor/motor lanes spread left→right.
    sensor_names: e.g. ["IR·L","IR·R","LDR·C1","LDR·C2"]
    motor_names:  e.g. ["FL","FR"]  (full node names)
    """
    if sensor_names is None:
        sensor_names = ["IR·L", "IR·R", "LDR·C1", "LDR·C2"]
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

    # ── Sensors — equal spacing left→right (order = L→C→R from robot_builder)
    n_s = len(sensor_names)
    _bh = PIN_R * 2 + PAD * 2
    meter_y_px = oy + int(ph * _FY_METER) + _bh // 2  # default

    # Zone-aware lane placement.
    # Three fixed regions across the editor width:
    #   L zone:  _FX_LEFT  .. 0.32
    #   C zone:  0.36      .. 0.64
    #   R zone:  0.68      .. _FX_RIGHT
    # Sensors are spread evenly within their region.
    # Zone is read from the sensor name: "IR·L" → L, "LDR·C1" → C, "IR·R" → R.
    # Wiring editor: L on screen-left, R on screen-right.
    # Matches top-down robot builder view (Forward = up).
    _REGIONS = {
        "L": (_FX_LEFT,  0.32),   # robot left = screen left
        "C": (0.36,      0.64),   # centre
        "R": (0.68,      _FX_RIGHT),  # robot right = screen right
    }

    def _sensor_zone(name: str) -> str:
        # zone is the character after "·" — "IR·L1" → "L"
        if "\u00b7" in name:
            z = name.split("\u00b7")[1][0]
            if z in ("L", "C", "R"):
                return z
        return "C"   # fallback

    # Group sensor names by zone, preserving order
    _zone_groups: dict[str, list[int]] = {"L": [], "C": [], "R": []}
    for i, name in enumerate(sensor_names):
        _zone_groups[_sensor_zone(name)].append(i)

    # Compute lane x for each sensor
    lanes = [_FX_MID] * n_s
    for z in ("L", "C", "R"):   # screen left→right order
        idxs = _zone_groups[z]
        if not idxs:
            continue
        lo, hi = _REGIONS[z]
        pad = (hi - lo) * 0.1   # 10% inner padding each side
        lo2, hi2 = lo + pad, hi - pad
        if len(idxs) == 1:
            lanes[idxs[0]] = (lo2 + hi2) / 2
        else:
            for k, idx in enumerate(idxs):
                lanes[idx] = lo2 + (hi2 - lo2) * k / (len(idxs) - 1)

    for i, name in enumerate(sensor_names):
        cx    = fx(lanes[i])
        stype = "ldr" if name.startswith("LDR") else "sensor"
        add(name, stype, "source", 2, cx, fy(_FY_SENSOR))
        # Channel color will be applied in _draw_banks via _bmap

    # ── Meters — exactly THREE, matching the physical AnaBBot (3 meters is
    # the hardware resource limit; we don't "improve" on it). Each meter has a
    # single header pin that accepts ONE connection (enforced in _add_wire).
    for i in range(1, 4):
        cx = fx(_FX_LEFT + (_FX_RIGHT - _FX_LEFT) * (i - 1) / 2)
        add(f"M{i}", "meter", "dest", 1, cx, fy(_FY_METER), horiz=True)

    # Remaining rows use pixel offsets from meter_y_px so they shift
    # down automatically when sensor columns are tall. Shared with the neuron-
    # body draw via _row_anchors so the triangle/pot row lines up with its pins
    # and the motor headers always clear the (taller) rotary pots.
    _A = _row_anchors(rect)
    row_step = _A["step"]
    ei_y     = _A["ei"]
    nt_y     = _A["nt"]
    neuron_body_y = _A["neuron"]
    mf_y     = _A["mf"]
    mb_y     = _A["mb"]

    # ── Neuron inputs (E/I) ───────────────────────────────────────────────
    for i in range(1, 7):
        cx = fx(_neuron_fx(i))
        add(f"E{i}", "neuron_E", "dest", 4, cx - 17, ei_y, horiz=True)
        add(f"I{i}", "neuron_I", "dest", 4, cx + 17, ei_y, horiz=True)

    # ── Neuron outputs (N/T) ──────────────────────────────────────────────
    for i in range(1, 7):
        cx = fx(_neuron_fx(i))
        add(f"N{i}", "neuron_N", "source", 1, cx - 17, nt_y)
        if i <= 4:
            add(f"T{i}", "neuron_T", "source", 1, cx + 17, nt_y)

    # ── Motors ────────────────────────────────────────────────────────────
    n_m = len(motor_names)
    mlanes = (list(_FX_MOTOR_LANES) if n_m <= 2
              else [_FX_LEFT + (_FX_RIGHT-_FX_LEFT)*i/max(1,n_m-1)
                    for i in range(n_m)])
    for i, name in enumerate(motor_names):
        cx   = fx(mlanes[i] if i < len(mlanes) else _FX_RIGHT)
        back = "B" + name[1:] if len(name) >= 2 else "B" + name
        add(name, "motor", "dest", 4, cx, mf_y)
        add(back, "motor", "dest", 4, cx, mb_y)

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
                 suppress_done: bool = False,
                 hint_connections: list | None = None,
                 offer_tour: bool = False,
                 tour_already_offered: bool = False,
                 chassis_polygon: list | None = None):
        self._title = title
        # Optional chassis outline drawn BEHIND the board, so the wiring panel
        # reads as the circuit board sitting on the actual robot. Supplied as
        # robot-local metre vertices (see robot_builder.chassis_polygon_m); it
        # is passed in rather than imported to keep this module independent of
        # the builder (which imports us).
        self._chassis_polygon = list(chassis_polygon) if chassis_polygon else None
        self._suppress_done = suppress_done

        cfg = initial_config or VehicleConfig()
        self._connections: list[Connection] = list(cfg.connections)
        self._biases: dict[str, float]      = dict(cfg.neuron_biases)
        self._gain:   float                 = cfg.gain

        self._sensor_names:     list = (list(sensor_names) if sensor_names
                                        else ["IR·L", "IR·R", "LDR·C1", "LDR·C2"])
        self._motor_names:      list = (list(motor_names)  if motor_names
                                        else ["FL", "FR"])
        self._sensor_positions: list | None = None  # set by robot builder
        self._sensor_channels:  dict = {}  # {name: "W"/"R"/"G"/"B"}

        self._rect: pygame.Rect | None = None
        self._banks: list[dict]        = []
        self._bmap:  dict[str, dict]   = {}

        self._sel_source:      str | None = None
        self._hover_wire:      int | None = None
        self._dragging_neuron: int | None = None
        self._drag_start_pos:  int        = 0
        self._drag_start_bias: float      = 0.0
        self._neuron_knob: dict[int, tuple] = {}  # i -> (cx,cy,r) for hit-test

        # ── Circuit-board tour (Phase 4) ──────────────────────────────────
        # On first open of a TUTORIAL editor, PAW-Bot offers a guided tour of
        # the circuit board. The narration strip (normally a one-line hint bar)
        # grows taller and lifts toward the motor pins while the tour/offer is
        # active, with PAW-Bot perched at its left edge. The tour is LINEAR: it
        # glows each region in turn while showing an explanation, advanced by a
        # Next button. Content text is loaded from a script so it can be edited
        # without touching code (see _TOUR_FALLBACK for placeholders).
        #
        # _tour_state: None      → no tour UI (normal editor)
        #              "offer"   → asking "Tour the circuit board?" (Yes/No)
        #              "running" → stepping through _tour_steps
        #              "done"    → finished (strip collapses back to hint bar)
        self._tour_state = "offer" if hint_connections else None
        self._tour_step  = 0
        self._tour_offer_btns: dict = {}   # 'yes'/'no' rects
        self._tour_next_btn = None
        # Each step: (region_key, title). Region_key drives the glow; the text
        # comes from the loaded script (or _TOUR_FALLBACK) by index.
        self._tour_steps = [
            ("sensors",   "Sensor pins"),
            ("motors",    "Motor pins"),
            ("neurons",   "Neurons"),
            ("ei",        "Excitatory vs inhibitory"),
            ("pots",      "Synaptic-weight pots"),
        ]
        self._tour_text = self._load_tour_text()
        self._confirmed: bool = False
        self._cancelled: bool = False
        self._done_btn:  pygame.Rect | None = None
        self._gain_bar:  pygame.Rect | None = None
        self._status = "Click a source bank to begin wiring"

        # Tutorial hint system: the connections the player is expected to make,
        # as (source, dest, color) tuples. The editor highlights the FIRST
        # still-missing one (source + dest nodes glow, and a ghost wire animates
        # between them) until the player makes it, then moves to the next. This
        # is what turns "I don't know where to click" into a guided gesture.
        # Empty/None outside the tutorial → no hints drawn (normal editor).
        self._hint_connections: list = list(hint_connections or [])
        self._hint_phase: float = 0.0   # advances with dt for the ghost-dot
        # Delete-hint: set True when the player presses Done with wrong wires
        # present. Wrong wires (present but not in the expected set) then pulse
        # AMBER with a scissors icon and "right-click to remove" guidance, until
        # removed — at which point Done will confirm. Only active in tutorials
        # (when hint_connections is non-empty).
        self._show_delete_hints: bool = False

        # ── Circuit-board tour (PAW-Bot guided walkthrough) ──────────────────
        # On first open of a guided (tutorial) editor, PAW-Bot offers a tour of
        # the circuit board. The narration strip at the bottom grows and lifts
        # toward the motor pins while the tour/offer is active; each step glows
        # a region of the board. Steps load from scripts/paw_bot/circuit_tour.
        self._tour_enabled: bool = bool(hint_connections is not None
                                        and offer_tour)
        # First guided visit: PAW-Bot pops up the full Yes/No offer. On EVERY
        # SUBSEQUENT visit we skip that (it hogs the screen and delays the next
        # guided edit) and start collapsed — only the "Play Tour" link shows, so
        # the tour is one click away but never blocks. "done" is that collapsed
        # state; the tour stays enabled so the link is live.
        if self._tour_enabled and tour_already_offered:
            self._tour_state = "done"
        elif self._tour_enabled:
            self._tour_state = "offer"
        else:
            self._tour_state = "off"
        # "off" | "offer" (Yes/No shown) | "running" | "done"
        self._tour_step: int = 0
        self._tour_steps: list = self._load_tour_steps() if self._tour_enabled \
            else []
        self._tour_btns: dict = {}   # rects for Yes/No/Next, filled at draw
        self._play_tour_btn = None   # "Play Tour" re-entry link, filled at draw
        # Shared glossary (FW-001 MVP) — modal "?" reference for wiring concepts.
        self._help_btn = None
        try:
            from engine.builder.vv_glossary import make_vv_glossary
            self._glossary = make_vv_glossary()
        except Exception:
            self._glossary = None
        self._pawbot = None
        if self._tour_enabled:
            try:
                from engine.launch_assets import PawBotSprite
                self._pawbot = PawBotSprite(target_h=84)
            except Exception:
                self._pawbot = None

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
        # advance hint animation by real elapsed time
        _now = pygame.time.get_ticks() / 1000.0
        if not hasattr(self, "_hint_last_t"):
            self._hint_last_t = _now
        self._hint_phase += (_now - self._hint_last_t)
        self._hint_last_t = _now
        surf.set_clip(rect)
        pygame.draw.rect(surf, BG(), rect)
        self._draw_columns(surf, fs, rect)
        self._draw_neuron_bodies(surf, fs, rect)
        self._draw_wires(surf)
        self._draw_banks(surf, fs, rect)
        # While the circuit tour is being offered or is running, suppress the
        # wiring-hint layer (glow + dashed "connect like this" line, delete
        # hints, control legend) so the two don't compete. The wiring hints
        # resume once the tour is dismissed/finished (state "done") — the wiring
        # itself sits untouched underneath the whole time.
        tour_blocking = self._tour_state in ("offer", "running")
        if not tour_blocking:
            self._draw_hint(surf)
            self._draw_delete_hints(surf)
        self._draw_pending(surf, mx, my)
        self._draw_ui(surf, fm, fh, rect)
        # Persistent control key — only in guided (tutorial) mode, and only
        # when the tour isn't taking over the screen.
        if self._hint_connections and not tour_blocking:
            self._draw_control_legend(surf, rect)
        # Circuit-board tour overlay (offer / running) — drawn last, on top.
        if self._tour_state not in ("off", "done"):
            self._draw_tour(surf, rect, fm, fh)
        # Glossary modal — drawn ABOVE the tour, captures the screen when open.
        if self._glossary is not None and self._glossary.is_open:
            self._glossary.draw(surf, rect)
        surf.set_clip(None)

    def handle_event(self, event: pygame.event.Event,
                     rect: pygame.Rect) -> bool:
        if rect != self._rect:
            self.set_panel(rect)
        # The glossary modal, when open, captures all input until closed.
        if self._glossary is not None and self._glossary.is_open:
            self._glossary.handle_event(event, rect)
            return True
        if event.type == pygame.MOUSEBUTTONDOWN:
            if not rect.collidepoint(event.pos):
                return False
            if event.button == 1:
                # "?" glossary button opens the modal.
                if (self._help_btn is not None and
                        self._glossary is not None and
                        self._help_btn.collidepoint(event.pos)):
                    self._glossary.open()
                    return True
                # "Play Tour" re-entry link (when tour is available, not active).
                if (self._play_tour_btn is not None and
                        self._play_tour_btn.collidepoint(event.pos)):
                    self._tour_state = "running"
                    self._tour_step = 0
                    return True
                # Tour buttons (Yes/No/Next) take priority over wiring.
                if self._tour_state not in ("off", "done") and \
                        self._tour_click(event.pos):
                    return True
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
        # Row labels: derive Y from first bank of each kind
        kind_label = {
            "sensor":  "SENSORS", "ldr":     "SENSORS",
            "meter":   "METERS",
            "neuron_E":"INPUTS",  "neuron_I":"INPUTS",
            "neuron_N":"OUTPUTS", "neuron_T":"OUTPUTS",
            "motor":   "MOTORS",
        }
        drawn_labels: set = set()
        for bank in self._banks:
            lbl = kind_label.get(bank["kind"])
            if lbl and lbl not in drawn_labels:
                t = font.render(lbl, True, TEXT_DIM())
                surf.blit(t, (ox + 2,
                              bank["cy"] - t.get_height()//2))
                drawn_labels.add(lbl)

        # Horizontal separators above INPUT and OUTPUT rows
        sep_kinds = [("neuron_E", "INPUTS"), ("neuron_N", "OUTPUTS")]
        for sep_kind, _ in sep_kinds:
            for bank in self._banks:
                if bank["kind"] == sep_kind:
                    sep_y = bank["cy"] - 20
                    pygame.draw.line(surf, BORDER(),
                                     (ox + 55, sep_y),
                                     (ox + pw - 4, sep_y), 1)
                    break

        # Sensor labels: read cx from bank map so they match zone positions
        bank_h = PIN_R * 2 + PAD * 2
        label_y = fy(_FY_SENSOR) - bank_h//2 - 8
        for name in self._sensor_names:
            bank = self._bmap.get(name)
            if bank is None:
                continue
            cx  = bank["cx"]
            col = AMBER() if not name.startswith("LDR") else AMBER()
            ch2  = self._sensor_channels.get(name, "W")
            lcol = (LDR_CH_COLS.get(ch2, AMBER())
                    if name.startswith("LDR") else AMBER())
            t   = font.render(name, True, lcol)
            surf.blit(t, (cx - t.get_width()//2,
                          label_y - t.get_height()))

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
        """Neuron bodies, matching the physical board: a downward triangular
        silkscreen OUTLINE that CIRCUMSCRIBES the rotary bias trim pot (the pot
        sits inside the triangle, as on the real AnaBBot). This removes the
        horizontal crowding that arose from drawing the pot beside the triangle."""
        import math as _m
        ox, oy, pw, ph = rect.x, rect.y, rect.width, rect.height
        def fx(f): return ox + int(pw * f)

        cy_n = _row_anchors(rect)["neuron"]
        knob_r = max(13, int(ph * 0.028))
        # Triangle sized so the pot fits comfortably inside its upper body.
        tri_hw = int(knob_r * 1.9)              # half-width at the top edge
        tri_h  = int(knob_r * 3.1)              # full height (apex below)
        top_y  = cy_n - knob_r - 4              # top edge of triangle
        apex_y = top_y + tri_h                  # downward point

        for i in range(1, 7):
            cx = fx(_neuron_fx(i))
            # Downward triangle OUTLINE (silkscreen), pot centered within it.
            pts = [(cx - tri_hw, top_y),
                   (cx + tri_hw, top_y),
                   (cx,          apex_y)]
            pygame.draw.polygon(surf, BORDER(), pts, 1)

            # ── Rotary bias trim pot, centered inside the triangle ──────────
            bias = self._biases.get(f"N{i}", 0.0)
            kcx, kcy = cx, top_y + knob_r + 2
            self._neuron_knob[i] = (kcx, kcy, knob_r)

            ARC0  = _m.radians(135)   # min (lower-left)
            SWEEP = _m.radians(270)
            frac  = (bias + 4.0) / 8.0
            ang   = ARC0 + SWEEP * frac

            # range track arc behind the knob
            track_r = knob_r + 3
            tpts = [(kcx + track_r * _m.cos(ARC0 + SWEEP * (s / 28)),
                     kcy + track_r * _m.sin(ARC0 + SWEEP * (s / 28)))
                    for s in range(29)]
            pygame.draw.lines(surf, BORDER(), False,
                              [(int(x), int(y)) for x, y in tpts], 1)
            # center detent tick (0 = straight up)
            top = ARC0 + SWEEP * 0.5
            pygame.draw.line(surf, TEXT_DIM(),
                             (int(kcx + track_r * _m.cos(top)),
                              int(kcy + track_r * _m.sin(top))),
                             (int(kcx + (track_r + 3) * _m.cos(top)),
                              int(kcy + (track_r + 3) * _m.sin(top))), 1)

            # knob body (themed)
            knob_edge = PHOSPHOR_MID() if bias >= 0 else AMBER_DIM()
            pygame.draw.circle(surf, PANEL_DEEP(), (kcx, kcy), knob_r)
            pygame.draw.circle(surf, knob_edge, (kcx, kcy), knob_r, 2)
            pygame.draw.circle(surf, BORDER(), (kcx, kcy),
                               max(2, knob_r - 4), 1)
            # pointer triangle toward wiper angle
            tip = (kcx + (knob_r - 2) * _m.cos(ang),
                   kcy + (knob_r - 2) * _m.sin(ang))
            perp = ang + _m.pi / 2
            basew = max(2, knob_r * 0.30)
            b1 = (kcx + basew * _m.cos(perp), kcy + basew * _m.sin(perp))
            b2 = (kcx - basew * _m.cos(perp), kcy - basew * _m.sin(perp))
            ptr_col = PHOSPHOR() if bias >= 0 else AMBER_DIM()
            pygame.draw.polygon(surf, ptr_col,
                                [(int(tip[0]), int(tip[1])),
                                 (int(b1[0]), int(b1[1])),
                                 (int(b2[0]), int(b2[1]))])

            # N# label near the apex, value just below it
            lbl = font.render(f"N{i}", True, TEXT())
            surf.blit(lbl, (cx - lbl.get_width() // 2, apex_y - 14))
            bv = font.render(f"{bias:+.1f}", True, TEXT_DIM())
            surf.blit(bv, (cx - bv.get_width() // 2, apex_y + 2))

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
            # Override with channel color for LDR banks
            if kind == "ldr":
                ch  = self._sensor_channels.get(name, "W")
                bc  = LDR_CH_COLS.get(ch, bc)
                pc  = bc

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

    # ── Circuit-board tour ────────────────────────────────────────────────
    # Placeholder text (used if the script file is missing). Each entry is a
    # list of lines for one step, in the order of self._tour_steps. Replace by
    # editing scripts/paw_bot/circuit_tour.txt (steps separated by blank lines).
    _TOUR_FALLBACK = [
        ["These are the SENSOR pins at the top — the robot's eyes.",
         "Each sensor reports a value: light level, distance, and so on."],
        ["At the bottom are the MOTOR pins — the robot's muscles.",
         "Whatever reaches them drives the wheels forward or back."],
        ["In the middle sit the NEURONS (the triangles).",
         "A neuron gathers inputs, adds them up, and passes the result on."],
        ["Each neuron has EXCITATORY (E) and INHIBITORY (I) inputs.",
         "E inputs push the output up; I inputs pull it down —",
         "electrically, one adds current, the other subtracts it."],
        ["The knob in each triangle is a POTENTIOMETER (a trim pot).",
         "Turning it sets the neuron's bias — its resting tendency."],
    ]

    def _load_tour_text(self):
        """Load tour narration from scripts/paw_bot/circuit_tour.txt if present
        (steps separated by blank lines, one line of text per display line),
        else fall back to the placeholder above."""
        import os
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        path = os.path.join(root, "scripts", "paw_bot", "circuit_tour.txt")
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
            steps = [blk.strip().splitlines()
                     for blk in raw.split("\n\n") if blk.strip()]
            if steps:
                return steps
        except Exception:
            pass
        return self._TOUR_FALLBACK

    # ── Tutorial hint overlay ─────────────────────────────────────────────
    def _next_hint(self):
        """Return the first expected (source,dest,color) connection the player
        has NOT yet made, or None if all hints are satisfied. Highlighting one
        at a time keeps it a guided, step-by-step lesson rather than a wall of
        glowing nodes."""
        if not self._hint_connections:
            return None
        have = {(c.source, c.dest, c.color) for c in self._connections}
        for h in self._hint_connections:
            if tuple(h) not in have:
                return tuple(h)
        return None

    # ── Circuit-board tour helpers ────────────────────────────────────────
    def _load_tour_steps(self):
        """Load (region_key, [text lines]) steps from the tour script. Falls
        back to a minimal built-in if the file is missing."""
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))),
            "scripts", "paw_bot", "circuit_tour.txt")
        steps = []
        try:
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
            for block in raw.split("\n\n"):
                lines = [ln for ln in block.splitlines()
                         if ln.strip() and not ln.lstrip().startswith("#")]
                if not lines:
                    continue
                key = lines[0].strip()
                text = " ".join(lines[1:]).strip()
                if key and text:
                    steps.append((key, text))
        except Exception:
            steps = []
        if not steps:
            steps = [("sensors", "These are the sensor pins."),
                     ("motors",  "These are the motor pins."),
                     ("neurons", "Each triangle is a neuron."),
                     ("pots",    "The knob is the neuron's bias pot.")]
        return steps

    def _region_rects(self, key, rect):
        """Return the list of bank rects that should glow for a tour region."""
        kindmap = {
            "sensors":    lambda b: b["kind"] in ("sensor", "ldr"),
            "meters":     lambda b: b["kind"] == "meter",
            "motors":     lambda b: b["kind"] == "motor",
            # The N/T output PINS (what the "outputs" step explains).
            "outputs":    lambda b: b["kind"] in ("neuron_N", "neuron_T"),
            "excitatory": lambda b: b["kind"] == "neuron_E",
            "inhibitory": lambda b: b["kind"] == "neuron_I",
        }
        if key in kindmap:
            return [b["rect"] for b in self._banks if kindmap[key](b)]
        if key in ("neurons", "pots"):
            # Both glow the neuron triangle area. "neurons" highlights the whole
            # triangle body; "pots" the knob inside it. We use the stored knob
            # geometry: for "neurons" expand to the triangle footprint, for
            # "pots" just the knob disc.
            rects = []
            for (cx, cy, r) in self._neuron_knob.values():
                if key == "pots":
                    rects.append(pygame.Rect(cx - r, cy - r, 2*r, 2*r))
                else:  # neurons — triangle body circumscribing the pot
                    tri_hw = int(r * 1.9); tri_h = int(r * 3.1)
                    top_y = cy - r - 4
                    rects.append(pygame.Rect(cx - tri_hw, top_y,
                                             tri_hw * 2, tri_h))
            return rects
        return []

    def _draw_tour(self, surf, rect, font_md, font_hd):
        """Render the circuit-board tour: glow the current region, and draw the
        enlarged narration strip (lifted toward the motor pins) with PAW-Bot at
        its left edge, the explanation text, and Yes/No or Next buttons."""
        import math
        self._tour_btns = {}
        if self._tour_state in ("off", "done"):
            return
        ox, oy, pw, ph = rect.x, rect.y, rect.width, rect.height
        try:
            import engine.theme as _T
            accent = _T.PHOSPHOR; panel = _T.PANEL_DEEP; border = _T.PHOSPHOR
            textc = getattr(_T, "TEXT", (210, 230, 210))
            dim = _T.TEXT_DIM
        except Exception:
            accent = (51, 255, 87); panel = (12, 22, 12)
            border = accent; textc = (210, 230, 210); dim = (120, 140, 120)
        pulse = 0.5 + 0.5 * math.sin(self._hint_phase * 3.0)

        # ── Region glow (only while running a step) ──────────────────────────
        if self._tour_state == "running" and self._tour_steps:
            key, _txt = self._tour_steps[self._tour_step]
            for r in self._region_rects(key, rect):
                gr = r.inflate(10, 10)
                alpha = int(70 + 130 * pulse)
                halo = pygame.Surface((gr.width, gr.height), pygame.SRCALPHA)
                pygame.draw.rect(halo, (*accent, alpha), halo.get_rect(),
                                 width=3, border_radius=6)
                surf.blit(halo, gr.topleft)

        # ── Enlarged narration strip, lifted toward the motor pins ───────────
        strip_h = max(96, int(ph * 0.15))
        # lift it above the bottom controls bar
        bottom_bar_h = max(36, int(ph * 0.07))
        strip_y = oy + ph - bottom_bar_h - strip_h - 8
        strip = pygame.Rect(ox + 8, strip_y, pw - 16, strip_h)
        panel_surf = pygame.Surface((strip.width, strip.height),
                                    pygame.SRCALPHA)
        panel_surf.fill((*panel[:3], 240))
        surf.blit(panel_surf, strip.topleft)
        pygame.draw.rect(surf, border, strip, 2, border_radius=6)

        # PAW-Bot perched at the left edge of the strip
        text_x = strip.x + 16
        if self._pawbot is not None:
            self._pawbot.draw(surf, strip.x + 60, strip.bottom - 4)
            text_x = strip.x + 120

        # Speaker name
        surf.blit(font_md.render("PAW-BOT", True, accent),
                  (text_x, strip.y + 8))

        if self._tour_state == "offer":
            msg = ("This is the circuit board. Want a quick tour of how it "
                   "works?")
            self._blit_wrapped(surf, font_md, msg, textc,
                               text_x, strip.y + 30, strip.right - text_x - 20)
            # Yes / No buttons
            yes = pygame.Rect(strip.right - 200, strip.bottom - 40, 80, 28)
            no  = pygame.Rect(strip.right - 110, strip.bottom - 40, 80, 28)
            for r, lbl, key in ((yes, "Yes", "tour_yes"),
                                (no, "No", "tour_no")):
                hov = r.collidepoint(pygame.mouse.get_pos())
                pygame.draw.rect(surf, panel if not hov else accent, r,
                                 border_radius=4)
                pygame.draw.rect(surf, accent, r, 1, border_radius=4)
                lc = (_T.BG if hov else textc) if "BG" in dir(_T) else textc
                surf.blit(font_md.render(lbl, True, lc),
                          (r.centerx - font_md.size(lbl)[0] // 2,
                           r.centery - 8))
                self._tour_btns[key] = r

        elif self._tour_state == "running" and self._tour_steps:
            _key, txt = self._tour_steps[self._tour_step]
            self._blit_wrapped(surf, font_md, txt, textc,
                               text_x, strip.y + 30, strip.right - text_x - 130)
            # step counter
            sc = f"{self._tour_step + 1}/{len(self._tour_steps)}"
            surf.blit(font_md.render(sc, True, dim),
                      (strip.right - 60, strip.y + 8))
            # Next / Finish button
            last = self._tour_step >= len(self._tour_steps) - 1
            lbl = "Finish" if last else "Next \u25b6"
            nb = pygame.Rect(strip.right - 110, strip.bottom - 40, 96, 28)
            hov = nb.collidepoint(pygame.mouse.get_pos())
            pygame.draw.rect(surf, panel if not hov else accent, nb,
                             border_radius=4)
            pygame.draw.rect(surf, accent, nb, 1, border_radius=4)
            lc = (_T.BG if hov else textc) if "BG" in dir(_T) else textc
            surf.blit(font_md.render(lbl, True, lc),
                      (nb.centerx - font_md.size(lbl)[0] // 2,
                       nb.centery - 8))
            self._tour_btns["tour_next"] = nb

    def _blit_wrapped(self, surf, font, text, color, x, y, max_w):
        """Word-wrap helper for the tour strip. Glossary terms are highlighted
        in the theme accent colour (the Field Trip convention) so the vocabulary
        the tour teaches stands out and reads as 'this is a defined term'."""
        try:
            import engine.theme as _T
            accent = _T.PHOSPHOR
        except Exception:
            accent = (51, 255, 87)
        # Build the set of single-word keywords to highlight from the glossary.
        # (Multi-word terms like "circuit board" are matched per-word here for
        # simplicity; each constituent word highlights.)
        kw = set()
        if self._glossary is not None:
            for e in self._glossary.entries:
                for part in e.term.lower().split():
                    kw.add(part)
        space_w = font.size(" ")[0]
        lh = font.get_height() + 2
        cx, cy = x, y
        for word in text.split():
            # strip trailing punctuation for the keyword test
            bare = word.strip(".,;:!?()").lower()
            col = accent if bare in kw else color
            ww = font.size(word)[0]
            if cx + ww > x + max_w and cx > x:
                cx = x; cy += lh
            surf.blit(font.render(word, True, col), (cx, cy))
            cx += ww + space_w
        return cy + lh

    def _tour_click(self, pos):
        """Handle clicks on tour buttons. Returns True if consumed."""
        for key, r in self._tour_btns.items():
            if r.collidepoint(pos):
                if key == "tour_yes":
                    self._tour_state = "running"; self._tour_step = 0
                elif key == "tour_no":
                    self._tour_state = "done"
                elif key == "tour_next":
                    if self._tour_step >= len(self._tour_steps) - 1:
                        self._tour_state = "done"
                    else:
                        self._tour_step += 1
                return True
        return False

    def _wrong_wire_indices(self):
        """Indices of present connections that are NOT in the expected set —
        i.e. wires the player should delete. Empty if no hints (free editor)."""
        if not self._hint_connections:
            return []
        expected = {(tuple(h)[0], tuple(h)[1]) for h in self._hint_connections}
        wrong = []
        for i, c in enumerate(self._connections):
            if (c.source, c.dest) not in expected:
                wrong.append(i)
        return wrong

    def _draw_hint(self, surf):
        """Glow the next-needed source and destination nodes and animate a
        ghost wire between them (a travelling dot shows start→end direction).
        Reuses _exit/_bezier so the ghost matches real wires; pulse/dot use
        _hint_phase, advanced per-frame in draw()."""
        hint = self._next_hint()
        if hint is None:
            return
        src, dst, _col = hint
        sb = self._bmap.get(src)
        db = self._bmap.get(dst)
        if not sb or not db:
            return
        import math
        accent = PHOSPHOR()   # theme phosphor color (function in this module)

        # Pulsing halo on source (start) and dest (end) node rects.
        pulse = 0.5 + 0.5 * math.sin(self._hint_phase * 3.0)
        for bank, label in ((sb, "start"), (db, "end")):
            r = bank["rect"].inflate(10, 10)
            alpha = int(70 + 120 * pulse)
            halo = pygame.Surface((r.width, r.height), pygame.SRCALPHA)
            pygame.draw.rect(halo, (*accent, alpha), halo.get_rect(),
                             width=3, border_radius=6)
            surf.blit(halo, r.topleft)

        # Ghost wire as a MARCHING DOTTED line — reads as "suggested path: draw
        # from here to here", NOT as current flowing through an existing wire
        # (which a solid line with a travelling dot wrongly implied). The dash
        # pattern marches source→dest via _hint_phase to keep the direction cue.
        p1 = self._exit(sb, "source")
        p2 = self._exit(db, "dest")
        ghost = tuple(min(255, c + 30) for c in accent)
        self._dashed_bezier(surf, p1, p2, ghost, width=3,
                            phase=self._hint_phase)

    def _dashed_bezier(self, surf, p1, p2, color, width=3,
                       dash=10, gap=8, phase=0.0):
        """Draw a cubic bezier (matching _bezier's control points) as a dashed
        line whose dashes march along the curve. `phase` (seconds) offsets the
        pattern so the dots appear to travel from p1 toward p2."""
        import math
        x1, y1 = p1; x2, y2 = p2
        dy = max(40, abs(y2 - y1) * 0.45)
        c1 = (x1, y1 + dy); c2 = (x2, y2 - dy)
        # Sample the curve into a dense polyline.
        steps = max(40, int(abs(y2 - y1) / 2))
        pts = []
        for i in range(steps + 1):
            t = i / steps; u = 1 - t
            bx = u**3*x1 + 3*u**2*t*c1[0] + 3*u*t**2*c2[0] + t**3*x2
            by = u**3*y1 + 3*u**2*t*c1[1] + 3*u*t**2*c2[1] + t**3*y2
            pts.append((bx, by))
        # Walk the polyline by arc length, drawing dash-on / gap-off segments.
        period = dash + gap
        # marching offset: subtract so dashes move p1->p2 as phase grows
        carry = (-phase * 40.0) % period
        prev = pts[0]
        dist_into = carry
        for cur in pts[1:]:
            seg = math.hypot(cur[0]-prev[0], cur[1]-prev[1])
            if seg <= 1e-6:
                prev = cur; continue
            covered = 0.0
            while covered < seg:
                pos_in_period = (dist_into) % period
                on = pos_in_period < dash
                # length until next on/off boundary
                if on:
                    remain = dash - pos_in_period
                else:
                    remain = period - pos_in_period
                step_len = min(remain, seg - covered)
                f0 = covered / seg; f1 = (covered + step_len) / seg
                a = (prev[0] + (cur[0]-prev[0])*f0,
                     prev[1] + (cur[1]-prev[1])*f0)
                b = (prev[0] + (cur[0]-prev[0])*f1,
                     prev[1] + (cur[1]-prev[1])*f1)
                if on:
                    pygame.draw.line(surf, color,
                                     (int(a[0]), int(a[1])),
                                     (int(b[0]), int(b[1])), width)
                covered += step_len
                dist_into += step_len
            prev = cur

    def _draw_delete_hints(self, surf):
        """When the player pressed Done with wrong wires present, pulse those
        wires AMBER (not red — red reads as resistor strength) and draw a
        scissors marker at each wire's midpoint to signal right-click-to-delete."""
        if not self._show_delete_hints:
            return
        import math
        try:
            import engine.theme as _T
            amber = getattr(_T, "AMBER", (255, 149, 0))
        except Exception:
            amber = (255, 149, 0)
        pulse = 0.5 + 0.5 * math.sin(self._hint_phase * 4.0)
        for idx in self._wrong_wire_indices():
            conn = self._connections[idx]
            sb = self._bmap.get(conn.source); db = self._bmap.get(conn.dest)
            if not sb or not db:
                continue
            p1 = self._exit(sb, "source"); p2 = self._exit(db, "dest")
            w = 2 + int(2 * pulse)
            self._bezier(surf, p1, p2, amber, w)
            # midpoint of the cubic (t=0.5) for the scissors marker
            x1, y1 = p1; x2, y2 = p2
            dy = max(40, abs(y2 - y1) * 0.45)
            c1 = (x1, y1 + dy); c2 = (x2, y2 - dy)
            t = 0.5; u = 1 - t
            mx = u**3*x1 + 3*u**2*t*c1[0] + 3*u*t**2*c2[0] + t**3*x2
            my = u**3*y1 + 3*u**2*t*c1[1] + 3*u*t**2*c2[1] + t**3*y2
            self._draw_scissors(surf, int(mx), int(my), amber, pulse)

    def _draw_scissors(self, surf, cx, cy, col, pulse):
        """A simple scissors glyph: two blades (crossed lines) + two finger
        rings, on a small dark disc so it reads against the wire."""
        r = 11 + int(2 * pulse)
        pygame.draw.circle(surf, (0, 0, 0), (cx, cy), r)
        pygame.draw.circle(surf, col, (cx, cy), r, 2)
        # blades crossing toward upper-right
        pygame.draw.line(surf, col, (cx - 5, cy + 5), (cx + 6, cy - 6), 2)
        pygame.draw.line(surf, col, (cx - 5, cy - 5), (cx + 6, cy + 6), 2)
        # finger rings at lower-left ends
        pygame.draw.circle(surf, col, (cx - 6, cy + 6), 3, 1)
        pygame.draw.circle(surf, col, (cx - 6, cy - 6), 3, 1)

    # ── Circuit-board tour rendering & interaction ────────────────────────
    def _tour_region_rects(self, region):
        """Return a list of pygame.Rects to glow for a tour region key."""
        rects = []
        if region == "sensors":
            rects = [b["rect"] for b in self._banks
                     if b.get("kind") == "sensor"]
        elif region == "motors":
            rects = [b["rect"] for b in self._banks
                     if b.get("kind") == "motor"]
        elif region == "neurons":
            for (kcx, kcy, kr) in self._neuron_knob.values():
                rects.append(pygame.Rect(kcx - kr*2, kcy - kr,
                                         kr*4, kr*4))
        elif region == "ei":
            rects = [b["rect"] for b in self._banks
                     if b.get("kind") in ("neuron_E", "neuron_I")]
        elif region == "pots":
            for (kcx, kcy, kr) in self._neuron_knob.values():
                rects.append(pygame.Rect(kcx - kr - 2, kcy - kr - 2,
                                         kr*2 + 4, kr*2 + 4))
        return rects

    def _draw_control_legend(self, surf, rect):
        """Persistent control key in the editor corner. The entry relevant to
        the current action highlights, to draw attention (esp. initially)."""
        import math
        try:
            import engine.theme as _T
            accent = _T.PHOSPHOR; dim = _T.TEXT_DIM; panel = _T.PANEL_DEEP
            amber = getattr(_T, "AMBER", (255, 149, 0))
        except Exception:
            accent = (51, 255, 87); dim = (120, 140, 120)
            panel = (16, 24, 16); amber = (255, 149, 0)
        font = self._font(12)
        # entries: (text, is_active)  — active entry pulses
        mid_wire = self._sel_source is not None
        entries = [
            ("L-click: connect", not mid_wire and not self._show_delete_hints),
            ("L-click dest: finish wire", mid_wire),
            ("R-click: delete wire", self._show_delete_hints),
        ]
        pad = 8; lh = font.get_height() + 4
        bw = max(font.size(e[0])[0] for e in entries) + pad * 2
        bh = lh * len(entries) + pad
        bx = rect.right - bw - 12
        by = rect.bottom - bh - max(36, int(rect.height * 0.07)) - 12
        legend = pygame.Surface((bw, bh), pygame.SRCALPHA)
        legend.fill((*panel[:3], 220))
        pygame.draw.rect(legend, accent, legend.get_rect(), 1, border_radius=4)
        pulse = 0.5 + 0.5 * math.sin(self._hint_phase * 3.0)
        y = pad // 2
        for text, active in entries:
            if active:
                c = tuple(int(d + (a - d) * pulse)
                          for d, a in zip(dim, accent))
                # active row gets a subtle marker
                pygame.draw.circle(legend, accent, (pad // 2 + 2, y + lh // 2), 3)
                tx = pad
            else:
                c = dim; tx = pad
            legend.blit(font.render(text, True, c), (tx, y + 2))
            y += lh
        surf.blit(legend, (bx, by))

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

        # Circled "?" glossary button, just right of the title. Themed outline
        # that pops with the accent; opens the modal wiring glossary.
        self._help_btn = None
        if self._glossary is not None:
            r = max(11, header_h // 2 - 4)
            hcx = ox + 8 + t.get_width() + 16 + r
            hcy = oy + header_h // 2
            hov = (pygame.mouse.get_pos()[0] - hcx) ** 2 + \
                  (pygame.mouse.get_pos()[1] - hcy) ** 2 <= r * r
            if hov:
                pygame.draw.circle(surf, PANEL_DEEP(), (hcx, hcy), r)
            pygame.draw.circle(surf, PHOSPHOR(), (hcx, hcy), r, 2)
            qf = font_md.render("?", True, PHOSPHOR())
            surf.blit(qf, (hcx - qf.get_width() // 2,
                           hcy - qf.get_height() // 2))
            self._help_btn = pygame.Rect(hcx - r, hcy - r, 2 * r, 2 * r)

        # Bottom bar
        bar_h  = max(36, int(ph * 0.07))
        bar_y  = oy + ph - bar_h
        pygame.draw.rect(surf, PANEL(), (ox, bar_y, pw, bar_h))
        pygame.draw.line(surf, BORDER(), (ox, bar_y), (ox + pw, bar_y))

        # Status
        st = font_md.render(self._status[:55], True, TEXT_DIM())
        surf.blit(st, (ox + 8, bar_y + 4))

        # "Play Tour" link — persistent re-entry to PAW-Bot's circuit tour
        # (mirrors the "Play Intro" link). Placed lower-left, just ABOVE the
        # status line, so the player can review the circuit board any time.
        self._play_tour_btn = None
        if self._tour_enabled and self._tour_state in ("done", "off"):
            lbl = font_md.render("\u25b6 Play Tour", True, PHOSPHOR())
            pad_x = 10; btn_h = lbl.get_height() + 8
            tr = pygame.Rect(ox + 8, bar_y - btn_h - 6,
                             lbl.get_width() + pad_x * 2, btn_h)
            hov = tr.collidepoint(pygame.mouse.get_pos())
            pygame.draw.rect(surf, PANEL_DEEP() if hov else PANEL(),
                             tr, border_radius=4)
            pygame.draw.rect(surf, BORDER(), tr, 1, border_radius=4)
            surf.blit(lbl, (tr.centerx - lbl.get_width() // 2,
                            tr.centery - lbl.get_height() // 2))
            self._play_tour_btn = tr

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
        # While the circuit tour is being offered or is running, the board is
        # in "tour mode" — wiring interaction is suspended (tour buttons are
        # handled earlier in handle_event). This prevents the player from half-
        # wiring during the tour and keeps the two flows sequential.
        if self._tour_state in ("offer", "running"):
            return
        # Done button
        if (not self._suppress_done and
                self._done_btn and self._done_btn.collidepoint(pos)):
            wrong = self._wrong_wire_indices()
            if wrong:
                # Don't confirm yet — guide the player to delete the wrong
                # wire(s) first. They pulse amber with a scissors icon.
                self._show_delete_hints = True
                self._status = ("Remove the flashing wire — right-click it "
                                "(scissors). Then press Done.")
            else:
                self._confirmed = True
            return

        # Gain bar
        if self._gain_bar and self._gain_bar.collidepoint(pos):
            frac = (pos[0] - self._gain_bar.x) / self._gain_bar.width
            self._gain = round(max(0.1, min(3.0, frac * 3.0)), 2)
            return

        # Neuron trim-pot (rotary knob) hit test — use the knob geometry stored
        # during draw. Click anywhere on the knob disc to grab it; horizontal
        # drag turns it (handled in handle_event).
        for i, (kcx, kcy, kr) in self._neuron_knob.items():
            if (pos[0] - kcx) ** 2 + (pos[1] - kcy) ** 2 <= (kr + 3) ** 2:
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
            # If that cleared the last wrong wire, drop the delete-hint state.
            if self._show_delete_hints and not self._wrong_wire_indices():
                self._show_delete_hints = False

    def _add_wire(self, source: str, dest: str):
        # One-input-per-meter rule: a meter has a single header pin. If a
        # DIFFERENT source is already wired to this meter, reject the new wire
        # (the player must remove the existing one first). Re-clicking the SAME
        # source falls through to the color-cycle path below. Neurons and motors
        # are unaffected — they accept multiple inputs.
        dbank = self._bmap.get(dest)
        if dbank and dbank.get("kind") == "meter":
            for c in self._connections:
                if c.dest == dest and c.source != source:
                    self._status = (f"{dest} already has an input "
                                    f"({c.source}) — remove it first "
                                    f"(one pin per meter)")
                    return
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
            Connection("LDR·C1", "FL", "blue"),
            Connection("LDR·C2", "FR", "blue"),
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
