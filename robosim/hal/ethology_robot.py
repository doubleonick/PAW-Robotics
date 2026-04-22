"""
robosim/hal/ethology_robot.py
------------------------------
EthologyRobot — behaviour hierarchy with subsumption architecture.

Priority (highest subsumes lower):
  1. ESCAPE  — collision detected: spin away from contact side for ESCAPE_MS
  2. AVOID   — IR raw ADC >= AVOID_RAW: steer away from nearer sensor
  3. CRUISE  — default: drive straight forward

Accepts a CogServo instance from the sketch so motor commands reach
the HAL correctly.

ADC thresholds (higher = closer, matches physical Sharp sensor):
  AVOID_RAW  — begin avoidance (object within ~35cm)
  ESCAPE_MS  — duration of escape spin in milliseconds
"""

from __future__ import annotations
from typing import Any

# ── Tuning constants ──────────────────────────────────────────────────────────
AVOID_RAW   = 400    # ADC threshold for IR avoidance (~35cm on Sharp curve)
CRUISE_SPD  = 50     # forward proportion during cruise
AVOID_SPD   = 40     # turn proportion during avoidance
ESCAPE_SPD  = 70     # spin proportion during escape
ESCAPE_MS   = 2000   # ms to spin after a collision


class _S:
    CRUISE = "CRUISE"
    AVOID  = "AVOID"
    ESCAPE = "ESCAPE"


class EthologyRobot:

    def __init__(self, servo=None):
        from robosim.hal.sketch_bridge import CogServo, CogProximity, CogCollision
        self._servo = servo if servo is not None else CogServo()

        # Sensors — read via HAL pin map
        self._leftIR    = CogProximity("A0")
        self._rightIR   = CogProximity("A1")
        self._leftFront = CogCollision(4)
        self._rightFront= CogCollision(2)
        self._leftRear  = CogCollision(3)
        self._rightRear = CogCollision(5)

        self._state        = _S.CRUISE
        self._escape_start = 0
        self._escape_dir   = 1    # +1 or -1
        self._escape_mode  = "arc"  # "arc" or "spin"

    def begin(self) -> None:
        self._state        = _S.CRUISE

    # ── Threshold checks (callable from generated sketches) ───────────────────

    def _is_locked(self) -> bool:
        """Return True if a timed behavior is currently running."""
        millis = getattr(self, "_millis_fn", None)
        now    = millis() if millis else 0
        return now < getattr(self, "_locked_until", 0)

    def front_contact_met(self) -> bool:
        if self._is_locked():
            return False
        return (int(self._leftFront.getData()) == 0 or
                int(self._rightFront.getData()) == 0)

    def rear_contact_met(self) -> bool:
        if self._is_locked():
            return False
        return (int(self._leftRear.getData()) == 0 or
                int(self._rightRear.getData()) == 0)

    def proximity_threshold_met(self) -> bool:
        if self._is_locked():
            return False
        return (int(self._leftIR.getRawData())  >= AVOID_RAW or
                int(self._rightIR.getRawData()) >= AVOID_RAW)

    def light_gradient_met(self) -> bool:
        return False   # EthologyRobot has no light sensors

    # ── Individual behavior methods (callable from generated sketches) ─────────

    def escape_front(self) -> None:
        """Reverse arc away from the front contact side. Runs to completion."""
        millis = getattr(self, "_millis_fn", None)
        now    = millis() if millis else 0

        # Start escape if not already locked to this behavior
        if not self._is_locked():
            lf = int(self._leftFront.getData())
            self._state           = _S.ESCAPE
            self._escape_start    = now
            self._escape_dir      = -1 if lf == 0 else 1
            self._escape_mode     = "arc"

        elapsed = now - self._escape_start
        if elapsed < ESCAPE_MS:
            if self._escape_dir == -1:
                self._servo.driveProportional(-ESCAPE_SPD // 4, -ESCAPE_SPD,
                                             ESCAPE_MS / 1000)
            else:
                self._servo.driveProportional(-ESCAPE_SPD, -ESCAPE_SPD // 4,
                                             ESCAPE_MS / 1000)
        else:
            self._state = _S.CRUISE

    def escape_rear(self) -> None:
        """Spin away from the rear contact side. Runs to completion."""
        millis = getattr(self, "_millis_fn", None)
        now    = millis() if millis else 0

        if not self._is_locked():
            lr = int(self._leftRear.getData())
            self._state           = _S.ESCAPE
            self._escape_start    = now
            self._escape_dir      = 1 if lr == 0 else -1
            self._escape_mode     = "spin"

        elapsed = now - self._escape_start
        if elapsed < ESCAPE_MS:
            spd = ESCAPE_SPD * self._escape_dir
            self._servo.driveProportional(-spd, -spd, ESCAPE_MS / 1000)
        else:
            self._state = _S.CRUISE

    def avoid_object(self) -> None:
        """Arc away from the nearer IR sensor."""
        self._state = _S.AVOID
        il = int(self._leftIR.getRawData())
        ir = int(self._rightIR.getRawData())
        if ir >= il:
            self._servo.driveProportional(CRUISE_SPD // 4, CRUISE_SPD, 0)
        else:
            self._servo.driveProportional(CRUISE_SPD, CRUISE_SPD // 4, 0)

    def approach_object(self) -> None:
        """Arc toward the nearer IR sensor."""
        self._state = _S.AVOID
        il = int(self._leftIR.getRawData())
        ir = int(self._rightIR.getRawData())
        if ir >= il:
            self._servo.driveProportional(CRUISE_SPD, CRUISE_SPD // 4, 0)
        else:
            self._servo.driveProportional(CRUISE_SPD // 4, CRUISE_SPD, 0)

    def seek_light(self) -> None:
        pass   # No light sensors on EthologyRobot

    def avoid_light(self) -> None:
        pass   # No light sensors on EthologyRobot

    def cruise_straight(self) -> None:
        self._state = _S.CRUISE
        self._servo.driveProportional(CRUISE_SPD, CRUISE_SPD, 0)

    def cruise_arc(self) -> None:
        """Gentle left arc — robot drifts rather than drives straight."""
        self._state = _S.CRUISE
        self._servo.driveProportional(CRUISE_SPD // 2, CRUISE_SPD, 0)

    def get_state_label(self) -> str:
        millis = getattr(self, "_millis_fn", None)
        now = millis() if millis else 0
        if self._state == _S.ESCAPE:
            remain = max(0, ESCAPE_MS - (now - self._escape_start))
            return f"ESCAPE  {remain/1000:.1f}s"
        if self._state == _S.AVOID:
            lr = int(self._leftIR.getRawData())
            rr = int(self._rightIR.getRawData())
            return f"AVOID  L={lr} R={rr}"
        lr = int(self._leftIR.getRawData())
        rr = int(self._rightIR.getRawData())
        return f"CRUISE  L={lr} R={rr}"

    def hierarchy(self) -> None:
        """Run one tick of the behaviour hierarchy."""
        millis = getattr(self, "_millis_fn", None)
        now = millis() if millis else 0

        # ── Read sensors ──────────────────────────────────────────────────────
        left_raw   = int(self._leftIR.getRawData())
        right_raw  = int(self._rightIR.getRawData())
        left_front = int(self._leftFront.getData())
        right_front= int(self._rightFront.getData())
        left_rear  = int(self._leftRear.getData())
        right_rear = int(self._rightRear.getData())

        front_hit = (left_front == 0 or right_front == 0)
        rear_hit  = (left_rear  == 0 or right_rear  == 0)

        # ── Priority 1: ESCAPE ────────────────────────────────────────────────
        if (front_hit or rear_hit) and self._state != _S.ESCAPE:
            self._state        = _S.ESCAPE
            self._escape_start = now
            # Front hit: reverse arc away from contact side
            # Rear hit:  spin to face away from contact side
            if front_hit:
                # left front → reverse arc left (slow left wheel while backing)
                # right front → reverse arc right (slow right wheel while backing)
                self._escape_dir = -1 if left_front == 0 else 1
                self._escape_mode = "arc"
            else:
                # left rear → spin CW (turn right to face away)
                # right rear → spin CCW (turn left to face away)
                self._escape_dir = 1 if left_rear == 0 else -1
                self._escape_mode = "spin"

        if self._state == _S.ESCAPE:
            elapsed = now - self._escape_start
            if elapsed < ESCAPE_MS:
                if self._escape_mode == "arc":
                    # Reverse arc: both wheels back, inner wheel slower
                    # escape_dir=-1 (left hit) → arc left while reversing:
                    #   left wheel slower, right wheel faster (both negative)
                    if self._escape_dir == -1:
                        self._servo.driveProportional(
                            -ESCAPE_SPD // 4, -ESCAPE_SPD, 0)
                    else:
                        self._servo.driveProportional(
                            -ESCAPE_SPD, -ESCAPE_SPD // 4, 0)
                else:
                    # Spin in place
                    spd = ESCAPE_SPD * self._escape_dir
                    self._servo.driveProportional(-spd, -spd, 0)
                return
            else:
                self._state = _S.CRUISE

        # ── Priority 2: AVOID ─────────────────────────────────────────────────
        if left_raw >= AVOID_RAW or right_raw >= AVOID_RAW:
            self._state = _S.AVOID
            if right_raw >= left_raw:
                # Obstacle closer on right → arc left (slow left wheel)
                self._servo.driveProportional(CRUISE_SPD // 4, CRUISE_SPD, 0)
            else:
                # Obstacle closer on left → arc right (slow right wheel)
                self._servo.driveProportional(CRUISE_SPD, CRUISE_SPD // 4, 0)
            return

        # ── Priority 3: CRUISE ────────────────────────────────────────────────
        self._state = _S.CRUISE
        self._servo.driveProportional(CRUISE_SPD, CRUISE_SPD, 0)

    def get_hud_info(self):
        """Return HUDInfo for the behavior panel."""
        from robosim.renderer.hud import HUDInfo, SensorBar

        il = int(self._leftIR.getRawData())
        ir = int(self._rightIR.getRawData())
        lf = int(self._leftFront.getData())
        rf = int(self._rightFront.getData())
        lr = int(self._leftRear.getData())
        rr = int(self._rightRear.getData())

        front = (lf == 0 or rf == 0)
        rear  = (lr == 0 or rr == 0)
        avoid = (il >= AVOID_RAW or ir >= AVOID_RAW)

        # Trigger reason
        if self._state == _S.ESCAPE:
            if self._escape_mode == "arc":
                side = "Left front" if lf == 0 else "Right front"
                trigger = f"{side} contact → reverse arc"
            else:
                side = "Left rear" if lr == 0 else "Right rear"
                trigger = f"{side} contact → spin away"
        elif self._state == _S.AVOID:
            side = "IR Right" if ir >= il else "IR Left"
            val  = ir if ir >= il else il
            trigger = f"{side}: {val} ≥ {AVOID_RAW}"
        else:
            trigger = "no threshold exceeded"

        sensors = [
            SensorBar("IR Left",      il, AVOID_RAW, 0, 720,
                      triggered=(il >= AVOID_RAW)),
            SensorBar("IR Right",     ir, AVOID_RAW, 0, 720,
                      triggered=(ir >= AVOID_RAW)),
            SensorBar("Front L",      1 - lf, 0.5, 0, 1,
                      triggered=(lf == 0)),
            SensorBar("Front R",      1 - rf, 0.5, 0, 1,
                      triggered=(rf == 0)),
            SensorBar("Rear L",       1 - lr, 0.5, 0, 1,
                      triggered=(lr == 0)),
            SensorBar("Rear R",       1 - rr, 0.5, 0, 1,
                      triggered=(rr == 0)),
        ]

        return HUDInfo(behavior=self._state, trigger=trigger, sensors=sensors,
                       robot_label=getattr(self, '_robot_label', ''),
                       robot_color=getattr(self, '_robot_color', (60,160,230)))
