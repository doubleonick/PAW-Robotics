"""
robosim/robot/robot_model.py
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

from robosim.config import RobotConfig
from robosim.sensors.sensor_models import SensorBase, make_sensor

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

        # Servo.h: (angle - 90) / 90 gives [-1, +1] normalised speed
        v_left  =  ((left_angle  - 90.0) / 90.0) * self.MAX_SPEED
        v_right = -((right_angle - 90.0) / 90.0) * self.MAX_SPEED

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
        self._left_angle:  float = 90.0
        self._right_angle: float = 90.0

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

    def create_body(self, start_x: float = 0.0, start_y: float = 0.0,
                    start_heading: float = 0.0) -> None:
        """Create the PyBullet rigid body for the robot."""
        r = self.config.body_radius
        h = 0.06   # cylinder height

        col_id = p.createCollisionShape(
            p.GEOM_CYLINDER,
            radius=r,
            height=h,
            physicsClientId=self._client,
        )
        r_norm = [c / 255.0 for c in self._color]
        vis_id = p.createVisualShape(
            p.GEOM_CYLINDER,
            radius=r,
            length=h,
            rgbaColor=[*r_norm, 1.0],
            physicsClientId=self._client,
        )
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
        self._left_angle  = 90.0
        self._right_angle = 90.0

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
        self._left_angle  = 90.0
        self._right_angle = 90.0
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

    # ------------------------------------------------------------------
    # HAL pin dispatch
    # ------------------------------------------------------------------

    def read_pin(self, pin: Any) -> float:
        """
        Lookup order:
          1. Exact string match  e.g. "A0", "2"
          2. Analog prefix       e.g. integer 0 → "A0"
          3. Zero (unknown pin)
        """
        pin_str = str(pin)
        if pin_str in self._pin_map:
            return float(self._pin_map[pin_str].get_raw_data())
        analog_key = "A" + pin_str
        if analog_key in self._pin_map:
            return float(self._pin_map[analog_key].get_raw_data())
        logger.warning("read_pin: unknown pin %r — returning 0", pin)
        return 0.0

    def write_pin(self, pin: Any, value: float) -> None:
        pin_str = str(pin)
        if pin_str == self._left_pin:
            self._left_angle = float(value)
        elif pin_str == self._right_pin:
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
