"""
games/ethology/hierarchy_builder.py
-------------------------------------
Hierarchy Builder for the Robot Ethology game.

Two-column drag interface:
  Left  — behavior pool (available behaviors)
  Right — active hierarchy (ordered, highest priority first)

Arrow buttons move behaviors between columns.
Up/Down buttons reorder the hierarchy.
Generate button writes a .ino sketch to games/ethology/sketches/.

Behavior → robot class mapping:
  If any light behavior is selected → LDREthologyRobot
  Otherwise                         → EthologyRobot

Generated sketch calls the robot's existing behavior logic —
the player controls ordering and selection, not implementation.
"""

import os
import sys
import datetime

ROOT     = os.path.dirname(os.path.dirname(os.path.dirname(
               os.path.abspath(__file__))))
GAME_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import pygame

# ── Palette — read dynamically from theme module ─────────────────────────────
import robosim.theme as T

WW, WH = 820, 560

# Code generation imported from codegen.py (no pygame dependency)
from games.ethology.codegen import (
    BEHAVIORS, BEHAVIOR_MAP, BEHAVIOR_CODE,
    needs_light, generate_sketch
)


# ── UI ────────────────────────────────────────────────────────────────────────

class HierarchyBuilder:

    def __init__(self, robot_label: str = "", result_path: str = ""):
        self._robot_label = robot_label   # "A", "B", or "" for standalone
        self._result_path = result_path   # path to write hypothesis JSON
        self._game_mode   = bool(robot_label and result_path)

        pygame.init()
        self._screen = pygame.display.set_mode((WW, WH))
        title = f"Hierarchy Builder — Robot {robot_label}" \
                if robot_label else "Hierarchy Builder — Robot Ethology"
        pygame.display.set_caption(title)
        self._clock  = pygame.time.Clock()

        from robosim.theme import font_hd, font_md, font_sm
        self._font_hd = font_hd()
        self._font_md = font_md()
        self._font_sm = font_sm()

        # Pool starts with all behaviors; hierarchy starts empty
        self._pool      = [b[1] for b in BEHAVIORS]
        self._hierarchy = []
        self._pool_sel  = -1   # selected index in pool
        self._hier_sel  = -1   # selected index in hierarchy

        self._status     = "Select behaviors and build your hierarchy"
        self._status_col = T.TEXT_DIM
        self._btn_rects  = {}

    def _set_status(self, msg, ok=True):
        self._status     = msg
        self._status_col = T.PHOSPHOR if ok else T.AMBER

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw_list(self, surf, items, sel_idx, x, y, w, h, title):
        """Draw a labeled list of behavior items. Returns list of item rects."""
        # Header
        pygame.draw.rect(surf, T.PANEL, (x, y, w, h), border_radius=6)
        pygame.draw.rect(surf, T.BORDER,  (x, y, w, h), 1, border_radius=6)
        tt = self._font_md.render(title, True, T.WHITE_GREEN)
        surf.blit(tt, (x + 10, y + 8))

        rects = []
        iy = y + 36
        row_h = 34
        for i, key in enumerate(items):
            label = BEHAVIOR_MAP[key][0]
            light = BEHAVIOR_MAP[key][2]
            r     = pygame.Rect(x + 6, iy, w - 12, row_h - 2)
            rects.append(r)

            sel = (i == sel_idx)
            bg  = T.PHOSPHOR_DIM if sel else T.PANEL
            pygame.draw.rect(surf, bg, r, border_radius=4)
            if sel:
                pygame.draw.rect(surf, T.PHOSPHOR_MID, r, 1, border_radius=4)

            lx = r.x + 10

            # Priority number for hierarchy
            if title.startswith("Hierarchy"):
                num = self._font_sm.render(f"{i+1}.", True,
                                           T.TEXT_DIM if not sel else T.WHITE_GREEN)
                surf.blit(num, (lx, r.centery - num.get_height()//2))
                lx += 24

            lt = self._font_md.render(label, True,
                                      T.WHITE_GREEN if sel else T.TEXT)
            surf.blit(lt, (lx, r.centery - lt.get_height()//2))
            iy += row_h

        return rects

    def _btn(self, surf, rect, label, name, accent=False, disabled=False):
        self._btn_rects[name] = rect
        mx, my = pygame.mouse.get_pos()
        hov = rect.collidepoint(mx, my) and not disabled
        if disabled:
            col = (26, 30, 44)
        elif accent:
            col = T.PHOSPHOR_MID if hov else (40, 100, 180)
        else:
            col = T.PHOSPHOR_DIM if hov else T.PANEL_DEEP
        pygame.draw.rect(surf, col, rect, border_radius=5)
        pygame.draw.rect(surf, T.BORDER if not disabled else (30,33,46),
                         rect, 1, border_radius=5)
        tc = T.TEXT_DIM if disabled else (T.WHITE_GREEN if accent else T.TEXT)
        t  = self._font_md.render(label, True, tc)
        surf.blit(t, (rect.centerx - t.get_width()//2,
                      rect.centery - t.get_height()//2))

    def _draw(self):
        surf = self._screen
        surf.fill(T.BG)
        self._btn_rects  = {}
        self._pool_rects = []
        self._hier_rects = []

        pad = 16

        # Title
        if self._game_mode:
            tt = self._font_hd.render(
                f"Build Hypothesis — Robot {self._robot_label}",
                True, T.WHITE_GREEN)
        else:
            tt = self._font_hd.render("Hierarchy Builder", True, T.WHITE_GREEN)
        surf.blit(tt, (pad, 12))
        from robosim.theme import draw_double_rule
        draw_double_rule(surf, 0, 46, WW)

        # Column layout
        col_w    = 280
        mid_w    = WW - col_w*2 - pad*3
        lx       = pad
        mid_x    = pad + col_w + pad
        rx       = mid_x + mid_w + pad
        list_y   = 54
        list_h   = WH - list_y - 90

        # Pool list
        self._pool_rects = self._draw_list(
            surf, self._pool, self._pool_sel,
            lx, list_y, col_w, list_h, "Behavior Pool")

        # Hierarchy list
        self._hier_rects = self._draw_list(
            surf, self._hierarchy, self._hier_sel,
            rx, list_y, col_w, list_h, "Hierarchy  (top = highest priority)")

        # Centre buttons
        bw, bh = mid_w - 8, 36
        bx     = mid_x + 4
        cy     = list_y + list_h//2 - bh*3

        self._btn(surf, pygame.Rect(bx, cy,      bw, bh), "→  Add",    "btn_add")
        self._btn(surf, pygame.Rect(bx, cy+46,   bw, bh), "←  Remove","btn_remove")
        self._btn(surf, pygame.Rect(bx, cy+100,  bw, bh), "↑  Up",    "btn_up")
        self._btn(surf, pygame.Rect(bx, cy+146,  bw, bh), "↓  Down",  "btn_down")

        # Bottom bar
        from robosim.theme import draw_double_rule
        draw_double_rule(surf, 0, WH-66, WW)

        can_act = len(self._hierarchy) > 0

        if self._game_mode:
            # [Clear All]  [Launch Arduino]  [Launch Experiment]
            self._btn(surf,
                      pygame.Rect(pad, WH-54, 90, 38),
                      "Clear All", "btn_clear")
            self._btn(surf,
                      pygame.Rect(pad + 98, WH-54, 160, 38),
                      "Launch Arduino", "btn_arduino",
                      disabled=not can_act)
            self._btn(surf,
                      pygame.Rect(WW - 190 - pad, WH-54, 190, 38),
                      "Launch Experiment", "btn_ok",
                      accent=True, disabled=not can_act)
        else:
            # [Clear All]  [Generate Sketch]
            self._btn(surf,
                      pygame.Rect(pad, WH-54, 90, 38),
                      "Clear All", "btn_clear")
            self._btn(surf,
                      pygame.Rect(WW - 180 - pad, WH-54, 180, 38),
                      "Generate Sketch", "btn_gen",
                      accent=True, disabled=not can_act)

        pygame.display.flip()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _handle_btn(self, name):
        if name == "btn_add":
            if self._pool_sel >= 0 and self._pool_sel < len(self._pool):
                key = self._pool.pop(self._pool_sel)
                self._hierarchy.append(key)
                self._pool_sel = min(self._pool_sel, len(self._pool)-1)
                self._hier_sel = len(self._hierarchy) - 1

        elif name == "btn_remove":
            if self._hier_sel >= 0 and self._hier_sel < len(self._hierarchy):
                key = self._hierarchy.pop(self._hier_sel)
                self._pool.append(key)
                self._hier_sel = min(self._hier_sel, len(self._hierarchy)-1)
                self._pool_sel = len(self._pool) - 1

        elif name == "btn_up":
            i = self._hier_sel
            if i > 0:
                self._hierarchy[i], self._hierarchy[i-1] = \
                    self._hierarchy[i-1], self._hierarchy[i]
                self._hier_sel = i - 1

        elif name == "btn_down":
            i = self._hier_sel
            if 0 <= i < len(self._hierarchy) - 1:
                self._hierarchy[i], self._hierarchy[i+1] = \
                    self._hierarchy[i+1], self._hierarchy[i]
                self._hier_sel = i + 1

        elif name == "btn_clear":
            # Return all hierarchy items to pool
            self._pool.extend(self._hierarchy)
            # Restore original order
            orig = [b[1] for b in BEHAVIORS]
            self._pool = [k for k in orig if k in self._pool]
            self._hierarchy = []
            self._pool_sel  = -1
            self._hier_sel  = -1
            self._set_status("Cleared", ok=True)

        elif name == "btn_arduino":
            self._launch_arduino()

        elif name == "btn_ok":
            self._submit_hypothesis()

        elif name == "btn_download":
            pass   # placeholder — not yet implemented

        elif name == "btn_gen":
            self._generate()

    def _launch_arduino(self):
        """Export sketch, launch IDE, write result with physical=True flag."""
        if not self._hierarchy:
            self._set_status("Add at least one behavior first", ok=False)
            return

        from games.ethology.codegen import generate_sketch
        from games.ethology.arduino_export import export, launch_ide

        sketch_name = f"current_hypothesis_{self._robot_label}.ino"
        code        = generate_sketch(self._hierarchy, sketch_name)

        try:
            ino_path = export(code, self._robot_label)
        except Exception as e:
            self._set_status(f"Export failed: {e}", ok=False)
            return

        found_ide = launch_ide(ino_path)
        if found_ide:
            self._set_status(f"Opened in Arduino IDE: {sketch_name}")
        else:
            self._set_status(f"IDE not found — folder opened: {sketch_name}", ok=False)

        # Write result JSON with physical flag — hub will enter physical experiment state
        import json
        result = {
            "robot":        self._robot_label,
            "hierarchy":    self._hierarchy,
            "sketch_path":  ino_path,
            "physical":     True,
        }
        with open(self._result_path, "w") as f:
            json.dump(result, f)

        pygame.quit()
        sys.exit(0)

    def _submit_hypothesis(self):
        """Write hypothesis to result file and close (game mode only)."""
        if not self._hierarchy:
            self._set_status("Add at least one behavior first", ok=False)
            return

        import json
        sketches_dir = os.path.join(GAME_DIR, "sketches")
        os.makedirs(sketches_dir, exist_ok=True)
        import datetime
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        name  = f"hypothesis_{self._robot_label}_{stamp}.ino"
        path  = os.path.join(sketches_dir, name)

        code = generate_sketch(self._hierarchy, name)
        with open(path, "w") as f:
            f.write(code)

        result = {
            "robot":       self._robot_label,
            "hierarchy":   self._hierarchy,
            "sketch_path": path,
        }
        with open(self._result_path, "w") as f:
            json.dump(result, f)

        pygame.quit()
        sys.exit(0)

    def _generate(self):
        if not self._hierarchy:
            self._set_status("Add at least one behavior first", ok=False)
            return

        sketches_dir = os.path.join(GAME_DIR, "sketches")
        os.makedirs(sketches_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        name  = f"hierarchy_{stamp}.ino"
        path  = os.path.join(sketches_dir, name)

        code = generate_sketch(self._hierarchy, name)
        with open(path, "w") as f:
            f.write(code)

        self._set_status(f"Saved → sketches/{name}")

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        running = True
        while running:
            self._draw()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    pos = event.pos
                    # Pool item click
                    for i, r in enumerate(self._pool_rects):
                        if r.collidepoint(pos):
                            self._pool_sel = i
                            self._hier_sel = -1
                            break
                    else:
                        # Hierarchy item click
                        for i, r in enumerate(self._hier_rects):
                            if r.collidepoint(pos):
                                self._hier_sel = i
                                self._pool_sel = -1
                                break
                        else:
                            # Button click
                            for name, rect in self._btn_rects.items():
                                if rect.collidepoint(pos):
                                    self._handle_btn(name)
                                    break
            self._clock.tick(30)
        pygame.quit()


if __name__ == "__main__":
    import robosim.theme as T
    T.apply(T.load_saved_theme())
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--robot",  default="",  help="Robot label (A or B)")
    ap.add_argument("--result", default="",  help="Path to write hypothesis JSON")
    ap.add_argument("--arena",  default="",  help="Arena path (unused, for future use)")
    args = ap.parse_args()
    HierarchyBuilder(robot_label=args.robot,
                     result_path=args.result).run()
