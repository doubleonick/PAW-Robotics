"""
engine/sensors/sensor_models.py
---------------------------------
Sensor simulation models.

Each sensor:
  - Knows its mount position and angle relative to the robot centre
  - Reads from PyBullet (raycasting or contact events)
  - Applies the same data pipeline as the Arduino C++ class it mirrors
  - Exposes get_raw_data() and get_data() matching the C++ API
  - Exposes hud_value() → [0, 1] for the renderer HUD overlay

Coordinate convention
---------------------
Robot body frame:  +X = right, +Y = forward, Z = up
World frame:       same, rotated by robot heading
"""

from __future__ import annotations

import math
import random
import logging
from typing import Any
import random
from dataclasses import dataclass

import pybullet as p

from engine.config import SensorConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base sensor
# ---------------------------------------------------------------------------

class SensorBase:
    """
    Abstract base.  Subclasses implement _compute_raw().
    """

    def __init__(self, config: SensorConfig):
        self.config   = config
        self.name     = config.name
        self.pin      = config.pin
        self._raw     = 0
        self._data    = 0

    # Called each physics step by the simulation
    def update(self, robot_pos: tuple[float, float],
               robot_heading: float,
               physics_client: int,
               robot_body_id: int,
               arena_body_ids: list[int]) -> None:
        raise NotImplementedError

    def get_raw_data(self) -> int:
        return self._raw

    def get_data(self) -> int:
        return self._data

    def hud_value(self) -> float:
        """Normalised [0, 1] value for HUD rendering."""
        raise NotImplementedError

    # World-space position and direction of this sensor
    def world_pose(self, robot_pos: tuple[float, float],
                   robot_heading: float) -> tuple[tuple[float, float], float]:
        """
        Returns (world_xy, world_angle_rad).

        robot_heading: radians CCW from world +X, pointing in the direction
                       of the robot body +Y axis (forward).

        Mount convention: (mx, my) = (body +X offset, body +Y offset)
          mx > 0 = to the robot's right
          my > 0 = forward

        Correct rotation for +Y-forward convention:
          body +Y (forward) in world = (cos h, sin h)
          body +X (right)   in world = (sin h, -cos h)   [+Y rotated 90° CW]

          wx = rx + mx * sin(h) + my * cos(h)
          wy = ry - mx * cos(h) + my * sin(h)
        """
        mx, my = self.config.mount
        cos_h  = math.cos(robot_heading)
        sin_h  = math.sin(robot_heading)

        wx = robot_pos[0] + mx * sin_h + my * cos_h
        wy = robot_pos[1] - mx * cos_h + my * sin_h

        # Sensor pointing direction in world frame
        # config.angle is degrees CCW from body +Y (forward)
        sensor_angle_body = math.radians(self.config.angle)
        world_angle = robot_heading + sensor_angle_body

        return (wx, wy), world_angle

    def _add_noise(self, value: float) -> float:
        if self.config.noise_stddev > 0:
            value += random.gauss(0, self.config.noise_stddev)
        return value


# ---------------------------------------------------------------------------
# IR Proximity sensor
# ---------------------------------------------------------------------------

class IRSensor(SensorBase):
    """
    Sharp GP2Y0A21YK0F distance sensor simulation.

    Physical characteristics:
      Range:        10 – 80 cm (0.10 – 0.80 m)
      Beam:         Triangulation — effective half-angle ~5° (very narrow)
      Output:       Analog, non-linear: V ≈ 27/d_cm (empirical)
      Update rate:  ~31 Hz (32 ms cycle)

    Simulation pipeline (mirrors CogProximity exactly):
      raycast hit_distance → synthetic raw ADC → clamp [120,720] → map [60,18]

    RAW_MIN/MAX are empirical calibration values from the physical sensor.
    They do NOT correspond to true ADC voltage values — they represent the
    observed output range of the specific sensor units used.

    The simulation converts distance → raw using the same inversion:
      closer → higher raw (consistent with Sharp's higher-V-when-closer response)

    Three rays cast per update: centre ± BEAM_HALF_ANGLE
    The minimum hit distance of the three is used (most conservative / realistic).
    """

    # Empirical raw range from CogProximity::analyzeData
    RAW_MIN       = 120    # maps to 60 cm (far edge of reliable range)
    RAW_MAX       = 720    # maps to 18 cm (near edge — slightly > 10cm minimum)
    DIST_MIN      = 0.10   # metres — sensor minimum (10 cm)
    DIST_MAX      = 0.80   # metres — sensor maximum (80 cm)
    # Sharp GP2Y0A21YK0F effective beam half-angle (triangulation geometry)
    BEAM_HALF_DEG = 5.0

    # Sharp GP2Y0A21YK0F sample interval: ~32 ms (31 Hz)
    SAMPLE_INTERVAL = 0.032   # seconds between sensor updates

    def __init__(self, config):
        super().__init__(config)
        self._next_sample_time: float = 0.0
        # Initialise to out-of-range values (nothing detected)
        self._raw  = 60   # below RAW_MIN — clearly out of range
        self._data = 60

    def update(self, robot_pos, robot_heading, physics_client, robot_body_id,
               arena_body_ids) -> None:
        # Throttle to sensor sample rate — avoids noise-driven flicker at 120 Hz
        import time
        now = time.monotonic()
        if now < self._next_sample_time:
            return   # return cached values from last sample
        self._next_sample_time = now + self.SAMPLE_INTERVAL

        (wx, wy), world_angle = self.world_pose(robot_pos, robot_heading)

        # Cast three rays: centre, +5°, -5°
        half_rad = math.radians(self.BEAM_HALF_DEG)
        ray_angles = [world_angle,
                      world_angle + half_rad,
                      world_angle - half_rad]

        # ── PyBullet domain (metres) ──────────────────────────────────────────
        # Raycast against walls AND other robots (mask=3 hits groups 1 and 2).
        hit_dist = self.DIST_MAX
        RAY_Z = 0.10   # above robot cylinder top (z=0.06m)
        for angle in ray_angles:
            ray_start = [wx, wy, RAY_Z]
            ray_end   = [wx + math.cos(angle) * self.DIST_MAX,
                         wy + math.sin(angle) * self.DIST_MAX,
                         RAY_Z]
            result = p.rayTestBatch(
                [ray_start], [ray_end],
                collisionFilterMask=3,
                physicsClientId=physics_client,
            )
            frac = result[0][2]
            if frac < 1.0:
                hit_dist = min(hit_dist, frac * self.DIST_MAX)

        # No wall within sensor range → return out-of-range sentinel.
        # This check MUST happen before any noise is applied: noise must never
        # convert an out-of-range distance into a plausible ADC reading.
        if hit_dist >= self.DIST_MAX:
            self._raw  = 60    # below RAW_MIN=120 — matches physical Sharp garbage output
            self._data = 60
            return

        # ── Sensor model boundary: metres → ADC ──────────────────────────────
        # Convert the geometric hit distance to a synthetic ADC count using the
        # Sharp GP2Y0A21YK0F response curve (closer = higher ADC).
        # After this line, metres are no longer used.
        t   = (hit_dist - self.DIST_MIN) / (self.DIST_MAX - self.DIST_MIN)
        raw = int(self.RAW_MAX - t * (self.RAW_MAX - self.RAW_MIN))

        # ── ADC domain (what the sketch sees) ────────────────────────────────
        # noise_stddev is in ADC counts, matching robot.json units.
        # Clamp to the sensor's valid ADC range before storing.
        if self.config.noise_stddev > 0:
            raw = int(raw + random.gauss(0, self.config.noise_stddev))
        raw        = max(self.RAW_MIN, min(self.RAW_MAX, raw))
        self._raw  = raw
        self._data = int(self._map(raw, self.RAW_MIN, self.RAW_MAX, 60, 18))

    def hud_value(self) -> float:
        """0=far(dim), 1=close(bright)."""
        return 1.0 - (self._data - 18) / max(1, (60 - 18))

    def beam_half_angle_rad(self) -> float:
        return math.radians(self.BEAM_HALF_DEG)

    @staticmethod
    def _map(v, in_min, in_max, out_min, out_max) -> float:
        return (v - in_min) * (out_max - out_min) / (in_max - in_min) + out_min


# ---------------------------------------------------------------------------
# Ambient light sensor (LDR)
# ---------------------------------------------------------------------------

class LightSensor(SensorBase):
    """
    SENSOR POLARITY — see firmware/shared/CogLight.h for the full contract.

    getData() returns 0 = BRIGHT, 100 = DARK, because the modelled LDR sits in
    a divider that reads HIGH IN THE DARK. This sensor returns raw on that
    same convention so the simulator and the robot agree end to end.

    If the physical robot is ever rebuilt with light sensors that rise with
    brightness, change the map in CogLight — one line, in one place — not the
    behaviours in EthologyRobot, and mirror it here. Every light behaviour
    inverts if the two disagree, which is exactly what happened before this
    was written down.

    Mirrors CogLight:
      analogRead [0, 1023] → map [0, 100]

    Simulation: Inverse-square sum of all light sources, attenuated by walls.
    Returns an equivalent ADC value [0, 1023].
    """

    # LDR field of view half-angle in degrees.
    # Physical LDRs are wide-angle but not omnidirectional.
    # 70 degrees gives a 140-degree cone — realistic for a bare LDR cell.
    FOV_HALF_DEG = 70.0

    def update(self, robot_pos, robot_heading, physics_client, robot_body_id,
               arena_body_ids) -> None:
        (wx, wy), sensor_world_angle = self.world_pose(robot_pos, robot_heading)

        # Imported lazily to avoid circular deps
        from engine.arena.arena_model import ArenaModel
        light_sources = ArenaModel.get_instance().light_sources if ArenaModel.get_instance() else []

        fov_half_rad = math.radians(self.FOV_HALF_DEG)
        total = 0.0
        for ls in light_sources:
            dx   = ls.x - wx
            dy   = ls.y - wy
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < 0.001:
                dist = 0.001

            # Angle from sensor to light source in world frame
            angle_to_light = math.atan2(dy, dx)

            # Angular difference between sensor facing direction and light
            # sensor_world_angle: 0 = world +X (east), π/2 = north
            diff = angle_to_light - sensor_world_angle
            # Normalise to [-π, π]
            diff = (diff + math.pi) % (2 * math.pi) - math.pi

            # Outside field of view — skip
            if abs(diff) > fov_half_rad:
                continue

            # Cosine directional weighting: 1.0 when light is dead ahead,
            # falling to 0 at the edge of the FOV cone
            directional = math.cos(diff)

            # Line-of-sight check
            ray_start = [wx, wy, 0.05]
            ray_end   = [ls.x, ls.y, 0.05]
            result    = p.rayTest(ray_start, ray_end,
                                  physicsClientId=physics_client)
            blocked   = result[0][2] < 0.99

            if not blocked:
                contribution = ls.intensity * directional / (dist * dist)
                total += contribution

        # Clamp and scale to ADC range
        # POLARITY: the modelled LDR is in a divider that reads HIGH IN THE
        # DARK and LOW IN THE LIGHT, matching the physical robot. The sim used
        # to return the opposite (more light -> higher raw), which inverted
        # every light gradient: approach_light behaved as avoid and vice versa,
        # while the object behaviours — which use the same motor commands but
        # a proximity gradient — stayed correct. That asymmetry is what
        # identified the sensor rather than the motor maths as the cause.
        #
        # CogLight then applies map(raw, 0, 1023, 100, 0), so brighter ends up
        # as a LOWER getData() value, which is what the hardware-verified
        # behaviours in EthologyRobot expect.
        # POLARITY — INVERT EXACTLY ONCE, HERE.
        #
        # getData() must return BRIGHTER -> LOWER, because that is the
        # convention EthologyRobot's hardware-verified light behaviours are
        # calibrated against:
        #
        #   gradient = rightLight - leftLight
        #   light on the LEFT  -> right sensor reads HIGHER -> gradient > 0
        #   approachLight, gradient > 0 -> driveProportional(-40, 40)
        #                               -> turns LEFT, toward it.  Correct.
        #
        # The same command is what avoidObject uses to turn away from a
        # right-hand obstacle, and both are right at once only under this
        # polarity. That consistency is the check, not the wheel arithmetic.
        #
        # DO NOT also invert the map in CogLight.get_data(). Inverting in both
        # places composes to 1023-(1023-x) = x and changes nothing at all —
        # a fix that looks applied and is not. That mistake was made here.
        raw   = 1023 - int(min(1023, total * 50))
        raw   = int(self._add_noise(float(raw)))
        raw   = max(0, min(1023, raw))
        self._raw  = raw
        # CogLight: map [0,1023] → [0,100]
        self._data = int(raw * 100 / 1023)

    def hud_value(self) -> float:
        return self._data / 100.0

    def _add_noise(self, value: float) -> float:
        if self.config.noise_stddev > 0:
            value += random.gauss(0, self.config.noise_stddev)
        return value


# ---------------------------------------------------------------------------
# Contact / collision sensor
# ---------------------------------------------------------------------------

class ContactSensor(SensorBase):
    """
    Mirrors CogCollision:
      digitalRead with INPUT_PULLUP → 0 = triggered, 1 = clear

    Simulation: PyBullet contact points on the robot body.
    The sensor fires if any contact point falls within its angular sector.
    """

    # Angular sector half-width for contact attribution (degrees)
    SECTOR_DEG = 60.0

    def __init__(self, config: SensorConfig):
        super().__init__(config)
        self._raw  = 1   # INPUT_PULLUP default: 1 = not triggered
        self._data = 1

    def update(self, robot_pos, robot_heading, physics_client, robot_body_id,
               arena_body_ids) -> None:
        triggered = False

        # Exclude only the floor (arena_body_ids[0]) and the robot's own body.
        # All other contacts — walls, internal walls, other robots — trigger.
        excluded = {arena_body_ids[0], robot_body_id}

        contacts = p.getContactPoints(bodyA=robot_body_id,
                                      physicsClientId=physics_client)
        if contacts:
            sensor_world_angle = (robot_heading +
                                  math.radians(self.config.angle))
            sector = math.radians(self.SECTOR_DEG)

            for c in contacts:
                # c[2] is bodyB — skip floor and self
                if c[2] in excluded:
                    continue

                # Contact position in world frame
                cx, cy = c[6][0], c[6][1]
                dx = cx - robot_pos[0]
                dy = cy - robot_pos[1]

                contact_angle = math.atan2(dy, dx)
                diff = abs(self._angle_diff(contact_angle, sensor_world_angle))
                if diff <= sector:
                    triggered = True
                    break

        # INPUT_PULLUP: 0 = triggered, 1 = clear
        self._raw  = 0 if triggered else 1
        self._data = self._raw

    def hud_value(self) -> float:
        return 1.0 if self._data == 0 else 0.0   # bright on trigger

    @staticmethod
    def _angle_diff(a: float, b: float) -> float:
        """Signed angular difference in [-π, π]."""
        d = a - b
        while d >  math.pi: d -= 2 * math.pi
        while d < -math.pi: d += 2 * math.pi
        return d


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_sensor(config: SensorConfig) -> SensorBase:
    kind = config.type.lower()
    if kind == "ir":
        return IRSensor(config)
    elif kind == "light":
        return LightSensor(config)
    elif kind == "contact":
        return ContactSensor(config)
    else:
        raise ValueError(f"Unknown sensor type: {config.type!r}")
