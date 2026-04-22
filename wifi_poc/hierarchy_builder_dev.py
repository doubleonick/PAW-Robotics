"""
hierarchy_builder_dev.py
-------------------------
Standalone development copy of the Hierarchy Builder.
Lives at the project root — run directly with:

    py -3.12 hierarchy_builder_dev.py

Changes made here can be folded back into
games/ethology/hierarchy_builder.py when ready.

WiFi changes (Task 3)
---------------------
"Launch Arduino" now tries RobotWiFiClient first:

  1. Reads robot IP / port from wifi_config.json (root folder).
     Falls back to 192.168.4.1:80 if file absent.

  2. Pings the robot.
     - Not reachable  → offer IDE fallback or cancel.
     - Busy           → show busy message, offer wait or cancel.
     - Idle           → send hierarchy, write result with wifi=True.

  3. On success the builder closes and the hub enters the physical
     experiment timer state exactly as before — the hub doesn't need
     to know whether WiFi or IDE was used.

  4. A "WiFi Config" button in the bottom bar opens a small in-window
     overlay where the player can edit IP and port.  Changes are saved
     immediately to wifi_config.json.
"""

import json
import os
import sys
import datetime

ROOT     = os.path.dirname(os.path.abspath(__file__))
GAME_DIR = os.path.join(ROOT, "games", "ethology")
sys.path.insert(0, ROOT)

import pygame
import robosim.theme as T
from games.ethology.codegen import (
    BEHAVIORS, BEHAVIOR_MAP, BEHAVIOR_CODE,
    needs_light, generate_sketch,
)

WW, WH = 820, 560

# ── WiFi config helpers ────────────────────────────────────────────────────────

WIFI_CONFIG_PATH = os.path.join(ROOT, "wifi_config.json")
_WIFI_DEFAULTS   = {"host": "192.168.4.1", "port": 80}


def load_wifi_config() -> dict:
    try:
        with open(WIFI_CONFIG_PATH) as f:
            cfg = json.load(f)
        return {
            "host": str(cfg.get("host", _WIFI_DEFAULTS["host"])),
            "port": int(cfg.get("port", _WIFI_DEFAULTS["port"])),
        }
    except Exception:
        return dict(_WIFI_DEFAULTS)


def save_wifi_config(host: str, port: int) -> None:
    with open(WIFI_CONFIG_PATH, "w") as f:
        json.dump({"host": host, "port": port}, f, indent=2)


# ── HierarchyBuilder ──────────────────────────────────────────────────────────

class HierarchyBuilder:

    def __init__(self, robot_label: str = "", result_path: str = ""):
        self._robot_label = robot_label
        self._result_path = result_path
        self._game_mode   = bool(robot_label and result_path)

        pygame.init()
        self._screen = pygame.display.set_mode((WW, WH))
        title = f"Hierarchy Builder — Robot {robot_label}" \
                if robot_label else "Hierarchy Builder — Robot Ethology"
        pygame.display.set_caption(title)
        self._clock = pygame.time.Clock()

        from robosim.theme import font_hd, font_md, font_sm
        self._font_hd = font_hd()
        self._font_md = font_md()
        self._font_sm = font_sm()

        self._pool      = [b[1] for b in BEHAVIORS]
        self._hierarchy = []
        self._pool_sel  = -1
        self._hier_sel  = -1

        self._status     = "Select behaviors and build your hierarchy"
        self._status_col = T.TEXT_DIM
        self._btn_rects  = {}

        # WiFi config overlay state
        self._wifi_cfg         = load_wifi_config()
        self._show_wifi_cfg    = False
        self._wifi_edit_field  = None    # "host" | "port" | None
        self._wifi_edit_buf    = ""      # text currently being typed
        self._wifi_cfg_btns    = {}

        # Standalone WiFi session state
        self._sa_session  = ""     # token from last successful send
        self._sa_running  = False  # True = robot currently running

    # ── Status ────────────────────────────────────────────────────────────────

    def _set_status(self, msg, ok=True):
        self._status     = msg
        self._status_col = T.PHOSPHOR if ok else T.AMBER

    # ── List drawing ──────────────────────────────────────────────────────────

    def _draw_list(self, surf, items, sel_idx, x, y, w, h, title):
        pygame.draw.rect(surf, T.PANEL,  (x, y, w, h), border_radius=6)
        pygame.draw.rect(surf, T.BORDER, (x, y, w, h), 1, border_radius=6)
        tt = self._font_md.render(title, True, T.WHITE_GREEN)
        surf.blit(tt, (x + 10, y + 8))

        rects = []
        iy    = y + 36
        row_h = 34
        for i, key in enumerate(items):
            label = BEHAVIOR_MAP[key][0]
            r     = pygame.Rect(x + 6, iy, w - 12, row_h - 2)
            rects.append(r)
            sel = (i == sel_idx)
            bg  = T.PHOSPHOR_DIM if sel else T.PANEL
            pygame.draw.rect(surf, bg, r, border_radius=4)
            if sel:
                pygame.draw.rect(surf, T.PHOSPHOR_MID, r, 1, border_radius=4)
            lx = r.x + 10
            if title.startswith("Hierarchy"):
                num = self._font_sm.render(f"{i+1}.",
                      True, T.TEXT_DIM if not sel else T.WHITE_GREEN)
                surf.blit(num, (lx, r.centery - num.get_height()//2))
                lx += 24
            lt = self._font_md.render(label, True,
                                      T.WHITE_GREEN if sel else T.TEXT)
            surf.blit(lt, (lx, r.centery - lt.get_height()//2))
            iy += row_h
        return rects

    # ── Button drawing ────────────────────────────────────────────────────────

    def _btn(self, surf, rect, label, name, accent=False, disabled=False,
             btn_dict=None):
        d = btn_dict if btn_dict is not None else self._btn_rects
        d[name] = rect
        mx, my = pygame.mouse.get_pos()
        hov = rect.collidepoint(mx, my) and not disabled
        if disabled:
            col = (26, 30, 44)
        elif accent:
            col = T.PHOSPHOR_MID if hov else (40, 100, 180)
        else:
            col = T.PHOSPHOR_DIM if hov else T.PANEL_DEEP
        pygame.draw.rect(surf, col,    rect, border_radius=5)
        pygame.draw.rect(surf, T.BORDER if not disabled else (30, 33, 46),
                         rect, 1, border_radius=5)
        tc = T.TEXT_DIM if disabled else (T.WHITE_GREEN if accent else T.TEXT)
        t  = self._font_md.render(label, True, tc)
        surf.blit(t, (rect.centerx - t.get_width()  // 2,
                      rect.centery - t.get_height() // 2))

    # ── Main draw ─────────────────────────────────────────────────────────────

    def _draw(self):
        surf = self._screen
        surf.fill(T.BG)
        self._btn_rects  = {}
        self._pool_rects = []
        self._hier_rects = []

        pad = 16

        # Title
        title_text = (f"Build Hypothesis — Robot {self._robot_label}"
                      if self._game_mode else "Hierarchy Builder")
        tt = self._font_hd.render(title_text, True, T.WHITE_GREEN)
        surf.blit(tt, (pad, 12))
        from robosim.theme import draw_double_rule
        draw_double_rule(surf, 0, 46, WW)

        # Column layout
        col_w  = 280
        mid_w  = WW - col_w * 2 - pad * 3
        lx     = pad
        mid_x  = pad + col_w + pad
        rx     = mid_x + mid_w + pad
        list_y = 54
        list_h = WH - list_y - 90

        self._pool_rects = self._draw_list(
            surf, self._pool, self._pool_sel,
            lx, list_y, col_w, list_h, "Behavior Pool")

        self._hier_rects = self._draw_list(
            surf, self._hierarchy, self._hier_sel,
            rx, list_y, col_w, list_h, "Hierarchy  (top = highest priority)")

        # Centre arrow buttons
        bw, bh = mid_w - 8, 36
        bx     = mid_x + 4
        cy     = list_y + list_h // 2 - bh * 3
        self._btn(surf, pygame.Rect(bx, cy,       bw, bh), "→  Add",    "btn_add")
        self._btn(surf, pygame.Rect(bx, cy + 46,  bw, bh), "←  Remove","btn_remove")
        self._btn(surf, pygame.Rect(bx, cy + 100, bw, bh), "↑  Up",    "btn_up")
        self._btn(surf, pygame.Rect(bx, cy + 146, bw, bh), "↓  Down",  "btn_down")

        # Bottom bar
        draw_double_rule(surf, 0, WH - 66, WW)
        can_act = len(self._hierarchy) > 0

        # Status line — above the buttons, always visible
        if self._status:
            st = self._font_sm.render(self._status, True, self._status_col)
            surf.blit(st, (pad, WH - 66 - st.get_height() - 4))

        if self._game_mode:
            self._btn(surf, pygame.Rect(pad,              WH-54, 90,  38),
                      "Clear All",        "btn_clear")
            self._btn(surf, pygame.Rect(pad + 98,         WH-54, 160, 38),
                      "WiFi Robot",       "btn_wifi",
                      disabled=not can_act)
            self._btn(surf, pygame.Rect(pad + 266,        WH-54, 120, 38),
                      "IDE Fallback",     "btn_arduino",
                      disabled=not can_act)
            self._btn(surf, pygame.Rect(WW - 8 - 34 - 8 - 158, WH-54, 158, 38),
                      "Launch Experiment","btn_ok",
                      accent=True, disabled=not can_act)
        else:
            # Standalone mode:
            # [Clear All]  [Send to Robot]  [Stop Robot]  [Generate Sketch] [...]
            # Send enabled when hierarchy non-empty and not currently running.
            # Stop enabled only when a run is active.
            can_send = can_act and not self._sa_running
            can_stop = self._sa_running

            self._btn(surf, pygame.Rect(pad,        WH-54,  90, 38),
                      "Clear All",       "btn_clear")
            self._btn(surf, pygame.Rect(pad + 98,   WH-54, 150, 38),
                      "Send to Robot",   "btn_sa_send",
                      accent=True,  disabled=not can_send)
            self._btn(surf, pygame.Rect(pad + 256,  WH-54, 120, 38),
                      "Stop Robot",      "btn_sa_stop",
                      disabled=not can_stop)
            self._btn(surf, pygame.Rect(pad + 384,  WH-54, 150, 38),
                      "Generate Sketch", "btn_gen",
                      disabled=not can_act)

        # WiFi config gear button — rightmost, 8px from window edge
        # Standalone: Generate Sketch ends at x=760, gear starts at x=772 → 12px gap
        # Game mode:  Launch Experiment ends at x=788, gear starts at x=772 → push
        #             Launch Experiment left so it ends at x=768
        self._btn(surf, pygame.Rect(WW - 8 - 34, WH-54, 34, 38),
                  "...", "btn_wifi_cfg")

        # WiFi config overlay
        if self._show_wifi_cfg:
            self._draw_wifi_cfg_overlay(surf)

        pygame.display.flip()

    # ── WiFi config overlay ───────────────────────────────────────────────────

    def _draw_wifi_cfg_overlay(self, surf):
        """
        Small centered overlay for editing robot IP and port.
        Active field is highlighted; type to edit, Enter to confirm.
        """
        ow, oh = 400, 220
        ox = (WW - ow) // 2
        oy = (WH - oh) // 2

        # Background panel
        pygame.draw.rect(surf, T.PANEL_DEEP, (ox, oy, ow, oh), border_radius=8)
        pygame.draw.rect(surf, T.BORDER,     (ox, oy, ow, oh), 2, border_radius=8)

        pad = 18
        y   = oy + pad

        title = self._font_md.render("WiFi Robot Config", True, T.WHITE_GREEN)
        surf.blit(title, (ox + pad, y));  y += 30

        from robosim.theme import draw_double_rule
        draw_double_rule(surf, ox, y, ox + ow);  y += 14

        self._wifi_cfg_btns = {}

        def field(label, key, val, field_y):
            lbl = self._font_sm.render(label, True, T.TEXT_DIM)
            surf.blit(lbl, (ox + pad, field_y))
            editing = (self._wifi_edit_field == key)
            display = self._wifi_edit_buf if editing else str(val)
            fr      = pygame.Rect(ox + 120, field_y - 2, ow - 140, 26)
            fg      = T.PHOSPHOR_DIM if editing else T.PANEL
            pygame.draw.rect(surf, fg,       fr, border_radius=4)
            pygame.draw.rect(surf, T.PHOSPHOR_MID if editing else T.BORDER,
                             fr, 1, border_radius=4)
            vt = self._font_sm.render(
                display + ("|" if editing else ""), True, T.WHITE_GREEN)
            surf.blit(vt, (fr.x + 6, fr.y + 4))
            self._wifi_cfg_btns[f"field_{key}"] = fr

        field("Robot IP",  "host", self._wifi_cfg["host"], y);  y += 36
        field("Port",      "port", self._wifi_cfg["port"], y);  y += 44

        # Current config summary
        summary = self._font_sm.render(
            f"Current: {self._wifi_cfg['host']}:{self._wifi_cfg['port']}",
            True, T.TEXT_DIM)
        surf.blit(summary, (ox + pad, y));  y += 28

        # Buttons
        bw = (ow - pad * 3) // 2
        self._btn(surf, pygame.Rect(ox + pad,          y, bw, 32),
                  "Save & Close", "cfg_save",   accent=True,
                  btn_dict=self._wifi_cfg_btns)
        self._btn(surf, pygame.Rect(ox + pad * 2 + bw, y, bw, 32),
                  "Cancel",       "cfg_cancel",
                  btn_dict=self._wifi_cfg_btns)

    # ── Button handlers ───────────────────────────────────────────────────────

    def _handle_btn(self, name):
        if name == "btn_add":
            if 0 <= self._pool_sel < len(self._pool):
                key = self._pool.pop(self._pool_sel)
                self._hierarchy.append(key)
                self._pool_sel = min(self._pool_sel, len(self._pool) - 1)
                self._hier_sel = len(self._hierarchy) - 1

        elif name == "btn_remove":
            if 0 <= self._hier_sel < len(self._hierarchy):
                key = self._hierarchy.pop(self._hier_sel)
                self._pool.append(key)
                self._hier_sel = min(self._hier_sel, len(self._hierarchy) - 1)
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
            self._pool.extend(self._hierarchy)
            orig           = [b[1] for b in BEHAVIORS]
            self._pool     = [k for k in orig if k in self._pool]
            self._hierarchy = []
            self._pool_sel  = -1
            self._hier_sel  = -1
            self._set_status("Cleared")

        elif name == "btn_wifi":
            self._launch_wifi()

        elif name == "btn_arduino":
            self._launch_ide()

        elif name == "btn_ok":
            self._submit_hypothesis()

        elif name == "btn_gen":
            self._generate()

        elif name == "btn_sa_send":
            self._send_to_robot()

        elif name == "btn_sa_stop":
            self._stop_robot()

        elif name == "btn_wifi_cfg":
            self._wifi_edit_field = None
            self._wifi_edit_buf   = ""
            self._show_wifi_cfg   = not self._show_wifi_cfg

    def _handle_wifi_cfg_btn(self, name):
        if name.startswith("field_"):
            # Commit any currently active field before switching to a new one
            if self._wifi_edit_field is not None:
                val = self._wifi_edit_buf.strip()
                if self._wifi_edit_field == "port":
                    try:
                        val = int(val)
                    except ValueError:
                        val = _WIFI_DEFAULTS["port"]
                self._wifi_cfg[self._wifi_edit_field] = val

            key                   = name[len("field_"):]
            self._wifi_edit_field = key
            self._wifi_edit_buf   = str(self._wifi_cfg[key])

        elif name == "cfg_save":
            # Commit any field still being typed (user clicked Save without pressing Enter)
            if self._wifi_edit_field is not None:
                val = self._wifi_edit_buf.strip()
                if self._wifi_edit_field == "port":
                    try:
                        val = int(val)
                    except ValueError:
                        val = _WIFI_DEFAULTS["port"]
                self._wifi_cfg[self._wifi_edit_field] = val
                self._wifi_edit_field = None

            host = self._wifi_cfg.get("host", _WIFI_DEFAULTS["host"])
            port = self._wifi_cfg.get("port", _WIFI_DEFAULTS["port"])
            try:
                port = int(port)
            except ValueError:
                port = _WIFI_DEFAULTS["port"]
            self._wifi_cfg = {"host": host, "port": port}
            save_wifi_config(host, port)
            self._show_wifi_cfg   = False
            self._wifi_edit_field = None
            self._set_status(f"WiFi config saved: {host}:{port}")

        elif name == "cfg_cancel":
            self._wifi_cfg        = load_wifi_config()   # revert
            self._show_wifi_cfg   = False
            self._wifi_edit_field = None

    def _handle_wifi_cfg_key(self, event):
        """Handle keypresses when the WiFi config overlay is open."""
        if self._wifi_edit_field is None:
            if event.key == pygame.K_ESCAPE:
                self._show_wifi_cfg = False
            return

        if event.key == pygame.K_RETURN:
            # Commit the edit to wifi_cfg dict (not saved until Save button)
            val = self._wifi_edit_buf.strip()
            if self._wifi_edit_field == "port":
                try:
                    val = int(val)
                except ValueError:
                    val = _WIFI_DEFAULTS["port"]
            self._wifi_cfg[self._wifi_edit_field] = val
            self._wifi_edit_field = None

        elif event.key == pygame.K_ESCAPE:
            self._wifi_edit_field = None

        elif event.key == pygame.K_BACKSPACE:
            self._wifi_edit_buf = self._wifi_edit_buf[:-1]

        else:
            ch = event.unicode
            # Port field: digits only
            if self._wifi_edit_field == "port":
                if ch.isdigit() and len(self._wifi_edit_buf) < 5:
                    self._wifi_edit_buf += ch
            else:
                # Host field: printable ASCII, reasonable length
                if ch and ch.isprintable() and len(self._wifi_edit_buf) < 39:
                    self._wifi_edit_buf += ch

    # ── Standalone WiFi send / stop ──────────────────────────────────────────

    def _get_client(self):
        from robot_wifi_client import RobotWiFiClient
        return RobotWiFiClient(
            host=self._wifi_cfg["host"],
            port=self._wifi_cfg["port"],
            timeout=4.0)

    def _send_to_robot(self):
        if not self._hierarchy:
            self._set_status("Add at least one behavior first", ok=False)
            return

        host = self._wifi_cfg["host"]
        port = self._wifi_cfg["port"]
        self._set_status(f"Connecting to {host}:{port} ...")
        self._draw()

        client = self._get_client()
        ping   = client.ping()

        if not ping.get("reachable"):
            self._set_status(
                f"Robot not reachable ({host}:{port}) — check WiFi or ... config",
                ok=False)
            return

        if ping.get("status") == "busy":
            self._set_status(
                f"Robot busy (session {ping.get('session','?')}) — "
                f"stop it first or wait", ok=False)
            return

        result = client.send_hierarchy(self._hierarchy)
        if not result.get("ok"):
            self._set_status(
                f"Send failed: {result.get('error', 'unknown')}",
                ok=False)
            return

        self._sa_session = result["session"]
        self._sa_running = True
        self._set_status(
            f"Running  session={self._sa_session}  —  "
            f"click Stop Robot when done")

    def _stop_robot(self):
        if not self._sa_session:
            self._set_status("No active session to stop", ok=False)
            return

        self._set_status("Stopping robot ...")
        self._draw()

        client = self._get_client()
        result = client.stop(self._sa_session)

        if result.get("ok"):
            self._set_status(
                f"Robot stopped — ready for next send")
        else:
            self._set_status(
                f"Stop failed: {result.get('error', 'unknown')} — "
                f"robot may have already stopped", ok=False)

        self._sa_session = ""
        self._sa_running = False

    # ── WiFi launch ───────────────────────────────────────────────────────────

    def _launch_wifi(self):
        """
        Send hierarchy to robot over WiFi.

        Flow:
          1. Ping robot.
          2a. Not reachable → set status, offer IDE fallback via status message.
          2b. Busy          → set status, player can retry.
          2c. Idle          → send_hierarchy, write result, close.
        """
        if not self._hierarchy:
            self._set_status("Add at least one behavior first", ok=False)
            return

        sys.path.insert(0, ROOT)
        from robot_wifi_client import RobotWiFiClient

        host = self._wifi_cfg["host"]
        port = self._wifi_cfg["port"]
        self._set_status(f"Connecting to {host}:{port} ...")
        self._draw()   # flush status immediately

        client = RobotWiFiClient(host=host, port=port, timeout=4.0)
        ping   = client.ping()

        if not ping.get("reachable"):
            self._set_status(
                f"Robot not reachable ({host}:{port}).  "
                f"Check WiFi or use IDE Fallback.", ok=False)
            return

        if ping.get("status") == "busy":
            self._set_status(
                f"Robot is busy (session {ping.get('session','?')}).  "
                f"Wait for it to finish or use IDE Fallback.", ok=False)
            return

        # Robot is idle — send the hierarchy
        result = client.send_hierarchy(self._hierarchy)
        if not result.get("ok"):
            self._set_status(
                f"Send failed: {result.get('error','unknown error')}.  "
                f"Try IDE Fallback.", ok=False)
            return

        session = result["session"]
        self._set_status(f"Sent to robot  session={session}")

        # Write result JSON — hub reads this after builder closes
        out = {
            "robot":     self._robot_label,
            "hierarchy": self._hierarchy,
            "wifi":      True,
            "session":   session,
            "host":      host,
            "port":      port,
        }
        with open(self._result_path, "w") as f:
            json.dump(out, f)

        pygame.quit()
        sys.exit(0)

    # ── IDE fallback (original _launch_arduino) ───────────────────────────────

    def _launch_ide(self):
        """Export sketch and open Arduino IDE (original path, unchanged)."""
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
            self._set_status(f"IDE not found — folder opened: {sketch_name}",
                             ok=False)

        out = {
            "robot":       self._robot_label,
            "hierarchy":   self._hierarchy,
            "sketch_path": ino_path,
            "physical":    True,
        }
        with open(self._result_path, "w") as f:
            json.dump(out, f)

        pygame.quit()
        sys.exit(0)

    # ── Simulate (unchanged) ──────────────────────────────────────────────────

    def _submit_hypothesis(self):
        if not self._hierarchy:
            self._set_status("Add at least one behavior first", ok=False)
            return

        sketches_dir = os.path.join(GAME_DIR, "sketches")
        os.makedirs(sketches_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        name  = f"hypothesis_{self._robot_label}_{stamp}.ino"
        path  = os.path.join(sketches_dir, name)

        code = generate_sketch(self._hierarchy, name)
        with open(path, "w") as f:
            f.write(code)

        out = {
            "robot":       self._robot_label,
            "hierarchy":   self._hierarchy,
            "sketch_path": path,
        }
        with open(self._result_path, "w") as f:
            json.dump(out, f)

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
                    if self._show_wifi_cfg:
                        self._handle_wifi_cfg_key(event)
                    elif event.key == pygame.K_ESCAPE:
                        running = False

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    pos = event.pos

                    # WiFi config overlay absorbs all clicks when open
                    if self._show_wifi_cfg:
                        for name, rect in self._wifi_cfg_btns.items():
                            if rect.collidepoint(pos):
                                self._handle_wifi_cfg_btn(name)
                                break
                        continue

                    # Normal builder clicks
                    for i, r in enumerate(self._pool_rects):
                        if r.collidepoint(pos):
                            self._pool_sel = i
                            self._hier_sel = -1
                            break
                    else:
                        for i, r in enumerate(self._hier_rects):
                            if r.collidepoint(pos):
                                self._hier_sel = i
                                self._pool_sel = -1
                                break
                        else:
                            for name, rect in self._btn_rects.items():
                                if rect.collidepoint(pos):
                                    self._handle_btn(name)
                                    break

            self._clock.tick(30)
        pygame.quit()


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import robosim.theme as T
    T.apply(T.load_saved_theme())
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--robot",  default="", help="Robot label (A or B)")
    ap.add_argument("--result", default="", help="Path to write hypothesis JSON")
    ap.add_argument("--arena",  default="", help="Arena path (unused, future use)")
    args = ap.parse_args()
    HierarchyBuilder(robot_label=args.robot,
                     result_path=args.result).run()
