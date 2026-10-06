"""
engine/playback.py
-------------------
Shared record/playback infrastructure for PAW games.

Classes
-------
PlaybackController
    Pure logic — no pygame, no drawing.
    Manages cursor, playing state, seeking, frame-by-frame stepping.
    Works with any list of objects that have a numeric .t attribute.

PlaybackHUD
    Draws the scrubber bar, time/frame labels, and play/pause icon
    into any pygame.Rect.  Optionally draws a signal/motor HUD overlay
    (enabled for BYOV; disabled for Ethology where it would spoil the
    exercise).

RecordingPicker
    In-pygame scrollable file list.  Given a directory and file
    extension, returns the selected path or None on cancel.
    Keyboard: ↑↓ navigate, Enter confirm, Esc cancel.
    Mouse:    click to select, double-click to confirm.
"""

from __future__ import annotations

import math
import os
import time
from typing import Any, Sequence

import pygame


# ── PlaybackController ─────────────────────────────────────────────────────────

class PlaybackController:
    """
    Manages playback state for a list of recorded frames.

    Parameters
    ----------
    frames : sequence of objects with a numeric `.t` attribute (seconds).
    """

    def __init__(self, frames: Sequence[Any]) -> None:
        if not frames:
            raise ValueError("frames must be non-empty")
        self._frames     = frames
        self._duration   = frames[-1].t
        self._cursor     = 0          # index into frames
        self._playing    = False
        self._wall_start = 0.0        # wall time when play began
        self._rec_start  = 0.0        # recording time at that wall time

    # ── Playback control ──────────────────────────────────────────────────────

    def play(self) -> None:
        if self._cursor >= len(self._frames) - 1:
            self._cursor = 0
        self._wall_start = time.monotonic()
        self._rec_start  = self._frames[self._cursor].t
        self._playing    = True

    def pause(self) -> None:
        self._playing = False

    def toggle_pause(self) -> None:
        if self._playing:
            self.pause()
        else:
            self.play()

    def restart(self) -> None:
        self._cursor  = 0
        self._playing = False

    def step(self, delta: int) -> None:
        """Advance or retreat by delta frames; pauses playback."""
        self._playing = False
        self._cursor  = max(0, min(len(self._frames) - 1,
                                   self._cursor + delta))

    def seek_frac(self, frac: float) -> None:
        """Seek to fractional position 0.0–1.0."""
        idx = int(max(0.0, min(1.0, frac)) * (len(self._frames) - 1))
        self._cursor     = idx
        self._rec_start  = self._frames[idx].t
        self._wall_start = time.monotonic()

    def tick(self, wall_dt: float | None = None) -> None:
        """
        Advance the cursor based on elapsed wall time.
        Call once per frame while playing.
        wall_dt is ignored — wall time is tracked internally for accuracy.
        """
        if not self._playing:
            return
        elapsed  = time.monotonic() - self._wall_start
        rec_t    = self._rec_start + elapsed
        if rec_t >= self._duration:
            rec_t        = self._duration
            self._playing = False
        self._cursor = self._frame_at_time(rec_t)

    # ── State accessors ───────────────────────────────────────────────────────

    @property
    def frames(self) -> Sequence[Any]:
        return self._frames

    @property
    def frame(self) -> Any:
        return self._frames[self._cursor]

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def frac(self) -> float:
        return self._cursor / max(1, len(self._frames) - 1)

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def is_done(self) -> bool:
        return (not self._playing and
                self._cursor >= len(self._frames) - 1)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _frame_at_time(self, t: float) -> int:
        frames = self._frames
        lo, hi = 0, len(frames) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if frames[mid].t < t:
                lo = mid + 1
            else:
                hi = mid
        return lo


# ── PlaybackHUD ────────────────────────────────────────────────────────────────

class PlaybackHUD:
    """
    Draws the playback scrubber bar and optional signal/motor HUD.

    Parameters
    ----------
    show_hud : bool
        If True, draw signal and motor value bars alongside the scrubber.
        Set False for games where showing this data defeats the purpose
        (e.g. Robot Ethology).
    accent_color : tuple
        RGB colour used for the filled portion of the scrubber bar.
    """

    SCRUB_H    = 14
    SCRUB_PAD  = 8
    PANEL_H    = 38    # height of the bottom panel strip
    HUD_H      = 48    # extra height when show_hud=True
    HANDLE_R   = 7

    def __init__(self,
                 show_hud:     bool  = False,
                 accent_color: tuple = (51, 200, 87)) -> None:
        self._show_hud    = show_hud
        self._accent      = accent_color
        self._scrub_rect  = pygame.Rect(0, 0, 0, 0)

    @property
    def panel_height(self) -> int:
        return self.PANEL_H + (self.HUD_H if self._show_hud else 0)

    def scrub_hit(self, pos: tuple) -> bool:
        """True if pos (screen coords) is on the scrubber bar.

        Valid only after draw() has run at least once (which sets the rect).
        A small vertical pad is included so the thin bar is easy to grab.
        """
        return self._scrub_rect.collidepoint(pos)

    def seek_at(self, mouse_x: int, ctrl: "PlaybackController") -> None:
        """Map a screen x onto the scrubber and seek the controller to it.

        Clamped to [0, 1]; pauses so the cursor stays where the user put it.
        """
        if self._scrub_rect.width <= 0:
            return
        frac = (mouse_x - self._scrub_rect.x) / self._scrub_rect.width
        frac = max(0.0, min(1.0, frac))
        ctrl.pause()
        ctrl.seek_frac(frac)

    def draw(self, surf: pygame.Surface, rect: pygame.Rect,
             ctrl: PlaybackController,
             font_sm: pygame.font.Font,
             font_md: pygame.font.Font) -> None:
        """Draw the HUD into rect (typically the bottom strip of the canvas)."""
        ox, oy, pw, ph = rect.x, rect.y, rect.width, rect.height

        # Background strip
        pygame.draw.rect(surf, (14, 18, 14), rect)
        pygame.draw.line(surf, (30, 58, 30),
                         (ox, oy), (ox + pw, oy), 1)

        # ── Scrubber bar ──────────────────────────────────────────────────────
        bx  = ox + self.SCRUB_PAD
        bw  = pw  - self.SCRUB_PAD * 2
        by  = oy  + 8
        bh  = self.SCRUB_H
        bar = pygame.Rect(bx, by, bw, bh)
        pygame.draw.rect(surf, (28, 36, 28), bar, border_radius=4)
        fw  = max(4, int(bw * ctrl.frac))
        pygame.draw.rect(surf, self._accent,
                         pygame.Rect(bx, by, fw, bh), border_radius=4)
        hx  = bx + int(bw * ctrl.frac)
        pygame.draw.circle(surf, (220, 255, 220),
                           (hx, by + bh // 2), self.HANDLE_R)
        self._scrub_rect = pygame.Rect(bx, by - 4, bw, bh + 8)

        # ── Time / frame labels ───────────────────────────────────────────────
        fr   = ctrl.frame
        t    = fr.t
        mins = int(t // 60);  secs = t % 60
        dt   = ctrl.duration
        dm   = int(dt // 60); ds   = dt % 60
        time_lbl = font_sm.render(
            f"{mins}:{secs:05.2f} / {dm}:{ds:05.2f}  "
            f"frame {ctrl.cursor + 1}/{len(ctrl.frames)}",
            True, (100, 160, 100))
        surf.blit(time_lbl, (bx, by + bh + 4))

        # Play/pause icon and hint
        icon = "▶" if not ctrl.is_playing else "⏸"
        ic   = font_md.render(icon, True, (180, 220, 180))
        surf.blit(ic, (ox + pw - ic.get_width() - 8, by + 2))

        hint = font_sm.render(
            "SPACE play/pause   ← → step   drag scrubber = seek",
            True, (50, 90, 50))
        surf.blit(hint, (ox + pw - hint.get_width() - 8,
                         by + bh + 4))

        # ── Optional signal/motor HUD ─────────────────────────────────────────
        if self._show_hud and hasattr(fr, "signals") and fr.signals:
            self._draw_signal_bars(surf, rect, fr, font_sm)

    def _draw_signal_bars(self, surf, rect, fr, font_sm):
        """Draw named signal bars for sensors and motors."""
        ox, oy, pw, ph = rect.x, rect.y, rect.width, rect.height
        signals = fr.signals or {}
        motors  = getattr(fr, "motors", None)

        # Only show key signals: RL, RR, PL, PR + motors L/R
        KEY_SIGS = ["RL", "RR", "PL", "PR"]
        items = [(k, signals[k]) for k in KEY_SIGS if k in signals]
        if motors:
            items += [("L", motors[0]), ("R", motors[1])]

        n    = len(items)
        if n == 0:
            return
        bw   = (pw - 20) // max(1, n)
        by   = oy + self.PANEL_H
        bh   = self.HUD_H - 14

        for i, (name, val) in enumerate(items):
            bx   = rect.x + 10 + i * bw
            val  = max(0.0, min(1.0, float(val)))
            fh   = int(bh * val)
            bar  = pygame.Rect(bx + 2, by, bw - 4, bh)
            fill = pygame.Rect(bx + 2, by + bh - fh, bw - 4, fh)
            pygame.draw.rect(surf, (20, 30, 20), bar, border_radius=2)
            col  = ((51, 200, 87) if name not in ("L", "R")
                    else (255, 149, 0))
            pygame.draw.rect(surf, col, fill, border_radius=2)
            lbl  = font_sm.render(name, True, (80, 120, 80))
            surf.blit(lbl, (bx + bw // 2 - lbl.get_width() // 2,
                            by + bh + 2))

    def handle_event(self, event: pygame.event.Event,
                     ctrl: PlaybackController) -> bool:
        """
        Handle keyboard/mouse events for playback.
        Returns True if the event was consumed.
        """
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE:
                ctrl.toggle_pause(); return True
            if event.key == pygame.K_RIGHT:
                ctrl.step(+1); return True
            if event.key == pygame.K_LEFT:
                ctrl.step(-1); return True

        elif event.type == pygame.MOUSEBUTTONDOWN:
            if self._scrub_rect.collidepoint(event.pos):
                frac = ((event.pos[0] - self._scrub_rect.x) /
                        max(1, self._scrub_rect.width))
                ctrl.seek_frac(frac); return True

        elif event.type == pygame.MOUSEMOTION:
            if (event.buttons[0] and
                    self._scrub_rect.collidepoint(event.pos)):
                frac = ((event.pos[0] - self._scrub_rect.x) /
                        max(1, self._scrub_rect.width))
                ctrl.seek_frac(frac); return True

        return False


# ── RecordingPicker ────────────────────────────────────────────────────────────

class RecordingPicker:
    """
    In-pygame scrollable file browser for recording files.

    Usage
    -----
    picker = RecordingPicker()
    path   = picker.run(rec_dir, ext=".vvrec")
    # path is None if user cancelled
    """

    def __init__(self,
                 title:      str   = "Select Recording",
                 bg_color:   tuple = (10, 14, 10),
                 text_color: tuple = (160, 220, 160),
                 sel_color:  tuple = (20, 50, 20),
                 acc_color:  tuple = (51, 200, 87)) -> None:
        self._title     = title
        self._bg        = bg_color
        self._text      = text_color
        self._sel_bg    = sel_color
        self._acc       = acc_color

    def run(self, rec_dir: str, ext: str = ".vvrec",
            screen: pygame.Surface | None = None,
            rect:   pygame.Rect   | None = None) -> str | None:
        """
        Show the picker as a modal overlay on the current display.

        If screen is None, uses pygame.display.get_surface().
        Never creates a new pygame window — always draws onto the
        existing display so the caller's window is not replaced.

        Returns selected file path, or None on cancel.
        """
        os.makedirs(rec_dir, exist_ok=True)
        files = sorted(
            (f for f in os.listdir(rec_dir) if f.endswith(ext)),
            reverse=True)   # newest first

        if not files:
            return None

        # Always use the existing display — never create a new window
        if screen is None:
            screen = pygame.display.get_surface()
        ww, wh = screen.get_size()
        pw = min(560, ww - 60)
        ph = min(80 + len(files) * 32, wh - 60, 520)
        if rect is None:
            rect = pygame.Rect((ww - pw) // 2, (wh - ph) // 2, pw, ph)

        standalone = False   # never standalone now

        font_hd = pygame.font.SysFont("Courier New", 16)
        font    = pygame.font.SysFont("Courier New", 14)
        font_sm = pygame.font.SysFont("Courier New", 12)
        clock   = pygame.time.Clock()

        sel        = 0
        scroll     = 0
        row_h      = 30
        visible    = max(1, (rect.height - 60) // row_h)
        last_click = (-1, 0.0)   # (index, wall_time) for double-click

        result     = None
        running    = True

        while running:
            ox, oy = rect.x, rect.y

            # Dim the rest of the screen (modal effect)
            overlay = pygame.Surface(screen.get_size(),
                                     pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 160))
            screen.blit(overlay, (0, 0))
            # Picker background
            pygame.draw.rect(screen, self._bg, rect)
            pygame.draw.rect(screen, (30, 58, 30), rect, 2,
                             border_radius=6)
            pygame.draw.rect(screen, (30, 58, 30), rect, 1)

            # Title
            tt = font_hd.render(self._title, True, self._acc)
            screen.blit(tt, (ox + 12, oy + 10))

            # File list
            list_y = oy + 38
            for i in range(scroll, min(scroll + visible, len(files))):
                ry  = list_y + (i - scroll) * row_h
                row = pygame.Rect(ox + 6, ry, rect.width - 12, row_h - 2)
                if i == sel:
                    pygame.draw.rect(screen, self._sel_bg, row,
                                     border_radius=3)
                    pygame.draw.rect(screen, self._acc, row, 1,
                                     border_radius=3)
                col = self._acc if i == sel else self._text
                ft  = font.render(files[i], True, col)
                screen.blit(ft, (ox + 12, ry + (row_h - ft.get_height()) // 2))

            # Scrollbar
            if len(files) > visible:
                sb_h  = rect.height - 60
                th    = max(20, sb_h * visible // len(files))
                ty    = 38 + sb_h * scroll // max(1, len(files))
                pygame.draw.rect(screen, (30, 50, 30),
                                 (ox + rect.width - 10, oy + 38, 6, sb_h))
                pygame.draw.rect(screen, self._acc,
                                 (ox + rect.width - 10, oy + ty, 6, th),
                                 border_radius=3)

            # Hint
            hint = font_sm.render(
                "↑↓ navigate   Enter/double-click open   Esc cancel",
                True, (50, 90, 50))
            screen.blit(hint, (ox + 12, oy + rect.height - 18))

            pygame.display.flip()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_UP:
                        sel    = max(0, sel - 1)
                        scroll = min(scroll, sel)
                    elif event.key == pygame.K_DOWN:
                        sel    = min(len(files) - 1, sel + 1)
                        if sel >= scroll + visible:
                            scroll = sel - visible + 1
                    elif event.key == pygame.K_RETURN:
                        result  = os.path.join(rec_dir, files[sel])
                        running = False
                    elif event.key == pygame.K_ESCAPE:
                        running = False

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    mx, my = event.pos
                    if rect.collidepoint(mx, my):
                        row_i = (my - (oy + 38)) // row_h + scroll
                        if 0 <= row_i < len(files):
                            now = time.monotonic()
                            if (last_click[0] == row_i and
                                    now - last_click[1] < 0.4):
                                # Double-click
                                result  = os.path.join(rec_dir, files[row_i])
                                running = False
                            else:
                                sel        = row_i
                                last_click = (row_i, now)
                    else:
                        running = False   # click outside = cancel

                elif event.type == pygame.MOUSEWHEEL:
                    scroll = max(0, min(len(files) - visible,
                                        scroll - event.y))

            clock.tick(30)

        return result
