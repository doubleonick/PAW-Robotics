"""
engine/hal/wall_drive_robot.py
--------------------------------
WallDriveRobot — drives forward until wall contact, then cycles headings.

Used by wall_drive.ino. Accepts a CogServo instance from the sketch.
"""

from __future__ import annotations
from typing import Any, Callable
import math

_RUNS: list[tuple[float, str]] = [
    ( 90.0, "North  head-on"),
    ( 70.0, "North  glancing"),
    ( 45.0, "NE corner"),
    (  0.0, "East   head-on"),
    (135.0, "NW corner"),
]

PRESS_MS = 3000
HOLD_MS  = 3000
SPEED    = 40


class _S:
    DRIVE = "DRIVE"
    PRESS = "PRESS"
    HOLD  = "HOLD"
    RESET = "RESET"


class WallDriveRobot:

    def __init__(self, servo=None):
        from engine.hal.sketch_bridge import CogServo
        self._servo        = servo if servo is not None else CogServo()
        self._state        = _S.DRIVE
        self._state_start  = 0
        self._run_idx      = 0
        self._started      = False
        self._reset_cb: Callable[[float, float, float], None] | None = None

    def begin(self, left_pin: Any = None, right_pin: Any = None,
              init_pwm: bool = True) -> None:
        # Pins already configured on servo by the sketch
        self._started = False

    def set_reset_callback(self,
                           cb: Callable[[float, float, float], None]) -> None:
        self._reset_cb = cb

    def notify_contact(self) -> None:
        if self._state == _S.DRIVE:
            from engine.hal.sketch_bridge import _millis_fn as millis
            now = millis() if millis else 0
            self._transition(_S.PRESS, now)

    def get_state_label(self) -> str:
        from engine.hal.sketch_bridge import _millis_fn as millis
        now     = millis() if millis else 0
        elapsed = now - self._state_start
        run_lbl = _RUNS[self._run_idx % len(_RUNS)][1]
        remain  = 0
        if self._state == _S.PRESS:
            remain = max(0, PRESS_MS - elapsed)
        elif self._state == _S.HOLD:
            remain = max(0, HOLD_MS - elapsed)
        la = self._servo.getLeftAngle()
        ra = self._servo.getRightAngle()
        return f"{self._state}  {run_lbl}  {remain/1000:.1f}s  L={la:.0f}° R={ra:.0f}°"

    def runSequence(self) -> None:
        from engine.hal.sketch_bridge import _millis_fn as millis
        now = millis() if millis else 0

        if not self._started:
            self._state       = _S.DRIVE
            self._state_start = now
            self._started     = True
            self._drive()
            return

        if self._state == _S.DRIVE:
            self._drive()

        elif self._state == _S.PRESS:
            self._drive()
            if now - self._state_start >= PRESS_MS:
                self._transition(_S.HOLD, now)

        elif self._state == _S.HOLD:
            if now - self._state_start >= HOLD_MS:
                self._transition(_S.RESET, now)

        elif self._state == _S.RESET:
            self._run_idx = (self._run_idx + 1) % len(_RUNS)
            heading_rad   = _RUNS[self._run_idx][0] * math.pi / 180.0
            if self._reset_cb:
                self._reset_cb(0.0, 0.0, heading_rad)
            self._transition(_S.DRIVE, now)

    def _drive(self) -> None:
        self._servo.driveProportional(SPEED, SPEED, 0)

    def _stop(self) -> None:
        self._servo.halt(0)

    def _transition(self, new_state: str, now: int) -> None:
        self._state       = new_state
        self._state_start = now
        if new_state == _S.HOLD:
            self._stop()
        elif new_state in (_S.DRIVE, _S.PRESS):
            self._drive()
