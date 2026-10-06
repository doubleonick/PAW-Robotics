"""
engine/physics_adapter.py
--------------------------
Abstract contract for all physics backends in PAW games.

Every physics system — whether PyBullet or 2D math — must implement
this interface.  Game hubs only talk to PhysicsAdapter, never directly
to PyBullet or RobotState.

Design principles
-----------------
- PyBullet is used wherever it has coverage (drive, collision, IR ray cast,
  manipulation).  2D math is only used where PyBullet cannot help (LDR,
  COLOR, HALL, ACOUSTIC).
- Adding a new physics backend means implementing this class.  No other
  files change.
- Methods that a backend cannot support raise NotImplementedError with a
  clear message, so games that accidentally use an incompatible backend
  fail loudly rather than silently.

Units
-----
All positions and distances are in metres.
All angles are in radians (0 = world +x, π/2 = world +y).
All speeds are normalised [-1.0, 1.0] (1.0 = full forward).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ── Data types returned by the adapter ───────────────────────────────────────

@dataclass
class ContactPoint:
    """A single contact between the robot and another body."""
    body_id:    int             # ID of the other body (-1 = wall/arena)
    position_w: tuple[float, float]   # world position of contact (x, y)
    normal_w:   tuple[float, float]   # contact normal pointing away from robot
    depth:      float           # penetration depth (metres, >= 0)


@dataclass
class ObjectState:
    """State of a manipulable object in the world."""
    obj_id:  int
    x:       float
    y:       float
    heading: float
    held:    bool = False


# ── Abstract base ─────────────────────────────────────────────────────────────

class PhysicsAdapter(ABC):
    """
    Abstract physics adapter.  Subclass this for each physics backend.

    Lifecycle
    ---------
    adapter = ConcreteAdapter(arena)   # create + load arena geometry
    adapter.reset_robot(x, y, heading) # place robot at start pose

    Per-tick loop:
        adapter.step(left, right, dt)   # advance physics
        x, y, h = adapter.get_pose()    # read robot pose
        dist = adapter.ray_cast(...)    # sensor queries
        contacts = adapter.contacts()   # collision queries

    Teardown:
        adapter.close()                 # release resources (PyBullet client etc.)
    """

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @abstractmethod
    def reset_robot(self, x: float, y: float, heading: float) -> None:
        """Place (or replace) the robot at the given world pose."""

    def close(self) -> None:
        """Release any resources held by this adapter (override if needed)."""

    # ── Per-tick ──────────────────────────────────────────────────────────────

    @abstractmethod
    def step(self, left: float, right: float, dt: float) -> None:
        """
        Advance the simulation by dt seconds.

        left, right: normalised motor speeds [-1.0, 1.0].
          +1.0 = full forward,  -1.0 = full reverse.
        dt: physics timestep in seconds (e.g. 1/120).
        """

    @abstractmethod
    def get_pose(self) -> tuple[float, float, float]:
        """Return current robot pose (x, y, heading) in world frame."""

    # ── Sensor rays ───────────────────────────────────────────────────────────

    @abstractmethod
    def ray_cast(self, wx: float, wy: float,
                 angle: float, max_range: float) -> float:
        """
        Cast a single ray from (wx, wy) in direction `angle`.
        Returns distance to first hit in metres, or max_range if no hit.

        Used by: IR proximity, ultrasonic (centre ray).
        """

    def ray_cast_cone(self, wx: float, wy: float,
                      angle: float,
                      cone_half_angle: float,
                      n_rays: int,
                      max_range: float) -> float:
        """
        Cast n_rays spread across a cone of half-width cone_half_angle.
        Returns the minimum (closest) hit distance.

        Default implementation calls ray_cast() n_rays times.
        Backends may override with a more efficient batch call.

        Used by: ultrasonic sensor.
        """
        import math
        best = max_range
        if n_rays <= 1:
            return self.ray_cast(wx, wy, angle, max_range)
        for i in range(n_rays):
            frac  = i / (n_rays - 1)          # 0.0 … 1.0
            off   = cone_half_angle * (frac * 2 - 1)   # -half … +half
            d     = self.ray_cast(wx, wy, angle + off, max_range)
            best  = min(best, d)
        return best

    # ── Collision ─────────────────────────────────────────────────────────────

    @abstractmethod
    def contacts(self) -> list[ContactPoint]:
        """
        Return all current contact points involving the robot body.
        Empty list = no collision.

        Used by: bump sensors, escape-trigger logic, contact detection.
        """

    def is_colliding(self) -> bool:
        """True if the robot is in contact with anything."""
        return len(self.contacts()) > 0

    # ── Manipulation (optional — raise NotImplementedError if unsupported) ────

    def create_object(self, shape: str,
                      x: float, y: float,
                      mass: float = 0.1,
                      **kwargs) -> int:
        """
        Add a manipulable object to the world.
        Returns an opaque object ID for later reference.

        shape: 'box', 'cylinder', 'sphere'
        mass: kg (0 = static/immovable)
        kwargs: shape-specific dimensions (e.g. radius=0.03, height=0.05)
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support object creation. "
            "Use PyBulletAdapter for manipulation games.")

    def get_object_state(self, obj_id: int) -> ObjectState:
        """Return position and heading of a world object."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support object state queries.")

    def attach_object(self, obj_id: int) -> None:
        """
        Attach obj_id to the robot (grasp).
        The object will move rigidly with the robot until release_object().
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support object attachment. "
            "Use PyBulletAdapter for manipulation games.")

    def release_object(self, obj_id: int) -> None:
        """Release a previously attached object."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support object release.")

    def gripper_contact(self,
                        gripper_wx: float,
                        gripper_wy: float,
                        gripper_radius: float = 0.02) -> int | None:
        """
        Check whether the gripper position is in contact with any object.
        Returns the object ID if contact found, None otherwise.

        Default: proximity check against known objects (override for accuracy).
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support gripper contact queries.")

    # ── Introspection ─────────────────────────────────────────────────────────

    @property
    def supports_manipulation(self) -> bool:
        """True if this adapter supports object creation and grasping."""
        return False

    @property
    def supports_multi_robot(self) -> bool:
        """True if this adapter can simulate multiple robots simultaneously."""
        return False

    @property
    def is_3d(self) -> bool:
        """True if this adapter uses full 3D physics (e.g. PyBullet)."""
        return False


# ── Physics-in-use probe ──────────────────────────────────────────────────────
# Lives here, on the CONTRACT, so it survives deletion of any one backend.
# Writes to physics_probe.txt in the repo root as well as the console, because
# launching via paw.py runs games as subprocesses whose stdout may not surface.
# Path derives from __file__, so the working directory does not matter.
#
# Remove this along with the SimpleDriveAdapter question it exists to settle.

def physics_probe(line: str) -> None:
    import os
    print(line, flush=True)
    try:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        with open(os.path.join(root, "physics_probe.txt"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

