"""
engine/adapters/pybullet_drive.py
----------------------------------
PyBullet physics adapter for PAW games requiring full 3D physics.

Wraps the existing engine/robot/robot_model.py and engine/arena/arena_model.py
infrastructure already used by Robot Ethology.  Provides the PhysicsAdapter
interface so game hubs are independent of PyBullet internals.

Appropriate for:
  - Robot Ethology (RE) — already uses PyBullet
  - State Machines — physical prediction needed
  - Novel Behavior — physical prediction + manipulation
  - Any game requiring robot-robot or robot-object interaction

Supports:
  - Accurate rigid-body drive with inertia
  - Physical wall sliding and bouncing
  - Multi-robot simulation
  - Object creation, attachment, and release (manipulation)
  - Accurate IR/SONIC ray casts via p.rayTestBatch
  - Body-part contact detection
"""

from __future__ import annotations

import math
import os
import sys
from typing import Any

# Ensure project root is on path
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, '..', '..')
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from engine.physics_adapter import PhysicsAdapter, ContactPoint, ObjectState

try:
    import pybullet as p
    import pybullet_data
    _PYBULLET_AVAILABLE = True
except ImportError:
    _PYBULLET_AVAILABLE = False


# ── Ray cast height ───────────────────────────────────────────────────────────
# Z height for ray casts — above robot cylinder top.
# Matches the value in sensor_models.py.
_RAY_Z = 0.10


class PyBulletAdapter(PhysicsAdapter):
    """
    Full 3D physics adapter using PyBullet.

    Parameters
    ----------
    arena_config : ArenaConfig
        Arena configuration object (engine.config.ArenaConfig).
        Contains wall geometry, dimensions, and robot start pose.
    robot_config : RobotConfig
        Robot hardware configuration (engine.config.RobotConfig).
    physics_client : int | None
        Existing PyBullet client ID to use.  If None, a new DIRECT
        client is created.  Pass an existing client when integrating
        with RE's existing simulation loop.
    """

    def __init__(self, arena_config, robot_config,
                 physics_client: int | None = None) -> None:
        if not _PYBULLET_AVAILABLE:
            raise RuntimeError(
                "PyBullet is not installed.  "
                "Install with: pip install pybullet")

        self._arena_cfg  = arena_config
        self._robot_cfg  = robot_config
        self._owns_client = physics_client is None

        if physics_client is None:
            self._client = p.connect(p.DIRECT)
            p.setGravity(0, 0, -9.81, physicsClientId=self._client)
            p.setAdditionalSearchPath(pybullet_data.getDataPath(),
                                      physicsClientId=self._client)
        else:
            self._client = physics_client

        # Lazy-loaded from robot/arena models
        self._arena_model = None
        self._robot_model = None
        self._arena_body_ids: list[int] = []

        # Attached object tracking
        self._attached_obj:        int | None = None
        self._attachment_constraint: int | None = None
        self._world_objects: dict[int, ObjectState] = {}

        # Cache current pose to avoid repeated PyBullet queries
        self._x       = 0.0
        self._y       = 0.0
        self._heading = 0.0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def load_world(self) -> None:
        """
        Build the arena and robot bodies in PyBullet.
        Called automatically by reset_robot() if not yet loaded.

        NOTE: constructing ArenaModel/RobotModel does NOT create any physics
        bodies — ArenaModel needs build() and RobotModel starts with
        _body_id = -1 until create_body() is called. Omitting those was the
        third and fourth never-executed bug in this adapter; without them
        every subsequent PyBullet call fails with
        'GetBasePositionAndOrientation failed'.
        """
        from engine.arena.arena_model import ArenaModel
        from engine.robot.robot_model import RobotModel

        if self._arena_model is None:
            self._arena_model = ArenaModel(
                self._arena_cfg, self._client)
            self._arena_model.build()
            self._arena_body_ids = self._arena_model.body_ids

        if self._robot_model is None:
            self._robot_model = RobotModel(
                self._robot_cfg, self._client)
            self._robot_model.create_body()

    def reset_robot(self, x: float, y: float, heading: float) -> None:
        if not getattr(self, "_announced", False):
            self._announced = True
            from engine.physics_adapter import physics_probe as _physics_probe
            _physics_probe(
                f"[PHYSICS] PyBulletAdapter in use — arena "
                f"{self._arena_cfg.width}x{self._arena_cfg.height}, "
                f"chassis {getattr(self._robot_cfg, 'chassis_spec', None)}, "
                f"body_radius {self._robot_cfg.body_radius}, "
                f"wheel_base {self._robot_cfg.wheel_base}")
        self.load_world()
        # RobotModel binds its physics client at construction — reset_pose()
        # takes no physicsClientId. (Passing one was a long-standing bug here;
        # nothing had ever called this adapter, so it never surfaced.)
        self._robot_model.reset_pose(x, y, heading)
        self._x, self._y, self._heading = x, y, heading

    def close(self) -> None:
        if self._owns_client and _PYBULLET_AVAILABLE:
            try:
                p.disconnect(self._client)
            except Exception:
                pass

    # ── Per-tick ──────────────────────────────────────────────────────────────

    def step(self, left: float, right: float, dt: float) -> None:
        """Execute one behaviour primitive: hold (left, right) for dt seconds.

        `dt` is a PRIMITIVE DURATION, not a physics timestep. It mirrors the
        firmware's

            drivetrain.driveProportional(leftProp, rightProp, durationInSeconds)

        which writes the servo angles and then blocks. The motors are committed
        for the whole duration with no sensing and no re-decision — that is the
        contract the physical robot honours and the one RE reproduces via
        ArduinoHAL's TimedAction gate.

        So the command is applied ONCE and the engine is sub-stepped at its own
        fixed timestep until the duration is consumed. Callers that want a fast
        control loop pass a small dt; they do not get to change the physics
        rate, and they should not want to.
        """
        self.load_world()
        self._robot_model.apply_drive(left, right)

        phys_dt = p.getPhysicsEngineParameters(
            physicsClientId=self._client)["fixedTimeStep"]
        n = max(1, int(round(dt / phys_dt)))
        for _ in range(n):
            # RobotModel.step applies locomotion forces and refreshes sensors;
            # it must run inside the loop so contacts are respected each step.
            self._robot_model.step(self._arena_body_ids)
            p.stepSimulation(physicsClientId=self._client)
        self._sync_pose()

    def _sync_pose(self) -> None:
        """Read robot pose from PyBullet into cached values."""
        pos, orn = p.getBasePositionAndOrientation(
            self._robot_model.body_id,
            physicsClientId=self._client)
        euler = p.getEulerFromQuaternion(orn)
        self._x       = pos[0]
        self._y       = pos[1]
        self._heading = euler[2]   # yaw

    def get_pose(self) -> tuple[float, float, float]:
        return self._x, self._y, self._heading

    # ── Sensor rays ───────────────────────────────────────────────────────────

    def ray_cast(self, wx: float, wy: float,
                 angle: float, max_range: float) -> float:
        """
        PyBullet ray cast — hits walls AND other robot bodies.
        Returns distance to first hit, or max_range if no hit.
        """
        ray_start = [wx, wy, _RAY_Z]
        ray_end   = [wx + math.cos(angle) * max_range,
                     wy + math.sin(angle) * max_range,
                     _RAY_Z]
        result = p.rayTestBatch(
            [ray_start], [ray_end],
            collisionFilterMask=3,
            physicsClientId=self._client)
        frac = result[0][2]
        if frac < 1.0:
            return frac * max_range
        return max_range

    def ray_cast_cone(self, wx: float, wy: float,
                      angle: float,
                      cone_half_angle: float,
                      n_rays: int,
                      max_range: float) -> float:
        """
        Batch cone ray cast — all rays in one PyBullet call.
        More efficient than calling ray_cast() n_rays times.
        """
        if n_rays <= 1:
            return self.ray_cast(wx, wy, angle, max_range)

        starts = []
        ends   = []
        for i in range(n_rays):
            frac = i / (n_rays - 1)
            off  = cone_half_angle * (frac * 2 - 1)
            a    = angle + off
            starts.append([wx, wy, _RAY_Z])
            ends.append([wx + math.cos(a) * max_range,
                         wy + math.sin(a) * max_range,
                         _RAY_Z])

        results = p.rayTestBatch(
            starts, ends,
            collisionFilterMask=3,
            physicsClientId=self._client)

        best = max_range
        for r in results:
            frac = r[2]
            if frac < 1.0:
                best = min(best, frac * max_range)
        return best

    # ── Collision ─────────────────────────────────────────────────────────────

    def contacts(self) -> list[ContactPoint]:
        """
        Return all current contact points for the robot body.
        """
        if self._robot_model is None:
            return []

        raw = p.getContactPoints(
            bodyA=self._robot_model.body_id,
            physicsClientId=self._client)
        if not raw:
            return []

        result = []
        for c in raw:
            body_b   = c[2]   # other body ID
            pos      = c[5]   # contact position on body A (world frame)
            normal   = c[7]   # contact normal on body B
            depth    = c[8]   # penetration depth

            # Identify arena walls as body_id = -1
            is_arena = (body_b in self._arena_body_ids)
            result.append(ContactPoint(
                body_id    = -1 if is_arena else body_b,
                position_w = (pos[0], pos[1]),
                normal_w   = (normal[0], normal[1]),
                depth      = abs(depth),
            ))
        return result

    # ── Manipulation ──────────────────────────────────────────────────────────

    def create_object(self, shape: str,
                      x: float, y: float,
                      mass: float = 0.1,
                      **kwargs) -> int:
        """
        Add a rigid body to the PyBullet world.

        shape: 'box', 'cylinder', 'sphere'
        kwargs for box:      half_extents=(lx, ly, lz)
        kwargs for cylinder: radius=r, height=h
        kwargs for sphere:   radius=r
        """
        if shape == "box":
            he   = kwargs.get("half_extents", (0.03, 0.03, 0.03))
            coll = p.createCollisionShape(p.GEOM_BOX,
                       halfExtents=he,
                       physicsClientId=self._client)
            vis  = p.createVisualShape(p.GEOM_BOX,
                       halfExtents=he,
                       rgbaColor=[0.8, 0.6, 0.2, 1.0],
                       physicsClientId=self._client)
        elif shape == "cylinder":
            r    = kwargs.get("radius", 0.03)
            h    = kwargs.get("height", 0.05)
            coll = p.createCollisionShape(p.GEOM_CYLINDER,
                       radius=r, height=h,
                       physicsClientId=self._client)
            vis  = p.createVisualShape(p.GEOM_CYLINDER,
                       radius=r, length=h,
                       rgbaColor=[0.6, 0.8, 0.2, 1.0],
                       physicsClientId=self._client)
        elif shape == "sphere":
            r    = kwargs.get("radius", 0.03)
            coll = p.createCollisionShape(p.GEOM_SPHERE,
                       radius=r,
                       physicsClientId=self._client)
            vis  = p.createVisualShape(p.GEOM_SPHERE,
                       radius=r,
                       rgbaColor=[0.2, 0.6, 0.8, 1.0],
                       physicsClientId=self._client)
        else:
            raise ValueError(f"Unknown shape: {shape!r}. "
                             "Use 'box', 'cylinder', or 'sphere'.")

        obj_id = p.createMultiBody(
            baseMass=mass,
            baseCollisionShapeIndex=coll,
            baseVisualShapeIndex=vis,
            basePosition=[x, y, 0.03],
            physicsClientId=self._client)

        self._world_objects[obj_id] = ObjectState(
            obj_id=obj_id, x=x, y=y, heading=0.0)
        return obj_id

    def get_object_state(self, obj_id: int) -> ObjectState:
        pos, orn = p.getBasePositionAndOrientation(
            obj_id, physicsClientId=self._client)
        euler = p.getEulerFromQuaternion(orn)
        state = ObjectState(
            obj_id  = obj_id,
            x       = pos[0],
            y       = pos[1],
            heading = euler[2],
            held    = (obj_id == self._attached_obj))
        self._world_objects[obj_id] = state
        return state

    def attach_object(self, obj_id: int) -> None:
        """Grasp obj_id — create a fixed constraint to the robot body."""
        if self._robot_model is None:
            raise RuntimeError("load_world() must be called before attach_object()")
        if self._attachment_constraint is not None:
            self.release_object(self._attached_obj)

        # Get object position relative to robot
        obj_pos, _ = p.getBasePositionAndOrientation(
            obj_id, physicsClientId=self._client)
        robot_pos, robot_orn = p.getBasePositionAndOrientation(
            self._robot_model.body_id, physicsClientId=self._client)

        # Create fixed joint
        self._attachment_constraint = p.createConstraint(
            parentBodyUniqueId=self._robot_model.body_id,
            parentLinkIndex=-1,
            childBodyUniqueId=obj_id,
            childLinkIndex=-1,
            jointType=p.JOINT_FIXED,
            jointAxis=[0, 0, 0],
            parentFramePosition=[0, 0, 0.05],
            childFramePosition=[0, 0, 0],
            physicsClientId=self._client)
        self._attached_obj = obj_id

        if obj_id in self._world_objects:
            self._world_objects[obj_id].held = True

    def release_object(self, obj_id: int) -> None:
        """Release attached object — remove the fixed constraint."""
        if self._attachment_constraint is not None:
            p.removeConstraint(self._attachment_constraint,
                               physicsClientId=self._client)
            self._attachment_constraint = None
            self._attached_obj = None
        if obj_id in self._world_objects:
            self._world_objects[obj_id].held = False

    def gripper_contact(self, gripper_wx: float,
                        gripper_wy: float,
                        gripper_radius: float = 0.02) -> int | None:
        """
        Check whether any world object is within gripper_radius of
        (gripper_wx, gripper_wy).  Returns object ID or None.
        """
        for obj_id in list(self._world_objects):
            state = self.get_object_state(obj_id)
            if math.hypot(state.x - gripper_wx,
                          state.y - gripper_wy) <= gripper_radius:
                return obj_id
        return None

    # ── Introspection ─────────────────────────────────────────────────────────

    @property
    def supports_manipulation(self) -> bool:
        return True

    @property
    def supports_multi_robot(self) -> bool:
        return True

    @property
    def is_3d(self) -> bool:
        return True

    @property
    def client(self) -> int:
        """Expose the PyBullet client ID for direct access when needed."""
        return self._client
