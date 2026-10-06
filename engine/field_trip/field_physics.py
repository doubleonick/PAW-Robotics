"""
engine/field_trip/field_physics.py
------------------------------------
NAMING NOTE — read ARCHITECTURE.md "Naming: game vs schema vs capability".

Despite the filename, this module contains NO world physics. It implements
**Virtual Fields**, the control schema Field Trip uses: sensor readings become
force vectors, forces become motor commands (plus three goal-condition checks
that are really challenge rules). World simulation — collision, integration,
ray casting — belongs to a PhysicsAdapter (`engine/adapters/`), not here.

Two known naming problems, deliberately left alone rather than renamed:

  1. "physics" is wrong; this is a controller. That misnomer is the likely
     cause of Field Trip's hand-rolled integration loop in hub.py — the module
     that sounds like physics isn't one, so world stepping got written inline
     instead of reaching for the adapter.
  2. Virtual Fields is a *schema*, not a game, so it will eventually be used
     outside Field Trip — by the Maze game, and by any hierarchy that ranks a
     potential-field behaviour among its candidates. The move trigger has
     already fired (tools/pf_sweep.py imports it from outside Field Trip).

Left in place so the dependency is untangled once, when the Maze game needs
Virtual Fields, rather than twice.

Virtual field model — SENSOR-VECTOR ("puppeteer stick"),
matching the physical robot's CogPotentialField.

Core formula (per SENSOR):
    reading  = how strongly this sensor senses its world now, in [0,1]
               IR  -> arena wall/boundary proximity along the sensor's aim
               LDR -> summed light response over the light sources
    aim      = robot_heading + sensor.mount_angle          # world aim
    force    = reading × policy × unit_vector(aim)          # Pull=+1 along, Push=-1 opposite

Net force = sum over sensors. The robot does NOT know where sources are; it only
feels the sum of its sensors' pulls and pushes (a reactive controller). Motors come
from the hardware-validated vectorToDifferential mapping (see force_to_motors),
with a base-speed forward bias so the robot always has motion to steer with.

Arena walls are the source objects IR reacts to (read directly from geometry).
The sensor's mounting angle sets BOTH what it reads (directional response) and the
direction of its force vector — consistent with the physical potential-field robot.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional

from engine.sensor_physics import ir_reading, ldr_reading


# ── Sensor policy ─────────────────────────────────────────────────────────────

ATTRACT = +1
REPEL   = -1


# ── Sensor descriptor ─────────────────────────────────────────────────────────

@dataclass
class FieldSensor:
    """One sensor on the robot, with its policy."""
    sensor_id:  str          # e.g. "IR·L", "LDR·C1"
    stype:      str          # "IR" | "LDR"
    channel:    str          # "W" | "R" | "G" | "B"
    x_m:        float        # forward offset from axle centre (m)
    y_m:        float        # lateral offset — left positive (m)
    angle_deg:  float        # mounting angle in robot frame — 0=forward
    policy:     int          # ATTRACT (+1) or REPEL (-1) — the RADIAL response

    # Tangential (circulation) response.  0.0 = pure radial = today's
    # behavior.  Positive swirls one way around the source, negative the
    # other.  Combined with policy this spans the full flow vocabulary:
    #   policy=+1, tangential=0   -> Seek   (toward)
    #   policy=-1, tangential=0   -> Flee   (away)
    #   policy= 0, tangential!=0  -> Orbit  (circle; policy 0 = no radial)
    #   policy=-1, tangential!=0  -> Flow-around (flee + circle = round it)
    #   policy=+1, tangential!=0  -> Spiral-in (seek + circle)
    # NOTE: policy may now be 0 (no radial term); see compute_force.
    tangential: float = 0.0

    @property
    def mount_angle_rad(self) -> float:
        return math.radians(self.angle_deg)


# ── Source descriptor ─────────────────────────────────────────────────────────

@dataclass
class FieldSource:
    """One field source in the arena."""
    source_id:  str          # e.g. "light_0", "wall_0"
    stype:      str          # "light" | "wall"
    x:          float        # world x (m) — for lights, centre; walls use segments
    y:          float        # world y (m)
    color:      str = "white"
    radius:     float = 0.20
    intensity:  float = 1.0
    # Wall segment endpoints (only for stype=="wall")
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0


# ── Repulsor contact tracker ───────────────────────────────────────────────────

@dataclass
class RepulsorContact:
    """Tracks grace-period cycles for one active repulsor."""
    source_id:    str
    cycles_left:  int = 3    # cycles at 0.5s each before failure

    def tick(self) -> bool:
        """Decrement and return True if still within grace period."""
        self.cycles_left -= 1
        return self.cycles_left > 0


# ── Force computation ─────────────────────────────────────────────────────────

def compute_sensor_reading(sensor: FieldSensor,
                            robot_x: float, robot_y: float,
                            robot_heading: float,
                            source: FieldSource,
                            arena: dict) -> float:
    """
    Compute the reading of one sensor for one source.
    Returns a value in [0, 1].
    """
    # World position and angle of this sensor
    h    = robot_heading
    wx   = robot_x + sensor.x_m * math.cos(h) - sensor.y_m * math.sin(h)
    wy   = robot_y + sensor.x_m * math.sin(h) + sensor.y_m * math.cos(h)
    wa   = h + sensor.mount_angle_rad

    if sensor.stype == "IR":
        if source.stype != "wall":
            return 0.0
        return ir_reading(wx, wy, wa, arena)

    elif sensor.stype in ("LDR", "COLOR"):
        if source.stype != "light":
            return 0.0
        # Normalize channel: robot_builder uses W/R/G/B;
        # sensor_physics expects white/red/green/blue
        _ch_map = {"W": "white", "R": "red",
                   "G": "green", "B": "blue"}
        _channel = _ch_map.get(sensor.channel, sensor.channel)
        return ldr_reading(wx, wy, wa, arena,
                           channel=_channel,
                           only_source=(source.x, source.y))
    return 0.0


def compute_force(sensors: list[FieldSensor],
                  sources: list[FieldSource],
                  robot_x: float, robot_y: float,
                  robot_heading: float,
                  arena: dict) -> tuple[float, float]:
    """
    Net (fx, fy) force in world frame — SENSOR-VECTOR ("puppeteer stick") model,
    matching the physical robot's CogPotentialField::computeNetVector.

    Each sensor is a string on the puppet. Its force points along the DIRECTION THE
    SENSOR IS AIMED (mount orientation in the world frame); its MAGNITUDE is what
    the sensor senses. The robot does not know where anything IS — it only feels the
    sum of its sensors' pulls and pushes. This is the reactive law that transfers to
    hardware.

    Per sensor (NOT per sensor×source):
        reading = how strongly this sensor senses its world right now, in [0,1]
                  IR  -> arena wall/boundary proximity along the sensor's aim
                         (walls are the source objects IR reacts to; read directly
                          from arena geometry via ir_reading)
                  LDR -> summed light response over all light sources
        aim     = robot_heading + sensor.mount_angle
        Pull (attract, +1): force ALONG aim   (toward what the sensor faces)
        Push (repel,   -1): force 180deg OPPOSITE aim (away)
        contrib = reading * policy * unit(aim)   [+ optional tangential term]

    The tangential term is retained for saved robots / advanced challenges; it is
    0.0 for pure Push/Pull.
    """
    fx = 0.0
    fy = 0.0

    lights = [s for s in sources if s.stype == "light"]

    for sensor in sensors:
        aim = robot_heading + sensor.mount_angle_rad
        ux, uy = math.cos(aim), math.sin(aim)
        tx, ty = -uy, ux                      # aim rotated +90deg (circulation)

        # --- sensor reading = MAGNITUDE (one value per sensor) ---
        if sensor.stype == "IR":
            # IR reacts to arena walls/boundary directly (walls are its sources).
            reading = ir_reading(
                robot_x + sensor.x_m * math.cos(robot_heading) - sensor.y_m * math.sin(robot_heading),
                robot_y + sensor.x_m * math.sin(robot_heading) + sensor.y_m * math.cos(robot_heading),
                aim, arena)
        else:
            # LDR/COLOR: sum response over all light sources.
            reading = 0.0
            for src in lights:
                reading += compute_sensor_reading(
                    sensor, robot_x, robot_y, robot_heading, src, arena)
            reading = min(1.0, reading)

        if reading < 0.001:
            continue

        fx += reading * (sensor.policy * ux + sensor.tangential * tx)
        fy += reading * (sensor.policy * uy + sensor.tangential * ty)

    return fx, fy


def force_to_motors(fx: float, fy: float,
                    robot_heading: float,
                    gain: float = 1.0,
                    base_speed: float = 0.35,
                    forward_gain: float = 0.6,
                    turn_gain: float = 1.2) -> tuple[float, float]:
    """
    Convert the world-frame force vector to differential-drive motor speeds using
    the HARDWARE-VALIDATED mapping (CogPotentialField::vectorToDifferential), so the
    game's steering matches the physical robot.

    The world force is first rotated into the ROBOT BODY frame:
        Vy = forward component (along the robot's heading)
        Vx = lateral  component (to the robot's right)
    Then, exactly as on hardware:
        forward = base_speed + forward_gain * Vy
        turn    = turn_gain  * Vx
        left    = forward + turn
        right   = forward - turn      (a vector to the right, +Vx, turns the robot right)

    The BASE_SPEED forward bias is the key to the sensor-vector model: the robot
    always creeps forward, so it is never frozen and always has motion to steer with.
    This avoids BOTH the tight-circle stall of a pure forward/lateral projection AND
    the spin-away-and-freeze of a turn-toward-resultant controller — the same reason
    the hardware uses it.

    Returns (left, right) each in [-1, 1].
    """
    # Rotate world force into body frame. Body +Y = heading, body +X = heading-90
    # (to the robot's right).
    ch = math.cos(robot_heading)
    sh = math.sin(robot_heading)
    Vy =  fx * ch + fy * sh          # forward (along heading)
    Vx =  fx * sh - fy * ch          # lateral, +X to the robot's right

    forward = base_speed + forward_gain * Vy
    turn    = turn_gain  * Vx

    # hub integration: omega ∝ (right - left). Hardware convention: +Vx (right)
    # => left>right => turns toward the robot's right. To get that under the hub's
    # (right-left) omega, we set left=forward+turn, right=forward-turn and the hub
    # produces the correct handedness (verified against the drivetrain baseline).
    left  = (forward + turn) * gain
    right = (forward - turn) * gain

    # normalise into [-1, 1] preserving the differential
    norm = max(abs(left), abs(right), 1.0)
    return left / norm, right / norm


# ── Success / failure detection ───────────────────────────────────────────────

def check_reach_light(robot_x: float, robot_y: float,
                      body_radius: float,
                      source: FieldSource) -> bool:
    """True when robot body overlaps the bright core of the light.
    Uses the light radius so the success zone is visually meaningful.
    """
    dist      = math.hypot(robot_x - source.x, robot_y - source.y)
    # Success when robot center is within the light radius
    # (the robot is clearly "in" the light)
    threshold = body_radius + source.radius * 0.5
    return dist <= threshold


def check_reach_wall(robot_x: float, robot_y: float,
                     body_radius: float,
                     source: FieldSource) -> bool:
    """True when the robot BODY contacts the wall surface. The wall has a real
    thickness, so 'contact' is body_radius + wall half-thickness from the
    centerline — consistent with the sim's collision boundary (a robot stopped at
    the wall face should register as having reached it)."""
    nx, ny = _nearest_point_on_segment(
        robot_x, robot_y,
        source.x0, source.y0, source.x1, source.y1)
    dist = math.hypot(robot_x - nx, robot_y - ny)
    half_t = getattr(source, "thickness", 0.025) / 2.0
    return dist <= body_radius + half_t


def check_repulsor_contact(robot_x: float, robot_y: float,
                            body_radius: float,
                            source: FieldSource,
                            contact_threshold: float = 0.05) -> bool:
    """
    True when robot is within contact_threshold of a repulsor source.
    contact_threshold is in addition to body_radius.
    """
    if source.stype == "light":
        dist = math.hypot(robot_x - source.x, robot_y - source.y)
        return dist <= body_radius + contact_threshold
    else:
        nx, ny = _nearest_point_on_segment(
            robot_x, robot_y,
            source.x0, source.y0, source.x1, source.y1)
        dist = math.hypot(robot_x - nx, robot_y - ny)
        return dist <= body_radius + contact_threshold


# ── Helpers ───────────────────────────────────────────────────────────────────

def _nearest_point_on_segment(px: float, py: float,
                               ax: float, ay: float,
                               bx: float, by: float) -> tuple[float, float]:
    """Return the point on segment AB nearest to P."""
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx*dx + dy*dy
    if seg_len_sq < 1e-10:
        return ax, ay
    t = max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy) / seg_len_sq))
    return ax + t*dx, ay + t*dy
