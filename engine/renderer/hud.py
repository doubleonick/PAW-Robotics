"""
engine/renderer/hud.py
------------------------
Behavior HUD panel — color-coordinated by sensor/behavior type.

Color grammar:
  Panel border  — robot color (ownership: red=A, blue=B)
  Behavior block — sensor/behavior color (what is happening)
  Sensor bars   — sensor color (IR = translucent pink-red,
                               contact = cyan,
                               light = pale yellow,
                               cruise = green)

Sensor/behavior color map:
  IR / proximity  → Avoid Object, Approach Object  → PINK_RED  (255,120,140)
  Contact         → Escape Front, Escape Rear       → CYAN      ( 60,200,220)
  Light / LDR     → Seek Light, Avoid Light         → PALE_YEL  (255,240,180)
  Always-true     → Cruise Straight, Cruise Arc     → GREEN     (100,200,100)
"""

from __future__ import annotations
from dataclasses import dataclass, field
import pygame

# ── Sensor/behavior color palette ────────────────────────────────────────────
PINK_RED  = (255, 120, 140)   # IR / proximity — translucent bars
CYAN      = ( 60, 200, 220)   # Contact — opaque
PALE_YEL  = (255, 240, 180)   # Light / LDR — opaque, amber text
GREEN     = (100, 200, 100)   # Cruise / always-true — opaque

# Map behavior state name → sensor color
BEHAVIOR_COLORS = {
    "AVOID":   PINK_RED,
    "SEEK":    PALE_YEL,
    "ESCAPE":  CYAN,
    "CRUISE":  GREEN,
    # Legacy / other states
    "DRIVE":   GREEN,
    "PRESS":   PINK_RED,
    "HOLD":    CYAN,
    "RESET":   (160, 140, 200),
}
DEFAULT_COLOR = (160, 160, 180)

# Map sensor label prefix → color
SENSOR_COLORS = {
    "IR":      PINK_RED,
    "FRONT":   CYAN,
    "REAR":    CYAN,
    "CONTACT": CYAN,
    "LDR":     PALE_YEL,
    "LIGHT":   PALE_YEL,
}


def _sensor_color(label: str) -> tuple:
    """Return the color for a sensor bar based on its label."""
    upper = label.upper()
    for key, col in SENSOR_COLORS.items():
        if key in upper:
            return col
    return DEFAULT_COLOR


def _dim(col: tuple, factor: float = 0.3) -> tuple:
    return tuple(max(0, min(255, int(c * factor))) for c in col)


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class SensorBar:
    label:      str
    value:      float
    threshold:  float
    value_min:  float = 0.0
    value_max:  float = 1023.0
    triggered:  bool  = False
    higher_bad: bool  = True


@dataclass
class HUDInfo:
    behavior:     str
    trigger:      str
    sensors:      list[SensorBar] = field(default_factory=list)
    robot_label:  str   = ""          # "A", "B", etc.
    robot_color:  tuple = (60,160,230) # robot body color


# ── HUD Panel ─────────────────────────────────────────────────────────────────

class HUDPanel:
    """
    Draws one robot's behavior HUD panel.
    Panel border uses robot_color; internals use sensor/behavior colors.
    """

    BORDER_W = 3   # robot-color border width

    def __init__(self, panel_w: int, panel_h: int):
        self._w = panel_w
        self._h = panel_h
        self._font_lg = pygame.font.SysFont("consolas", 26, bold=True)
        self._font_md = pygame.font.SysFont("consolas", 15)
        self._font_sm = pygame.font.SysFont("consolas", 13)

    def draw(self, surf: pygame.Surface, info: HUDInfo,
             offset_x: int = 0, fps: float = 0.0) -> None:
        w   = self._w
        h   = self._h
        bw  = self.BORDER_W
        pad = 14

        beh_col    = BEHAVIOR_COLORS.get(info.behavior, DEFAULT_COLOR)
        robot_col  = info.robot_color

        # ── Panel background ──────────────────────────────────────────────────
        bg = pygame.Surface((w, h))
        bg.fill((14, 16, 22))
        surf.blit(bg, (offset_x, 0))

        # Robot-color border (left and right edges)
        pygame.draw.rect(surf, robot_col,
                         pygame.Rect(offset_x, 0, w, h), bw)

        x = offset_x + pad + bw

        # ── Robot label strip ─────────────────────────────────────────────────
        y = bw + 6
        strip_h = 34
        strip = pygame.Surface((w - bw*2, strip_h), pygame.SRCALPHA)
        strip.fill((*robot_col, 60))
        surf.blit(strip, (offset_x + bw, y - 4))

        if info.robot_label:
            lbl = self._font_lg.render(
                f"ROBOT  {info.robot_label}", True, robot_col)
            surf.blit(lbl, (offset_x + w//2 - lbl.get_width()//2, y))
        y += strip_h + 4

        # FPS (small, dim)
        fps_t = self._font_sm.render(f"{fps:.0f} fps", True, (60, 70, 90))
        surf.blit(fps_t, (offset_x + w - fps_t.get_width() - pad, y - strip_h))

        # ── Behavior name block ───────────────────────────────────────────────
        name_surf = self._font_lg.render(info.behavior, True, beh_col)
        block_r   = pygame.Rect(offset_x + bw + 2, y,
                                w - bw*2 - 4, name_surf.get_height() + 10)
        # Dark tinted background using behavior color
        block_bg_s = pygame.Surface(
            (block_r.width, block_r.height), pygame.SRCALPHA)
        block_bg_s.fill((*_dim(beh_col, 0.18), 220))
        surf.blit(block_bg_s, (block_r.x, block_r.y))
        pygame.draw.rect(surf, _dim(beh_col, 0.5), block_r, 1)
        surf.blit(name_surf,
                  (offset_x + w//2 - name_surf.get_width()//2, y + 5))
        y += block_r.height + 8

        # ── Trigger reason ────────────────────────────────────────────────────
        if info.trigger:
            # Wrap if too long
            words = info.trigger.split()
            line, lines = "", []
            for word in words:
                test = (line + " " + word).strip()
                if self._font_sm.size(test)[0] <= w - pad*2 - bw*2:
                    line = test
                else:
                    if line: lines.append(line)
                    line = word
            if line: lines.append(line)
            for ln in lines:
                t = self._font_sm.render(ln, True, _dim(beh_col, 1.4))
                surf.blit(t, (x, y))
                y += 16
        y += 4

        # ── Divider ───────────────────────────────────────────────────────────
        pygame.draw.line(surf, (35, 40, 56),
                         (offset_x + 8, y), (offset_x + w - 8, y), 1)
        y += 10

        # ── Sensor bars ───────────────────────────────────────────────────────
        bar_w   = w - pad*2 - bw*2
        bar_h   = 16
        lbl_h   = 15
        row_gap = 10
        ir_alpha = 160   # translucent fill for IR bars

        for sb in info.sensors:
            scol = _sensor_color(sb.label)
            is_ir = "IR" in sb.label.upper()

            # Label
            lbl_col = scol if sb.triggered else _dim(scol, 0.55)
            lbl_t   = self._font_sm.render(sb.label, True, lbl_col)
            surf.blit(lbl_t, (x, y))

            # Value (right-aligned)
            val_t = self._font_sm.render(
                f"{int(sb.value)}",
                True, scol if sb.triggered else (80, 90, 110))
            surf.blit(val_t,
                      (offset_x + w - bw - pad - val_t.get_width(), y))
            y += lbl_h + 2

            # Bar track
            track_r = pygame.Rect(x, y, bar_w, bar_h)
            pygame.draw.rect(surf, (24, 28, 40), track_r, border_radius=3)

            # Fill
            span   = max(0.001, sb.value_max - sb.value_min)
            frac   = max(0.0, min(1.0, (sb.value - sb.value_min) / span))
            fill_w = int(bar_w * frac)
            if fill_w > 0:
                if is_ir:
                    # Translucent IR bar
                    fs = pygame.Surface((fill_w, bar_h), pygame.SRCALPHA)
                    fs.fill((*scol, ir_alpha if sb.triggered else 60))
                    surf.blit(fs, (x, y))
                    pygame.draw.rect(surf, scol,
                                     pygame.Rect(x, y, fill_w, bar_h),
                                     1, border_radius=3)
                else:
                    fill_c = scol if sb.triggered else _dim(scol, 0.4)
                    pygame.draw.rect(surf, fill_c,
                                     pygame.Rect(x, y, fill_w, bar_h),
                                     border_radius=3)

            # Threshold marker
            thr_frac = max(0.0, min(1.0,
                           (sb.threshold - sb.value_min) / span))
            thr_x    = x + int(bar_w * thr_frac)
            pygame.draw.line(surf, (220, 200, 80),
                             (thr_x, y - 2), (thr_x, y + bar_h + 2), 2)
            thr_lbl = self._font_sm.render(
                f"{int(sb.threshold)}", True, (140, 120, 50))
            surf.blit(thr_lbl,
                      (thr_x - thr_lbl.get_width()//2, y + bar_h + 2))

            y += bar_h + 18 + row_gap
