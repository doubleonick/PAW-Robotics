"""
engine/cr_logo.py
-------------------
"PAW Robotics" logo (legacy "Ci" monogram; unused).

The C and i are bold, blocky letterforms whose outer edges trace the
perimeter of a shared circle.  The C occupies roughly the left 280° of
the circle; the i (stem + tittle) sits in the remaining 80° gap on the
right side.

draw_logo_box(surf, rect, padding) draws the logo centred inside rect.
draw_logo(surf, cx, cy, r)         draws directly at centre (cx,cy), radius r.

Colors are read from engine.theme so the logo always matches the
current theme.
"""

import pygame
import math


def draw_logo(surf: pygame.Surface,
              cx: int, cy: int, r: int,
              color=None) -> None:
    """
    Draw the Ci logo centred at (cx, cy) with outer radius r.
    color defaults to the current theme's primary (PHOSPHOR) color.
    """
    import engine.theme as T
    col = color or T.PHOSPHOR

    # ── Stroke geometry ────────────────────────────────────────────────────────
    # The letter stroke is ~22% of the radius — big, chunky.
    stroke   = max(3, int(r * 0.22))
    r_outer  = r                          # outer edge of both letters
    r_inner  = r - stroke                 # inner edge of letter stroke

    # ── C — thick arc, left ~280° ─────────────────────────────────────────────
    # Gap is centred on the right (0°).  Half-gap = 40° each side.
    HALF_GAP_DEG = 40
    c_start_deg  =  HALF_GAP_DEG          # lower gap edge
    c_end_deg    = 360 - HALF_GAP_DEG     # upper gap edge

    # Draw the C as a filled annular sector (polygon: outer arc + reversed inner arc)
    steps          = 80
    arc_pts_outer  = []
    arc_pts_inner  = []
    span           = c_end_deg - c_start_deg   # ~280 degrees

    for i in range(steps + 1):
        ang_deg = c_start_deg + span * i / steps
        ang_rad = math.radians(ang_deg)
        co, si  = math.cos(ang_rad), math.sin(ang_rad)
        arc_pts_outer.append((cx + r_outer * co, cy - r_outer * si))
        arc_pts_inner.append((cx + r_inner * co, cy - r_inner * si))

    poly = arc_pts_outer + list(reversed(arc_pts_inner))
    if len(poly) >= 3:
        pygame.draw.polygon(surf, col, [(int(x), int(y)) for x, y in poly])

    # ── i — right side of the circle ─────────────────────────────────────────
    # The i fills the gap (±HALF_GAP_DEG from the right).
    # Stem half-width fits inside the gap with a small margin.
    stem_hw = max(2, int(r_outer * math.sin(math.radians(HALF_GAP_DEG)) * 0.55))
    stem_x  = cx + int(r_outer * math.cos(math.radians(HALF_GAP_DEG / 2)))

    # y-coords of the gap edges at the stem_x column
    gap_top_y = cy - int(r_outer * math.sin(math.radians(HALF_GAP_DEG)))
    gap_bot_y = cy + int(r_outer * math.sin(math.radians(HALF_GAP_DEG)))

    # Tittle (dot) — sits just above the top of the stem
    tittle_gap = max(2, int(r * 0.08))
    tittle_r   = max(3, stem_hw)
    tittle_cy  = gap_top_y - tittle_gap - tittle_r

    # Stem — rectangular block filling the gap vertically
    stem_rect = pygame.Rect(
        stem_x - stem_hw,
        gap_top_y,
        stem_hw * 2,
        gap_bot_y - gap_top_y)

    pygame.draw.rect(surf, col, stem_rect)
    pygame.draw.circle(surf, col, (stem_x, tittle_cy), tittle_r)


def draw_logo_box(surf: pygame.Surface,
                  rect: pygame.Rect,
                  padding: int = 8) -> None:
    """Draw the Ci logo centred inside rect with padding."""
    inner = rect.inflate(-padding * 2, -padding * 2)
    r     = min(inner.width, inner.height) // 2
    if r < 8:
        return
    cx = inner.centerx
    cy = inner.centery
    draw_logo(surf, cx, cy, r)
