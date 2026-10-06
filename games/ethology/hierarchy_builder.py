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


# ── Output-path hooks ────────────────────────────────────────────────────────
# By default, generated sketches and robot.json resolve against the source tree
# (dev behavior, unchanged). A packaging layer (the frozen .exe entry point) can
# override these so sketches are written to a per-user writable location and
# robot.json is read from the bundled resources. Keeping this as overridable
# hooks avoids threading "am I frozen?" conditionals through the builder.

# ── BLE diagnostics ───────────────────────────────────────────────────────────
# BLE pairing is the flakiest part of a classroom session, so these traces are
# worth keeping — but a student double-clicking the packaged app should not see
# them. Off by default; set PAW_BLE_DEBUG=1 to bring them back.
_BLE_DEBUG = bool(os.environ.get("PAW_BLE_DEBUG"))


def _ble_dbg(msg: str) -> None:
    if _BLE_DEBUG:
        print(f"[BLE-DEBUG] {msg}", flush=True)


def _default_sketches_dir() -> str:
    return os.path.join(GAME_DIR, "sketches")


def _default_robot_json() -> str:
    return os.path.join(GAME_DIR, "robot.json")


# These names are what the builder calls; a host may reassign them at startup.
sketches_dir_provider = _default_sketches_dir
robot_json_provider   = _default_robot_json

import pygame

# ── Palette — read dynamically from theme module ─────────────────────────────
import engine.theme as T

# Window size computed at runtime to fill the screen
import pygame as _pg
_pg.init()
WW, WH = _pg.display.Info().current_w, _pg.display.Info().current_h
# Apply same taskbar margin as Layout.compute_window_size
import sys as _sys
_taskbar = {"win32": 48, "darwin": 50}.get(_sys.platform, 52)
WW = max(820, WW - 16)
WH = max(560, WH - _taskbar - 16)
del _pg, _sys, _taskbar

# Code generation imported from codegen.py (no pygame dependency)
from games.ethology.codegen import (
    BEHAVIORS, BEHAVIOR_MAP, BEHAVIOR_CODE,
    needs_light, generate_sketch
)


# ── UI ────────────────────────────────────────────────────────────────────────

class HierarchyBuilder:

    def __init__(self, robot_label: str = "", result_path: str = "",
                 classroom_mode: bool = False):
        self._robot_label = robot_label   # "A", "B", or "" for standalone
        self._result_path = result_path   # path to write hypothesis JSON
        self._game_mode   = bool(robot_label and result_path)
        # Classroom mode: a standalone build that still exposes the HARDWARE
        # actions (Launch Arduino, Send via BLE) but NOT the in-game
        # "Launch Experiment" action. This is the classroom tool: author a
        # hierarchy and flash it to a physical robot, no game shell.
        self._classroom_mode = classroom_mode

        pygame.init()
        self._screen = pygame.display.set_mode((WW, WH))
        title = f"Hierarchy Builder — Robot {robot_label}" \
                if robot_label else "Hierarchy Builder — Robot Ethology"
        pygame.display.set_caption(title)
        self._clock  = pygame.time.Clock()

        from engine.theme import font_hd, font_md, font_sm
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
        surf.blit(tt, (x + 10, y + 10))

        rects = []
        iy = y + 40
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
        from engine.theme import draw_double_rule
        draw_double_rule(surf, 0, 46, WW)

        # Column layout — proportional to window width
        # Lists take ~30% each, middle controls take ~40%
        col_w    = max(220, int(WW * 0.27))
        mid_w    = WW - col_w * 2 - pad * 3
        lx       = pad
        mid_x    = pad + col_w + pad
        rx       = mid_x + mid_w + pad
        list_y   = 68
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
        from engine.theme import draw_double_rule
        draw_double_rule(surf, 0, WH-66, WW)

        can_act = len(self._hierarchy) > 0

        if self._classroom_mode:
            # [Clear All]  [Launch Arduino]  [Send via BLE]
            # Hardware actions only — no in-game "Launch Experiment".
            self._btn(surf,
                      pygame.Rect(pad, WH-54, 90, 38),
                      "Clear All", "btn_clear")
            self._btn(surf,
                      pygame.Rect(pad + 98, WH-54, 150, 38),
                      "Launch Arduino", "btn_arduino",
                      disabled=not can_act)
            self._btn(surf,
                      pygame.Rect(pad + 256, WH-54, 150, 38),
                      "Send via BLE", "btn_ble",
                      accent=True, disabled=not can_act)
        elif self._game_mode:
            # [Clear All]  [Launch Arduino]  [Send via BLE]  [Launch Experiment]
            self._btn(surf,
                      pygame.Rect(pad, WH-54, 90, 38),
                      "Clear All", "btn_clear")
            self._btn(surf,
                      pygame.Rect(pad + 98, WH-54, 150, 38),
                      "Launch Arduino", "btn_arduino",
                      disabled=not can_act)
            self._btn(surf,
                      pygame.Rect(pad + 256, WH-54, 150, 38),
                      "Send via BLE", "btn_ble",
                      disabled=not can_act)
            self._btn(surf,
                      pygame.Rect(WW - 210 - pad, WH-54, 210, 38),
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

        elif name == "btn_ble":
            _ble_dbg("Send via BLE button clicked")
            self._launch_ble()

        elif name == "btn_ok":
            self._submit_hypothesis()

        elif name == "btn_download":
            pass   # placeholder — not yet implemented

        elif name == "btn_gen":
            self._generate()

    def _ble_firmware_ino(self) -> str | None:
        """Path to the real BLE firmware sketch, or None if not in this build.

        The standalone app has an instructor-only "Initialize Robot" button
        that opens exactly this file; the in-game builder had no equivalent, so
        a player in Robot Ethology had NO route to working BLE firmware at all.
        The generated sketch does not contain any.
        """
        try:
            from app_paths import resource_path          # frozen standalone
            cand = resource_path("firmware", "ethology_ble_robot",
                                 "ethology_ble_robot.ino")
        except Exception:
            here = os.path.dirname(os.path.abspath(__file__))
            cand = os.path.normpath(os.path.join(
                here, "..", "..", "firmware", "ethology_ble_robot",
                "ethology_ble_robot.ino"))
        return cand if os.path.exists(cand) else None

    def _launch_bluetooth_firmware(self, robot_name: str | None = None) -> bool:
        """Open the BLE scaffolding sketch in the Arduino IDE."""
        from games.ethology.arduino_export import launch_ide
        ino = self._ble_firmware_ino()
        if ino is None:
            self._set_status(
                "BLE firmware not found in this build — ask your instructor.",
                ok=False)
            return False
        who = robot_name or self._preferred_robot()
        if launch_ide(ino):
            self._set_status(
                f"Opened the Bluetooth program for {who} — set ROBOT_NAME, "
                "upload it, then press Send via BLE again.")
        else:
            self._set_status("Arduino IDE not found — the Bluetooth program's "
                             "folder was opened.", ok=False)
        return True

    def _launch_arduino(self):
        """Export sketch, launch IDE, write result with physical=True flag.

        Two destinations, because they are different programs: the Bluetooth
        scaffolding (which lets the robot RECEIVE a hierarchy) and the
        hypothesis sketch (which HAS one compiled in). The player is asked
        which they want rather than being silently given one — the generated
        hypothesis sketch contains no BLE, so handing it over in answer to
        "enable Bluetooth" was actively misleading.
        """
        want_ble = self._paw_bot_prompt(
            "Do you want to upload a program to allow Bluetooth communication "
            "with your robot? Or would you like to upload a program with your "
            "hierarchy hypothesis?",
            "",
            yes_label="Bluetooth",
            no_label="Hypothesis")

        if want_ble:
            self._launch_bluetooth_firmware()
            return

        if not self._hierarchy:
            self._set_status("Add at least one behavior first", ok=False)
            return

        from games.ethology.codegen import generate_sketch
        from games.ethology.arduino_export import export, launch_ide

        sketch_name = f"current_hypothesis_{self._robot_label}.ino"
        code        = generate_sketch(self._hierarchy, sketch_name, robot_json_path=robot_json_provider())

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
        if self._result_path:
            with open(self._result_path, "w") as f:
                json.dump(result, f)

        if self._classroom_mode:
            # Classroom tool: stay open after launching the IDE / writing the
            # sketch, so the user can keep working or re-launch.
            return

        pygame.quit()
        sys.exit(0)

    def _pick_robot(self) -> str | None:
        """Scan for PAW robots and let the instructor pick which to target
        (Robot A vs Robot B). Returns the chosen advertised name (e.g.
        'RobotA'), or None if cancelled / none found.

        Follows a standard scan -> pick -> connect flow. If nothing is found,
        shows a timeout message asking the instructor to power on the robot and
        bring it near the computer.
        """
        self._set_status("Scanning for robots\u2026", ok=True)
        pygame.display.flip()
        _ble_dbg("_pick_robot: starting scan_paw_robots()...")
        try:
            from engine.bluetooth.robot_bt_client import scan_paw_robots
            found = scan_paw_robots()          # [(name, address), ...]
            _ble_dbg(f"scan_paw_robots found: {found!r}")
        except Exception as e:
            import traceback; traceback.print_exc()
            found = []
            self._set_status(f"Scan error: {e}", ok=False)
            _ble_dbg(f"scan_paw_robots raised: {e!r}")
            return None

        if not found:
            # Nothing answered. The overwhelmingly likely reason is that the
            # robot has no Bluetooth program on it, so offer to fix that
            # rather than just reporting the symptom. Per robot, per session.
            if self._ble_firmware_ack(self._preferred_robot()):
                pass                       # already acknowledged; fall through
            else:
                return None                # sent off to upload, or declined

            # A robot that is already running a hierarchy DOES still advertise
            # (see the Running case in ethology_ble_robot.ino), so it will be
            # found and will answer "busy". Finding nothing therefore means the
            # robot is off, out of range, or has no BLE program on it — and the
            # last of those is by far the most common, so it is named first.
            self._robot_pick_message(
                "No robots found.",
                "Check that the robot is switched ON and its light is "
                "BLINKING — blinking means it is waiting for a hierarchy. "
                "If the light is off, upload the Bluetooth program with "
                "\"Launch Arduino\". If it is SOLID, the robot is already "
                "running one; switch it off and on to send another.")
            return None

        if len(found) == 1:
            # Only one robot found — but name it explicitly and let the
            # instructor confirm or cancel, in case it's not the one intended.
            name = found[0][0]
            if self._confirm_robot(name):
                return name
            return None

        # Multiple robots — present a picker (choice is explicit there).
        return self._robot_pick_dialog(found)

    def _confirm_robot(self, name: str) -> bool:
        """Confirm a connection to a named robot. Returns True to proceed.
        Shown when a single robot is auto-found, so the instructor always sees
        WHICH robot is about to be used and can cancel if it's the wrong one."""
        WW, WH = self._screen.get_size()

        # Size the buttons to their LABELS. They were fixed at 150 px wide,
        # but "Connect to RobotA" is wider than that at this font, so the text
        # spilled past its own border and the box looked unclosed. Any label
        # change would break it again; measuring cannot.
        yes_label, no_label = f"Connect to {name}", "Cancel"
        pad_x, btn_h, gap = 24, 42, 20
        yes_w = self._font_sm.size(yes_label)[0] + pad_x * 2
        no_w  = max(110, self._font_sm.size(no_label)[0] + pad_x * 2)
        total = yes_w + gap + no_w
        yes_r = pygame.Rect(WW//2 - total//2,             WH//2 + 30, yes_w, btn_h)
        no_r  = pygame.Rect(yes_r.right + gap,            WH//2 + 30, no_w,  btn_h)
        clock = pygame.time.Clock()
        while True:
            mouse = pygame.mouse.get_pos()
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return False
                if e.type == pygame.KEYDOWN:
                    if e.key in (pygame.K_RETURN,):
                        return True
                    if e.key == pygame.K_ESCAPE:
                        return False
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    if yes_r.collidepoint(e.pos):
                        return True
                    if no_r.collidepoint(e.pos):
                        return False
            ov = pygame.Surface((WW, WH), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 180)); self._screen.blit(ov, (0, 0))
            tt = self._font_md.render(f"Connect to {name}?", True, T.WHITE_GREEN)
            self._screen.blit(tt, (WW//2 - tt.get_width()//2, WH//2 - 40))
            sub = self._font_sm.render(
                "This is the only robot found nearby.", True, T.TEXT_DIM)
            self._screen.blit(sub, (WW//2 - sub.get_width()//2, WH//2 - 8))
            for r, label, accent in ((yes_r, yes_label, True),
                                     (no_r, no_label, False)):
                hov = r.collidepoint(mouse)
                pygame.draw.rect(self._screen, T.PANEL if not hov else
                                 T.PANEL_DEEP, r, border_radius=6)
                pygame.draw.rect(self._screen,
                                 T.WHITE_GREEN if accent else T.BORDER, r,
                                 2 if accent else 1, border_radius=6)
                # shrink font if label is long
                fnt = self._font_sm
                lt = fnt.render(label, True,
                                T.WHITE_GREEN if accent else T.TEXT_DIM)
                self._screen.blit(lt, (r.centerx - lt.get_width()//2,
                                       r.centery - lt.get_height()//2))
            pygame.display.flip()
            clock.tick(60)

    def _robot_pick_dialog(self, found: list) -> str | None:
        """Modal list of discovered robots; returns the chosen name or None."""
        WW, WH = self._screen.get_size()
        f_title = self._font_md
        f_item  = self._font_md
        rows = []
        for i, (name, _addr) in enumerate(found):
            r = pygame.Rect(WW//2 - 180, WH//2 - 60 + i*54, 360, 46)
            rows.append((r, name))
        cancel_r = pygame.Rect(WW//2 - 80, WH//2 - 60 + len(found)*54 + 12,
                               160, 38)
        clock = pygame.time.Clock()
        while True:
            mouse = pygame.mouse.get_pos()
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return None
                if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                    return None
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    if cancel_r.collidepoint(e.pos):
                        return None
                    for r, name in rows:
                        if r.collidepoint(e.pos):
                            return name
            # dim backdrop
            ov = pygame.Surface((WW, WH), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 180)); self._screen.blit(ov, (0, 0))
            tt = f_title.render("Select a robot to send to:", True, T.WHITE_GREEN)
            self._screen.blit(tt, (WW//2 - tt.get_width()//2, WH//2 - 110))
            for r, name in rows:
                hov = r.collidepoint(mouse)
                pygame.draw.rect(self._screen, T.PANEL if not hov else
                                 T.PANEL_DEEP, r, border_radius=6)
                pygame.draw.rect(self._screen, T.PHOSPHOR, r, 1, border_radius=6)
                it = f_item.render(name, True, T.TEXT)
                self._screen.blit(it, (r.centerx - it.get_width()//2,
                                       r.centery - it.get_height()//2))
            hov = cancel_r.collidepoint(mouse)
            pygame.draw.rect(self._screen, T.PANEL if not hov else T.PANEL_DEEP,
                             cancel_r, border_radius=6)
            pygame.draw.rect(self._screen, T.BORDER, cancel_r, 1, border_radius=6)
            ct = self._font_sm.render("Cancel", True, T.TEXT_DIM)
            self._screen.blit(ct, (cancel_r.centerx - ct.get_width()//2,
                                   cancel_r.centery - ct.get_height()//2))
            pygame.display.flip()
            clock.tick(60)

    def _robot_pick_message(self, title: str, body: str) -> None:
        """Simple OK message (e.g. no robots found).

        The box is sized to its content and the button sits BELOW the text.
        Both used to be at fixed offsets from the screen centre — the OK
        button at WH//2+50 while the body wrapped downward from WH//2-20 — so
        a message longer than about three lines ran straight through the
        button. Lengthening the "no robots found" text is what exposed it.
        """
        WW, WH = self._screen.get_size()

        max_w = min(560, WW - 120)
        words, lines, line = body.split(), [], ""
        for w in words:
            trial = (line + " " + w).strip()
            if self._font_sm.size(trial)[0] <= max_w:
                line = trial
            else:
                lines.append(line)
                line = w
        if line:
            lines.append(line)

        pad, line_h, btn_h = 26, 22, 40
        box_w = max_w + pad * 2
        box_h = pad + 30 + len(lines) * line_h + 18 + btn_h + pad
        box = pygame.Rect(WW//2 - box_w//2, WH//2 - box_h//2, box_w, box_h)
        ok_r = pygame.Rect(box.centerx - 60, box.bottom - pad - btn_h, 120, btn_h)

        clock = pygame.time.Clock()
        while True:
            mouse = pygame.mouse.get_pos()
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return
                if e.type == pygame.KEYDOWN and e.key in (
                        pygame.K_ESCAPE, pygame.K_RETURN):
                    return
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    if ok_r.collidepoint(e.pos):
                        return

            ov = pygame.Surface((WW, WH), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 190)); self._screen.blit(ov, (0, 0))
            pygame.draw.rect(self._screen, T.PANEL, box, border_radius=8)
            pygame.draw.rect(self._screen, T.WHITE_GREEN, box, 2, border_radius=8)

            tt = self._font_md.render(title, True, T.WHITE_GREEN)
            self._screen.blit(tt, (box.centerx - tt.get_width()//2, box.y + pad))
            y = box.y + pad + 30
            for ln in lines:
                bl = self._font_sm.render(ln, True, T.TEXT)
                self._screen.blit(bl, (box.centerx - bl.get_width()//2, y))
                y += line_h

            hov = ok_r.collidepoint(mouse)
            pygame.draw.rect(self._screen,
                             T.PANEL_DEEP if hov else T.PANEL, ok_r, border_radius=6)
            pygame.draw.rect(self._screen, T.WHITE_GREEN, ok_r, 2, border_radius=6)
            ot = self._font_sm.render("OK", True, T.WHITE_GREEN)
            self._screen.blit(ot, (ok_r.centerx - ot.get_width()//2,
                                   ok_r.centery - ot.get_height()//2))
            pygame.display.flip()
            clock.tick(60)

    def _preferred_robot(self) -> str:
        """Which robot this builder session is for.

        The builder is launched per robot label (A or B), so use that. Falls
        back to RobotA only when there is no label at all.
        """
        lbl = getattr(self, "_robot_label", None) or getattr(self, "robot_label", None)
        if lbl:
            lbl = str(lbl).strip().upper().replace("ROBOT", "").strip()
            if lbl in ("A", "B"):
                return f"Robot{lbl}"
        return "RobotA"

    def _ble_firmware_ack(self, robot_name: str | None = None) -> bool:
        """True if the player may proceed to send over BLE.

        Scope is PER ROBOT and PER SESSION, and both matter:

        * PER ROBOT — this used to be one global flag file. Acknowledge it
          once and the prompt never appeared again, including for a second
          robot that had no firmware on it. RobotB was unreachable and the
          game gave no hint why.

        * PER SESSION — in memory, not on disk. A new playthrough may well be
          a new robot, or the same one re-flashed with something else; a flag
          that outlived the session meant the first Send via BLE of the next
          playthrough failed with a bare "no robot could be reached".

        Returns False if the player declines or is sent off to upload, so the
        send is abandoned rather than failing later with a misleading scan.
        """
        who = robot_name or "this robot"
        if not hasattr(self, "_ble_acked"):
            self._ble_acked = set()          # reset every session by construction
        if who in self._ble_acked:
            return True

        choice = self._paw_bot_prompt(
            f"To send your hierarchy to {who} via BLE, that robot needs a "
            "special program on it to enable Bluetooth communications.",
            "Would you like me to launch the Arduino IDE so you can upload "
            "the program?",
            yes_label="Yes, launch Arduino",
            no_label="No, not now")

        if not choice:
            self._set_status(
                f"Send cancelled — {who} needs the Bluetooth program first.",
                ok=False)
            return False

        # Mark BEFORE launching: they have been told, and the message should
        # not reappear for this robot even if the IDE fails to open.
        self._ble_acked.add(who)
        self._launch_bluetooth_firmware(robot_name)

        self._paw_bot_prompt(
            "If you have trouble with uploading, or need to (re-)upload to a "
            "(new) robot, you may always select \"Launch Arduino\".",
            "You may also use that button to upload your hypothesis directly.",
            yes_label="Got it", no_label=None)
        return False

    def _paw_bot_prompt(self, body: str, question: str,
                        yes_label: str = "Yes", no_label: str | None = "No") -> bool:
        """Modal PAW-Bot message with Yes/No, or a single button if no_label
        is None. Returns True for yes. Follows the same shape as
        _confirm_robot() so the two read alike."""
        WW, WH = self._screen.get_size()

        def wrap(text, font, width):
            words, lines, cur = text.split(), [], ""
            for w in words:
                t = (cur + " " + w).strip()
                if font.size(t)[0] <= width:
                    cur = t
                else:
                    lines.append(cur); cur = w
            if cur:
                lines.append(cur)
            return lines

        box_w = min(720, WW - 80)
        body_lines = wrap(body, self._font_sm, box_w - 60)
        q_lines    = wrap(question, self._font_sm, box_w - 60)
        n_lines    = len(body_lines) + len(q_lines) + 1
        box_h      = 90 + n_lines * 22 + 60
        box        = pygame.Rect(WW//2 - box_w//2, WH//2 - box_h//2, box_w, box_h)

        if no_label is None:
            yes_r = pygame.Rect(box.centerx - 90, box.bottom - 56, 180, 40)
            no_r  = None
        else:
            yes_r = pygame.Rect(box.centerx - 200, box.bottom - 56, 190, 40)
            no_r  = pygame.Rect(box.centerx + 10,  box.bottom - 56, 190, 40)

        clock = pygame.time.Clock()
        while True:
            mouse = pygame.mouse.get_pos()
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    return False
                if e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_RETURN:
                        return True
                    if e.key == pygame.K_ESCAPE and no_r is not None:
                        return False
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    if yes_r.collidepoint(e.pos):
                        return True
                    if no_r is not None and no_r.collidepoint(e.pos):
                        return False

            ov = pygame.Surface((WW, WH), pygame.SRCALPHA)
            ov.fill((0, 0, 0, 190)); self._screen.blit(ov, (0, 0))
            pygame.draw.rect(self._screen, T.PANEL, box, border_radius=8)
            pygame.draw.rect(self._screen, T.WHITE_GREEN, box, 2, border_radius=8)

            y = box.y + 22
            hdr = self._font_md.render("PAW-BOT:", True, T.WHITE_GREEN)
            self._screen.blit(hdr, (box.x + 30, y)); y += 34
            for ln in body_lines:
                self._screen.blit(self._font_sm.render(ln, True, T.TEXT), (box.x + 30, y))
                y += 22
            y += 10
            for ln in q_lines:
                self._screen.blit(self._font_sm.render(ln, True, T.WHITE_GREEN), (box.x + 30, y))
                y += 22

            buttons = [(yes_r, yes_label, True)]
            if no_r is not None:
                buttons.append((no_r, no_label, False))
            for r, label, accent in buttons:
                hov = r.collidepoint(mouse)
                pygame.draw.rect(self._screen,
                                 T.PANEL_DEEP if hov else T.PANEL, r, border_radius=6)
                pygame.draw.rect(self._screen,
                                 T.WHITE_GREEN if accent else T.BORDER, r,
                                 2 if accent else 1, border_radius=6)
                lt = self._font_sm.render(
                    label, True, T.WHITE_GREEN if accent else T.TEXT_DIM)
                self._screen.blit(lt, (r.centerx - lt.get_width()//2,
                                       r.centery - lt.get_height()//2))
            pygame.display.flip()
            clock.tick(60)

    def _launch_ble(self):
        """
        Connect to the physical robot over BLE, send the hierarchy,
        and write the result JSON with ble=True so the hub enters
        physical experiment state.  On failure, shows the PAW-Bot
        connection failure dialog.
        """
        if not self._hierarchy:
            _ble_dbg("_launch_ble: no hierarchy — aborting (add a behavior first)")
            self._set_status("Add at least one behavior first", ok=False)
            return

        _ble_dbg("_launch_ble: hierarchy OK, calling _pick_robot()")
        # Scan -> pick -> connect: choose which robot (A/B) to send to.
        target_name = self._pick_robot()
        _ble_dbg(f"_pick_robot returned: {target_name!r}")
        if not target_name:
            self._set_status("Send cancelled.", ok=False)
            return

        while True:   # retry loop
            self._set_status(f"Connecting to {target_name}\u2026", ok=True)
            pygame.display.flip()

            session = None
            error   = None
            try:
                from engine.bluetooth.robot_bt_client import RobotBLEClient
                client = RobotBLEClient(target_name)
                result_ping = client.ping()
                if not result_ping.get("reachable"):
                    error = result_ping.get("error", "device not found")
                elif result_ping.get("status") == "busy":
                    # By design: one hierarchy per power cycle. Say what to do
                    # rather than what went wrong — "reset the Arduino" is
                    # ambiguous (reset button? re-upload?) and the actual
                    # requirement is a power cycle.
                    error = ("Robot is already running a hierarchy. "
                             "Switch it OFF and ON, wait for the light to "
                             "blink, then send again.")
                else:
                    resp = client.send_hierarchy(self._hierarchy)
                    if resp.get("ok"):
                        session = resp["session"]
                    else:
                        error = resp.get("error", "hierarchy rejected")
            except Exception as e:
                error = str(e)

            if session is not None:
                break   # success

            # Connection failed — show PAW-Bot dialog
            self._set_status(f"BLE failed: {error}", ok=False)
            print(f"[BLE] error: {error}", flush=True)
            choice = self._ble_fail_dialog()
            if choice == "retry":
                continue
            elif choice == "simulate":
                # Signal hub to launch simulation instead
                import json
                result = {
                    "robot":     self._robot_label,
                    "hierarchy": self._hierarchy,
                    "ble":       False,
                    "simulate":  True,
                }
                with open(self._result_path, "w") as f:
                    json.dump(result, f)
                pygame.quit()
                sys.exit(0)
            else:
                return   # cancelled

        # Success — write result JSON
        import json
        result = {
            "robot":     self._robot_label,
            "hierarchy": self._hierarchy,
            "ble":       True,
            "session":   session,
            "device":    "RobotA",
        }
        if self._result_path:
            with open(self._result_path, "w") as f:
                json.dump(result, f)

        if self._classroom_mode:
            # Classroom tool: stay open so the user can send again / keep
            # working. Just confirm success; don't quit the app.
            self._set_status("Sent to robot via BLE \u2713", ok=True)
            return

        pygame.quit()
        sys.exit(0)

    def _ble_fail_dialog(self) -> str:
        """
        Show PAW-Bot BLE failure dialog.
        Returns "retry", "simulate", or "cancel".
        """
        import os
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "scripts", "paw_bot", "ble_connect_failed.txt")
        if os.path.exists(script_path):
            with open(script_path) as f:
                text = f.read()
        else:
            text = ("PAW-BOT: Failed to connect to your robot.\n"
                    "PAW-BOT: Press Try Again, or Continue in Simulation.")

        # Simple blocking dialog using pygame
        screen = pygame.display.get_surface()
        W, H   = screen.get_size()
        font   = pygame.font.SysFont("Courier New", 15)

        # Render text lines
        lines  = [l for l in text.strip().split("\n") if l.strip()]
        choice = None

        # Button rects
        BTN_W, BTN_H = 220, 40
        retry_r  = pygame.Rect(W//2 - BTN_W - 10, H*2//3, BTN_W, BTN_H)
        sim_r    = pygame.Rect(W//2 + 10,          H*2//3, BTN_W, BTN_H)

        while choice is None:
            screen.fill((10, 18, 10))
            # Draw text
            y = H // 4
            for line in lines:
                line = line.strip()
                if line.startswith("PAW-BOT:"):
                    line = line[8:].strip()
                surf = font.render(line, True, (160, 220, 160))
                screen.blit(surf, (W//2 - surf.get_width()//2, y))
                y += surf.get_height() + 6

            # Draw buttons — in classroom mode there is no simulation, so the
            # second button is a plain Cancel rather than "Continue in Simulation".
            sim_label = ("Cancel" if self._classroom_mode
                         else "Continue in Simulation")
            for rect, label, col in [
                (retry_r, "Try Again",  (40, 120, 60)),
                (sim_r,   sim_label,    (60,  80, 120)),
            ]:
                pygame.draw.rect(screen, col, rect, border_radius=6)
                lt = font.render(label, True, (220, 255, 220))
                screen.blit(lt, (rect.centerx - lt.get_width()//2,
                                 rect.centery - lt.get_height()//2))

            pygame.display.flip()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    choice = "cancel"
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if retry_r.collidepoint(event.pos):
                        choice = "retry"
                    elif sim_r.collidepoint(event.pos):
                        choice = "cancel" if self._classroom_mode else "simulate"
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        choice = "cancel"

        return choice

    def _submit_hypothesis(self):
        """Write hypothesis to result file and close (game mode only)."""
        if not self._hierarchy:
            self._set_status("Add at least one behavior first", ok=False)
            return

        import json
        sketches_dir = sketches_dir_provider()
        os.makedirs(sketches_dir, exist_ok=True)
        import datetime
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        name  = f"hypothesis_{self._robot_label}_{stamp}.ino"
        path  = os.path.join(sketches_dir, name)

        code = generate_sketch(self._hierarchy, name, robot_json_path=robot_json_provider())
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

        sketches_dir = sketches_dir_provider()
        os.makedirs(sketches_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        name  = f"hierarchy_{stamp}.ino"
        path  = os.path.join(sketches_dir, name)

        code = generate_sketch(self._hierarchy, name, robot_json_path=robot_json_provider())
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
    import engine.theme as T
    T.apply(T.load_saved_theme())
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--robot",  default="",  help="Robot label (A or B)")
    ap.add_argument("--result", default="",  help="Path to write hypothesis JSON")
    ap.add_argument("--arena",  default="",  help="Arena path (unused, for future use)")
    args = ap.parse_args()
    HierarchyBuilder(robot_label=args.robot,
                     result_path=args.result).run()
