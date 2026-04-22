"""
valentinos/engine/robot_body.py
--------------------------------
Physical geometry of the Ana BBot and its sensor models.

All measurements in meters.  Robot-local coordinates:
  +x = forward (toward front of robot)
  +y = left
  Origin = midpoint of the front axle

Physical dimensions (from measurements):
  Body:     0.167m long × 0.094m wide
  Axle:     0.060m from front edge  → origin is 0.060m from front
            → rear of body is 0.107m behind origin
  Track:    ~0.120m center-to-center (wheels extend 18mm each side)
  Caster:   rear centerline, 0.087m behind axle (167-20-60 = 87mm)
  Wheel ø:  ~0.050m

Sensor mounting configurations (Option A — named physical positions):

  "standard"      IR sensors at front corners, angled outward 30°
                  LDR sensors at front center, angled slightly outward
  "forward"       Both IR sensors facing directly forward, side by side
  "fwd_back"      Left IR forward, right IR backward (or vice versa)

Within each config, sensor positions are fixed body-relative coords.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Literal

# ── Robot geometry constants ───────────────────────────────────────────────────

BODY_LENGTH    = 0.167    # front to back
BODY_WIDTH     = 0.094    # left to right
AXLE_FROM_FRONT = 0.060   # axle is 60mm from front edge
# Origin = axle midpoint
BODY_FRONT     =  AXLE_FROM_FRONT                     # +0.060m ahead of origin
BODY_REAR      = -(BODY_LENGTH - AXLE_FROM_FRONT)     # -0.107m behind origin
BODY_LEFT      =  BODY_WIDTH / 2                      # +0.047m
BODY_RIGHT     = -BODY_WIDTH / 2                      # -0.047m
WHEEL_TRACK    =  0.120                                # center-to-center
CASTER_X       = -(BODY_LENGTH - AXLE_FROM_FRONT - 0.020)  # -0.087m

# ── Sensor geometry ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SensorMount:
    """
    Position and orientation of one sensor in robot-local coordinates.

    x, y   : position (m) relative to axle midpoint
    angle  : heading relative to robot forward axis (radians)
             0 = straight ahead, +ve = left, -ve = right
    """
    x:     float
    y:     float
    angle: float   # radians


# Named IR sensor configurations
IR_CONFIGS: dict[str, tuple[SensorMount, SensorMount]] = {
    "standard": (
        # RL — left IR, forward, angled out 30° to the left
        SensorMount(x=BODY_FRONT, y=+0.020, angle=math.radians(+30)),
        # RR — right IR, forward, angled out 30° to the right
        SensorMount(x=BODY_FRONT, y=-0.020, angle=math.radians(-30)),
    ),
    "forward": (
        # Both IR sensors facing directly forward, side by side
        SensorMount(x=BODY_FRONT, y=+0.015, angle=0.0),
        SensorMount(x=BODY_FRONT, y=-0.015, angle=0.0),
    ),
    "fwd_back": (
        # RL forward, RR backward
        SensorMount(x=BODY_FRONT, y=+0.015, angle=0.0),
        SensorMount(x=BODY_REAR,  y=-0.015, angle=math.radians(180)),
    ),
}

# LDR sensors — fixed position (not repositionable on physical robot)
LDR_MOUNTS: tuple[SensorMount, SensorMount] = (
    # PL — left LDR, front-center, slight outward angle
    SensorMount(x=BODY_FRONT, y=+0.012, angle=math.radians(+15)),
    # PR — right LDR, front-center, slight outward angle
    SensorMount(x=BODY_FRONT, y=-0.012, angle=math.radians(-15)),
)

SensorConfig = Literal["standard", "forward", "fwd_back"]


# ── IR sensor model ───────────────────────────────────────────────────────────

def ir_reading(distance_m: float) -> float:
    """
    Normalize IR proximity reading from physical distance.

    Full scale (1.0) at 4 inches (0.102m).
    Drops to 0.1 at 18 inches (0.457m).
    Zero beyond 18 inches.

    Uses a simple inverse-distance curve fitted to those two points.
    """
    if distance_m <= 0.0:
        return 1.0
    FULL_SCALE_M = 0.102   # 4 inches
    MIN_RANGE_M  = 0.457   # 18 inches
    if distance_m > MIN_RANGE_M:
        return 0.0
    if distance_m <= FULL_SCALE_M:
        return 1.0
    # Power law fit to two physical data points:
    #   f(0.102m) = 1.0  (full scale at 4 inches)
    #   f(0.457m) = 0.1  (floor at 18 inches)
    # f(d) = (FULL_SCALE_M / d) ^ k
    # k = log(0.1) / log(0.102/0.457) ≈ 1.5354
    _K = 1.5354
    raw = (FULL_SCALE_M / distance_m) ** _K
    return max(0.0, min(1.0, raw))


def ldr_reading(illuminance: float, gain: float = 1.0) -> float:
    """
    Normalize LDR reading from illuminance (arbitrary units, 0..1 scale).

    illuminance=1.0 → output 1.0 (bright light pointed at sensor)
    illuminance=0.0 → output 0.0 (darkness)
    Ambient floor ~0.3 in typical room (illuminance ~0.3)

    gain: per-sensor trimpot adjustment (0.5..2.0 typical range)
    """
    raw = illuminance * gain
    return max(0.0, min(1.0, raw))


# ── Robot physics ─────────────────────────────────────────────────────────────

@dataclass
class RobotState:
    """
    World-frame pose and velocity of one robot.

    x, y     : world position (m) of the axle midpoint
    heading  : world heading (radians), 0 = +x axis, CCW positive
    """
    x:       float = 0.0
    y:       float = 0.0
    heading: float = 0.0

    def step(self, left: float, right: float, dt: float,
             max_speed: float = 0.25) -> None:
        """
        Differential drive kinematics — pivot at front axle midpoint.

        left, right : motor drive in [-1.0, 1.0]
        dt          : timestep (seconds)
        max_speed   : wheel rim speed at drive=1.0 (m/s), ~25cm/s default
        """
        vl = left  * max_speed
        vr = right * max_speed
        v  = (vl + vr) / 2.0          # forward speed of axle midpoint
        w  = (vr - vl) / WHEEL_TRACK  # angular velocity (rad/s)

        self.heading += w * dt
        self.x       += v * math.cos(self.heading) * dt
        self.y       += v * math.sin(self.heading) * dt

    def sensor_world_pos(self, mount: SensorMount) -> tuple[float, float, float]:
        """
        Return (world_x, world_y, world_angle) for a sensor mount.
        """
        h  = self.heading
        wx = self.x + mount.x * math.cos(h) - mount.y * math.sin(h)
        wy = self.y + mount.x * math.sin(h) + mount.y * math.cos(h)
        wa = h + mount.angle
        return wx, wy, wa

    def body_corners(self) -> list[tuple[float, float]]:
        """Return 4 world-frame corners of the robot body (for rendering)."""
        h      = self.heading
        cos_h, sin_h = math.cos(h), math.sin(h)
        corners_local = [
            ( BODY_FRONT, +BODY_WIDTH/2),
            ( BODY_FRONT, -BODY_WIDTH/2),
            ( BODY_REAR,  -BODY_WIDTH/2),
            ( BODY_REAR,  +BODY_WIDTH/2),
        ]
        return [
            (self.x + lx*cos_h - ly*sin_h,
             self.y + lx*sin_h + ly*cos_h)
            for lx, ly in corners_local
        ]
