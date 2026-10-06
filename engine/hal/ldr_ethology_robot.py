"""
engine/hal/ldr_ethology_robot.py
-----------------------------------
LDREthologyRobot — full ethology hierarchy with light-seeking.

Priority (highest subsumes lower):
  1. ESCAPE  — collision: front=reverse arc, rear=spin away
  2. AVOID   — IR raw >= AVOID_RAW: arc away from obstacle
  3. SEEK    — LDR gradient >= SEEK_GRAD: arc toward brighter side
  4. CRUISE  — default: drive straight forward

LDR readings are raw ADC [0, 1023] from CogLight.getRawData().
Gradient = right_raw - left_raw (positive = brighter on right).
"""

from __future__ import annotations

# ── Tuning constants ──────────────────────────────────────────────────────────
AVOID_RAW   = 400    # IR ADC threshold for avoidance (~35cm)
SEEK_GRAD   = 2      # minimum LDR gradient to trigger seeking
CRUISE_SPD  = 50
AVOID_SPD   = 50
SEEK_SPD    = 50
ESCAPE_SPD  = 70
ESCAPE_MS   = 2000


class _S:
    CRUISE = "CRUISE"
    AVOID  = "AVOID"
    SEEK   = "SEEK"
    ESCAPE = "ESCAPE"


class LDREthologyRobot:

    def __init__(self, servo=None):
        from engine.hal.sketch_bridge import (
            CogServo, CogProximity, CogLight, CogCollision)
        self._servo = servo if servo is not None else CogServo()

        self._leftIR     = CogProximity("A0")
        self._rightIR    = CogProximity("A1")
        self._leftLight  = CogLight("A2")
        self._rightLight = CogLight("A3")
        self._leftFront  = CogCollision(4)
        self._rightFront = CogCollision(2)
        self._leftRear   = CogCollision(3)
        self._rightRear  = CogCollision(5)

        self._state        = _S.CRUISE
        self._escape_start = 0
        self._escape_dir   = 1
        self._escape_mode  = "arc"

    def begin(self) -> None:
        self._state        = _S.CRUISE

    # ── Threshold checks ──────────────────────────────────────────────────────

    def _is_locked(self) -> bool:
        """Check lock via shared servo duration lock if available."""
        fn = getattr(self, "_locked_now", None)
        if fn is not None:
            return fn()
        # Fallback: check local _locked_until
        millis = getattr(self, "_millis_fn", None)
        now    = millis() if millis else 0
        return now < getattr(self, "_locked_until", 0)

    def front_contact_met(self) -> bool:
        if self._is_locked():
            return False
        return (int(self._leftFront.getData())  == 0 or
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
        if self._is_locked():
            return False
        ll = int(self._leftLight.getRawData())
        rl = int(self._rightLight.getRawData())
        return abs(rl - ll) >= SEEK_GRAD

    # ── Individual behavior methods ───────────────────────────────────────────

    def escape_front(self) -> None:
        """Reverse arc away from front contact. Runs to completion."""
        millis = getattr(self, "_millis_fn", None)
        now    = millis() if millis else 0

        if not self._is_locked():
            lf = int(self._leftFront.getData())
            self._state           = _S.ESCAPE
            self._escape_start    = now
            self._escape_dir      = -1 if lf == 0 else 1
            self._escape_mode     = "arc"

        if now - self._escape_start < ESCAPE_MS:
            if self._escape_dir == -1:
                self._servo.driveProportional(-ESCAPE_SPD // 4, -ESCAPE_SPD,
                                             ESCAPE_MS / 1000)
            else:
                self._servo.driveProportional(-ESCAPE_SPD, -ESCAPE_SPD // 4,
                                             ESCAPE_MS / 1000)
        else:
            self._state = _S.CRUISE

    def escape_back(self) -> None:
        """Spin away from rear contact. Runs to completion."""
        millis = getattr(self, "_millis_fn", None)
        now    = millis() if millis else 0

        if not self._is_locked():
            lr = int(self._leftRear.getData())
            self._state           = _S.ESCAPE
            self._escape_start    = now
            self._escape_dir      = 1 if lr == 0 else -1
            self._escape_mode     = "spin"

        if now - self._escape_start < ESCAPE_MS:
            spd = ESCAPE_SPD * self._escape_dir
            self._servo.driveProportional(-spd, -spd, ESCAPE_MS / 1000)
        else:
            self._state = _S.CRUISE

    def avoid_object(self) -> None:
        self._state = _S.AVOID
        il = int(self._leftIR.getRawData())
        ir = int(self._rightIR.getRawData())
        if ir >= il:
            self._servo.driveProportional(AVOID_SPD // 4, AVOID_SPD, 0)
        else:
            self._servo.driveProportional(AVOID_SPD, AVOID_SPD // 4, 0)

    def approach_object(self) -> None:
        self._state = _S.AVOID
        il = int(self._leftIR.getRawData())
        ir = int(self._rightIR.getRawData())
        if ir >= il:
            self._servo.driveProportional(AVOID_SPD, AVOID_SPD // 4, 0)
        else:
            self._servo.driveProportional(AVOID_SPD // 4, AVOID_SPD, 0)

    def approach_light(self) -> None:
        self._state = _S.SEEK
        ll = int(self._leftLight.getRawData())
        rl = int(self._rightLight.getRawData())
        if rl > ll:
            self._servo.driveProportional(SEEK_SPD, SEEK_SPD // 3, 0)
        else:
            self._servo.driveProportional(SEEK_SPD // 3, SEEK_SPD, 0)

    def avoid_light(self) -> None:
        self._state = _S.SEEK
        ll = int(self._leftLight.getRawData())
        rl = int(self._rightLight.getRawData())
        if rl > ll:
            self._servo.driveProportional(SEEK_SPD // 3, SEEK_SPD, 0)
        else:
            self._servo.driveProportional(SEEK_SPD, SEEK_SPD // 3, 0)

    def cruise_straight(self) -> None:
        self._state = _S.CRUISE
        self._servo.driveProportional(CRUISE_SPD, CRUISE_SPD, 0)

    def cruise_arc(self) -> None:
        self._state = _S.CRUISE
        self._servo.driveProportional(CRUISE_SPD // 2, CRUISE_SPD, 0)

    def get_state_label(self) -> str:
        millis = getattr(self, "_millis_fn", None)
        now = millis() if millis else 0
        if self._state == _S.ESCAPE:
            remain = max(0, ESCAPE_MS - (now - self._escape_start))
            return f"ESCAPE  {remain/1000:.1f}s  ({self._escape_mode})"
        lr = int(self._leftIR.getRawData())
        rr = int(self._rightIR.getRawData())
        ll = int(self._leftLight.getRawData())
        rl = int(self._rightLight.getRawData())
        return (f"{self._state}  "
                f"IR L={lr} R={rr}  "
                f"LDR L={ll} R={rl} grad={rl-ll:+d}")

    def hierarchy(self) -> None:
        millis = getattr(self, "_millis_fn", None)
        now = millis() if millis else 0

        # ── Read sensors ──────────────────────────────────────────────────────
        ir_left    = int(self._leftIR.getRawData())
        ir_right   = int(self._rightIR.getRawData())
        ldr_left   = int(self._leftLight.getRawData())
        ldr_right  = int(self._rightLight.getRawData())
        left_front = int(self._leftFront.getData())
        right_front= int(self._rightFront.getData())
        left_rear  = int(self._leftRear.getData())
        right_rear = int(self._rightRear.getData())

        front_hit  = (left_front == 0 or right_front == 0)
        rear_hit   = (left_rear  == 0 or right_rear  == 0)
        gradient   = ldr_right - ldr_left   # positive = brighter on right

        # ── Priority 1: ESCAPE ────────────────────────────────────────────────
        if (front_hit or rear_hit) and self._state != _S.ESCAPE:
            self._state        = _S.ESCAPE
            self._escape_start = now
            if front_hit:
                self._escape_dir  = -1 if left_front == 0 else 1
                self._escape_mode = "arc"
            else:
                self._escape_dir  = 1 if left_rear == 0 else -1
                self._escape_mode = "spin"

        if self._state == _S.ESCAPE:
            elapsed = now - self._escape_start
            if elapsed < ESCAPE_MS:
                if self._escape_mode == "arc":
                    if self._escape_dir == -1:
                        self._servo.driveProportional(
                            -ESCAPE_SPD // 4, -ESCAPE_SPD, 0)
                    else:
                        self._servo.driveProportional(
                            -ESCAPE_SPD, -ESCAPE_SPD // 4, 0)
                else:
                    spd = ESCAPE_SPD * self._escape_dir
                    self._servo.driveProportional(-spd, -spd, 0)
                return
            else:
                self._state = _S.CRUISE

        # ── Priority 2: AVOID ─────────────────────────────────────────────────
        if ir_left >= AVOID_RAW or ir_right >= AVOID_RAW:
            self._state = _S.AVOID
            if ir_right >= ir_left:
                # Closer on right → arc left
                self._servo.driveProportional(AVOID_SPD // 4, AVOID_SPD, 0)
            else:
                # Closer on left → arc right
                self._servo.driveProportional(AVOID_SPD, AVOID_SPD // 4, 0)
            return

        # ── Priority 3: SEEK ──────────────────────────────────────────────────
        if abs(gradient) >= SEEK_GRAD:
            self._state = _S.SEEK
            if gradient > 0:
                # Brighter on right → arc right
                self._servo.driveProportional(SEEK_SPD, SEEK_SPD // 3, 0)
            else:
                # Brighter on left → arc left
                self._servo.driveProportional(SEEK_SPD // 3, SEEK_SPD, 0)
            return

        # ── Priority 4: CRUISE ────────────────────────────────────────────────
        self._state = _S.CRUISE
        self._servo.driveProportional(CRUISE_SPD, CRUISE_SPD, 0)

    def get_hud_info(self):
        """Return HUDInfo for the behavior panel."""
        from engine.renderer.hud import HUDInfo, SensorBar

        il = int(self._leftIR.getRawData())
        ir = int(self._rightIR.getRawData())
        ll = int(self._leftLight.getRawData())
        rl = int(self._rightLight.getRawData())
        lf = int(self._leftFront.getData())
        rf = int(self._rightFront.getData())
        lr = int(self._leftRear.getData())
        rr = int(self._rightRear.getData())
        grad = rl - ll

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
        elif self._state == _S.SEEK:
            side = "Right brighter" if grad > 0 else "Left brighter"
            trigger = f"{side}: grad={grad:+d} ≥ {SEEK_GRAD}"
        else:
            trigger = "no threshold exceeded"

        sensors = [
            SensorBar("IR Left",   il,  AVOID_RAW, 0, 720,
                      triggered=(il >= AVOID_RAW)),
            SensorBar("IR Right",  ir,  AVOID_RAW, 0, 720,
                      triggered=(ir >= AVOID_RAW)),
            SensorBar("LDR Left",  ll,  0,         0, 1023,
                      triggered=(self._state == _S.SEEK)),
            SensorBar("LDR Right", rl,  0,         0, 1023,
                      triggered=(self._state == _S.SEEK)),
            SensorBar("Front L",   1-lf, 0.5, 0, 1,
                      triggered=(lf == 0)),
            SensorBar("Front R",   1-rf, 0.5, 0, 1,
                      triggered=(rf == 0)),
        ]

        return HUDInfo(behavior=self._state, trigger=trigger, sensors=sensors,
                       robot_label=getattr(self, '_robot_label', ''),
                       robot_color=getattr(self, '_robot_color', (60,160,230)))
