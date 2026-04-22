"""
valentinos/builder/wiring_editor.py
------------------------------------
Interactive wiring diagram editor for the Ana BBot.

Signal banks mirror the physical board: each signal (RL, E1, FL, etc.)
is represented as a small bordered rectangle containing anonymous pins.
The bank label is the signal name. Click anywhere inside a bank to wire
from/to that signal — identical to plugging a jumper into any pin in that
physical header.

Layout (left → right = signal flow):
  Column 0 : Sensor banks      (RL, RR, PL, PR)  — 2 pins each
  Column 1 : Neuron E/I banks  (E1-E6, I1-I6)    — 1 pin each
  Column 2 : Neuron bodies     (bias trimpot, drag LEFT/RIGHT)
  Column 3 : Neuron N/T banks  (N1-N6, T1-T4)    — 1 pin each
  Column 4 : Motor banks       (FL, BL, FR, BR)   — 4 pins each
             Meter banks       (M1, M2, M3)       — 2 pins each

Interaction:
  Left-click a source bank  → select it (highlighted border)
  Left-click a dest bank    → create blue wire if source selected
  Left-click a wire         → cycle color: blue→green→red→blue
  Right-click a wire        → remove it
  Drag neuron trimpot L/R   → adjust bias -4..+4
  Enter or Done button      → confirm
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

BG           = (10,  12,  10)
PANEL        = (14,  18,  14)
PANEL_DEEP   = ( 8,  10,   8)
BORDER       = (30,  58,  30)
TEXT         = (160, 220, 160)
TEXT_DIM     = ( 70, 110,  70)
TEXT_BRIGHT  = (220, 255, 220)
PHOSPHOR     = ( 51, 255,  87)
PHOSPHOR_MID = ( 30, 160,  50)
AMBER        = (255, 149,   0)
AMBER_DIM    = ( 80,  46,   0)
CYAN         = ( 60, 230, 230)
YELLOW       = (255, 230,  60)
WHITE        = (240, 240, 240)
GREY         = (100, 110, 100)
RED_NODE     = (220,  60,  60)
GREEN_NODE   = ( 60, 200,  80)

WIRE_COLORS = {"blue":  ( 80, 140, 255),
               "green": ( 60, 210,  80),
               "red":   (220,  60,  60)}
WIRE_WIDTHS = {"blue": 2, "green": 3, "red": 4}
WIRE_CYCLE  = ["blue", "green", "red"]

# Bank border color by role
BANK_COLOR = {
    "sensor":   AMBER,
    "neuron_E": GREEN_NODE,
    "neuron_I": RED_NODE,
    "neuron_N": CYAN,
    "neuron_T": YELLOW,
    "motor":    WHITE,
    "meter":    GREY,
}

# Pin dot color (slightly dimmer than border)
PIN_COLOR = {
    "sensor":   (180, 100,   0),
    "neuron_E": ( 30, 130,  40),
    "neuron_I": (140,  30,  30),
    "neuron_N": ( 30, 160, 160),
    "neuron_T": (180, 160,  20),
    "motor":    (160, 160, 160),
    "meter":    ( 70,  80,  70),
}

# ── Bank geometry ──────────────────────────────────────────────────────────────

PIN_R    =  3    # pin dot radius
PIN_STEP =  9    # spacing between pin dots within a bank
PAD      =  5    # padding inside bank border

def _bank_rect(pins: int, cx: int, cy: int,
               horizontal: bool = False) -> pygame.Rect:
    """
    Return the pygame.Rect for a bank of `pins` pins centred at (cx, cy).
    horizontal=False → pins arranged vertically (default)
    horizontal=True  → pins in a row (used for neuron E/I which are tight)
    """
    if horizontal:
        w = pins * PIN_STEP + PAD * 2
        h = PIN_R * 2 + PAD * 2
    else:
        w = PIN_R * 2 + PAD * 2
        h = pins * PIN_STEP + PAD * 2
    return pygame.Rect(cx - w // 2, cy - h // 2, w, h)


def _pin_positions(rect: pygame.Rect, pins: int,
                   horizontal: bool = False) -> list[tuple[int, int]]:
    """Return pixel positions of pin dots inside a bank rect."""
    pts = []
    if horizontal:
        y = rect.centery
        x0 = rect.x + PAD + PIN_R
        for i in range(pins):
            pts.append((x0 + i * PIN_STEP, y))
    else:
        x = rect.centerx
        y0 = rect.y + PAD + PIN_R
        for i in range(pins):
            pts.append((x, y0 + i * PIN_STEP))
    return pts


# ── Layout ─────────────────────────────────────────────────────────────────────

# Window size — computed at first use, after pygame.init()
WW, WH = 1060, 700   # defaults; overridden at runtime by _get_window_size()


def _get_window_size() -> tuple[int, int]:
    import sys
    info      = pygame.display.Info()
    taskbar_h = {"win32": 48, "darwin": 50}.get(sys.platform, 52)
    w = max(900, info.current_w  - 8 * 2)
    h = max(600, info.current_h  - taskbar_h - 8 * 2)
    return w, h

# ── Layout constants ───────────────────────────────────────────────────────────
#
# Board view: front of robot = LEFT edge, rear = RIGHT edge.
# Top of board = right side of robot. Bottom = left side of robot.
#
#   top    PL·····RL          neurons          FR BR   ← right of robot
#          ··                                          
#   centre             (neurons N1-N6)                 
#          ··                                          
#   bottom PR·····RR          neurons          FL BL   ← left of robot
#
# P* (LDR) at front corners — flush against top/bottom edges.
# R* (IR)  same x as P*, pulled inward toward vertical centre.
# F*/B*    at rear — FR/BR top-right, FL/BL bottom-right.
# B* immediately right of corresponding F*.

# Usable vertical range: ~70 (below header) to ~640 (above help bar)
_Y_TOP    =  70    # top edge of usable area
_Y_BOT    = 640    # bottom edge of usable area
_Y_MID    = (_Y_TOP + _Y_BOT) // 2   # 355

# Sensor x — single column for all sensors (same x for P* and R*)
COL_SENSOR = 65

# P* (LDR) — flush against top/bottom edges
PL_Y = _Y_TOP + 30    # 100 — top-left corner
PR_Y = _Y_BOT - 30    # 610 — bottom-left corner

# R* (IR)  — same x, pulled 20% toward centre from each edge
_range   = _Y_BOT - _Y_TOP          # 570
RL_Y = _Y_TOP + int(_range * 0.20)  # 184 — inboard from PL
RR_Y = _Y_BOT - int(_range * 0.20)  # 526 — inboard from PR

# Neuron columns
COL_EI     = 240
COL_NEURON = 415
COL_NT     = 595

# Motor columns — B* immediately right of F* (16px gap)
COL_MOTOR_F  = 830   # F* (forward) inputs
COL_MOTOR_B  = 885   # B* (backward) inputs — right of F*
COL_METER    = 150   # Meters — between sensor column and neuron inputs

# Motor y — 20% from top (right of robot) and 20% from bottom (left)
FR_Y = _Y_TOP + int(_range * 0.20)  # 184  right side → FR/BR
FL_Y = _Y_BOT - int(_range * 0.20)  # 526  left  side → FL/BL

TRIMPOT_W = 54
TRIMPOT_H = 11


def _neuron_y(idx: int) -> int:
    # 6 neurons spread evenly across usable vertical range
    spacing = (_Y_BOT - _Y_TOP) // 7
    return _Y_TOP + spacing * idx


# ── Bank registry ──────────────────────────────────────────────────────────────

def _build_banks() -> list[dict]:
    banks = []

    def add(name, role, kind, pins, cx, cy, horiz=False):
        rect = _bank_rect(pins, cx, cy, horiz)
        banks.append({"name": name, "role": role, "kind": kind,
                       "pins": pins, "cx": cx, "cy": cy,
                       "rect": rect, "horiz": horiz})

    # ── Sensors ───────────────────────────────────────────────────────────
    # P* (LDR) at front corners, flush against top/bottom
    # R* (IR)  same x, pulled toward vertical centre
    # PR/RR at top (right side of robot = top of board)
    # PL/RL at bottom (left side of robot = bottom of board)
    add("PR", "sensor", "source", 2, COL_SENSOR, PL_Y)   # top corner
    add("RR", "sensor", "source", 2, COL_SENSOR, RL_Y)   # inboard from PR
    add("RL", "sensor", "source", 2, COL_SENSOR, RR_Y)   # inboard from PL
    add("PL", "sensor", "source", 2, COL_SENSOR, PR_Y)   # bottom corner

    # ── Neuron E/I inputs ─────────────────────────────────────────────────
    for i in range(1, 7):
        cy = _neuron_y(i)
        add(f"E{i}", "neuron_E", "dest", 1, COL_EI, cy - 17)
        add(f"I{i}", "neuron_I", "dest", 1, COL_EI, cy + 17)

    # ── Neuron N/T outputs ────────────────────────────────────────────────
    for i in range(1, 7):
        cy = _neuron_y(i)
        add(f"N{i}", "neuron_N", "source", 1, COL_NT, cy - 17)
        if i <= 4:
            add(f"T{i}", "neuron_T", "source", 1, COL_NT, cy + 17)

    # ── Motors ────────────────────────────────────────────────────────────
    # FR/BR top-right (right side of robot), FL/BL bottom-right (left side)
    # B* column immediately right of F* column
    add("FR", "motor", "dest", 4, COL_MOTOR_F, FR_Y)
    add("BR", "motor", "dest", 4, COL_MOTOR_B, FR_Y)
    add("FL", "motor", "dest", 4, COL_MOTOR_F, FL_Y)
    add("BL", "motor", "dest", 4, COL_MOTOR_B, FL_Y)

    # ── Meters ────────────────────────────────────────────────────────────
    # M3 top, M2 middle, M1 bottom — matches physical board orientation
    add("M3", "meter", "dest", 2, COL_METER, _Y_MID - 40)
    add("M2", "meter", "dest", 2, COL_METER, _Y_MID)
    add("M1", "meter", "dest", 2, COL_METER, _Y_MID + 40)

    return banks


# ── Editor ─────────────────────────────────────────────────────────────────────

class WiringEditor:

    def __init__(self, initial_config: VehicleConfig | None = None,
                 title: str = "Vehicle Wiring — Valentino's Vehicles"):
        self._title  = title
        self._banks  = _build_banks()
        self._bmap   = {b["name"]: b for b in self._banks}

        cfg = initial_config or VehicleConfig()
        self._connections: list[Connection] = list(cfg.connections)
        self._biases: dict[str, float]      = dict(cfg.neuron_biases)
        self._gain:   float                 = cfg.gain

        self._sel_source: str | None = None   # bank name currently selected
        self._hover_wire: int | None = None
        self._dragging_neuron: int | None = None   # 1-based
        self._drag_start_x:    int   = 0
        self._drag_start_bias: float = 0.0
        self._confirmed: bool  = False
        self._cancelled: bool  = False
        self._done_btn: pygame.Rect | None = None
        self._status = "Click a source bank to begin wiring"

    # ── Public entry ──────────────────────────────────────────────────────

    def run(self) -> VehicleConfig | None:
        pygame.init()
        global WW, WH
        WW, WH = _get_window_size()
        screen = pygame.display.set_mode((WW, WH))
        pygame.display.set_caption(self._title)
        clock  = pygame.time.Clock()
        font_sm = self._font(13)
        font_md = self._font(15)
        font_hd = self._font(19)

        running = True
        result  = None

        while running:
            mx, my = pygame.mouse.get_pos()
            self._hover_wire = self._wire_near(mx, my)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_RETURN:
                        result  = self._build_config()
                        running = False
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        self._left_click(event.pos)
                    elif event.button == 3:
                        self._right_click(event.pos)
                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button == 1:
                        self._dragging_neuron = None
                elif event.type == pygame.MOUSEMOTION:
                    if self._dragging_neuron is not None:
                        dx  = event.pos[0] - self._drag_start_x
                        key = f"N{self._dragging_neuron}"
                        new = self._drag_start_bias + dx * 0.06
                        self._biases[key] = max(-4.0, min(4.0, new))

            if self._confirmed:
                result  = self._build_config()
                running = False
            elif self._cancelled:
                running = False   # result stays None

            # ── Draw ──────────────────────────────────────────────────────
            screen.fill(BG)
            self._draw_columns(screen, font_sm)
            self._draw_neuron_bodies(screen, font_sm)
            self._draw_wires(screen)
            self._draw_banks(screen, font_sm)
            self._draw_pending(screen, mx, my)
            self._draw_ui(screen, font_md, font_hd)

            pygame.display.flip()
            clock.tick(60)

        # Do NOT call pygame.quit() here — the simulator owns the pygame
        # lifecycle. We just close our window and return.
        return result

    # ── Font helper ───────────────────────────────────────────────────────

    def _font(self, size: int) -> pygame.font.Font:
        for name in ("Courier New", "Courier", "monospace"):
            try:
                f = pygame.font.SysFont(name, size)
                if f:
                    return f
            except Exception:
                pass
        return pygame.font.Font(None, size)

    # ── Drawing ───────────────────────────────────────────────────────────

    def _draw_columns(self, surf, font):
        # Column headers
        headers = [
            (COL_SENSOR,  "SENSORS"),
            (COL_METER,   "METERS"),
            (COL_EI,      "INPUTS"),
            (COL_NEURON,  "NEURONS"),
            (COL_NT,      "OUTPUTS"),
            ((COL_MOTOR_F + COL_MOTOR_B) // 2, "MOTORS"),
        ]
        for cx, lbl in headers:
            t = font.render(lbl, True, TEXT_DIM)
            surf.blit(t, (cx - t.get_width() // 2, 30))

        # Vertical separators
        for cx in (COL_EI - 30, COL_NT - 30):
            pygame.draw.line(surf, BORDER, (cx, 58), (cx, WH - 62), 1)

        # Sensor position labels — PR/RR top, RL/PL bottom
        for label, y in [("PR", PL_Y), ("RR", RL_Y),
                          ("RL", RR_Y), ("PL", PR_Y)]:
            t = font.render(label, True, AMBER)
            surf.blit(t, (COL_SENSOR - t.get_width() - 6,
                          y - t.get_height() // 2))

        # Motor F/B sub-labels
        for cx, lbl in [(COL_MOTOR_F, "F"), (COL_MOTOR_B, "B")]:
            t = font.render(lbl, True, BORDER)
            surf.blit(t, (cx - t.get_width()//2, 50))

        # Motor R/L position labels
        for label, y in [("R", FR_Y), ("L", FL_Y)]:
            t = font.render(label, True, BORDER)
            surf.blit(t, ((COL_MOTOR_F + COL_MOTOR_B)//2 - t.get_width()//2,
                          y - 28))

    def _draw_neuron_bodies(self, surf, font):
        for i in range(1, 7):
            cy    = _neuron_y(i)
            has_T = (i <= 4)

            # Neuron triangle (points right)
            pts = [(COL_NEURON - 32, cy - 26),
                   (COL_NEURON - 32, cy + 26),
                   (COL_NEURON + 20, cy)]
            pygame.draw.polygon(surf, PANEL_DEEP, pts)
            pygame.draw.polygon(surf, BORDER, pts, 1)

            lbl = font.render(f"N{i}", True, TEXT)
            surf.blit(lbl, (COL_NEURON - 16,
                            cy - lbl.get_height() // 2))

            # Bias trimpot bar (below triangle, drag left/right)
            bias  = self._biases.get(f"N{i}", 0.0)
            tr    = pygame.Rect(COL_NEURON - TRIMPOT_W // 2,
                                cy + 30, TRIMPOT_W, TRIMPOT_H)
            pygame.draw.rect(surf, PANEL_DEEP, tr, border_radius=3)
            pygame.draw.rect(surf, BORDER, tr, 1, border_radius=3)

            # Fill from centre
            centre_x = tr.x + tr.width // 2
            frac     = bias / 4.0   # -1..+1
            bar_w    = int(abs(frac) * tr.width // 2)
            if bar_w > 0:
                col = PHOSPHOR_MID if bias >= 0 else AMBER_DIM
                bx  = centre_x if bias >= 0 else centre_x - bar_w
                pygame.draw.rect(surf, col,
                                 pygame.Rect(bx, tr.y, bar_w, tr.height),
                                 border_radius=2)

            # Centre tick
            pygame.draw.line(surf, BORDER,
                             (centre_x, tr.y), (centre_x, tr.bottom), 1)

            # Bias value
            bv = font.render(f"{bias:+.1f}", True, TEXT_DIM)
            surf.blit(bv, (tr.right + 4, tr.y))

            # T label
            if has_T:
                tl = font.render("T", True, YELLOW)
                surf.blit(tl, (COL_NT + 9, cy + 11))

    def _draw_banks(self, surf, font):
        for bank in self._banks:
            name  = bank["name"]
            role  = bank["role"]
            rect  = bank["rect"]
            horiz = bank["horiz"]
            pins  = bank["pins"]
            sel   = (name == self._sel_source)

            border_col = BANK_COLOR[role]
            pin_col    = PIN_COLOR[role]

            # Highlight if selected
            if sel:
                glow = pygame.Rect(rect.x - 3, rect.y - 3,
                                   rect.width + 6, rect.height + 6)
                pygame.draw.rect(surf, TEXT_BRIGHT, glow, 2, border_radius=5)

            # Bank background + border
            pygame.draw.rect(surf, PANEL_DEEP, rect, border_radius=3)
            pygame.draw.rect(surf, border_col, rect, 1, border_radius=3)

            # Pin dots
            for px, py in _pin_positions(rect, pins, horiz):
                pygame.draw.circle(surf, pin_col, (px, py), PIN_R)

            # Labels:
            # Sensors (left side) → label drawn in _draw_columns, skip here
            # Motors/meters (right side) → label above
            # Neurons E/I and N/T (centre) → label above
            lbl = font.render(name, True, border_col if not sel else TEXT_BRIGHT)
            if role == "sensor":
                pass   # labels drawn in _draw_columns as part of column guides
            elif role in ("motor", "meter"):
                surf.blit(lbl, (rect.centerx - lbl.get_width() // 2,
                                rect.y - lbl.get_height() - 2))
            else:
                surf.blit(lbl, (rect.centerx - lbl.get_width() // 2,
                                rect.y - lbl.get_height() - 2))

    def _draw_wires(self, surf):
        for idx, conn in enumerate(self._connections):
            src_b = self._bmap.get(conn.source)
            dst_b = self._bmap.get(conn.dest)
            if not src_b or not dst_b:
                continue
            p1  = self._wire_exit(src_b, "source")
            p2  = self._wire_exit(dst_b, "dest")
            col = WIRE_COLORS[conn.color]
            wid = WIRE_WIDTHS[conn.color]
            if idx == self._hover_wire:
                col = tuple(min(255, c + 60) for c in col)
                wid += 2
            self._bezier(surf, p1, p2, col, wid)

    def _wire_exit(self, bank: dict, kind: str) -> tuple[int, int]:
        """Return the pixel point where a wire connects to a bank."""
        rect = bank["rect"]
        # Sources always exit from the right edge
        # Dests always enter from the left edge
        # Exception: neuron outputs (N/T) are in the centre-right area,
        # their wires should exit right; neuron inputs (E/I) enter left.
        if kind == "source":
            return (rect.right, rect.centery)
        else:
            return (rect.left, rect.centery)

    def _draw_pending(self, surf, mx, my):
        if self._sel_source is None:
            return
        b = self._bmap.get(self._sel_source)
        if not b:
            return
        p1 = self._wire_exit(b, "source")
        self._bezier(surf, p1, (mx, my), WIRE_COLORS["blue"], 1)

    def _bezier(self, surf, p1, p2, color, width):
        x1, y1 = p1
        x2, y2 = p2
        dx     = max(40, abs(x2 - x1) * 0.45)
        ctrl1  = (x1 + dx, y1)
        ctrl2  = (x2 - dx, y2)
        steps  = max(24, int(abs(x2 - x1) / 4))
        pts    = []
        for i in range(steps + 1):
            t  = i / steps
            u  = 1 - t
            bx = u**3*x1 + 3*u**2*t*ctrl1[0] + 3*u*t**2*ctrl2[0] + t**3*x2
            by = u**3*y1 + 3*u**2*t*ctrl1[1] + 3*u*t**2*ctrl2[1] + t**3*y2
            pts.append((int(bx), int(by)))
        if len(pts) >= 2:
            pygame.draw.lines(surf, color, False, pts, width)

    def _draw_ui(self, surf, font_md, font_hd):
        # Title bar
        pygame.draw.rect(surf, PANEL, (0, 0, WW, 26))
        pygame.draw.line(surf, BORDER, (0, 26), (WW, 26))
        surf.blit(font_hd.render("Vehicle Wiring Editor", True, TEXT_BRIGHT),
                  (12, 4))
        ct = font_md.render(
            f"Connections: {len(self._connections)}   GAIN: {self._gain:.2f}",
            True, TEXT_DIM)
        surf.blit(ct, (WW - ct.get_width() - 12, 5))

        # Bottom bar
        pygame.draw.rect(surf, PANEL, (0, WH - 58, WW, 58))
        pygame.draw.line(surf, BORDER, (0, WH - 58), (WW, WH - 58))
        # Close button — bottom left, separated from Done
        close_r = pygame.Rect(12, WH - 32, 100, 24)
        mx2c, my2c = pygame.mouse.get_pos()
        hov_c = close_r.collidepoint(mx2c, my2c)
        pygame.draw.rect(surf, PANEL_DEEP if not hov_c else (40, 20, 20),
                         close_r, border_radius=4)
        pygame.draw.rect(surf, BORDER, close_r, 1, border_radius=4)
        cl = font_md.render("Close  [Esc]", True, TEXT_DIM)
        surf.blit(cl, (close_r.centerx - cl.get_width()//2,
                       close_r.centery - cl.get_height()//2))
        self._close_btn = close_r

        lines = [
            "Click source bank → dest bank to wire  |  Click wire: cycle weight  |  Right-click wire: remove",
            "Drag bias trimpot LEFT / RIGHT  |  Click GAIN bar to adjust  |  Enter or Done to confirm",
        ]
        for i, line in enumerate(lines):
            surf.blit(font_md.render(line, True, TEXT_DIM),
                      (120, WH - 54 + i * 20))

        # GAIN bar
        gain_r = pygame.Rect(WW - 170, WH - 54, 158, 16)
        pygame.draw.rect(surf, PANEL_DEEP, gain_r, border_radius=3)
        pygame.draw.rect(surf, BORDER,     gain_r, 1, border_radius=3)
        fw = int(gain_r.width * (self._gain / 3.0))
        if fw > 0:
            pygame.draw.rect(surf, PHOSPHOR_MID,
                             pygame.Rect(gain_r.x, gain_r.y, fw, gain_r.height),
                             border_radius=3)
        surf.blit(font_md.render(f"GAIN {self._gain:.2f}", True, TEXT),
                  (gain_r.x + 4, gain_r.y))
        self._gain_bar = gain_r

        # Done button
        btn = pygame.Rect(WW - 170, WH - 32, 158, 24)
        mx2, my2 = pygame.mouse.get_pos()
        hov = btn.collidepoint(mx2, my2)
        pygame.draw.rect(surf, PHOSPHOR_MID if hov else PANEL_DEEP,
                         btn, border_radius=4)
        pygame.draw.rect(surf, PHOSPHOR, btn, 1, border_radius=4)
        bl = font_md.render("Done  [Enter]", True, TEXT_BRIGHT)
        surf.blit(bl, (btn.centerx - bl.get_width() // 2,
                       btn.centery - bl.get_height() // 2))
        self._done_btn = btn

    # ── Interaction ───────────────────────────────────────────────────────

    def _bank_at(self, pos) -> dict | None:
        """Return the bank whose rect contains pos, or None."""
        for bank in self._banks:
            if bank["rect"].collidepoint(pos):
                return bank
        return None

    def _wire_near(self, mx, my, threshold=8) -> int | None:
        for idx, conn in enumerate(self._connections):
            sb = self._bmap.get(conn.source)
            db = self._bmap.get(conn.dest)
            if not sb or not db:
                continue
            p1 = self._wire_exit(sb, "source")
            p2 = self._wire_exit(db, "dest")
            if self._near_bezier(mx, my, p1, p2, threshold):
                return idx
        return None

    def _near_bezier(self, px, py, p1, p2, thr) -> bool:
        x1, y1 = p1
        x2, y2 = p2
        dx     = max(40, abs(x2 - x1) * 0.45)
        ctrl1  = (x1 + dx, y1)
        ctrl2  = (x2 - dx, y2)
        steps  = max(24, int(abs(x2 - x1) / 4))
        for i in range(steps + 1):
            t  = i / steps
            u  = 1 - t
            bx = u**3*x1 + 3*u**2*t*ctrl1[0] + 3*u*t**2*ctrl2[0] + t**3*x2
            by = u**3*y1 + 3*u**2*t*ctrl1[1] + 3*u*t**2*ctrl2[1] + t**3*y2
            if math.hypot(px - bx, py - by) < thr:
                return True
        return False

    def _left_click(self, pos):
        # Close button (cancel and exit)
        if hasattr(self, '_close_btn') and self._close_btn.collidepoint(pos):
            # result stays None — caller treats as cancelled
            self._cancelled = True
            return

        # Done button
        if self._done_btn and self._done_btn.collidepoint(pos):
            self._confirmed = True
            return

        # GAIN bar
        if hasattr(self, '_gain_bar') and self._gain_bar.collidepoint(pos):
            frac = (pos[0] - self._gain_bar.x) / self._gain_bar.width
            self._gain = round(max(0.1, min(3.0, frac * 3.0)), 2)
            return

        # Trimpot drag (below each neuron triangle)
        for i in range(1, 7):
            cy = _neuron_y(i)
            tr = pygame.Rect(COL_NEURON - TRIMPOT_W // 2,
                             cy + 30, TRIMPOT_W, TRIMPOT_H + 8)
            if tr.collidepoint(pos):
                self._dragging_neuron = i
                self._drag_start_x    = pos[0]
                self._drag_start_bias = self._biases.get(f"N{i}", 0.0)
                return

        # Wire click (cycle or implicit hit)
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
        kind = bank["kind"]

        if self._sel_source is None:
            if kind == "source":
                self._sel_source = name
                self._status = f"Wiring from {name} — click a destination bank"
        else:
            if name == self._sel_source:
                self._sel_source = None
                self._status = "Deselected"
            elif kind == "dest":
                self._add_wire(self._sel_source, name)
                self._sel_source = None
            elif kind == "source":
                self._sel_source = name
                self._status = f"Wiring from {name} — click a destination bank"

    def _right_click(self, pos):
        w = self._wire_near(*pos, threshold=10)
        if w is not None:
            removed = self._connections.pop(w)
            self._status = f"Removed {removed.source}→{removed.dest}"

    def _add_wire(self, source: str, dest: str):
        # If already connected, cycle color
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
