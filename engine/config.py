"""
engine/config.py
-----------------
Dataclasses for arena and robot configuration.
Loaded from JSON at launch; nothing is hardcoded here.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import json
import os

# Sub-structures
# ---------------------------------------------------------------------------

@dataclass
class LightSource:
    x: float          # metres
    y: float          # metres
    intensity: float  # 0.0 – 1.0 nominal
    radius: float     # effective radius in metres
    color: str = "white"  # "white"/"red"/"green"/"blue"


@dataclass
class SensorConfig:
    name: str
    type: str                       # "ir" | "light" | "contact"
    mount: tuple[float, float]      # (x, y) offset from robot centre in metres
    angle: float                    # degrees, 0 = forward (+Y)
    pin: str                        # e.g. "A0", "2"
    range_min: float = 0.0
    range_max: float = 1.0
    noise_stddev: float = 0.0
    # HUD display
    hud_color: tuple[int, int, int] = (255, 255, 255)
    hud_alpha: int = 160


@dataclass
class MotorConfig:
    left_pin: str   # servo channel / pin label
    right_pin: str


# ---------------------------------------------------------------------------
# Top-level configs
# ---------------------------------------------------------------------------

@dataclass
class InternalWall:
    x0: float
    y0: float
    x1: float
    y1: float
    thickness: float = 0.05


@dataclass
class ArenaConfig:
    width: float  = 2.0    # metres
    height: float = 2.0    # metres
    wall_thickness: float = 0.05
    light_sources:  list[LightSource]  = field(default_factory=list)
    internal_walls: list[InternalWall] = field(default_factory=list)
    # Robot start pose from arena JSON — None means use random/default
    robot_start_x:   float = 0.0
    robot_start_y:   float = -0.6
    robot_start_deg: float = 90.0
    robot_start_set: bool  = False   # True if arena JSON contained robot_start

    @staticmethod
    def from_dict(d: dict) -> "ArenaConfig":
        lights = [LightSource(**ls) for ls in d.get("light_sources", [])]
        walls  = [InternalWall(**w)  for w  in d.get("internal_walls", [])]
        rs = d.get("robot_start", None)
        return ArenaConfig(
            width=d.get("width", 2.0),
            height=d.get("height", 2.0),
            wall_thickness=d.get("wall_thickness", 0.05),
            light_sources=lights,
            internal_walls=walls,
            robot_start_x   = float(rs["x"])           if rs else 0.0,
            robot_start_y   = float(rs["y"])           if rs else -0.6,
            robot_start_deg = float(rs["heading_deg"]) if rs else 90.0,
            robot_start_set = rs is not None,
        )

    @staticmethod
    def from_file(path: str) -> "ArenaConfig":
        with open(path, "r") as f:
            return ArenaConfig.from_dict(json.load(f))


def _chassis_from_geometry(d: dict):
    """Derive a chassis spec from a robot.json that describes its body the CAD
    way (geometry + bounding_square) rather than carrying an explicit spec.

    games/ethology/robot.json is written this way, so without this RE's polygon
    collision path stays dormant even though the data is present.
    """
    geo = d.get("geometry")
    if geo == "octagon" and d.get("bounding_square"):
        return {"type": "octagon", "bsquare_m": d["bounding_square"]}
    if geo == "rectangle" and d.get("width_m") and d.get("length_m"):
        return {"type": "rectangle", "width_m": d["width_m"],
                "length_m": d["length_m"]}
    if geo == "triangle" and d.get("circum_r_m"):
        return {"type": "triangle", "circum_r_m": d["circum_r_m"]}
    return None


@dataclass
class RobotConfig:
    # Geometry
    geometry: str = "circle"        # "circle" | "polygon"
    radius: float = 0.029           # metres  (rolling radius from CAD)
    body_radius: float = 0.084      # half of 168mm frame width
    wheel_base: float = 0.168       # left-to-right wheel separation (metres)

    # Drive
    motor: MotorConfig = field(default_factory=lambda: MotorConfig("6", "5"))

    # Sensors
    sensors: list[SensorConfig] = field(default_factory=list)

    # Mass distribution entries (name, mass_kg, offset_x, offset_y)
    mass_components: list[dict] = field(default_factory=list)

    # Physics
    total_mass_kg: float = 0.8

    # Chassis outline. Either a spec dict {"type": "octagon", "bsquare_m": ...}
    # or a key into robot_builder.CHASSIS. When present, RobotModel builds a
    # convex-hull collision shape from the DRAWN outline instead of a cylinder,
    # so a rectangular robot can catch a wall on its corner and slip along it.
    chassis_spec: dict | str | None = None

    @staticmethod
    def from_dict(d: dict) -> "RobotConfig":
        motor = MotorConfig(**d.get("motor", {"left_pin": "6", "right_pin": "5"}))

        sensors = []
        for name, sc in d.get("sensors", {}).items():
            mount = tuple(sc.get("mount", [0.0, 0.0]))
            hud_color = tuple(sc.get("hud_color", [255, 255, 255]))
            sensors.append(SensorConfig(
                name=name,
                type=sc["type"],
                mount=mount,
                angle=sc.get("angle", 0.0),
                pin=sc["pin"],
                range_min=sc.get("range", [0.0, 1.0])[0],
                range_max=sc.get("range", [0.0, 1.0])[1],
                noise_stddev=sc.get("noise_stddev", 0.0),
                hud_color=hud_color,
                hud_alpha=sc.get("hud_alpha", 160),
            ))

        return RobotConfig(
            geometry=d.get("geometry", "circle"),
            radius=d.get("radius", 0.029),
            body_radius=d.get("body_radius", 0.084),
            wheel_base=d.get("wheel_base", 0.168),
            motor=motor,
            sensors=sensors,
            mass_components=d.get("mass_components", []),
            total_mass_kg=d.get("total_mass_kg", 0.8),
            chassis_spec=(d.get("chassis_spec") or d.get("chassis")
                          or _chassis_from_geometry(d)),
        )

    @staticmethod
    def from_file(path: str) -> "RobotConfig":
        with open(path, "r") as f:
            return RobotConfig.from_dict(json.load(f))
