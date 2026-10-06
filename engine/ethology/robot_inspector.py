"""
engine/ethology/robot_inspector.py
----------------------------------
The Robot Inspector — a read-only, top-down "specimen view" of a robot's
morphology for Robot Ethology.

Design intent (important): this is meant to feel like looking at a real animal,
not a schematic. An ethologist sees a deer's eyes as orbs on a face and must
*infer* that they are light-gathering organs with some field of view and
purpose — nobody draws the FOV cone or labels the organ. So the inspector shows
the robot's body and its sensors as recognizable PHYSICAL OBJECTS at their actual
positions and orientations, but with NO annotations, FOV cones, range labels, or
"this is a light sensor" captions. The player does the inferential work.

It reads a morphology JSON (the existing robot.json format: body geometry +
`sensors` with per-sensor `type`, `mount` [x,y metres], `angle` degrees). This
is the same data the simulation consumes, so the specimen the player inspects is
exactly the robot whose behavior they observe.

Standalone module (FW-007): no game-state coupling. The caller hands it a loaded
morphology dict and a rect; it renders. Modular by design so it can later back
the instructor robot-builder (FW-006) as the read-only half of that tool.
"""
from __future__ import annotations
import math
import pygame


# Sensor "physical object" palettes — recognizable forms, not labelled. Colors
# are intentionally object-like (a real LDR is a little amber dome; an IR
# rangefinder a dark module with two eyes; a bump switch a small lever).
def _theme():
    try:
        import engine.theme as T
        return T
    except Exception:
        return None


class RobotInspector:
    def __init__(self, morphology: dict, title: str = "Specimen",
                 robot_color: tuple = (200, 50, 50)):
        self.morph = morphology
        self.title = title
        # The robot's own identity colour (e.g. Robot A red, Robot B blue, as in
        # the opening demo) — used for the chassis/outline so the specimen
        # matches how this robot appears in the game, not the UI theme.
        self.robot_color = robot_color

    # ── geometry helpers ──────────────────────────────────────────────────
    def _chassis_vertices(self) -> list[tuple[float, float]]:
        """Body polygon in robot-local metres (origin = centre, +Y forward)."""
        v = self.morph.get("vertices_m")
        if v:
            return [(p[0], p[1]) for p in v]
        # fall back to a circle approximation
        r = self.morph.get("radius", 0.0775)
        return [(r * math.cos(a), r * math.sin(a))
                for a in [i * math.pi / 8 for i in range(16)]]

    def _bounds_m(self) -> float:
        """Half-extent (metres) used to scale the drawing to the panel."""
        verts = self._chassis_vertices()
        ext = max(max(abs(x), abs(y)) for x, y in verts)
        # include sensor mounts (they can sit outside the chassis)
        for s in self.morph.get("sensors", {}).values():
            mx, my = s.get("mount", [0, 0])
            ext = max(ext, abs(mx), abs(my))
        return ext * 1.25  # margin

    # ── draw ──────────────────────────────────────────────────────────────
    def draw(self, surf: pygame.Surface, rect: pygame.Rect) -> None:
        T = _theme()
        if T is not None:
            bg = T.PANEL_DEEP; line = T.PHOSPHOR; dim = T.TEXT_DIM
            text = getattr(T, "TEXT", (215, 235, 215)); border = T.BORDER
        else:
            bg = (14, 20, 14); line = (90, 200, 110); dim = (120, 140, 120)
            text = (215, 235, 215); border = (60, 90, 60)

        pygame.draw.rect(surf, bg, rect, border_radius=6)
        pygame.draw.rect(surf, border, rect, 1, border_radius=6)

        # The robot's identity colour drives the chassis; theme only frames it.
        rc = self.robot_color

        # world→screen transform: robot +Y (forward) points UP on screen.
        cx, cy = rect.centerx, rect.centery + 8
        half = self._bounds_m()
        scale = (min(rect.width, rect.height) * 0.42) / half

        def to_screen(mx, my):
            # +Y forward → up (screen -y); +X right → right (screen +x)
            return (int(cx + mx * scale), int(cy - my * scale))

        # title (the specimen's name only — no functional labels)
        f_title = self._font(16, bold=True)
        surf.blit(f_title.render(self.title, True, rc),
                  (rect.x + 12, rect.y + 8))

        # ── chassis (robot's own colour) ──
        verts = [to_screen(x, y) for x, y in self._chassis_vertices()]
        if len(verts) >= 3:
            pygame.draw.polygon(surf, self._mix(bg, rc, 0.30), verts)
            pygame.draw.polygon(surf, rc, verts, 2)

        # ── wheels (physical objects on the body sides) ──
        wb = self.morph.get("wheel_base", 0.08)
        wr = self.morph.get("wheel_radius", 0.024)
        for side in (-1, 1):
            wx, wy = side * wb / 2, 0.0
            self._draw_wheel(surf, to_screen, wx, wy, wr, scale, rc, bg)

        # ── heading cue (which way is forward) — a subtle bodily mark, like a
        # snout, not a label ──
        nose = to_screen(0, max(y for _, y in self._chassis_vertices()))
        pygame.draw.circle(surf, self._mix(bg, rc, 0.7), nose, 4)

        # ── sensors as recognizable physical objects (NO annotations) ──
        for name, s in self.morph.get("sensors", {}).items():
            mx, my = s.get("mount", [0, 0])
            ang = s.get("angle", 0)
            stype = s.get("type", "")
            self._draw_sensor(surf, to_screen, mx, my, ang, stype,
                              scale, rc, bg, text)

    # ── sensor renderers (object-like, unlabelled) ────────────────────────
    def _draw_sensor(self, surf, to_screen, mx, my, ang_deg, stype,
                     scale, line, bg, text):
        sx, sy = to_screen(mx, my)
        # body-forward is +Y(up); sensor angle is CCW from forward.
        a = math.radians(ang_deg)
        # screen direction the sensor "faces" (up = -y)
        fdx, fdy = math.sin(a), -math.cos(a)

        if stype == "light":
            # An LDR: a SMALL round dome (amber) with a lighter centre — reads
            # as a little eye/lens. Real LDRs are small, so keep it modest. A
            # tiny facing nub cues direction without annotating it.
            r = max(3, int(0.008 * scale))
            amber = (210, 170, 70)
            pygame.draw.circle(surf, amber, (sx, sy), r)
            pygame.draw.circle(surf, self._mix(amber, (255, 255, 255), 0.5),
                               (sx, sy), max(1, r // 2))
            pygame.draw.circle(surf, (40, 30, 10), (sx, sy), r, 1)
            nx, ny = int(sx + fdx * (r + 2)), int(sy + fdy * (r + 2))
            pygame.draw.circle(surf, amber, (nx, ny), max(1, r // 3))

        elif stype == "ir":
            # IR rangefinder (Sharp): a dark-grey casing whose LONG axis lies
            # ALONG the mounting edge (parallel to the face it sits on), so the
            # module reads as facing outward. The emitter/receiver arrays are
            # light-grey windows on the OUTWARD long edge of that casing.
            along = max(14, int(0.030 * scale))   # casing's longer dimension
            deep  = max(6, int(0.013 * scale))    # casing's shorter dimension
            casing = (55, 55, 58)                 # dark grey
            # Casing rotated 90° from the arrays' line: its LONG axis runs along
            # the FACING (outward) direction, short axis along the edge. (Pass
            # swapped dims to _draw_array, whose 1st size arg is the along-edge
            # axis — so give it the SHORT dim there and the LONG dim as depth.)
            self._draw_array(surf, sx, sy, deep, along, ang_deg, casing)
            # outward facing + along-edge unit vectors
            a = math.radians(ang_deg)
            ofx, ofy = math.sin(a), -math.cos(a)              # outward (facing)
            pax, pay = math.sin(a + math.pi/2), -math.cos(a + math.pi/2)
            # two arrays on the outward edge, offset along the edge
            edge = deep * 0.5
            arr_along = max(3, int(along * 0.26))
            arr_deep  = max(2, int(deep * 0.5))
            lite = (200, 200, 205)                            # light grey
            for s2 in (-1, 1):
                ax = sx + ofx * edge + pax * along * 0.26 * s2
                ay = sy + ofy * edge + pay * along * 0.26 * s2
                self._draw_array(surf, ax, ay, arr_along, arr_deep,
                                 ang_deg, lite)

        elif stype == "contact":
            # Bump switch: a small lever/whisker bar across the front.
            w = max(7, int(0.014 * scale))
            perp = math.radians(ang_deg + 90)
            pdx, pdy = math.sin(perp), -math.cos(perp)
            x1 = int(sx + pdx * w / 2); y1 = int(sy + pdy * w / 2)
            x2 = int(sx - pdx * w / 2); y2 = int(sy - pdy * w / 2)
            pygame.draw.line(surf, (160, 160, 170), (x1, y1), (x2, y2), 2)
            pygame.draw.circle(surf, (160, 160, 170), (sx, sy), 2)
        else:
            pygame.draw.circle(surf, line, (sx, sy), 4, 1)

    def _draw_array(self, surf, cx, cy, along, deep, ang_deg, color):
        """Draw an IR emitter/receiver window as a small rounded rect lying on
        the casing's outward edge: long axis ALONG the edge, short axis along
        the facing direction (i.e. rotated 90° from facing the viewer)."""
        a = math.radians(ang_deg)
        ca, sa = math.cos(a), math.sin(a)
        pts = []
        # local: x = along-edge (perp to facing), y = depth (along facing)
        for dx, dy in ((-along/2, -deep/2), (along/2, -deep/2),
                       (along/2, deep/2), (-along/2, deep/2)):
            # rotate local axes so 'along' lies on the edge and 'deep' on facing
            rx = dx * ca - dy * sa
            ry = dx * sa + dy * ca
            pts.append((int(cx + rx), int(cy - ry)))
        pygame.draw.polygon(surf, color, pts)
        pygame.draw.polygon(surf, self._mix(color, (60, 60, 60), 0.4), pts, 1)

    def _draw_oriented_rect(self, surf, cx, cy, w, h, ang_deg, fill, edge):
        a = math.radians(ang_deg)
        # rect corners in local (forward = +Y up); rotate by -ang for screen
        ca, sa = math.cos(a), math.sin(a)
        pts = []
        for dx, dy in ((-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2)):
            # local: x=right, y=forward(up). rotate so forward aligns to facing.
            rx = dx * ca - dy * sa
            ry = dx * sa + dy * ca
            pts.append((int(cx + rx), int(cy - ry)))
        pygame.draw.polygon(surf, fill, pts)
        pygame.draw.polygon(surf, edge, pts, 1)

    def _draw_wheel(self, surf, to_screen, wx, wy, wr, scale, line, bg):
        # a wheel: a dark rounded bar along the body's fore-aft axis
        length = wr * 2.6
        x1, y1 = to_screen(wx, wy + length / 2)
        x2, y2 = to_screen(wx, wy - length / 2)
        col = self._mix(bg, (40, 40, 48), 1.0)
        pygame.draw.line(surf, (40, 40, 48), (x1, y1), (x2, y2),
                         max(3, int(wr * scale)))
        pygame.draw.line(surf, self._mix((40, 40, 48), line, 0.3),
                         (x1, y1), (x2, y2), 1)

    # ── utils ─────────────────────────────────────────────────────────────
    @staticmethod
    def _mix(c1, c2, t):
        c1 = c1 if isinstance(c1, tuple) else (0, 0, 0)
        c2 = c2 if isinstance(c2, tuple) else (255, 255, 255)
        return tuple(max(0, min(255, int(a + (b - a) * t)))
                     for a, b in zip(c1[:3], c2[:3]))

    @staticmethod
    def _font(size, bold=False):
        try:
            return pygame.font.SysFont("consolas", size, bold=bold)
        except Exception:
            return pygame.font.Font(None, size)
