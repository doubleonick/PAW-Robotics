"""
tools/playback.py
------------------
Playback viewer for RoboSim recordings (.robrec files).

Shows:
  - Static trajectory trace (full path colour-coded by time)
  - Animated playback at recorded speed
  - Scrubber timeline at bottom

Controls:
  SPACE        play / pause
  ← →          step one frame
  Click scrubber  seek to position
  Esc          quit

Run:  py -3.12 tools/playback.py recordings/my_run.robrec
      py -3.12 tools/playback.py            (opens file browser)
"""

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
from robosim.recorder import load_recording, Frame
from robosim.config import ArenaConfig

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Colours
C_BG      = (14,  16,  22)
C_FLOOR   = (30,  34,  44)
C_WALL    = (80,  88, 110)
C_ROBOT   = (60, 160, 230)
C_HDG     = (255, 255, 255)
C_TEXT    = (200, 210, 230)
C_DIM     = ( 80,  90, 115)
C_PANEL   = (20,  24,  34)
C_HEADING = (255, 215,  70)
C_TRACE_A = ( 80, 180, 255)   # start of trace
C_TRACE_B = (255, 100,  80)   # end of trace

MARGIN  = 50
PANEL_H = 72


def _trace_color(frac: float) -> tuple:
    """Lerp from C_TRACE_A to C_TRACE_B across the recording."""
    r = int(C_TRACE_A[0] + frac * (C_TRACE_B[0] - C_TRACE_A[0]))
    g = int(C_TRACE_A[1] + frac * (C_TRACE_B[1] - C_TRACE_A[1]))
    b = int(C_TRACE_A[2] + frac * (C_TRACE_B[2] - C_TRACE_A[2]))
    return (r, g, b)


class PlaybackViewer:

    def __init__(self, rec_path: str, arena_path: str = "arena.json"):
        self._rec_path = rec_path
        self._frames   = load_recording(rec_path)
        if not self._frames:
            print("Empty recording.")
            sys.exit(1)

        arena_file = os.path.join(ROOT, arena_path)
        self._arena = (ArenaConfig.from_file(arena_file)
                       if os.path.exists(arena_file) else ArenaConfig())

        self._duration        = self._frames[-1].t
        self._cursor          = 0
        self._playing         = False
        self._play_start_wall = 0.0
        self._play_start_rec  = 0.0

        pygame.init()
        info = pygame.display.Info()
        ww   = min(1100, info.current_w - 40)
        wh   = min(820,  info.current_h - 80)
        self._screen = pygame.display.set_mode((ww, wh), pygame.RESIZABLE)
        pygame.display.set_caption(
            f"Playback — {os.path.basename(rec_path)}")

        self._font_hd = pygame.font.SysFont("consolas", 20)
        self._font_md = pygame.font.SysFont("consolas", 15)
        self._font_sm = pygame.font.SysFont("consolas", 13)
        self._clock   = pygame.time.Clock()

    # ── Layout ────────────────────────────────────────────────────────────────

    @property
    def _ww(self): return self._screen.get_width()
    @property
    def _wh(self): return self._screen.get_height()

    def _compute_scale(self):
        aw, ah    = self._arena.width, self._arena.height
        canvas_w  = self._ww  - MARGIN * 2
        canvas_h  = self._wh  - MARGIN * 2 - PANEL_H
        self._scl = min(canvas_w / aw, canvas_h / ah)
        self._cx  = MARGIN + canvas_w // 2
        self._cy  = MARGIN + canvas_h // 2

    def _to_screen(self, wx, wy):
        return (int(self._cx + wx * self._scl),
                int(self._cy - wy * self._scl))

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw_arena(self, surf):
        aw, ah = self._arena.width, self._arena.height
        tl = self._to_screen(-aw/2,  ah/2)
        br = self._to_screen( aw/2, -ah/2)
        pygame.draw.rect(surf, C_FLOOR,
                         pygame.Rect(tl[0], tl[1],
                                     br[0]-tl[0], br[1]-tl[1]))
        t = self._arena.wall_thickness
        for p0, p1 in [
            ((-aw/2-t, ah/2+t), ( aw/2+t,  ah/2+t)),
            ((-aw/2-t,-ah/2-t), ( aw/2+t, -ah/2-t)),
            (( aw/2,  -ah/2),   ( aw/2,    ah/2  )),
            ((-aw/2-t,-ah/2),   (-aw/2-t,  ah/2  )),
        ]:
            pygame.draw.line(surf, C_WALL,
                             self._to_screen(*p0),
                             self._to_screen(*p1), 4)
        for iw in self._arena.internal_walls:
            pygame.draw.line(surf, C_WALL,
                             self._to_screen(iw.x0, iw.y0),
                             self._to_screen(iw.x1, iw.y1),
                             max(2, int(iw.thickness * self._scl)))

        # Light sources — soft glow ring
        for ls in self._arena.light_sources:
            cx, cy = self._to_screen(ls.x, ls.y)
            r_px   = int(ls.radius * self._scl)
            for ring in range(max(1, r_px), 0, -max(1, r_px // 10)):
                alpha = int(60 * (1.0 - ring / r_px))
                s = pygame.Surface((ring*2, ring*2), pygame.SRCALPHA)
                pygame.draw.circle(s, (255, 220, 80, alpha),
                                   (ring, ring), ring)
                surf.blit(s, (cx - ring, cy - ring))
            pygame.draw.circle(surf, (255, 220, 80), (cx, cy), r_px, 2)
            pygame.draw.circle(surf, (255, 220, 80), (cx, cy), 3)

    def _draw_trace(self, surf, up_to: int):
        """Draw full trajectory trace, greying out frames beyond cursor."""
        n = len(self._frames)
        for i in range(1, n):
            f0, f1  = self._frames[i-1], self._frames[i]
            frac    = i / max(1, n - 1)
            col     = _trace_color(frac)
            if i > up_to:
                # Future path — dim
                col = tuple(c // 4 for c in col)
            pygame.draw.line(surf, col,
                             self._to_screen(f0.x, f0.y),
                             self._to_screen(f1.x, f1.y), 2)

    def _draw_robot(self, surf, fr: Frame):
        cx, cy = self._to_screen(fr.x, fr.y)
        r = max(4, int(0.084 * self._scl))
        pygame.draw.circle(surf, C_ROBOT, (cx, cy), r, 2)
        h  = math.radians(fr.hdg)
        hx = cx + int(math.cos(h) * r * 1.6)
        hy = cy - int(math.sin(h) * r * 1.6)
        pygame.draw.line(surf, C_HDG, (cx, cy), (hx, hy), 2)

    def _draw_panel(self, surf):
        py = self._wh - PANEL_H
        pygame.draw.rect(surf, C_PANEL, (0, py, self._ww, PANEL_H))
        pygame.draw.line(surf, (40, 45, 62), (0, py), (self._ww, py), 1)

        # Scrubber bar
        bx = 10
        bw = self._ww - 20
        by = py + 12
        bh = 14
        pygame.draw.rect(surf, (30, 36, 52),
                         (bx, by, bw, bh), border_radius=4)

        # Filled portion
        frac = self._cursor / max(1, len(self._frames) - 1)
        fw   = max(4, int(bw * frac))
        pygame.draw.rect(surf, C_TRACE_A,
                         (bx, by, fw, bh), border_radius=4)

        # Cursor handle
        hx = bx + int(bw * frac)
        pygame.draw.circle(surf, (255, 255, 255), (hx, by + bh//2), 7)

        self._scrubber_rect = pygame.Rect(bx, by - 4, bw, bh + 8)

        # Time labels
        fr    = self._frames[self._cursor]
        t_cur = self._font_sm.render(f"{fr.t:.2f}s", True, C_TEXT)
        t_tot = self._font_sm.render(f"/ {self._duration:.2f}s", True, C_DIM)
        f_lbl = self._font_sm.render(
            f"frame {self._cursor+1}/{len(self._frames)}", True, C_DIM)
        surf.blit(t_cur, (bx,          py + 32))
        surf.blit(t_tot, (bx + 60,     py + 32))
        surf.blit(f_lbl, (bx + 160,    py + 32))

        hint = self._font_sm.render(
            "SPACE = play/pause   ← → = step   click scrubber = seek   Esc = quit",
            True, C_DIM)
        surf.blit(hint, (self._ww - hint.get_width() - 10, py + 52))

        # Play/pause indicator
        icon = "▶" if not self._playing else "⏸"
        it   = self._font_md.render(icon, True, C_HEADING)
        surf.blit(it, (self._ww - it.get_width() - 10, py + 28))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _frame_at_time(self, t: float) -> int:
        lo, hi = 0, len(self._frames) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if self._frames[mid].t < t:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def _seek(self, mouse_x: int):
        bx = 10
        bw = self._ww - 20
        frac = max(0.0, min(1.0, (mouse_x - bx) / bw))
        self._cursor = int(frac * (len(self._frames) - 1))

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        self._scrubber_rect = pygame.Rect(0, 0, 0, 0)
        running = True
        while running:
            now = time.monotonic()

            if self._playing:
                elapsed = now - self._play_start_wall
                rec_t   = self._play_start_rec + elapsed
                if rec_t >= self._duration:
                    rec_t         = self._duration
                    self._playing = False
                self._cursor = self._frame_at_time(rec_t)

            # Draw
            surf = self._screen
            surf.fill(C_BG)
            self._compute_scale()
            self._draw_arena(surf)
            self._draw_trace(surf, self._cursor)
            self._draw_robot(surf, self._frames[self._cursor])
            self._draw_panel(surf)

            # Title
            title = self._font_hd.render(
                os.path.basename(self._rec_path), True, C_HEADING)
            surf.blit(title, (10, 8))

            pygame.display.flip()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

                elif event.type == pygame.VIDEORESIZE:
                    self._screen = pygame.display.set_mode(
                        event.size, pygame.RESIZABLE)

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:
                        if self._playing:
                            self._playing = False
                        else:
                            if self._cursor >= len(self._frames) - 1:
                                self._cursor = 0
                            self._play_start_wall = now
                            self._play_start_rec  = self._frames[self._cursor].t
                            self._playing = True
                    elif event.key == pygame.K_RIGHT:
                        self._cursor  = min(self._cursor + 1,
                                            len(self._frames) - 1)
                        self._playing = False
                    elif event.key == pygame.K_LEFT:
                        self._cursor  = max(self._cursor - 1, 0)
                        self._playing = False
                    elif event.key == pygame.K_ESCAPE:
                        running = False

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if self._scrubber_rect.collidepoint(event.pos):
                        self._seek(event.pos[0])
                        self._playing = False

                elif event.type == pygame.MOUSEMOTION:
                    if event.buttons[0] and \
                            self._scrubber_rect.collidepoint(event.pos):
                        self._seek(event.pos[0])

            self._clock.tick(60)

        pygame.quit()


# ── File browser ──────────────────────────────────────────────────────────────

def pick_recording(rec_dir: str = "") -> str | None:
    if not rec_dir:
        rec_dir = os.path.join(ROOT, "recordings")
    os.makedirs(rec_dir, exist_ok=True)
    files = sorted(f for f in os.listdir(rec_dir) if f.endswith(".robrec"))
    if not files:
        print(f"No recordings in {rec_dir}")
        return None

    pygame.init()
    screen = pygame.display.set_mode((520, min(80 + len(files)*30, 500)))
    pygame.display.set_caption("Select Recording")
    font_hd = pygame.font.SysFont("consolas", 18)
    font    = pygame.font.SysFont("consolas", 15)
    font_sm = pygame.font.SysFont("consolas", 13)
    sel     = 0
    clock   = pygame.time.Clock()

    while True:
        screen.fill((14, 16, 22))
        tt = font_hd.render("Select a recording:", True, (255, 215, 70))
        screen.blit(tt, (16, 12))
        for i, name in enumerate(files):
            y   = 44 + i * 28
            col = (60, 140, 220) if i == sel else (200, 210, 230)
            if i == sel:
                pygame.draw.rect(screen, (28, 38, 58),
                                 (8, y - 2, 504, 26), border_radius=4)
            ft = font.render(name, True, col)
            screen.blit(ft, (14, y + 2))
        h = font_sm.render(
            "↑↓ select   Enter open   Esc cancel", True, (70, 80, 100))
        screen.blit(h, (16, screen.get_height() - 22))
        pygame.display.flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); return None
            elif event.type == pygame.KEYDOWN:
                if   event.key == pygame.K_UP:
                    sel = max(0, sel - 1)
                elif event.key == pygame.K_DOWN:
                    sel = min(len(files) - 1, sel + 1)
                elif event.key == pygame.K_RETURN:
                    pygame.quit()
                    return os.path.join(rec_dir, files[sel])
                elif event.key == pygame.K_ESCAPE:
                    pygame.quit(); return None
        clock.tick(30)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*",
                    help=".robrec file and/or arena .json file")
    ap.add_argument("--recordings", default="",
                    help="Directory to browse for recordings")
    args = ap.parse_args()

    # Separate rec file from arena file by extension
    rec_arg   = next((a for a in args.files if a.endswith(".robrec")), None)
    arena_arg = next((a for a in args.files if a.endswith(".json")),   "arena.json")

    # Determine recordings directory
    rec_dir = args.recordings if args.recordings else \
              os.path.join(ROOT, "recordings")

    if rec_arg:
        path = rec_arg
    else:
        path = pick_recording(rec_dir)

    if path and os.path.exists(path):
        PlaybackViewer(path, arena_arg).run()
    else:
        print("No recording selected.")
