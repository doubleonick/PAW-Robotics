"""
engine/hal/ir_tune_robot.py
-----------------------------
IRTuneRobot — proportional speed ramp based on IR sensor distance.

Drives forward, slows as it approaches a wall, stops at threshold,
then returns to start and repeats. Used to tune IR sensor response.

Accepts a CogServo instance from the sketch.
Reads IR via read_pin (HAL) using analog pin labels.
"""

from __future__ import annotations
from typing import Any

# ADC thresholds (higher = closer)
STOP_RAW     = 600    # stop when raw >= this
START_RAW    = 200    # begin ramping when raw >= this (below = full speed)
MAX_SPEED    = 50     # proportion at full speed
MIN_SPEED    = 10     # minimum proportion when close
RETURN_SPEED = 30     # proportion for return journey


class _S:
    APPROACH = "APPROACH"
    RETURN   = "RETURN"


class IRTuneRobot:

    def __init__(self, servo=None):
        from engine.hal.sketch_bridge import CogServo
        self._servo   = servo if servo is not None else CogServo()
        self._state   = _S.APPROACH
        self._started = False

    def begin(self, left_pin: Any = None, right_pin: Any = None) -> None:
        self._started = False

    def get_state_label(self) -> str:
        return self._state

    def runSequence(self) -> None:
        from engine.hal.sketch_bridge import _read_pin
        if _read_pin is None:
            return

        if not self._started:
            self._started = True
            self._state   = _S.APPROACH

        # Read both IR sensors (A0=left, A1=right), use max (nearest obstacle)
        left_raw  = int(_read_pin("A0"))
        right_raw = int(_read_pin("A1"))
        raw       = max(left_raw, right_raw)

        if self._state == _S.APPROACH:
            if raw >= STOP_RAW:
                self._servo.halt(0)
                self._state = _S.RETURN
            else:
                # Proportional speed: ramp down as we approach
                if raw < START_RAW:
                    speed = MAX_SPEED
                else:
                    t     = (raw - START_RAW) / (STOP_RAW - START_RAW)
                    speed = int(MAX_SPEED - t * (MAX_SPEED - MIN_SPEED))
                self._servo.driveProportional(speed, speed, 0)

        elif self._state == _S.RETURN:
            if raw < START_RAW:
                # Far enough — stop and approach again
                self._servo.halt(0)
                self._state = _S.APPROACH
            else:
                self._servo.driveProportional(-RETURN_SPEED, -RETURN_SPEED, 0)
