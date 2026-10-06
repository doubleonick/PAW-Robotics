"""
games/ethology/codegen.py
--------------------------
Pure code generation — no pygame, no UI.
Imported by both hierarchy_builder.py and game.py.

Sketch output is driven by the hardware profile defined in
robots/hardware_profiles.json so that pin numbers and servo
initialisation code match the physical robot exactly.
"""

import datetime
import json
import os

# ── Paths ─────────────────────────────────────────────────────────────────────
_HERE       = os.path.dirname(os.path.abspath(__file__))
_ROBOTS_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "robots"))

# ── Behaviour registry ────────────────────────────────────────────────────────
#
# (display label, WIRE NAME, needs a light source)
#
# The wire names MUST match BEHAVIOR_NAMES in firmware EthologyRobot.cpp. That
# table is the authority — EthologyRobot::setHierarchy() rejects a hierarchy
# WHOLE if any name is unrecognised, so a mismatch here does not degrade
# gracefully, it makes the behaviour unusable with no partial run.
#
# NAMING CONVENTION: verb_target. avoid_/approach_ are exact pairs;
# escape_ names where the robot was struck rather than what it flees.
#
# Display labels are independent of wire names and may be reworded freely.

BEHAVIORS = [
    ("Escape Front",    "escape_front",    False),
    ("Escape Back",     "escape_back",     False),
    ("Avoid Object",    "avoid_object",    False),
    ("Approach Object", "approach_object", False),
    ("Approach Light",  "approach_light",  True),
    ("Avoid Light",     "avoid_light",     True),
    ("Cruise Straight", "cruise_straight", False),
    ("Cruise Arc",      "cruise_arc",      False),
]

# Wire names that were used before the convention was settled. Saved
# hierarchies — including student work in %LOCALAPPDATA% — still contain
# these, and a stale key would silently fail to match a correct answer, so
# they are translated on load rather than rejected. Do not write them.
LEGACY_BEHAVIOR_ALIASES = {
    "seek_light":  "approach_light",   # paired with avoid_light
    "escape_rear": "escape_back",      # matches escapeBackCollision()
}


def canonical_behavior(name: str) -> str:
    """Map a possibly-legacy wire name to the current one."""
    return LEGACY_BEHAVIOR_ALIASES.get(name, name)


def canonical_hierarchy(names) -> list:
    """Map a whole saved hierarchy to current wire names."""
    return [canonical_behavior(n) for n in names]

BEHAVIOR_MAP  = {b[1]: b for b in BEHAVIORS}

# (guard, action) — the ACTUAL EthologyRobot method names.
#
# These must match firmware/shared/EthologyRobot.h exactly. Every one of them
# was previously snake_case (front_contact_met, escape_front, ...) while the
# class has always been camelCase, so NONE of the twelve resolved and every
# sketch this generator produced failed to compile. Nothing downstream of
# "Launch Arduino" had ever been through a compiler.
#
# Guard-then-action order is load-bearing: lightGradientThreshold() and
# collisionThreshold() CACHE the sensor readings their paired actions consume,
# so the guard must always be evaluated first. Same rule as
# EthologyRobot::_runRung().
BEHAVIOR_CODE = {
    "escape_front":    ("collisionThreshold()",     "escapeFrontCollision()"),
    "escape_back":     ("backCollisionThreshold()", "escapeBackCollision()"),
    "avoid_object":    ("proximityThreshold()",     "avoidObject()"),
    "approach_object": ("proximityThreshold()",     "approachObject()"),
    "approach_light":  ("lightGradientThreshold()", "approachLight()"),
    "avoid_light":     ("lightGradientThreshold()", "avoidLight()"),
    "cruise_straight": ("true",                     "cruiseStraight()"),
    "cruise_arc":      ("true",                     "cruiseArc()"),
}


def needs_light(hierarchy: list) -> bool:
    return any(BEHAVIOR_MAP[k][2] for k in hierarchy)


# ── Hardware profile loading ───────────────────────────────────────────────────

def load_hardware_profile(profile_key=None):
    """
    Load a hardware profile from robots/hardware_profiles.json.
    Returns (profile_dict, profile_key).
    Falls back to the default profile if profile_key is None or not found.
    """
    profiles_path = os.path.join(_ROBOTS_DIR, "hardware_profiles.json")
    with open(profiles_path) as f:
        all_profiles = json.load(f)

    default_key = all_profiles.get("default", "uno_r4_wifi__prototype")
    key = profile_key or default_key
    if key not in all_profiles["profiles"]:
        key = default_key

    return all_profiles["profiles"][key], key


def load_robot_profile(robot_json_path):
    """
    Load the hardware profile and motor pins from a robot.json file.
    Returns (profile_dict, profile_key, left_pin_str, right_pin_str).
    """
    with open(robot_json_path) as f:
        robot = json.load(f)
    profile_key = robot.get("hardware_profile")
    motor       = robot.get("motor", {})
    left_pin    = motor.get("left_pin",  "D6")
    right_pin   = motor.get("right_pin", "D5")
    profile, key = load_hardware_profile(profile_key)
    return profile, key, left_pin, right_pin


# ── Pin normalisation (used by simulation and sketch generation) ───────────────

def pin_to_int(pin):
    """
    Convert a pin identifier to a bare integer for begin() calls.
      "D6" -> 6,  "D5" -> 5,  6 -> 6,  "6" -> 6
    """
    s = str(pin).strip().upper()
    if s.startswith("D"):
        return int(s[1:])
    return int(s)


# ── Sketch generation ─────────────────────────────────────────────────────────

def generate_sketch(hierarchy, sketch_name,
                    robot_json_path=None, profile_key=None):
    """
    Generate an Arduino .ino sketch for the given hierarchy.

    Hardware configuration is read from the robot.json file (which
    references robots/hardware_profiles.json).  Falls back to the
    default profile (uno_r4_wifi__prototype, pins D6/D5) if no
    robot.json is supplied.

    Parameters
    ----------
    hierarchy       : ordered list of behaviour key strings
    sketch_name     : label used in the sketch comment header
    robot_json_path : path to robot.json (reads motor pins + profile)
    profile_key     : override profile key (ignores robot.json profile)
    """
    if robot_json_path and os.path.exists(robot_json_path):
        profile, p_key, left_pin, right_pin = load_robot_profile(robot_json_path)
    else:
        profile, p_key = load_hardware_profile(profile_key)
        left_pin  = "D6"
        right_pin = "D5"

    left_int  = pin_to_int(left_pin)
    right_int = pin_to_int(right_pin)

    # EthologyRobot handles all sensors — LDREthologyRobot is superseded
    robot_class = "EthologyRobot"
    robot_hdr   = "EthologyRobot.h"

    # Build hierarchy() body
    lines = []
    for i, key in enumerate(hierarchy):
        cond, action = BEHAVIOR_CODE[key]
        label = BEHAVIOR_MAP[key][0]
        if cond != "true":
            cond = f"bot.{cond}"
        if i == 0:
            lines.append(f"  if ({cond}) {{  // {label}")
        elif cond == "true":
            lines.append(f"  else {{  // {label}")
        else:
            lines.append(f"  else if ({cond}) {{  // {label}")
        lines.append(f"    bot.{action};")
        lines.append( "  }")

    hier_body = "\n".join(lines)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    # Resolve profile template fields
    includes    = "\n".join(f"#include {inc}"
                            for inc in profile.get("sketch_includes", ["<Servo.h>"]))
    servo_decl  = profile.get("sketch_servo_decl", "CogServo driveServos;")
    servo_begin = profile.get(
        "sketch_servo_begin",
        "driveServos.begin({left_pin}, {right_pin});"
    ).format(left_pin=left_int, right_pin=right_int)
    # Robot OWNS its CogServo and Robot::begin(left, right) starts it, so the
    # sketch declares only the robot. The key is sketch_robot_decl; the old
    # sketch_bot_decl passed a CogServo to a constructor that never existed.
    bot_decl    = profile.get(
        "sketch_robot_decl",
        profile.get("sketch_bot_decl", "{robot_class} bot;")
    ).format(robot_class=robot_class)
    bot_begin   = profile.get("sketch_bot_begin",
                              "bot.begin({left_pin}, {right_pin});")
    bot_begin   = bot_begin.format(left_pin=left_int, right_pin=right_int)

    behavior_list = "\n".join(
        f"    {i+1}. {BEHAVIOR_MAP[k][0]}" for i, k in enumerate(hierarchy))

    return (
        f"/*\n"
        f"  {sketch_name}\n"
        f"  Generated by PAW Hierarchy Builder — {ts}\n"
        f"  Board/shield: {profile.get('label', p_key)}\n\n"
        f"  Hierarchy (highest priority first):\n"
        f"{behavior_list}\n\n"
        f"  Architecture mirrors the physical robot:\n"
        f"    - EthologyRobot provides individual behaviour methods\n"
        f"    - hierarchy() chains them in priority order\n"
        f"    - loop() calls hierarchy() each tick\n"
        f"*/\n\n"
        f"{includes}\n"
        f'#include "CogServo.h"\n'
        f'#include "{robot_hdr}"\n\n'
        f"{servo_decl}\n"
        f"{bot_decl}\n\n"
        f"void hierarchy() {{\n"
        f"{hier_body}\n"
        f"}}\n\n"
        f"void setup() {{\n"
        f"  Serial.begin(9600);\n"
        f"  {servo_begin}\n"
        f"  {bot_begin}\n"
        f"\n"
        f"  // cruise_arc picks a direction with random() and holds it. Without\n"
        f"  // a seed every power cycle replays the same sequence of turns, so\n"
        f"  // two robots side by side would arc identically.\n"
        f"  randomSeed(analogRead(A5));\n"
        f"}}\n\n"
        f"void loop() {{\n"
        f"  // Sense first. readSensors() halts the motors and samples every\n"
        f"  // sensor once, so all guards below see the same reading and a tick\n"
        f"  // where nothing fires leaves the robot stopped.\n"
        f"  bot.readSensors();\n"
        f"  hierarchy();\n"
        f"}}\n"
    )
