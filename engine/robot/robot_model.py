"""
engine/robot/robot_model.py
-----------------------------
RobotModel: owns the PyBullet rigid body, differential-drive kinematics,
sensor collection, and pin-map dispatch for the HAL.

Physics design
--------------
Motors are implemented as force-based actuators, NOT velocity overrides.
Using resetBaseVelocity() every frame bypasses PyBullet collision response
entirely — the robot passes through walls. Instead we:

  1. Compute desired wheel velocities from servo angles
  2. Measure current body velocity from PyBullet
  3. Apply a corrective force proportional to the velocity error
     (PD controller on velocity, clamped to a max force)

PyBullet then resolves that force against contact constraints naturally.
The robot accelerates toward the desired speed but is physically blocked
by walls, and will slide/slow along them as friction dictates.

Locomotion is a Strategy class so future modes (tail-drive, etc.) can be
swapped in without touching RobotModel.
"""

from __future__ import annotations

import math
import logging
from typing import Any

import pybullet as p
import numpy as np

from engine.config import RobotConfig
from engine.sensors.sensor_models import SensorBase, make_sensor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Locomotion strategy base
# ---------------------------------------------------------------------------

class LocomotionStrategy:
    def apply(self, left_angle: float, right_angle: float,
              body_id: int, config: RobotConfig,
              physics_client: int) -> None:
        raise NotImplementedError


class DifferentialDrive(LocomotionStrategy):
    """
    Differential drive locomotion.

    Sets body velocity directly each step via resetBaseVelocity.
    This is simple and reliable. Wall collisions are handled by
    clamping the commanded velocity against actual contact normals
    — if a wall blocks +Y motion, the physics solver zeroes that
    component before we read it back, so we don't fight the wall.
    """

    MAX_SPEED = 0.35    # m/s at full command (proportion=±100)

    def apply(self, left_angle: float, right_angle: float,
              body_id: int, config: RobotConfig,
              physics_client: int) -> None:

        # CogServo writes MICROSECONDS now, not angles. The parameters keep
        # their old names because write_pin() is generic, but the values are
        # pulse widths: 1500 = stop, +/-SPAN_US = full speed.
        #
        # Reading these as angles would treat 1500 as (1500-90)/90 = 15.7x
        # full speed — the robot would leave the arena on the first tick.
        NEUTRAL_US, SPAN_US = 1500.0, 600.0
        v_left  =  ((left_angle  - NEUTRAL_US) / SPAN_US) * self.MAX_SPEED
        v_right = -((right_angle - NEUTRAL_US) / SPAN_US) * self.MAX_SPEED

        # Desired body velocity
        v_des = (v_left + v_right) / 2.0
        w_des = (v_right - v_left) / config.wheel_base

        # Current heading
        _, orn = p.getBasePositionAndOrientation(
            body_id, physicsClientId=physics_client)
        heading = p.getEulerFromQuaternion(orn)[2]

        # Decompose desired linear velocity into world-frame components
        vx = v_des * math.cos(heading)
        vy = v_des * math.sin(heading)

        p.resetBaseVelocity(
            body_id,
            linearVelocity=[vx, vy, 0],
            angularVelocity=[0, 0, w_des],
            physicsClientId=physics_client,
        )


# ---------------------------------------------------------------------------
# RobotModel
# ---------------------------------------------------------------------------

class RobotModel:
    """
    Owns:
      - PyBullet body
      - Sensor collection
      - Pin-map → sensor/motor dispatch
      - Current servo angles (set by HAL write_pin)
      - Pose (read from PyBullet each step)
    """

    def __init__(self, config: RobotConfig, physics_client: int,
                 color: tuple = (50, 150, 230)):
        self.config         = config
        self._client        = physics_client
        self._body_id: int  = -1
        self._locomotion    = DifferentialDrive()
        self._color         = color

        # Current servo angles (Servo.h: 0–180°, 90=neutral/stop)
        # Set by write_pin() from CogServo, read by DifferentialDrive.apply()
        # Microseconds (see DifferentialDrive.apply); 1500 = stop.
        self._left_angle:  float = 1500.0
        self._right_angle: float = 1500.0

        # Pose (updated each step from PyBullet)
        self._pos_x:   float = 0.0
        self._pos_y:   float = 0.0
        self._heading: float = 0.0

        # Sensors keyed by name and by pin
        self._sensors: dict[str, SensorBase] = {}
        self._pin_map: dict[str, SensorBase] = {}

        for sc in config.sensors:
            sensor = make_sensor(sc)
            self._sensors[sc.name] = sensor
            self._pin_map[sc.pin]  = sensor

        self._left_pin  = str(config.motor.left_pin)
        self._right_pin = str(config.motor.right_pin)

    # ------------------------------------------------------------------
    # Physics body creation
    # ------------------------------------------------------------------

    def _chassis_vertices(self):
        """Chassis outline in robot-local metres, or None for a cylinder.

        The spec may arrive as `chassis_spec` (a dict) or `chassis` (a key into
        robot_builder.CHASSIS). geometry == "circle" forces the cylinder even
        when a spec is present, so a config can opt out.
        """
        # NOTE: cfg.geometry is deliberately NOT consulted. Its default is
        # "circle" and predates polygon support, so honouring it would disable
        # polygons for every config already on disk. The presence of a chassis
        # spec is the signal; omit the spec to get a cylinder.
        spec = getattr(self.config, "chassis_spec", None)
        if spec is None:
            return None
        try:
            from engine.builder.robot_builder import chassis_polygon_m, CHASSIS
            if isinstance(spec, str):
                spec = CHASSIS.get(spec)
                if spec is None:
                    return None
            return chassis_polygon_m(spec)
        except Exception:
            return None

    def create_body(self, start_x: float = 0.0, start_y: float = 0.0,
                    start_heading: float = 0.0) -> None:
        """Create the PyBullet rigid body for the robot.

        Uses the chassis OUTLINE when one is available, so the collision shape
        matches the drawn body. This is what lets a rectangular robot catch a
        wall on its corner, slip along it and bump free — behaviour a cylinder
        cannot produce, because a circle has no corner and no orientation.

        Falls back to a cylinder of body_radius when no chassis spec is given.
        """
        h = 0.06   # body height
        r = self.config.body_radius
        r_norm = [c / 255.0 for c in self._color]

        verts = self._chassis_vertices()
        if verts:
            # A convex hull of the outline extruded to height h. PyBullet builds
            # a hull from the point cloud, so both faces must be supplied.
            cloud = ([[x, y, -h / 2] for x, y in verts] +
                     [[x, y,  h / 2] for x, y in verts])
            col_id = p.createCollisionShape(
                p.GEOM_MESH, vertices=cloud, physicsClientId=self._client)
            # No visual shape: createVisualShape(GEOM_MESH) requires indices as
            # well as vertices, and nothing renders from PyBullet anyway — the
            # games draw the chassis themselves from the pose. -1 means "no
            # visual", which is valid and cheaper.
            vis_id = -1
        else:
            col_id = p.createCollisionShape(
                p.GEOM_CYLINDER, radius=r, height=h,
                physicsClientId=self._client)
            vis_id = p.createVisualShape(
                p.GEOM_CYLINDER, radius=r, length=h,
                rgbaColor=[*r_norm, 1.0], physicsClientId=self._client)
        start_orn = p.getQuaternionFromEuler(
            [0, 0, start_heading],
            physicsClientId=self._client,
        )
        self._body_id = p.createMultiBody(
            baseMass=self.config.total_mass_kg,
            baseCollisionShapeIndex=col_id,
            baseVisualShapeIndex=vis_id,
            basePosition=[start_x, start_y, h / 2],
            baseOrientation=start_orn,
            physicsClientId=self._client,
        )

        # Physics material — realistic rubber-on-floor feel
        p.changeDynamics(
            self._body_id, -1,
            lateralFriction=0.7,
            spinningFriction=0.02,
            rollingFriction=0.002,
            restitution=0.1,
            linearDamping=0.5,
            angularDamping=0.8,
            physicsClientId=self._client,
        )

        # Collision group assignment:
        #   group=0b10 (2)  mask=0b11 (3) — robot collides with walls (group 1)
        #   and with other robots (group 2).
        #   IR raycasts use mask=0b11 so they hit both walls and robots.
        p.setCollisionFilterGroupMask(
            self._body_id, -1,
            collisionFilterGroup=2,
            collisionFilterMask=3,
            physicsClientId=self._client,
        )

        self._pos_x   = start_x
        self._pos_y   = start_y
        self._heading = start_heading
        logger.info("Robot body created (id=%d) at (%.3f, %.3f) heading=%.2f°",
                    self._body_id, start_x, start_y, math.degrees(start_heading))

    # ------------------------------------------------------------------
    # Teleport (for reset)
    # ------------------------------------------------------------------

    def halt_velocity(self) -> None:
        """Zero all velocity immediately."""
        p.resetBaseVelocity(
            self._body_id,
            linearVelocity=[0, 0, 0],
            angularVelocity=[0, 0, 0],
            physicsClientId=self._client,
        )
        self._left_angle  = 1500.0
        self._right_angle = 1500.0

    def reset_pose(self, x: float = 0.0, y: float = 0.0,
                   heading: float = 0.0) -> None:
        """Instantly move robot to a new pose and zero its velocity."""
        h = 0.06
        orn = p.getQuaternionFromEuler([0, 0, heading],
                                        physicsClientId=self._client)
        p.resetBasePositionAndOrientation(
            self._body_id,
            [x, y, h / 2],
            orn,
            physicsClientId=self._client,
        )
        p.resetBaseVelocity(
            self._body_id,
            linearVelocity=[0, 0, 0],
            angularVelocity=[0, 0, 0],
            physicsClientId=self._client,
        )
        self._left_angle  = 1500.0
        self._right_angle = 1500.0
        self._pos_x   = x
        self._pos_y   = y
        self._heading = heading

    # ------------------------------------------------------------------
    # Step
    # ------------------------------------------------------------------

    def step(self, arena_body_ids: list[int]) -> None:
        """Update pose from PyBullet, apply motors, refresh sensors."""
        pos, orn = p.getBasePositionAndOrientation(
            self._body_id, physicsClientId=self._client)
        self._pos_x   = pos[0]
        self._pos_y   = pos[1]
        self._heading = p.getEulerFromQuaternion(orn)[2]

        # Apply motor forces (physics-based, respects contacts)
        self._locomotion.apply(
            self._left_angle, self._right_angle,
            self._body_id, self.config, self._client,
        )

        # Update sensors
        for sensor in self._sensors.values():
            sensor.update(
                (self._pos_x, self._pos_y),
                self._heading,
                self._client,
                self._body_id,
                arena_body_ids,
            )

    def apply_drive(self, left: float, right: float) -> None:
        """Set wheel commands from normalised [-1, 1] values.

        This is the entry point for callers that speak in normalised motor
        commands (PhysicsAdapter.step) rather than servo angles. Sketches
        driving through the HAL should keep using write_pin() — this method
        produces exactly the same servo angles that CogServo would.

        Mapping, derived from firmware CogServo::driveProportional:

            leftProportion = -leftProportion            // firmware negates LEFT
            angle = map(prop, -100, 100, 180, 0)        // INVERTED map

        which yields  left_angle = 90 + L*0.9,  right_angle = 90 - R*0.9
        for proportions L, R in [-100, 100].

        (engine/hal/sketch_bridge.py reaches the same angles by the mirror
        route — a non-inverted map with the RIGHT proportion negated. Its
        comment says it is negating right "to mirror CogServo.cpp", which is
        misleading: the firmware negates left. The two inversions cancel, so
        both are correct. Verified against both firmware variants.)

        Drive.apply() then reads these back as
            v_left  =  ((left_us  - 1500) / 600) * MAX_SPEED
            v_right = -((right_us - 1500) / 600) * MAX_SPEED
        giving v = command * MAX_SPEED on both wheels, as intended.
        """
        left  = max(-1.0, min(1.0, float(left)))
        right = max(-1.0, min(1.0, float(right)))
        # MICROSECONDS, matching CogServo: 1500 = stop, +/-SPAN_US = full.
        NEUTRAL_US, SPAN_US = 1500.0, 600.0
        self._left_angle  = NEUTRAL_US + left  * SPAN_US
        self._right_angle = NEUTRAL_US - right * SPAN_US

    # ------------------------------------------------------------------
    # HAL pin dispatch
    # ------------------------------------------------------------------

    def read_pin(self, pin: Any) -> float:
        """
        Lookup order — all normalised to match robot.json pin strings:
          1. Exact match          e.g. "A0", "D2", "2"
          2. D-form               e.g. integer 2 → "D2"
          3. Bare numeric         e.g. "D2" → "2"
          4. A-form (analog)      e.g. integer 0 → "A0"
        Handles CogCollision(2) matching robot.json pin "D2", etc.
        """
        raw  = str(pin).strip().upper()
        bare = raw.lstrip("D").lstrip("A") if raw[0] in ("D","A") else raw
        for candidate in (raw, "D" + bare, bare, "A" + bare):
            if candidate in self._pin_map:
                return float(self._pin_map[candidate].get_raw_data())
        logger.warning("read_pin: unknown pin %r — returning 0", pin)
        return 0.0

    def write_pin(self, pin: Any, value: float) -> None:
        # Normalise pin identifier — strip leading "D" so that
        # sketch begin(0, 1) matches robot.json "D0"/"D1" pins.
        pin_str = str(pin).upper().lstrip("D") if str(pin).upper().startswith("D")                   else str(pin)
        left_norm  = str(self._left_pin).upper().lstrip("D")                       if str(self._left_pin).upper().startswith("D")                      else str(self._left_pin)
        right_norm = str(self._right_pin).upper().lstrip("D")                      if str(self._right_pin).upper().startswith("D")                      else str(self._right_pin)
        if pin_str == left_norm:
            self._left_angle = float(value)
        elif pin_str == right_norm:
            self._right_angle = float(value)
        else:
            logger.debug("write_pin: unhandled pin %r = %s", pin, value)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def body_id(self) -> int:
        return self._body_id

    @property
    def pos_x(self) -> float:
        return self._pos_x

    @property
    def pos_y(self) -> float:
        return self._pos_y

    @property
    def heading(self) -> float:
        return self._heading

    @property
    def sensors(self) -> dict[str, SensorBase]:
        return self._sensors

    @property
    def left_angle(self) -> float:
        return self._left_angle

    @property
    def right_angle(self) -> float:
        return self._right_angle
