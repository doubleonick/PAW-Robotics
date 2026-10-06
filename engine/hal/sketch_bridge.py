"""
engine/hal/sketch_bridge.py
-----------------------------
Python equivalents of the Arduino C++ class tree, designed to be injected
into the sketch's exec namespace so the .ino file runs as-is.

Class hierarchy mirrors the C++ exactly:
  CogAnaDigi
  ├── CogProximity
  ├── CogLight
  └── CogCollision
  CogServo
  Robot (composes CogServo)
  EthologyRobot(Robot)

The HAL read/write callbacks are set once at module level before the sketch
is exec'd, via SketchBridge.install(hal).
"""

from __future__ import annotations

import math
from typing import Callable, Any

# These are set by SketchBridge.install()
_read_pin:  Callable[[Any], float] | None = None
_write_pin: Callable[[Any, float], None] | None = None
_halt_fn:   Callable[[], None]       | None = None
_delay_fn:  Callable[[float], None] | None = None
_millis_fn: Callable[[], int] | None = None


# ---------------------------------------------------------------------------
# CogAnaDigi
# ---------------------------------------------------------------------------

class CogAnaDigi:
    ANALOG  = "Analog"
    DIGITAL = "Digital"

    def __init__(self, pin_label):
        if isinstance(pin_label, str):
            self._init_from_label(pin_label)
        else:
            self._sensor_type = self.DIGITAL
            self._pin = int(pin_label)
        self._raw_data = 0

    def _init_from_label(self, label: str):
        upper = label.upper()
        if 'A' in upper:
            self._sensor_type = self.ANALOG
            idx = upper.index('A')
            self._pin = int(upper[idx + 1:].strip())
        else:
            self._sensor_type = self.DIGITAL
            self._pin = int(label.strip())

    def get_raw_data(self) -> int:
        if _read_pin is None:
            return 0
        val = _read_pin(self._pin if self._sensor_type == self.DIGITAL
                        else f"A{self._pin}")
        self._raw_data = int(val)
        return self._raw_data

    def get_sensor_type(self) -> str:
        return self._sensor_type

    def get_pin(self) -> int:
        return self._pin

    # camelCase aliases to match C++ API used in sketches
    def getRawData(self)    -> int: return self.get_raw_data()
    def getSensorType(self) -> str: return self.get_sensor_type()
    def getPin(self)        -> int: return self.get_pin()


# ---------------------------------------------------------------------------
# CogProximity
# ---------------------------------------------------------------------------

class CogProximity(CogAnaDigi):
    def __init__(self, pin_label: str):
        super().__init__(pin_label)
        self._raw_data = 0
        self._data     = 0

    def get_raw_data(self) -> int:
        self._raw_data = super().get_raw_data()
        return self._raw_data

    def _analyze_data(self, raw: int) -> int:
        clamped = max(120, min(720, raw))
        t = (clamped - 120) / (720 - 120)
        return int(60 - t * (60 - 18))

    def get_data(self) -> int:
        raw        = self.get_raw_data()
        self._data = self._analyze_data(raw)
        return self._data

    # camelCase aliases
    def getRawData(self) -> int: return self.get_raw_data()
    def getData(self)    -> int: return self.get_data()


# ---------------------------------------------------------------------------
# CogLight
# ---------------------------------------------------------------------------

class CogLight(CogAnaDigi):
    def __init__(self, pin_label: str):
        super().__init__(pin_label)
        self._raw_data = 0
        self._data     = 0

    def get_raw_data(self) -> int:
        self._raw_data = super().get_raw_data()
        return self._raw_data

    def get_data(self) -> int:
        raw        = self.get_raw_data()
        self._data = int(raw * 100 / 1023)
        return self._data

    # camelCase aliases
    def getRawData(self) -> int: return self.get_raw_data()
    def getData(self)    -> int: return self.get_data()


# ---------------------------------------------------------------------------
# CogCollision
# ---------------------------------------------------------------------------

class CogCollision(CogAnaDigi):
    def __init__(self, pin):
        super().__init__(pin)
        self._data = 1   # INPUT_PULLUP default

    def get_data(self) -> int:
        if _read_pin is None:
            return 1
        self._data = int(_read_pin(self._pin))
        return self._data

    # camelCase alias
    def getData(self) -> int: return self.get_data()


# ---------------------------------------------------------------------------
# CogServo
# ---------------------------------------------------------------------------

class CogServo:
    """
    Mirrors CogServo in Servo.h mode.

    Servo.h convention:
      angle 0   = full speed one direction
      angle 90  = stop (neutral)
      angle 180 = full speed opposite direction

    driveProportional(left, right, duration):
      Negates right internally (matching CogServo.cpp) then maps
      [-100, 100] → [0, 180] degrees via mapProportionToAngle().

    The simulation only implements Servo.h mode. Sketches using the
    Adafruit PWM library on the physical robot will produce equivalent
    behaviour as long as the proportional range is the same — this is
    the intended reality gap comparison point.

    Both pwm_driver constructor arg and init_pwm are accepted but
    ignored so sketches written for either library transpile cleanly.
    """

    # ── Microseconds, mirroring firmware/shared/CogServo ──────────────────
    # This shim used to map proportions to ANGLES and call Servo.write().
    # The firmware moved to writeMicroseconds() because Servo.h maps
    # write(angle) onto 544..2400 us, so write(90) emits 1472 us — 28 us below
    # neutral, about 14% of full speed. "Stop" was a slow spin.
    #
    # Values here must match CogServo.h exactly, or the simulator drives at a
    # different speed from the robot: at CRUISE_SPEED 60 the old angle path
    # produced 915 us where the firmware produces 1140 us.
    NEUTRAL_US = 1500
    SPAN_US    = 600     # +/-100 -> neutral -/+ 600
    MIN_US     = 900
    MAX_US     = 2100

    NEUTRAL = NEUTRAL_US   # legacy alias; several getters still say "angle"
    ANGLE_MIN = 0.0
    ANGLE_MAX = 180.0

    def __init__(self, pwm_driver=None):
        # pwm_driver accepted but ignored
        self._left_pin:   Any   = None
        self._right_pin:  Any   = None
        self._left_angle: float = self.NEUTRAL_US    # microseconds, despite the name
        self._right_angle:float = self.NEUTRAL_US

    def begin(self, left_pin, right_pin, init_pwm=True) -> None:
        self._left_pin  = left_pin
        self._right_pin = right_pin
        self._write_neutral()

    def driveProportional(self, left_prop: int, right_prop: int,
                          duration: float) -> None:
        # Mirror CogServo.cpp EXACTLY: it negates the LEFT proportion, not
        # the right. This shim negated the right instead — the mirror image.
        # It happened to look correct because both sides were then mapped
        # through a symmetric function, but it inverted every turn.
        left_prop         = -left_prop
        self._left_angle  = self._prop_to_us(left_prop)
        self._right_angle = self._prop_to_us(right_prop)
        self._write_angles(self._left_angle, self._right_angle)
        if duration > 0 and _delay_fn:
            _delay_fn(duration * 1000)

    def drive_proportional(self, left_prop: int, right_prop: int,
                           duration: float) -> None:
        self.driveProportional(left_prop, right_prop, duration)

    def drive(self, duration: float) -> None:
        self._write_angles(self._left_angle, self._right_angle)
        if duration > 0 and _delay_fn:
            _delay_fn(duration * 1000)

    def translate(self, delta: int) -> None:
        self._left_angle  = self._clamp(self._left_angle  + delta)
        self._right_angle = self._clamp(self._right_angle + delta)
        self._write_angles(self._left_angle, self._right_angle)

    def rotate(self, left_delta: int, right_delta: int) -> None:
        self._left_angle  = self._clamp(self._left_angle  + left_delta)
        self._right_angle = self._clamp(self._right_angle + right_delta)
        self._write_angles(self._left_angle, self._right_angle)

    def halt(self, duration: float = 0) -> None:
        self._write_neutral()
        if duration > 0 and _delay_fn:
            _delay_fn(duration * 1000)

    def getLeftAngle(self)  -> float: return self._left_angle
    def getRightAngle(self) -> float: return self._right_angle
    def get_left_angle(self)  -> float: return self._left_angle
    def get_right_angle(self) -> float: return self._right_angle

    @classmethod
    def _prop_to_us(cls, prop: int) -> float:
        """[-100, 100] -> microseconds about neutral. 0 -> 1500.

        Matches CogServo::mapProportionToMicros: neutral - prop*SPAN/100.
        """
        prop = max(-100, min(100, prop))
        return cls._clamp(cls.NEUTRAL_US - (prop * cls.SPAN_US) / 100.0)

    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(float(cls.MIN_US), min(float(cls.MAX_US), v))

    def _write_neutral(self) -> None:
        self._left_angle  = self.NEUTRAL_US
        self._right_angle = self.NEUTRAL_US
        self._write_angles(self.NEUTRAL_US, self.NEUTRAL_US)

    def _write_angles(self, left: float, right: float) -> None:
        if _write_pin and self._left_pin is not None:
            _write_pin(self._left_pin,  left)
        if _write_pin and self._right_pin is not None:
            _write_pin(self._right_pin, right)


# ---------------------------------------------------------------------------
# Robot
# ---------------------------------------------------------------------------

class Robot:
    def __init__(self):
        self._drivetrain = CogServo()

    def begin(self, left_pin, right_pin):
        self._drivetrain.begin(left_pin, right_pin)

    def drive(self, duration: float):
        self._drivetrain.drive(duration)

    def driveProportional(self, left_prop: int, right_prop: int,
                          duration: float):
        self._drivetrain.drive_proportional(left_prop, right_prop, duration)

    def translate(self, delta: int):
        self._drivetrain.translate(delta)

    def rotate(self, left_delta: int, right_delta: int):
        self._drivetrain.rotate(left_delta, right_delta)

    def halt(self, duration: float = 0):
        self._drivetrain.halt(duration)

    def getLeftAngle(self)  -> float: return self._drivetrain.get_left_angle()
    def getRightAngle(self) -> float: return self._drivetrain.get_right_angle()


# ---------------------------------------------------------------------------
# EthologyRobot — imported from dedicated module
# ---------------------------------------------------------------------------

# The full implementation lives in ethology_robot.py.
# Imported here so the sketch namespace receives it automatically.
from engine.hal.ethology_robot import EthologyRobot


# ---------------------------------------------------------------------------
# Adafruit stub (sketch instantiates it but uses Servo.h mode)
# ---------------------------------------------------------------------------

class Adafruit_PWMServoDriver:
    def __init__(self, addr=0x40): pass
    def begin(self): pass
    def setPWMFreq(self, freq): pass
    def writeMicroseconds(self, channel, us): pass


# ---------------------------------------------------------------------------
# SketchBridge — installs callbacks and returns namespace additions
# ---------------------------------------------------------------------------

class SketchBridge:

    @staticmethod
    def install(hal) -> dict:
        """
        Return a dict of class/function names to inject into the sketch
        namespace.  Each HAL gets its own bound versions of the bridge
        classes so that multiple robots running simultaneously do not
        share module-level callback globals.
        """
        # Capture this HAL's callbacks in local variables
        _rp = hal._read_pin
        _wp = hal._write_pin
        _df = hal._delay
        _mf = hal._millis

        # Also set module globals for backward compat (single-robot sketches
        # that import sketch_bridge functions directly still work)
        global _read_pin, _write_pin, _delay_fn, _millis_fn, _halt_fn
        _read_pin  = _rp
        _write_pin = _wp
        _delay_fn  = _df
        _millis_fn = _mf

        # Shared lock state — servo writes it, bot threshold checks read it.
        # A single mutable list cell so the closure can update it.
        _lock = [0]   # _lock[0] = wall-clock ms when lock expires (0 = unlocked)

        def _lock_until_ms(duration_ms: float) -> None:
            """Record that a behavior is locked for duration_ms milliseconds."""
            if duration_ms > 0 and _mf:
                _lock[0] = _mf() + int(duration_ms)

        def _locked_now() -> bool:
            """Return True if a behavior lock is currently active."""
            if _lock[0] <= 0:
                return False
            return bool(_mf and _mf() < _lock[0])

        # Build HAL-bound subclasses that close over this HAL's callbacks.
        # Each instantiation from the sketch will use the correct robot's pins.

        class _CogAnaDigi(CogAnaDigi):
            def get_data(self):
                if _rp is None: return self._data
                self._data = _rp(self._pin if self._sensor_type == self.DIGITAL
                                 else self._pin)
                return self._data
            def get_raw_data(self):
                if _rp is None: return self._data
                return _rp(self._pin)
            getData    = get_data
            getRawData = get_raw_data

        class _CogProximity(CogProximity):
            """HAL-bound CogProximity: raw read uses HAL callback,
            getData() uses CogProximity._analyze_data() as on physical robot."""
            def get_raw_data(self) -> int:
                if _rp is None: return 0
                self._raw_data = int(_rp(f"A{self._pin}"))
                return self._raw_data
            getRawData = get_raw_data

        class _CogLight(CogLight):
            """HAL-bound CogLight: raw read uses HAL callback,
            getData() maps [0,1023] → [0,100] as on physical robot."""
            def get_raw_data(self) -> int:
                if _rp is None: return 0
                self._raw_data = int(_rp(f"A{self._pin}"))
                return self._raw_data
            getRawData = get_raw_data

        class _CogCollision(CogCollision):
            def get_data(self) -> int:
                if _rp is None: return 1   # INPUT_PULLUP default
                self._data = int(_rp(self._pin))
                return self._data
            # raw is same as data for digital pins
            def get_raw_data(self) -> int: return self.get_data()
            getData    = get_data
            getRawData = get_raw_data

        class _CogServo(CogServo):
            def _write_angles(self, left: float, right: float) -> None:
                if _wp and self._left_pin is not None:
                    _wp(self._left_pin,  left)
                if _wp and self._right_pin is not None:
                    _wp(self._right_pin, right)

            def halt(self, duration: float = 0) -> None:
                self._write_neutral()
                if duration > 0 and _df:
                    _df(duration * 1000)
                    _lock_until_ms(duration * 1000)

            def driveProportional(self, left_prop, right_prop, duration):
                # Same conversion as the base class: MICROSECONDS, and it is
                # the LEFT proportion that CogServo.cpp negates. This override
                # exists only to add the tick lock below, so the maths must
                # not diverge from the parent — it silently did before.
                left_prop         = -left_prop
                self._left_angle  = self._prop_to_us(left_prop)
                self._right_angle = self._prop_to_us(right_prop)
                self._write_angles(self._left_angle, self._right_angle)
                if duration > 0 and _df:
                    _df(duration * 1000)
                    _lock_until_ms(duration * 1000)

            drive_proportional = driveProportional

            def drive(self, duration: float) -> None:
                self._write_angles(self._left_angle, self._right_angle)
                if duration > 0 and _df:
                    _df(duration * 1000)

        class _Robot(Robot):
            def __init__(self):
                self._drivetrain = _CogServo()
            def begin(self, left_pin, right_pin):
                self._drivetrain.begin(left_pin, right_pin)
            def driveProportional(self, l, r, d):
                self._drivetrain.drive_proportional(l, r, d)
            def halt(self, d=0):
                self._drivetrain.halt(d)
            def getLeftAngle(self):  return self._drivetrain.get_left_angle()
            def getRightAngle(self): return self._drivetrain.get_right_angle()

        # Robot subclasses — inject bound sensor/servo classes via factory fns
        def _make_ethology(servo=None):
            from engine.hal.ethology_robot import EthologyRobot as _ER
            import json as _json, os as _os

            # Load sensor pin assignments from robot.json so this
            # factory stays in sync with the robot description.
            # Fallback to physical defaults if robot.json not found.
            _pins = {"leftProx":"A0","rightProx":"A1","leftLight":"A2",
                     "rightLight":"A3","leftFrontBump":"D4","rightFrontBump":"D2",
                     "leftBackBump":"D8","rightBackBump":"D7"}
            _rjson = _os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                "..", "games", "ethology", "robot.json")
            try:
                with open(_rjson) as _f:
                    _rdata = _json.load(_f)
                for _sname, _sdata in _rdata.get("sensors", {}).items():
                    if _sname in _pins:
                        _pins[_sname] = _sdata["pin"]
            except Exception:
                pass

            def _pin_int(p):
                s = str(p).strip().upper()
                return int(s[1:]) if s.startswith(("A","D")) else int(s)

            obj = _ER.__new__(_ER)
            obj._servo           = servo if servo is not None else _CogServo()
            obj.leftProx         = _CogProximity(_pins["leftProx"])
            obj.rightProx        = _CogProximity(_pins["rightProx"])
            obj.leftLight        = _CogLight(_pins["leftLight"])
            obj.rightLight       = _CogLight(_pins["rightLight"])
            obj.leftFrontBump    = _CogCollision(_pin_int(_pins["leftFrontBump"]))
            obj.rightFrontBump   = _CogCollision(_pin_int(_pins["rightFrontBump"]))
            obj.leftBackBump     = _CogCollision(_pin_int(_pins.get("leftBackBump",  "D8")))
            obj.rightBackBump    = _CogCollision(_pin_int(_pins.get("rightBackBump", "D7")))
            # State that __init__ would have set. This factory uses
            # __new__ to bypass __init__ (so it can inject bound sensor
            # classes), which means EVERY member the class relies on must be
            # listed HERE too. It is a hand-maintained duplicate of __init__
            # and it silently rots: cruiseArc's _arcLeft/_arcUntilMs and the
            # proximity cache were added to the class and not here, so every
            # generated sketch raised AttributeError on the first tick and
            # the robot simply did not move.
            obj._leftProxData       = 60      # far
            obj._rightProxData      = 60
            obj._lightGradient      = 0
            obj._leftFrontBumpData  = 1
            obj._rightFrontBumpData = 1
            obj._leftBackBumpData   = 1
            obj._rightBackBumpData  = 1
            obj._arcLeft            = False
            obj._arcUntilMs         = 0.0
            obj._escape_start       = 0
            obj._escape_dir         = 1
            obj._in_escape          = False
            obj._contact_cooldown_until = 0.0
            obj._millis_fn       = _mf
            obj._robot_label     = ""
            obj._robot_color     = (60, 160, 230)
            return obj

        def _make_ldr_ethology(servo=None):
            # LDREthologyRobot is superseded by EthologyRobot (which now
            # includes light sensors). Redirect to the same factory.
            return _make_ethology(servo)

        # Callable "classes" that behave like constructors but return
        # properly bound instances
        class _EthologyRobotBound:
            def __new__(cls, servo=None):
                return _make_ethology(servo)

        class _LDREthologyRobotBound:
            def __new__(cls, servo=None):
                return _make_ldr_ethology(servo)

        from engine.hal.demo_robot import DemoRobot
        from engine.hal.ir_tune_robot import IRTuneRobot
        from engine.hal.physics_demo import PhysicsDemo, WallDriveRobot as _WDR
        from engine.hal.wall_drive_robot import WallDriveRobot

        return {
            "CogAnaDigi":              _CogAnaDigi,
            "CogProximity":            _CogProximity,
            "CogLight":                _CogLight,
            "CogCollision":            _CogCollision,
            "CogServo":                _CogServo,
            "Robot":                   _Robot,
            "EthologyRobot":           _EthologyRobotBound,
            "LDREthologyRobot":        _LDREthologyRobotBound,
            "DemoRobot":               DemoRobot,
            "IRTuneRobot":             IRTuneRobot,
            "PhysicsDemo":             PhysicsDemo,
            "WallDriveRobot":          WallDriveRobot,
            "Adafruit_PWMServoDriver": Adafruit_PWMServoDriver,
        }
