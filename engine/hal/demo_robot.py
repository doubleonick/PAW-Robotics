"""
engine/hal/demo_robot.py
--------------------------
DemoRobot — timed spin/drive sequence for basic movement testing.

Accepts a CogServo instance from the sketch (same pattern as WallDriveRobot).
Motor commands go through the passed servo so they reach the HAL correctly.
"""

from __future__ import annotations
from typing import Any

_State = type('_State', (), {
    'SPIN_CCW': 'SPIN_CCW',
    'DRIVE_FWD': 'DRIVE_FWD',
    'SPIN_CW': 'SPIN_CW',
    'DRIVE_BACK': 'DRIVE_BACK',
    'HALT': 'HALT',
})()

# (left_prop, right_prop) — CogServo negates right internally
# So (60, 60) → left fwd, right fwd = straight forward
# And (60, -60) → left fwd, right fwd also? NO:
#   right_internal = -(-60) = 60 → angle = (60+100)*180/200 = 144° (back)
#   We want spin: left fwd, right back → (60, 60) because CogServo negates right
#   Wait: right_internal = -(60) = -60 → angle = (-60+100)*180/200 = 36° (back) ✓
# Summary: both props same sign = straight, opposite sign = spin

_SEQUENCE = [
    (_State.SPIN_CCW,   1500, ( 60,  60)),   # left fwd,  right back  → CCW
    (_State.DRIVE_FWD,  2000, ( 60, -60)),   # Wait — let me think again...
]

# CogServo.driveProportional(left, right):
#   right_internal = -right
#   left_angle  = (left + 100) * 180/200
#   right_angle = (-right + 100) * 180/200
#
# For straight forward: need both wheels going forward
#   left_angle > 90 → left > 0
#   right_angle < 90 → -right > 0... wait
#   right_angle = (-right + 100)*180/200
#   right_angle < 90 means (-right + 100) < 100 means -right < 0 means right > 0
#   right_angle > 90 means right < 0
#
# In DifferentialDrive:
#   v_left  =  (left_angle  - 90)/90 * MAX   → positive when left_angle > 90
#   v_right = -(right_angle - 90)/90 * MAX   → positive when right_angle < 90
#
# So: straight forward = left>0, right>0 → driveProportional(+X, +X) ✓
#     spin CCW = left back, right fwd OR left fwd, right back
#       left fwd (+), right back (-): driveProportional(+X, -X)
#       Actually: right back means v_right negative means right_angle > 90
#                 right_angle > 90 means -right + 100 > 100 means right < 0
#       So spin CCW = left fwd, right back = driveProportional(+X, -X)

_STEPS = [
    (_State.SPIN_CCW,   1200, ( 60, -60)),   # spin CCW: left fwd, right back
    (_State.DRIVE_FWD,  2000, ( 60,  60)),   # straight forward
    (_State.SPIN_CW,    1200, (-60,  60)),   # spin CW: left back, right fwd
    (_State.DRIVE_BACK, 2000, (-60, -60)),   # straight backward
    (_State.HALT,        800, (  0,   0)),   # halt
]


class DemoRobot:

    def __init__(self, servo=None):
        from engine.hal.sketch_bridge import CogServo
        self._servo      = servo if servo is not None else CogServo()
        self._step_idx   = 0
        self._step_start = 0
        self._started    = False

    def begin(self, left_pin: Any = None, right_pin: Any = None) -> None:
        # Pins configured on servo by sketch; begin() just marks ready
        self._started = False

    def get_state_label(self) -> str:
        return _STEPS[self._step_idx][0]

    def runSequence(self) -> None:
        from engine.hal.sketch_bridge import _millis_fn as millis
        now = millis() if millis else 0

        if not self._started:
            self._started    = True
            self._step_idx   = 0
            self._step_start = now
            self._apply_step()
            return

        _, duration_ms, _ = _STEPS[self._step_idx]
        if now - self._step_start >= duration_ms:
            self._step_idx   = (self._step_idx + 1) % len(_STEPS)
            self._step_start = now
            self._apply_step()

    def _apply_step(self) -> None:
        _, _, (left, right) = _STEPS[self._step_idx]
        self._servo.driveProportional(left, right, 0)
