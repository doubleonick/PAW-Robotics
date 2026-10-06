"""
engine/adapters/simple_drive.py
--------------------------------
2D physics adapter for PAW games that use idealised differential drive.

Uses RobotState from engine/robot_body.py for motion and
_ray_segment_intersect from sensor_physics.py for ray casting.

This adapter is appropriate for:
  - Valentino's Vehicles (BYOV) — Braitenberg vehicles, no manipulation
  - Virtual Fields (VF) — reactive navigation, no manipulation

It does NOT support:
  - Object creation / manipulation (raises NotImplementedError)
  - Multi-robot simulation
  - Physical inertia (velocity is set directly each tick)
  - Accurate wall sliding (robot stops at wall boundary)

When a game is upgraded to require full physics (object interaction,
physical prediction), swap this for PyBulletAdapter — no other code
changes.
"""

from __future__ import annotations

import math
import sys
import os

# Ensure project root is on path so valentinos imports work
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, '..', '..')
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from engine.physics_adapter import PhysicsAdapter, ContactPoint
from engine.sensor_physics import _ray_segment_intersect, _wall_segments


# ── Wall thickness (metres) ───────────────────────────────────────────────────
# Must match the value used in arena.py draw / wall_segments.
_WALL_T = 0.012



# ── Deletion tripwire ─────────────────────────────────────────────────────────
# SimpleDriveAdapter is believed to have NO remaining callers: Field Trip,
# Valentino's and Robot Ethology all collide through PyBulletAdapter as of
# dev14i. Believed is not verified, so before deleting this file we want
# PLAYTEST evidence rather than a grep.
#
# Constructing this class now announces itself loudly on the console AND appends
# to physics_probe.txt in the repo root. Play through every game and every mode;
# if the file never mentions SimpleDrive, nothing reaches it and it can go.
#
# PyBulletAdapter logs its own construction to the same file, so the report is
# positive as well as negative: it shows what IS being used, not merely that
# something is not.

from engine.physics_adapter import physics_probe as _physics_probe

class SimpleDriveAdapter(PhysicsAdapter):
    """
    2D differential-drive physics adapter.

    Parameters
    ----------
    arena : dict
        Arena definition dict (must contain 'width', 'height',
        optional 'internal_walls').
    wheelbase : float
        Distance between wheels in metres.  Defaults to the AnaBBot
        standard (80 mm).
    max_speed : float
        Linear speed at motor command 1.0, in m/s.
    """

    # AnaBBot physical constants
    DEFAULT_WHEELBASE = 0.080   # metres
    DEFAULT_MAX_SPEED = 0.175   # m/s at command 1.0 (CRUISE_SPD 50 / 100 * 0.35)
    # AnaBBot / EthologyBot body radius (games/ethology/robot.json). Previously
    # absent entirely, which made the robot a dimensionless point for collision.
    DEFAULT_BODY_RADIUS = 0.0775

    def __init__(self, arena: dict,
                 wheelbase:   float = DEFAULT_WHEELBASE,
                 max_speed:   float = DEFAULT_MAX_SPEED,
                 body_radius: float = DEFAULT_BODY_RADIUS) -> None:
        import traceback
        _caller = "".join(traceback.format_stack()[-3:-1]).strip().replace("\n", " | ")
        _physics_probe(f"[PHYSICS] *** SimpleDriveAdapter CONSTRUCTED *** "
                       f"— this file was believed unused. Called from: {_caller[:400]}")
        self._arena       = arena
        self._wheelbase   = wheelbase
        self._max_speed   = max_speed
        self._body_radius = body_radius

        # Robot pose — set by reset_robot()
        self._x       = 0.0
        self._y       = 0.0
        self._heading = 0.0   # radians, 0=right, π/2=up

        # Contact state — set each step()
        self._colliding = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def reset_robot(self, x: float, y: float, heading: float) -> None:
        self._x       = x
        self._y       = y
        self._heading = heading
        self._colliding = False

    # ── Per-tick ──────────────────────────────────────────────────────────────

    def step(self, left: float, right: float, dt: float) -> None:
        """
        Advance 2D differential drive by dt seconds.

        left, right are normalised [-1, 1]; 1.0 = max_speed forward.
        Uses the standard differential-drive kinematic equations:
            v     = (left + right) / 2 * max_speed
            omega = (right - left) / wheelbase * max_speed
        """
        v     = (left + right) * 0.5 * self._max_speed
        omega = (right - left) / self._wheelbase * self._max_speed

        new_heading = self._heading + omega * dt
        new_x       = self._x + v * math.cos(new_heading) * dt
        new_y       = self._y + v * math.sin(new_heading) * dt

        # Wall collision — check proposed position; revert if inside any wall
        if self._inside_wall(new_x, new_y):
            self._colliding = True
            # Try sliding: accept x-only or y-only movement
            if not self._inside_wall(new_x, self._y):
                self._x = new_x
            elif not self._inside_wall(self._x, new_y):
                self._y = new_y
            # else: fully blocked, stay put
        else:
            self._colliding = False
            self._x = new_x
            self._y = new_y

        self._heading = new_heading % (2 * math.pi)

    def get_pose(self) -> tuple[float, float, float]:
        return self._x, self._y, self._heading

    # ── Sensor rays ───────────────────────────────────────────────────────────

    def ray_cast(self, wx: float, wy: float,
                 angle: float, max_range: float) -> float:
        """
        2D ray cast against arena wall segments.
        Returns distance to first hit, or max_range if no hit.
        """
        dx   = math.cos(angle)
        dy   = math.sin(angle)
        best = max_range

        for (ax, ay), (bx, by) in _wall_segments(self._arena):
            t = _ray_segment_intersect(wx, wy, dx, dy, ax, ay, bx, by)
            if t is not None and t < best:
                best = t

        return best

    # ── Collision ─────────────────────────────────────────────────────────────

    def contacts(self) -> list[ContactPoint]:
        """
        Return a contact point if the robot centre is within wall_thickness
        of any wall segment, otherwise empty list.

        This is a simplified approximation — it detects the robot centre
        being close to a wall, not the robot body edge.  Accurate body-edge
        collision requires the robot chassis polygon, which is available from
        body_corners() in robot_body.py if needed.
        """
        if not self._colliding:
            return []
        # Return a single generic contact (no specific normal computed)
        return [ContactPoint(
            body_id    = -1,
            position_w = (self._x, self._y),
            normal_w   = (0.0, 0.0),   # unknown without polygon
            depth      = 0.0,
        )]

    # ── Introspection ─────────────────────────────────────────────────────────

    @property
    def supports_manipulation(self) -> bool:
        return False

    @property
    def supports_multi_robot(self) -> bool:
        return False

    @property
    def is_3d(self) -> bool:
        return False

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _inside_wall(self, x: float, y: float) -> bool:
        """
        True if position (x, y) is outside the arena boundary or inside
        any internal wall region.

        The margin is the ROBOT BODY RADIUS plus half the wall thickness, so
        the robot's EDGE stops at the wall face.

        This previously used only half the wall thickness, i.e. it treated the
        robot as a dimensionless point: the centre stopped at the wall, leaving
        the whole front half of the body buried inside it. Visible in
        Valentino's as severe wall overlap.

        Wall thickness now comes from the arena (which carries its own
        wall_thickness) rather than a module constant, so arenas authored at
        different scales collide correctly.
        """
        aw = self._arena["width"]
        ah = self._arena["height"]
        wall_t = self._arena.get("wall_thickness", _WALL_T)
        # The arena boundary has no thickness of its own — the body edge is the
        # limit. Internal walls add their half-thickness below.
        margin = self._body_radius

        # Boundary check
        if (x < -aw / 2 + margin or x > aw / 2 - margin or
                y < -ah / 2 + margin or y > ah / 2 - margin):
            return True

        # Internal walls — check if point is within wall_thickness of segment
        for iw in self._arena.get("internal_walls", []):
            ax, ay = iw["x0"], iw["y0"]
            bx, by = iw["x1"], iw["y1"]
            seg_dx = bx - ax
            seg_dy = by - ay
            seg_len_sq = seg_dx ** 2 + seg_dy ** 2
            if seg_len_sq < 1e-12:
                continue
            t = max(0.0, min(1.0,
                             ((x - ax) * seg_dx + (y - ay) * seg_dy)
                             / seg_len_sq))
            cx = ax + t * seg_dx
            cy = ay + t * seg_dy
            half_t = iw.get("thickness", wall_t) / 2.0
            if math.hypot(x - cx, y - cy) <= self._body_radius + half_t:
                return True

        return False
