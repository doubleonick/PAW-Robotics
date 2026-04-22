"""
robosim/layout.py
------------------
Layout manager for Curious Robotics game screens.

Screen is divided into:
  - Left panel (PANEL_FRAC of total width)
      - Controls region (top, adapts to content)
      - Narrative region (bottom, compresses from top as controls grow)
  - Arena region (right, full height)

All measurements in pixels, computed from window size at init.
"""

import pygame


PANEL_FRAC    = 0.32    # left panel as fraction of total width
MIN_NARR_H    = 80      # minimum narrative region height in pixels
CTRL_MIN_FRAC = 0.30    # controls always at least this fraction of panel h
CTRL_MAX_FRAC = 0.70    # controls never more than this fraction of panel h


class Layout:
    """
    Computes and exposes named rects for each screen region.
    Call update(ctrl_h) each frame with the measured controls height.
    """

    def __init__(self, ww: int, wh: int):
        self.ww = ww
        self.wh = wh
        self.panel_w = int(ww * PANEL_FRAC)
        self._ctrl_h = int(wh * 0.50)   # default 50/50
        self._update_rects()

    def update(self, ctrl_h: int) -> None:
        """Call with actual measured height of controls content."""
        min_h = int(self.wh * CTRL_MIN_FRAC)
        max_h = int(self.wh * CTRL_MAX_FRAC)
        self._ctrl_h = max(min_h, min(max_h, ctrl_h))
        self._update_rects()

    def _update_rects(self) -> None:
        pw = self.panel_w
        wh = self.wh
        ch = self._ctrl_h
        nh = max(MIN_NARR_H, wh - ch)

        self.controls  = pygame.Rect(0,   0,  pw, ch)
        self.narrative = pygame.Rect(0,   ch, pw, nh)
        self.arena     = pygame.Rect(pw,  0,  self.ww - pw, wh)
        self.panel     = pygame.Rect(0,   0,  pw, wh)

    @property
    def ctrl_inner(self) -> pygame.Rect:
        """Controls rect with padding."""
        return self.controls.inflate(-16, -16)

    @property
    def narr_inner(self) -> pygame.Rect:
        """Narrative rect with padding."""
        return self.narrative.inflate(-12, -12)

    @staticmethod
    def compute_window_size(target_frac: float = 1.0) -> tuple[int, int]:
        """
        Return (w, h) for a maximized-but-not-fullscreen window.
        target_frac is ignored (kept for API compatibility) — window is
        always sized to fill the usable desktop area.
        Must be called after pygame.init().
        """
        import sys
        info      = pygame.display.Info()
        taskbar_h = {"win32": 48, "darwin": 50}.get(sys.platform, 52)
        margin    = 8
        w = max(800, info.current_w  - margin * 2)
        h = max(500, info.current_h  - taskbar_h - margin * 2)
        return w, h
