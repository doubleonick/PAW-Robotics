"""
engine/renderer/pygame_renderer.py
-------------------------------------
PyGame top-down renderer.

Renders:
  - Arena floor (dark) + boundary walls
  - Light source glows
  - Robot silhouette (circle + heading indicator)
  - Sensor HUD overlay — semi-transparent indicators rendered at each
    sensor's world position, sized proportional to sensor reading:
      IR       → cone/wedge, length scales with proximity
      Light    → filled circle, radius scales with lux
      Contact  → small filled circle, brightens on trigger
  - All HUD indicators stay at minimum size/opacity at zero reading

Coordinate mapping
------------------
World space: metres, origin at arena centre, +Y = up (forward on screen)
Screen space: pixels, origin top-left, +Y = down
The renderer flips Y so the robot's +Y (forward) points up on screen.
"""

from __future__ import annotations

import math
import logging
from typing import Any

import pygame
from engine.render_shadows import draw_shadows

from engine.config import ArenaConfig, RobotConfig
from engine.renderer.hud import HUDPanel, HUDInfo
from engine.sensors.sensor_models import (
    SensorBase, IRSensor, LightSensor, ContactSensor
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colour palette  (industrial/utilitarian — dark theme)
# ---------------------------------------------------------------------------
C_BG          = (18,  20,  24)
C_FLOOR       = (28,  30,  36)
C_WALL        = (72,  76,  84)
C_WALL_LIGHT  = (100, 105, 115)
C_ROBOT_FILL  = (52, 140, 220)
C_ROBOT_EDGE  = (180, 210, 255)
C_HEADING     = (255, 230, 80)
C_LIGHT_GLOW  = (255, 210, 80)
C_HUD_IR      = (80,  220, 160)
C_HUD_LIGHT   = (255, 230, 100)
C_HUD_CONTACT = (255, 80,  80)
C_TEXT        = (200, 205, 215)
C_TEXT_DIM    = (100, 108, 120)
C_PANEL_BG    = (22,  24,  30, 210)   # RGBA
STATUS_H      = 26                     # bottom status bar height px


class PyGameRenderer:

    # HUD constants
    HUD_MIN_ALPHA   = 30    # opacity at zero reading
    HUD_MAX_ALPHA   = 180
    HUD_IR_LEN_MAX  = 0.28  # metres — max ray length drawn
    HUD_LDR_R_MAX   = 0.06  # metres — max circle radius
    HUD_CONTACT_R   = 0.025 # metres — contact indicator radius

    def __init__(self, arena_cfg: ArenaConfig, robot_cfg: RobotConfig,
                 window_title: str = "RoboSim",
                 show_hud: bool = False,
                 scale_px_per_m: float | None = None,
                 ir_only: bool = False,
                 arena_name: str = "",
                 robot_name: str = "",
                 dual_hud: bool = False):
        self._arena     = arena_cfg
        self._robot     = robot_cfg
        self._dual_hud  = dual_hud and show_hud

        hud_panel_w = 300
        margin      = 40

        import pygame as _pg
        if not _pg.get_init():
            _pg.init()
        info = _pg.display.Info()

        # Dual HUD: panels on both sides — arena in the centre
        total_hud = hud_panel_w * (2 if self._dual_hud else 1)
        usable_w  = info.current_w - total_hud - margin * 2
        usable_h  = info.current_h - 80        - margin * 2

        if scale_px_per_m is not None:
            scale = scale_px_per_m
        else:
            scale = min(usable_w / arena_cfg.width,
                        usable_h / arena_cfg.height)

        self._scale  = scale
        self._hud_w  = hud_panel_w
        arena_px_w   = int(arena_cfg.width  * scale) + margin * 2
        self._w      = total_hud + arena_px_w
        self._h      = int(arena_cfg.height * scale) + margin * 2
        self._margin = margin

        # Arena canvas starts after left HUD
        self._arena_offset_x = hud_panel_w if show_hud else 0

        import logging
        logging.getLogger(__name__).info(
            "Display: desktop=%dx%d  window=%dx%d  scale=%.1f px/m  dual_hud=%s",
            info.current_w, info.current_h, self._w, self._h, self._scale,
            self._dual_hud)

        self._show_hud   = show_hud
        self._ir_only    = ir_only
        self._arena_name = arena_name
        self._robot_name = robot_name
        self._hud_panel:  HUDPanel | None = None
        self._hud_panel2: HUDPanel | None = None   # right panel for dual mode
        self._surface: pygame.Surface | None = None
        self._hud_surface: pygame.Surface | None = None
        self._clock: pygame.time.Clock | None = None
        self._font_small: pygame.font.Font | None = None
        self._font_mono:  pygame.font.Font | None = None
        self._font_large: pygame.font.Font | None = None
        self._panel_cache: pygame.Surface | None = None
        self._panel_cache_key: tuple | None = None

        self._frame_count = 0
        self._fps         = 0.0

    # ------------------------------------------------------------------
    # Init / shutdown
    # ------------------------------------------------------------------

    def init(self) -> None:
        import os
        # Position window at top-left so title bar is within screen
        # Position window sensibly — use env var if set, otherwise 80,60
        os.environ.setdefault("SDL_VIDEO_WINDOW_POS", "80,60")
        # pygame already initialised in __init__ for display info query
        if not pygame.get_init():
            pygame.init()
        pygame.display.set_caption("PAW Robotics")
        self._surface     = pygame.display.set_mode((self._w, self._h))
        self._hud_surface = pygame.Surface((self._w, self._h),
                                           pygame.SRCALPHA)
        self._clock       = pygame.time.Clock()

        # Fonts — prefer monospace for HUD readouts
        try:
            self._font_small = pygame.font.SysFont("consolas", 20)
            self._font_mono  = pygame.font.SysFont("consolas", 19)
            self._font_large = pygame.font.SysFont("consolas", 26)
        except Exception:
            self._font_small = pygame.font.SysFont(None, 22)
            self._font_mono  = pygame.font.SysFont(None, 21)
            self._font_large = pygame.font.SysFont(None, 28)
        self._hud_panel  = HUDPanel(self._hud_w, self._h)
        if self._dual_hud:
            self._hud_panel2 = HUDPanel(self._hud_w, self._h)

        logger.info("Renderer initialised (%d × %d px, %.1f px/m)",
                    self._w, self._h, self._scale)

    def shutdown(self) -> None:
        pygame.quit()

    def tick(self, fps: int = 60) -> float:
        """Advance clock, return actual dt in seconds."""
        dt = self._clock.tick(fps) / 1000.0
        self._frame_count += 1
        # Rolling FPS estimate
        if dt > 0:
            self._fps = 0.9 * self._fps + 0.1 * (1.0 / dt)
        return dt

    # ------------------------------------------------------------------
    # World → screen helpers
    # ------------------------------------------------------------------

    def _to_screen(self, wx: float, wy: float) -> tuple[int, int]:
        """World metres → screen pixels (Y flipped).
        Origin is centred in the arena canvas (between HUD panels).
        """
        left_hud  = self._hud_w if self._show_hud else 0
        right_hud = self._hud_w if self._dual_hud else 0
        canvas_cx = left_hud + (self._w - left_hud - right_hud) // 2
        canvas_cy = self._h // 2
        sx = int(wx * self._scale) + canvas_cx
        sy = int(-wy * self._scale) + canvas_cy
        return sx, sy

    def _to_screen_dist(self, d: float) -> int:
        return max(1, int(d * self._scale))

    # ------------------------------------------------------------------
    # Main draw call
    # ------------------------------------------------------------------

    def draw(self, robot_x: float, robot_y: float, robot_heading: float,
             sensors: dict[str, SensorBase],
             light_sources: list,
             state_label: str = "",
             hud_info: "HUDInfo | None" = None,
             extra_robots: list = None,
             robot_color: tuple = None,
             robot_label: str = "") -> None:
        """Full frame render."""
        surf = self._surface
        surf.fill(C_BG)

        self._draw_floor(surf)
        self._draw_shadows(surf, light_sources)
        self._draw_light_glows(surf, light_sources)
        self._draw_walls(surf)
        self._draw_internal_walls(surf)

        # Sensor HUD overlay for all robots when enabled
        if self._show_hud:
            self._hud_surface.fill((0, 0, 0, 0))
            hud_sensors = {
                k: v for k, v in sensors.items()
                if (not self._ir_only or isinstance(v, IRSensor))
            }
            self._draw_sensor_hud(self._hud_surface, robot_x, robot_y,
                                   robot_heading, hud_sensors)
            # Extra robots' sensor overlays
            if extra_robots:
                for rd in extra_robots:
                    rd_sensors = {
                        k: v for k, v in rd.get("sensors", {}).items()
                        if (not self._ir_only or isinstance(v, IRSensor))
                    }
                    self._draw_sensor_hud(self._hud_surface,
                                          rd["x"], rd["y"], rd["heading"],
                                          rd_sensors)
            surf.blit(self._hud_surface, (0, 0))

        # Draw primary robot with its color and label
        self._draw_robot(surf, robot_x, robot_y, robot_heading,
                         color=robot_color, label=robot_label)

        # Draw additional robots
        if extra_robots:
            for rd in extra_robots:
                self._draw_robot(surf,
                                 rd["x"], rd["y"], rd["heading"],
                                 color=rd.get("color"),
                                 label=rd.get("label", ""))

        if self._ir_only:
            self._draw_ir_rays(surf, robot_x, robot_y, robot_heading, sensors)
        if self._show_hud and hud_info is not None and self._hud_panel:
            if self._dual_hud and extra_robots and \
                    extra_robots[0].get("hud_info") is not None \
                    and self._hud_panel2:
                self._hud_panel.draw(surf, hud_info, offset_x=0,
                                     fps=self._fps)
                right_x = self._w - self._hud_w
                self._hud_panel2.draw(surf, extra_robots[0]["hud_info"],
                                      offset_x=right_x, fps=self._fps)
            else:
                self._hud_panel.draw(surf, hud_info, offset_x=0,
                                     fps=self._fps)
        elif self._show_hud:
            self._draw_hud_panel(surf, sensors)
            if state_label:
                self._draw_state_label(surf, state_label)
        self._draw_file_labels(surf)

        pygame.display.flip()

    # ------------------------------------------------------------------
    # Arena elements
    # ------------------------------------------------------------------

    def _draw_shadows(self, surf: pygame.Surface,
                      light_sources: list) -> None:
        """Draw wall shadows using the shared engine shadow renderer."""
        # Build a transient arena dict from RE's ArenaConfig + light data
        # Convert LightSource objects → dicts for render_shadows
        def _ls_to_dict(ls):
            return {"x": ls.x, "y": ls.y,
                    "radius": ls.radius,
                    "color": getattr(ls, "color", "white")}
        arena_dict = {
            "width":          self._arena.width,
            "height":         self._arena.height,
            "light_sources":  [_ls_to_dict(ls) for ls in light_sources],
            "internal_walls": [
                {"x0": w.x0, "y0": w.y0, "x1": w.x1, "y1": w.y1}
                for w in getattr(self._arena, "_config",
                    self._arena).internal_walls
            ],
        }
        left_hud  = self._hud_w if self._show_hud else 0
        right_hud = self._hud_w if self._dual_hud else 0
        canvas_w  = self._w - left_hud - right_hud
        canvas_rect = pygame.Rect(left_hud, 0, canvas_w, self._h)
        draw_shadows(surf, arena_dict, self._to_screen,
                     self._scale, canvas_rect)

    def _draw_floor(self, surf: pygame.Surface) -> None:
        w_px = self._to_screen_dist(self._arena.width)
        h_px = self._to_screen_dist(self._arena.height)
        cx, cy = self._to_screen(0, 0)
        rect = pygame.Rect(cx - w_px // 2, cy - h_px // 2, w_px, h_px)
        pygame.draw.rect(surf, C_FLOOR, rect)

    def _draw_walls(self, surf: pygame.Surface) -> None:
        w = self._arena.width
        h = self._arena.height
        t = self._arena.wall_thickness

        # Each wall is defined by its world-space bounding box:
        #   (left_x, bottom_y, right_x, top_y)
        # After Y-flip, world bottom_y becomes screen top (smallest sy).
        # pygame.Rect needs (screen_left, screen_top, width_px, height_px).
        walls_world = [
            # (world_left,  world_bottom, world_right,  world_top)
            (-w/2 - t,  h/2,       w/2 + t,  h/2 + t),   # north
            (-w/2 - t, -h/2 - t,   w/2 + t, -h/2    ),   # south
            ( w/2,     -h/2,       w/2 + t,  h/2    ),   # east
            (-w/2 - t, -h/2,      -w/2,       h/2    ),   # west
        ]
        for wl, wb, wr, wt in walls_world:
            # Convert top-left in screen space:
            # world top    (wt, large y) → screen top    (small sy)  ← _to_screen flips y
            # world bottom (wb, small y) → screen bottom (large sy)
            # So screen_top comes from world_top (wt), screen_left from world_left (wl)
            sx, sy_top = self._to_screen(wl, wt)
            wpx = self._to_screen_dist(wr - wl)
            hpx = self._to_screen_dist(wt - wb)
            rect = pygame.Rect(sx, sy_top, wpx, hpx)
            pygame.draw.rect(surf, C_WALL, rect)
            pygame.draw.rect(surf, C_WALL_LIGHT, rect, 1)

    def _draw_internal_walls(self, surf: pygame.Surface) -> None:
        """Draw internal wall segments added via the arena builder."""
        for iw in self._arena.internal_walls:
            x0, y0 = self._to_screen(iw.x0, iw.y0)
            x1, y1 = self._to_screen(iw.x1, iw.y1)
            thick  = max(2, self._to_screen_dist(iw.thickness))
            pygame.draw.line(surf, C_WALL, (x0, y0), (x1, y1), thick)
            pygame.draw.line(surf, C_WALL_LIGHT, (x0, y0), (x1, y1), 1)

    def _draw_light_glows(self, surf: pygame.Surface,
                           light_sources: list) -> None:
        for ls in light_sources:
            cx, cy = self._to_screen(ls.x, ls.y)
            r_px   = self._to_screen_dist(ls.radius)
            # Layered soft glow
            for layer in range(4, 0, -1):
                alpha  = int(18 * layer * ls.intensity)
                radius = int(r_px * layer * 0.55)
                glow   = pygame.Surface((radius * 2, radius * 2),
                                        pygame.SRCALPHA)
                pygame.draw.circle(glow, (*C_LIGHT_GLOW, alpha),
                                   (radius, radius), radius)
                surf.blit(glow, (cx - radius, cy - radius))
            # Centre dot
            pygame.draw.circle(surf, C_LIGHT_GLOW, (cx, cy), 3)

    # ------------------------------------------------------------------
    # Robot
    # ------------------------------------------------------------------

    def _draw_robot(self, surf: pygame.Surface,
                    rx: float, ry: float, heading: float,
                    color: tuple = None, label: str = "") -> None:
        cx, cy = self._to_screen(rx, ry)
        r_px   = self._to_screen_dist(self.config_body_radius)

        fill = color if color else C_ROBOT_FILL
        edge = tuple(min(255, c + 60) for c in fill) if color else C_ROBOT_EDGE

        pygame.draw.circle(surf, fill, (cx, cy), r_px)
        pygame.draw.circle(surf, edge, (cx, cy), r_px, 2)

        # Heading line
        hx = int(cx + math.cos(heading) * r_px * 0.85)
        hy = int(cy - math.sin(heading) * r_px * 0.85)
        pygame.draw.line(surf, C_HEADING, (cx, cy), (hx, hy), 3)
        pygame.draw.circle(surf, C_HEADING, (hx, hy), 4)

        # Robot label (A/B etc.)
        if label and self._font_small:
            lt = self._font_small.render(label, True, (255, 255, 255))
            surf.blit(lt, (cx - lt.get_width()//2,
                           cy - lt.get_height()//2))

    @property
    def config_body_radius(self) -> float:
        return self._robot.body_radius

    # ------------------------------------------------------------------
    # Sensor HUD overlay
    # ------------------------------------------------------------------

    def _draw_sensor_hud(self, hud: pygame.Surface,
                          rx: float, ry: float, heading: float,
                          sensors: dict[str, SensorBase]) -> None:
        for name, sensor in sensors.items():
            (wx, wy), world_angle = sensor.world_pose((rx, ry), heading)
            sx, sy = self._to_screen(wx, wy)
            v    = sensor.hud_value()
            cfg  = sensor.config
            col  = cfg.hud_color
            alpha_range = self.HUD_MAX_ALPHA - self.HUD_MIN_ALPHA
            alpha = int(self.HUD_MIN_ALPHA + v * alpha_range)

            if isinstance(sensor, IRSensor):
                self._draw_hud_ir(hud, sx, sy, world_angle, v, col, alpha)
            elif isinstance(sensor, LightSensor):
                self._draw_hud_light(hud, sx, sy, v, col, alpha)
            elif isinstance(sensor, ContactSensor):
                self._draw_hud_contact(hud, sx, sy, v, col, alpha)

            # Label: abbreviated name
            label = self._sensor_label(name)
            if label and self._font_small:
                txt = self._font_small.render(label, True, col)
                hud.blit(txt, (sx + 6, sy - 6))

    @staticmethod
    def _sensor_label(name: str) -> str:
        """Map sensor name to a short HUD label."""
        table = {
            "leftProx":       "L-IR",
            "rightProx":      "R-IR",
            "leftLight":      "L-LDR",
            "rightLight":     "R-LDR",
            "leftFrontBump":  "LF",
            "rightFrontBump": "RF",
            "leftRearBump":   "LR",
            "rightRearBump":  "RR",
        }
        return table.get(name, name[:4])

    def _draw_hud_ir(self, hud: pygame.Surface, sx: int, sy: int,
                      world_angle: float, v: float, col: tuple,
                      alpha: int) -> None:
        """
        Sharp GP2Y0A21YK0F: narrow 5° half-angle beam.
        Draws a thin wedge + centre ray. Length scales with proximity (v).
        """
        # Full ray length at max range; shorten proportionally when close
        max_len  = self._to_screen_dist(IRSensor.DIST_MAX)
        data_cm  = int(IRSensor._map(None,   # use hud_value directly
                       0, 1, 60, 18) if False else 0)
        # Use v directly: v=1 → very close, v=0 → far
        # Show the actual detected distance as ray length
        ray_len  = int(max_len * max(0.05, 1.0 - v))   # shorter when closer

        half_rad = math.radians(IRSensor.BEAM_HALF_DEG)

        # Wedge tip points
        ex1 = sx + int(math.cos(world_angle + half_rad) * ray_len)
        ey1 = sy - int(math.sin(world_angle + half_rad) * ray_len)
        ex2 = sx + int(math.cos(world_angle - half_rad) * ray_len)
        ey2 = sy - int(math.sin(world_angle - half_rad) * ray_len)
        # Centre ray tip
        ecx = sx + int(math.cos(world_angle) * ray_len)
        ecy = sy - int(math.sin(world_angle) * ray_len)

        poly_surf = pygame.Surface(hud.get_size(), pygame.SRCALPHA)
        pygame.draw.polygon(poly_surf, (*col, alpha // 2),
                            [(sx, sy), (ex1, ey1), (ex2, ey2)])
        hud.blit(poly_surf, (0, 0))
        # Centre ray (solid)
        pygame.draw.line(hud, (*col, alpha), (sx, sy), (ecx, ecy), 2)

    def _draw_hud_light(self, hud: pygame.Surface, sx: int, sy: int,
                         v: float, col: tuple, alpha: int) -> None:
        """Filled circle, radius proportional to light reading."""
        min_r = 4
        max_r = self._to_screen_dist(self.HUD_LDR_R_MAX)
        r     = int(min_r + v * (max_r - min_r))
        r     = max(min_r, r)

        circle_surf = pygame.Surface((r * 2 + 2, r * 2 + 2), pygame.SRCALPHA)
        pygame.draw.circle(circle_surf, (*col, alpha), (r + 1, r + 1), r)
        hud.blit(circle_surf, (sx - r - 1, sy - r - 1))

    def _draw_hud_contact(self, hud: pygame.Surface, sx: int, sy: int,
                           v: float, col: tuple, alpha: int) -> None:
        """Small circle that brightens on trigger."""
        r = self._to_screen_dist(self.HUD_CONTACT_R)
        r = max(5, r)

        circle_surf = pygame.Surface((r * 2 + 2, r * 2 + 2), pygame.SRCALPHA)
        pygame.draw.circle(circle_surf, (*col, alpha), (r + 1, r + 1), r)
        if v > 0.5:  # triggered — add bright ring
            pygame.draw.circle(circle_surf, (*col, 255),
                               (r + 1, r + 1), r, 2)
        hud.blit(circle_surf, (sx - r - 1, sy - r - 1))

    # ------------------------------------------------------------------
    # HUD panel (sensor readouts)
    # ------------------------------------------------------------------

    def _draw_hud_panel(self, surf: pygame.Surface,
                         sensors: dict[str, SensorBase]) -> None:
        """Left-sidebar HUD panel. Branches on ir_only mode."""
        if self._ir_only:
            self._draw_ir_panel(surf, sensors)
        else:
            self._draw_generic_panel(surf, sensors)

    def _draw_generic_panel(self, surf: pygame.Surface,
                            sensors: dict[str, SensorBase]) -> None:
        """Generic sensor readout panel (original implementation)."""
        panel_x = 0
        panel_y = 0
        line_h  = 28
        padding = 14

        lines = [f"FPS  {self._fps:5.1f}",
                 f"{'─' * 20}"]
        for name, sensor in sensors.items():
            raw  = sensor.get_raw_data()
            data = sensor.get_data()
            lines.append(f"{name}")
            lines.append(f"  raw={raw:>5}  val={data:>4}")

        cache_key = tuple(lines)
        if cache_key != getattr(self, '_panel_cache_key', None):
            self._panel_cache_key = cache_key
            panel_w = self._hud_w
            panel_h = self._h
            panel   = pygame.Surface((panel_w, panel_h))
            panel.fill((22, 24, 32))
            # Divider line between panel and arena
            pygame.draw.line(panel, C_WALL_LIGHT,
                             (panel_w - 1, 0), (panel_w - 1, panel_h), 2)
            y = padding
            for i, line in enumerate(lines):
                if line.startswith('─'):
                    pygame.draw.line(panel, C_WALL_LIGHT,
                                     (padding, y + line_h // 2),
                                     (panel_w - padding, y + line_h // 2), 1)
                    y += line_h
                    continue
                col = C_HEADING if i == 0 else (C_TEXT_DIM if line.startswith('  ') else C_TEXT)
                font = self._font_large if i == 0 else self._font_mono
                txt = font.render(line, True, col)
                panel.blit(txt, (padding, y))
                y += line_h
            self._panel_cache = panel

        surf.blit(self._panel_cache, (panel_x, panel_y))


    def _draw_state_label(self, surf: pygame.Surface, label: str) -> None:
        """Draw current demo state at bottom of HUD sidebar."""
        if not self._font_large:
            return
        padding = 14
        y = self._h - 80
        # Background strip
        bg = pygame.Surface((self._hud_w - 2, 64))
        bg.fill((30, 34, 44))
        surf.blit(bg, (0, y - 8))
        # Label in two lines if it contains two spaces
        parts = label.split("  ", 1)
        txt1 = self._font_mono.render(parts[0], True, C_HEADING)
        surf.blit(txt1, (padding, y))
        if len(parts) > 1:
            txt2 = self._font_mono.render(parts[1], True, C_TEXT)
            surf.blit(txt2, (padding, y + 30))

    def _draw_file_labels(self, surf: pygame.Surface) -> None:
        """Arena/robot name labels removed — backend detail, not shown to player."""
        pass

    def _draw_ir_rays(self, surf: pygame.Surface,
                       rx: float, ry: float, heading: float,
                       sensors: dict[str, SensorBase]) -> None:
        """
        Draw IR sensor rays on the arena canvas.
        Each ray goes from the sensor's world position to its detected
        hit point (or max range if no hit). The hit point is shown as
        a bright dot. The ray colour matches the sensor's hud_color.
        """
        import math
        for name, sensor in sensors.items():
            if not isinstance(sensor, IRSensor):
                continue
            (wx, wy), world_angle = sensor.world_pose((rx, ry), heading)
            hv        = sensor.hud_value()          # 0=far, 1=close
            data_cm   = sensor.get_data()
            hit_dist  = data_cm / 100.0             # metres to hit point
            col       = sensor.config.hud_color

            # Sensor origin on screen
            sx, sy = self._to_screen(wx, wy)

            # Hit point on screen
            hx_w = wx + math.cos(world_angle) * hit_dist
            hy_w = wy + math.sin(world_angle) * hit_dist
            hx, hy = self._to_screen(hx_w, hy_w)

            # Ray line — brightness scales with proximity
            alpha_frac = 0.3 + 0.7 * hv
            ray_col = tuple(int(c * alpha_frac) for c in col)
            pygame.draw.line(surf, ray_col, (sx, sy), (hx, hy), 2)

            # Hit dot — brighter when close
            dot_r = 4 + int(6 * hv)
            pygame.draw.circle(surf, col, (hx, hy), dot_r)
            pygame.draw.circle(surf, (255, 255, 255), (hx, hy), dot_r, 1)

            # Distance label next to hit dot
            if self._font_mono and data_cm < 75:
                lbl = self._font_mono.render(f"{data_cm}cm", True, col)
                surf.blit(lbl, (hx + dot_r + 4, hy - 10))

    def _draw_ir_panel(self, surf: pygame.Surface,
                        sensors: dict[str, SensorBase]) -> None:
        """
        Dedicated IR verification panel.
        Shows for each IR sensor:
          - Name and pin
          - Raw ADC value (large)
          - getData() distance in cm (large)
          - Horizontal bar graph: full width = DIST_MAX, bar length = reading
          - Visual ray line on arena canvas from sensor to detected hit
        """
        panel_x = 0
        panel_w = self._hud_w - 2
        padding = 18
        y       = padding

        # --- Background ---
        bg = pygame.Surface((panel_w, self._h))
        bg.fill((16, 18, 26))
        pygame.draw.line(bg, C_WALL_LIGHT, (panel_w - 1, 0), (panel_w - 1, self._h), 2)
        surf.blit(bg, (0, 0))

        # --- FPS header ---
        if self._font_mono:
            fps_txt = self._font_mono.render(f"FPS  {self._fps:5.1f}", True, C_TEXT_DIM)
            surf.blit(fps_txt, (padding, y))
        y += 32

        # Divider
        pygame.draw.line(surf, C_WALL_LIGHT, (padding, y), (panel_w - padding, y), 1)
        y += 16

        # --- IR sensor entries ---
        ir_sensors = {k: v for k, v in sensors.items() if isinstance(v, IRSensor)}

        for name, sensor in ir_sensors.items():
            raw  = sensor.get_raw_data()
            data = sensor.get_data()
            hv   = sensor.hud_value()          # 0=far, 1=close
            col  = sensor.config.hud_color

            # Sensor name
            if self._font_small:
                lbl = self._font_small.render(name, True, col)
                surf.blit(lbl, (padding, y))
            y += 28

            # Pin label
            if self._font_mono:
                pin_txt = self._font_mono.render(
                    f"pin {sensor.config.pin}", True, C_TEXT_DIM)
                surf.blit(pin_txt, (padding + 8, y))
            y += 26

            # Raw ADC — large
            if self._font_large:
                raw_lbl = self._font_mono.render("raw ADC", True, C_TEXT_DIM)
                surf.blit(raw_lbl, (padding, y))
                raw_val = self._font_large.render(f"{raw:>4}", True, C_TEXT)
                surf.blit(raw_val, (padding + 130, y))
            y += 36

            # Distance cm — large, colour-coded
            dist_col = (
                (255, 80,  80)  if data <= 20 else   # red   — very close
                (255, 180, 50)  if data <= 35 else   # amber — approaching
                (80,  220, 120)                       # green — clear
            )
            if self._font_mono and self._font_large:
                cm_lbl = self._font_mono.render("dist cm", True, C_TEXT_DIM)
                surf.blit(cm_lbl, (padding, y))
                cm_val = self._font_large.render(f"{data:>3}", True, dist_col)
                surf.blit(cm_val, (padding + 130, y))
            y += 40

            # Bar graph — width proportional to distance (full = 80cm = DIST_MAX)
            bar_x     = padding
            bar_y     = y
            bar_w     = panel_w - padding * 2
            bar_h     = 22
            fill_frac = max(0.0, min(1.0, 1.0 - hv))  # 0=close(small bar), 1=far(full bar)
            fill_w    = int(bar_w * fill_frac)

            # Background track
            pygame.draw.rect(surf, (40, 44, 56),
                             (bar_x, bar_y, bar_w, bar_h), border_radius=4)
            # Fill
            if fill_w > 0:
                pygame.draw.rect(surf, col,
                                 (bar_x, bar_y, fill_w, bar_h), border_radius=4)
            # Threshold marker at STOP_CM (20cm)
            stop_frac = (IRSensor.DIST_MAX - 0.20) / IRSensor.DIST_MAX
            marker_x  = bar_x + int(bar_w * stop_frac)
            pygame.draw.line(surf, (255, 80, 80),
                             (marker_x, bar_y - 2), (marker_x, bar_y + bar_h + 2), 2)

            # Distance labels on bar
            if self._font_mono:
                near_lbl = self._font_mono.render("10", True, C_TEXT_DIM)
                far_lbl  = self._font_mono.render("80cm", True, C_TEXT_DIM)
                surf.blit(near_lbl, (bar_x, bar_y + bar_h + 4))
                surf.blit(far_lbl,  (bar_x + bar_w - 50, bar_y + bar_h + 4))

            y += bar_h + 30

            # Separator between sensors
            pygame.draw.line(surf, (35, 40, 52),
                             (padding, y), (panel_w - padding, y), 1)
            y += 20

        # --- Legend at bottom ---
        if self._font_mono:
            legend = self._font_mono.render(
                "red marker = 20cm stop", True, (180, 100, 100))
            surf.blit(legend, (padding, self._h - 50))

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    @staticmethod
    def poll_events() -> bool:
        """Return False if the user requests quit."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
        return True
