"""
engine/hal/ethology_robot.py
------------------------------
Python simulation of EthologyRobot — faithfully mirrors EthologyRobot.cpp/h
from ethologyPrototypeV2 so simulation and physical robot produce identical
behaviour for identical sensor inputs.

Sensor scaling (matches physical CogProximity/CogLight):
  CogProximity.getData()  → clamp raw [120,720] → map to [60,18] cm
                            closer object = SMALLER number
  CogLight.getData()      → map raw [0,1023] → [0,100]
                            brighter = LARGER number

Thresholds (match EthologyRobot.h constants):
  PROX_THRESHOLD  = 35 cm   (proximity met if getData() <= 35)
  LIGHT_THRESHOLD = 15       (gradient met if abs(R-L) >= 15)
  COLL_THRESHOLD  = 1        (collision met if getData() == 0)

Target hierarchy for robots A and B:
  escape_front → avoid_object → seek_light → cruise_straight

driveProportional(left, right, duration):
  Matches physical CogServo.cpp / Robot.cpp convention.
  duration > 0 on physical robot causes blocking delay();
  in simulation the call is non-blocking — the simulation tick
  rate determines effective duration.
"""

from __future__ import annotations
from typing import Any


# ── Constants — mirror EthologyRobot.h ───────────────────────────────────────

PROX_THRESHOLD  = 15    # cm — getData() <= this means object present
LIGHT_THRESHOLD = 10    # getData() units — abs gradient to trigger light beh.
COLL_THRESHOLD  = 1     # collision met when getData() == 0 (INPUT_PULLUP logic)


class EthologyRobot:
    """
    Python equivalent of EthologyRobot (ethologyPrototypeV2).

    Sensors are public attributes matching the C++ layout:
        rightProx, leftProx       (CogProximity on A1, A0)
        rightLight, leftLight     (CogLight on A3, A2)
        rightFrontBump            (CogCollision on pin 2)
        leftFrontBump             (CogCollision on pin 4)

    Cached sensor reads (filled by threshold checks, used by behaviors):
        _lightGradient            int: rightLight.getData() - leftLight.getData()
        _leftFrontBumpData        int: 0 or 1
        _rightFrontBumpData       int: 0 or 1
    """

    def __init__(self, servo=None):
        from engine.hal.sketch_bridge import (
            CogServo, CogProximity, CogLight, CogCollision
        )

        self._servo = servo if servo is not None else CogServo()

        # Public sensor members — match C++ public layout exactly
        self.rightProx      = CogProximity("A1")
        self.leftProx       = CogProximity("A0")
        self.rightLight     = CogLight("A3")
        self.leftLight      = CogLight("A2")
        self.rightFrontBump = CogCollision(2)
        self.leftFrontBump  = CogCollision(4)

        # Cached values set by threshold checks
        self._lightGradient      = 0
        self._leftFrontBumpData  = 1   # INPUT_PULLUP default = 1 (not pressed)
        self._rightFrontBumpData = 1

        # Escape timing
        self._escape_start = 0
        self._escape_dir   = 1    # +1 right, -1 left
        self._in_escape    = False

    def begin(self, left_channel: int = 6,
              right_channel: int = 5) -> None:
        """
        Mirror Robot::begin() — initialise drivetrain.

        When the sketch passes an external servo (the common pattern:
          CogServo driveServos;
          EthologyRobot bot(driveServos);
          driveServos.begin(0, 1);   // sketch sets pins
          bot.begin();               // this call — servo already begun
        ) we skip re-initialising _servo so the sketch's pin assignment
        is preserved.  The sentinel is _left_pin already being set.
        """
        if getattr(self._servo, "_left_pin", None) is None:
            self._servo.begin(left_channel, right_channel)

    # ── Sensor threshold checks ───────────────────────────────────────────────
    # Each caches sensor readings for use by the corresponding behavior.
    # Order matches EthologyRobot.cpp exactly.

    def proximityThreshold(self) -> bool:
        """True if either proximity sensor reports object within PROX_THRESHOLD cm."""
        return (self.rightProx.getData() <= PROX_THRESHOLD or
                self.leftProx.getData()  <= PROX_THRESHOLD)

    def lightGradientThreshold(self) -> bool:
        """
        True if left/right light sensors differ by >= LIGHT_THRESHOLD.
        Caches _lightGradient = rightLight - leftLight.
        """
        self._lightGradient = (self.rightLight.getData() -
                               self.leftLight.getData())
        return abs(self._lightGradient) >= LIGHT_THRESHOLD

    def collisionThreshold(self) -> bool:
        """
        True if either front bumper is pressed.

        On the physical robot: reads INPUT_PULLUP pins (0=pressed).
        In simulation: reads PyBullet contact state set by notify_contact().

        We read the HAL pins first; if they report contact, use that.
        If the HAL pins report no contact but notify_contact() has set
        the cache (PyBullet collision detected), use the cached value.
        This ensures both physical and simulation paths work correctly.
        """
        hal_left  = self.leftFrontBump.getData()
        hal_right = self.rightFrontBump.getData()
        if hal_left == 0 or hal_right == 0:
            # Physical robot: bumper pin actually pressed
            self._leftFrontBumpData  = hal_left
            self._rightFrontBumpData = hal_right
        # else: keep cached values set by notify_contact() (simulation)
        return (self._leftFrontBumpData == 0 or
                self._rightFrontBumpData == 0)

    # Public camelCase aliases used by generated sketches
    def proximity_threshold_met(self)     -> bool: return self.proximityThreshold()
    def light_gradient_met(self)          -> bool: return self.lightGradientThreshold()
    def front_contact_met(self)           -> bool: return self.collisionThreshold()
    def rear_contact_met(self)            -> bool: return False  # no rear bumpers

    def notify_contact(self) -> None:
        """
        Called by the simulation when a physics body collision is detected.
        Sets both front bumper caches to 0 (pressed).
        """
        self._leftFrontBumpData  = 0
        self._rightFrontBumpData = 0

    def clear_contact(self) -> None:
        """
        Reset bumper state and set a cooldown so the escape behaviour
        has time to move the robot away from the wall before contact
        can fire again.  Cooldown matches the escape arc duration (0.8s)
        plus a small margin.
        """
        import time as _time
        self._leftFrontBumpData  = 1
        self._rightFrontBumpData = 1
        self._contact_cooldown_until = _time.monotonic() + 1.0

    # ── Behaviours ────────────────────────────────────────────────────────────
    # Mirror EthologyRobot.cpp behavior methods exactly.
    # driveProportional(left, right, duration) — duration is blocking on hardware;
    # in simulation the tick rate controls effective duration.

    def avoidObject(self) -> None:
        """Arc away from the nearer proximity sensor."""
        rp = self.rightProx.getData()
        lp = self.leftProx.getData()
        if rp <= PROX_THRESHOLD and lp <= PROX_THRESHOLD:
            if rp <= lp:
                self._servo.driveProportional(-40, 40, 0.3)
            else:
                self._servo.driveProportional(40, -40, 0.3)
        elif rp <= PROX_THRESHOLD:
            self._servo.driveProportional(-40, 40, 0.3)
        elif lp <= PROX_THRESHOLD:
            self._servo.driveProportional(40, -40, 0.3)
        else:
            self.cruiseStraight()

    def approachObject(self) -> None:
        """Arc toward the nearer proximity sensor."""
        if self.rightProx.getData() >= PROX_THRESHOLD:
            self._servo.driveProportional(40, 60, 0.1)
        elif self.leftProx.getData() >= PROX_THRESHOLD:
            self._servo.driveProportional(60, 40, 0.1)

    def approachLight(self) -> None:
        """
        Spin toward the brighter light sensor using cached gradient.
        gradient = rightLight - leftLight  (positive = light is to the right)
        With CogServo negation:
          driveProportional(40,-40) = left FWD, right BWD = spin RIGHT
          driveProportional(-40,40) = left BWD, right FWD = spin LEFT
        """
        if self._lightGradient >= LIGHT_THRESHOLD:
            # Light on right → spin right
            self._servo.driveProportional(40, -40, 0.3)
        elif self._lightGradient <= -LIGHT_THRESHOLD:
            # Light on left → spin left
            self._servo.driveProportional(-40, 40, 0.3)
        else:
            self.cruiseStraight()

    def avoidLight(self) -> None:
        """
        Spin away from the brighter light sensor using cached gradient.
        gradient = rightLight - leftLight  (positive = light is to the right)
        With CogServo negation:
          driveProportional(-40,40) = left BWD, right FWD = spin LEFT (away from right)
          driveProportional(40,-40) = left FWD, right BWD = spin RIGHT (away from left)
        """
        if self._lightGradient >= LIGHT_THRESHOLD:
            # Light on right → spin left (away from it)
            self._servo.driveProportional(-40, 40, 0.3)
        elif self._lightGradient <= -LIGHT_THRESHOLD:
            # Light on left → spin right (away from it)
            self._servo.driveProportional(40, -40, 0.3)
        else:
            self.cruiseStraight()

    def escapeFrontCollision(self) -> None:
        """
        Arc backward away from the bumped side.

        CogServo::driveProportional negates both proportions before
        mapping to servo angle, so the effective direction is inverted
        from what the values suggest naively.  The commands below are
        calibrated for the physical robot with negation applied:

          driveProportional(-60,-60) -> both wheels backward (reverse)
          driveProportional(-60,-30) -> left faster back, right slower back
                                        -> arc backward to the RIGHT
          driveProportional(-30,-60) -> left slower back, right faster back
                                        -> arc backward to the LEFT
        """
        if self._leftFrontBumpData == 0:
            # left side hit → arc backward to the right
            self._servo.driveProportional(-60, -30, 0.8)
        elif self._rightFrontBumpData == 0:
            # right side hit → arc backward to the left
            self._servo.driveProportional(-30, -60, 0.8)
        else:
            # both bumped (simulation generic contact) → arc back-right
            self._servo.driveProportional(-60, -30, 0.8)
        self.clear_contact()

    def escalateFrontCollision(self) -> None:
        """Back up then ram forward."""
        self._servo.driveProportional(-50, -50, 0.2)
        self._servo.driveProportional(100, 100, 0.1)

    def cruiseStraight(self) -> None:
        self._servo.driveProportional(60, 60, 0.1)

    def cruiseLeftArc(self) -> None:
        self._servo.driveProportional(30, 50, 0.1)

    def cruiseRightArc(self) -> None:
        self._servo.driveProportional(50, 30, 0.1)

    # Public aliases matching generated sketch method names
    def escape_front(self)   -> None: self.escapeFrontCollision()
    def avoid_object(self)   -> None: self.avoidObject()
    def seek_light(self)     -> None: self.approachLight()
    def avoid_light(self)    -> None: self.avoidLight()
    def cruise_straight(self)-> None: self.cruiseStraight()
    def cruise_arc(self)     -> None: self.cruiseLeftArc()

    # ── Hierarchy ─────────────────────────────────────────────────────────────

    def hierarchy(self) -> None:
        """
        Default subsumption hierarchy: escape → avoid → seek_light → cruise.
        Mirrors the target hierarchy for robots A and B.
        Generated sketches call individual methods instead of this.
        """
        if self.collisionThreshold():
            self.escapeFrontCollision()
        elif self.proximityThreshold():
            self.avoidObject()
        elif self.lightGradientThreshold():
            self.approachLight()
        else:
            self.cruiseStraight()

    # ── HUD / debug ───────────────────────────────────────────────────────────

    def get_state_label(self) -> str:
        rp = self.rightProx.getData()
        lp = self.leftProx.getData()
        rl = self.rightLight.getData()
        ll = self.leftLight.getData()
        lf = self._leftFrontBumpData
        rf = self._rightFrontBumpData
        if lf == 0 or rf == 0:
            side = "L" if lf == 0 else "R"
            return f"ESCAPE  {side} front"
        if rp <= PROX_THRESHOLD or lp <= PROX_THRESHOLD:
            return f"AVOID  R={rp}cm L={lp}cm"
        if abs(rl - ll) >= LIGHT_THRESHOLD:
            return f"SEEK_LIGHT  R={rl} L={ll} Δ={rl-ll}"
        return f"CRUISE  R={rp}cm L={lp}cm"

    def get_hud_info(self):
        from engine.renderer.hud import HUDInfo, SensorBar
        rp = self.rightProx.getData()
        lp = self.leftProx.getData()
        rl = self.rightLight.getData()
        ll = self.leftLight.getData()
        lf = self.leftFrontBump.getData()
        rf = self.rightFrontBump.getData()

        if lf == 0 or rf == 0:
            behavior = "ESCAPE"
            side = "Left" if lf == 0 else "Right"
            trigger = f"{side} front contact"
        elif rp <= PROX_THRESHOLD or lp <= PROX_THRESHOLD:
            behavior = "AVOID"
            side = "Right" if rp <= lp else "Left"
            val  = rp if rp <= lp else lp
            trigger = f"{side} prox: {val}cm ≤ {PROX_THRESHOLD}cm"
        elif abs(rl - ll) >= LIGHT_THRESHOLD:
            behavior = "SEEK_LIGHT"
            trigger = f"light gradient: R={rl} L={ll} Δ={rl-ll}"
        else:
            behavior = "CRUISE"
            trigger = "no threshold exceeded"

        sensors = [
            SensorBar("Prox R",   rp, PROX_THRESHOLD,  18, 60,
                      triggered=(rp <= PROX_THRESHOLD), higher_bad=False),
            SensorBar("Prox L",   lp, PROX_THRESHOLD,  18, 60,
                      triggered=(lp <= PROX_THRESHOLD), higher_bad=False),
            SensorBar("Light R",  rl, 50,               0, 100,
                      triggered=False),
            SensorBar("Light L",  ll, 50,               0, 100,
                      triggered=False),
            SensorBar("Front R",  1 - rf, 0.5,          0,  1,
                      triggered=(rf == 0)),
            SensorBar("Front L",  1 - lf, 0.5,          0,  1,
                      triggered=(lf == 0)),
        ]

        return HUDInfo(
            behavior=behavior, trigger=trigger, sensors=sensors,
            robot_label=getattr(self, "_robot_label", ""),
            robot_color=getattr(self, "_robot_color", (60, 160, 230))
        )
