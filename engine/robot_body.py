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
    Normalised IR proximity reading from a raw distance measurement.
    Based on Sharp GP2Y0A21 sensor: 10cm–80cm range.

    NOTE: sensor_physics.ir_reading() is the authoritative implementation
    for simulation use.  This function is retained for compatibility.
    """
    if distance_m <= 0.0:
        return 1.0
    NEAR_M = 0.10   # 10cm — saturation
    FAR_M  = 0.80   # 80cm — minimum detectable
    if distance_m > FAR_M:
        return 0.0
    if distance_m <= NEAR_M:
        return 1.0
    _K = 1.2
    return max(0.0, min(1.0, (NEAR_M / distance_m) ** _K))
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

    x, y          : world position (m) of the axle midpoint
    heading       : world heading (radians), 0 = +x axis, CCW positive
    chassis_spec  : optional chassis definition dict for rendering
    """
    x:            float = 0.0
    y:            float = 0.0
    heading:      float = 0.0
    chassis_spec: dict  = None

    def __post_init__(self):
        if self.chassis_spec is None:
            object.__setattr__(self, "chassis_spec", {})

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
        """
        Return world-frame polygon corners of the robot body (for rendering).
        Reads chassis shape from data/byov/robot.json if present,
        otherwise falls back to AnaBBot rectangle.
        """
        h = self.heading
        cos_h, sin_h = math.cos(h), math.sin(h)

        # Use chassis_spec from instance first, then robot.json fallback
        corners_local = None
        try:
            import json as _json, os as _os, math as _m
            if self.chassis_spec:
                _chassis = self.chassis_spec.get("type", "rectangle")
                _spec    = self.chassis_spec
            else:
                _rj = _os.path.join(
                    _os.path.dirname(_os.path.dirname(
                        _os.path.abspath(__file__))),
                    "data", "byov", "robot.json")
                if _os.path.exists(_rj):
                    _cfg = _json.load(open(_rj))
                    _chassis = _cfg.get("chassis", "rectangle")
                    _spec    = _cfg.get("chassis_spec", {})
                else:
                    _chassis = "rectangle"
                    _spec    = {}
            # Chassis type checks run regardless of source
            if _chassis == "rectangle":
                w = _spec.get("width_m",  BODY_WIDTH)  / 2
                l = _spec.get("length_m", BODY_LENGTH)
                front = AXLE_FROM_FRONT
                rear  = -(l - front)
                corners_local = [
                    ( front, +w), ( front, -w),
                    ( rear,  -w), ( rear,  +w)]
            elif _chassis == "octagon":
                a   = _spec.get("bsquare_m", 0.169) / 2
                cut = a * _m.sqrt(2) / (1 + _m.sqrt(2))
                corners_local = [
                    (a, a-cut),   (a, -(a-cut)),
                    (a-cut, -a),  (-a+cut, -a),
                    (-a, -(a-cut)), (-a, a-cut),
                    (-a+cut, a),  (a-cut, a)]
            elif _chassis == "triangle":
                R  = _spec.get("circum_r_m", 0.169*_m.sqrt(2)/2)
                ir = R / 2
                hs = R * _m.sqrt(3) / 2
                corners_local = [(ir, -hs), (ir, hs), (-R, 0.0)]
        except Exception:
            pass

        if corners_local is None:
            corners_local = [
                ( BODY_FRONT, +BODY_WIDTH/2),
                ( BODY_FRONT, -BODY_WIDTH/2),
                ( BODY_REAR,  -BODY_WIDTH/2),
                ( BODY_REAR,  +BODY_WIDTH/2),
            ]
            # Default: already in (forward, lateral) order
            return [
                (self.x + lx*cos_h - ly*sin_h,
                 self.y + lx*sin_h + ly*cos_h)
                for lx, ly in corners_local
            ]

        # chassis_polygon_m returns (x=lateral, y=forward).
        # Rotation matrix expects (lx=forward, ly=lateral).
        # Extra 90° CW rotation to align drawing with heading:
        # apply (lx=px, ly=-py) before the heading rotation.
        return [
            (self.x + px*cos_h + py*sin_h,
             self.y + px*sin_h - py*cos_h)
            for px, py in corners_local
        ]
