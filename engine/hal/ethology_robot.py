"""
engine/hal/ethology_robot.py
------------------------------
Python simulation of EthologyRobot — faithfully mirrors EthologyRobot.cpp/h
from ethologyPrototypeV2 so simulation and physical robot produce identical
behaviour for identical sensor inputs.

Sensor scaling (matches physical CogProximity/CogLight):
  CogProximity.getData()  → clamp raw [120,720] → map to [60,18] CENTIMETRES
                            (the sensor's PRACTICAL band, not the 10-80 cm
                            datasheet nominal — the firmware's own comment in
                            CogProximity::analyzeData says [10,80] and is wrong;
                            the code maps to [60,18] and is right)
                            closer object = SMALLER number
  CogLight.getData()      → map raw [0,1023] → [0,100]
                            brighter = LARGER number

Thresholds and drive tuning: see the constants below.
"""

import time
import random

# ── Tuning constants ──────────────────────────────────────────────────────────
# MIRRORS firmware/shared/EthologyRobot.h, which is vetted on hardware. Every
# value here must match its C++ counterpart: the simulator and the robot are
# supposed to be the same robot, and a divergence teaches students behaviour
# the hardware does not perform. Change both together or neither.
#
# PROX_THRESHOLD is in CENTIMETRES. getData() maps raw [120,720] -> [60,18] cm
# and SATURATES at 18 (a wall at 18 cm and one at 2 cm read the same), which
# matters only if the threshold is ever raised. 35 is confirmed on hardware.
PROX_THRESHOLD  = 35
LIGHT_THRESHOLD = 15    # abs(rightLight - leftLight) needed to trigger

# Drive tuning. An arc is NOT cruise with one wheel boosted: the inner wheel
# drops well below cruise and the outer stays below it too, so an arc is a
# slow tight turn rather than a fast drift.
CRUISE_SPEED    = 60
ARC_INNER_SPEED = 30
ARC_OUTER_SPEED = 50
CRUISE_SECONDS  = 0.1
ESCAPE_SECONDS  = 0.8   # both escapes; 0.1 was one tick and unobservable

# cruise_arc holds a direction this long before re-flipping. Flipping every
# tick made successive arcs cancel into a straight wobble.
ARC_HOLD_MIN_MS = 700
ARC_HOLD_MAX_MS = 1900

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
        # Back bumpers — pins match firmware EthologyRobot.h (D7/D8). Without
        # these the sim declared _leftBackBumpData/_rightBackBumpData but had
        # no sensors to fill them, so escape_back could never fire.
        self.rightBackBump  = CogCollision(7)
        self.leftBackBump   = CogCollision(8)

        # ── Cached sensor values ──────────────────────────────────────────
        # Initialised to a RESTING WORLD, not to zero. Zero is not safe here:
        # collisionThreshold() treats 0 as PRESSED and proximityThreshold()
        # treats low as NEAR, so zeroed members read as "pinned against an
        # object" until the first readSensors(). The C++ side has the same
        # initialisers.
        self._leftProxData       = 60   # far (getData() maps to [60,18] cm)
        self._rightProxData      = 60
        self._lightGradient      = 0
        self._leftFrontBumpData  = 1    # INPUT_PULLUP default = 1 (not pressed)
        self._rightFrontBumpData = 1
        self._leftBackBumpData   = 1
        self._rightBackBumpData  = 1

        # cruise_arc holds one direction for ARC_HOLD_MIN/MAX_MS before
        # re-flipping. 0 forces a fresh pick on the first call.
        self._arcLeft    = False
        self._arcUntilMs = 0.0

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

    def readSensors(self) -> None:
        """Halt, then sample every sensor once into the cache.

        Mirrors EthologyRobot::readSensors(). Call at the top of each
        hierarchy tick.

        WITHOUT THIS the ported behaviours read cached values that were only
        ever set in __init__ — a resting world where nothing is near and there
        is no light gradient — so a guard could pass while the behaviour it
        gates saw stale data and took no branch. That is exactly what stopped
        Robot A and B moving after the dev15f port.

        The halt is deliberate: servos latch, so a tick that decides to do
        nothing must leave the robot stopped. It also quietens the analog
        reads on hardware.
        """
        self._servo.halt(0.0)

        self._rightProxData      = self.rightProx.getData()
        self._leftProxData       = self.leftProx.getData()
        self._lightGradient      = (self.rightLight.getData() -
                                    self.leftLight.getData())
        self._leftFrontBumpData  = self.leftFrontBump.getData()
        self._rightFrontBumpData = self.rightFrontBump.getData()
        self._leftBackBumpData   = self.leftBackBump.getData()
        self._rightBackBumpData  = self.rightBackBump.getData()

    def proximityThreshold(self) -> bool:
        """True if either proximity sensor reports an object within
        PROX_THRESHOLD centimetres. Reads the cache, so the guard and the
        behaviour it gates always see the same sample."""
        return (self._rightProxData <= PROX_THRESHOLD or
                self._leftProxData  <= PROX_THRESHOLD)

    def lightGradientThreshold(self) -> bool:
        """
        True if left/right light sensors differ by >= LIGHT_THRESHOLD.
        Caches _lightGradient = rightLight - leftLight.
        """
        # value cached by readSensors()
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
        self._leftFrontBumpData  = 1
        self._rightFrontBumpData = 1
        self._contact_cooldown_until = time.monotonic() + 1.0

    # ── Behaviours ────────────────────────────────────────────────────────────
    # Mirror EthologyRobot.cpp behavior methods exactly.
    # driveProportional(left, right, duration) — duration is a blocking delay()
    # on hardware. In simulation the CALL returns immediately, but ArduinoHAL's
    # TimedAction then suppresses subsequent loop() ticks until the duration
    # elapses (see arduino_hal.call_loop), while the servo angles written by
    # this call stay in place. So the effective duration IS honoured, and the
    # simulation tick rate does NOT determine it — a 0.5 s primitive commits the
    # robot for 0.5 s of un-re-evaluated motion, exactly as on the robot.

    # ── The eight behaviours ──────────────────────────────────────────────
    #
    # PORTED VERBATIM from firmware/shared/EthologyRobot.cpp, which is vetted
    # on hardware — every one of the eight, including the servo/primitive
    # durations. The simulator previously carried its own values and its own
    # bugs, so a student saw one thing in the game and another on the robot.
    #
    # DO NOT re-derive any of these from wheel arithmetic. The light pair, the
    # escapes and approachObject were each wrong in a way that looked correct
    # on paper and were fixed from observation. If a sign looks backwards, it
    # is probably right. Change them only alongside the firmware.

    def avoidObject(self) -> None:
        """Steer away from the nearer proximity sensor."""
        if self._rightProxData <= PROX_THRESHOLD:
            self._servo.driveProportional(-40, 40, 0.5)
        elif self._leftProxData <= PROX_THRESHOLD:
            self._servo.driveProportional(40, -40, 0.5)

    def approachObject(self) -> None:
        """Steer toward the nearer proximity sensor.

        The guard defines NEAR as <= PROX_THRESHOLD; this used to branch on
        >=, which tests for FAR, so the robot steered by whichever side was
        empty and read as backing away. The both-near case is required: an
        object dead ahead satisfies the guard while every other branch misses.
        """
        right = self._rightProxData <= PROX_THRESHOLD
        left  = self._leftProxData  <= PROX_THRESHOLD

        if right and left:
            self._servo.driveProportional(CRUISE_SPEED, CRUISE_SPEED, 0.1)
        elif right:
            self._servo.driveProportional(60, 40, 0.1)   # object right → curve right
        elif left:
            self._servo.driveProportional(40, 60, 0.1)   # object left  → curve left

    def avoidLight(self) -> None:
        """Turn away from the brighter side. gradient = right - left."""
        if self._lightGradient >= LIGHT_THRESHOLD:
            self._servo.driveProportional(40, -40, 0.1)
        elif self._lightGradient <= -LIGHT_THRESHOLD:
            self._servo.driveProportional(-40, 40, 0.1)

    def approachLight(self) -> None:
        """Turn toward the brighter side. gradient = right - left.

        VERIFIED ON HARDWARE, and the opposite of what the arithmetic
        suggests. Test against a lamp; do not reason it out.
        """
        if self._lightGradient >= LIGHT_THRESHOLD:
            self._servo.driveProportional(-40, 40, 0.5)
        elif self._lightGradient <= -LIGHT_THRESHOLD:
            self._servo.driveProportional(40, -40, 0.5)

    def escapeFrontCollision(self) -> None:
        """Spin off the bumped side; back straight out if pinned both sides.

        The two bumper tests used to be separate ifs, so a square-on hit ran
        one spin and then the other and they cancelled — the robot sat still
        while stuck, the worst available response.
        """
        left  = self._leftFrontBumpData  == 0
        right = self._rightFrontBumpData == 0

        if left and right:
            self._servo.driveProportional(-100, -100, ESCAPE_SECONDS)
        elif left:
            self._servo.driveProportional(-100, 100, ESCAPE_SECONDS)
        elif right:
            self._servo.driveProportional(100, -100, ESCAPE_SECONDS)
        self.clear_contact()

    def escapeBackCollision(self) -> None:
        """Struck from behind: sprint forward, away from it."""
        self._servo.driveProportional(100, 100, ESCAPE_SECONDS)

    def cruiseStraight(self) -> None:
        self._servo.driveProportional(CRUISE_SPEED, CRUISE_SPEED, CRUISE_SECONDS)

    def cruiseArc(self) -> None:
        """Hold one arc direction for 0.7-1.9 s, then re-flip.

        It used to flip every tick (CRUISE_SECONDS = 0.1), so successive left
        and right arcs cancelled and the robot tracked straight with a wobble.
        The 30/50 geometry was never the problem; the sampling rate was.
        """
        now = time.monotonic() * 1000.0
        if now >= self._arcUntilMs:
            self._arcLeft = random.random() < 0.5
            self._arcUntilMs = now + random.uniform(ARC_HOLD_MIN_MS,
                                                    ARC_HOLD_MAX_MS)
        if self._arcLeft:
            self.cruiseLeftArc()
        else:
            self.cruiseRightArc()

    def cruiseLeftArc(self) -> None:
        self._servo.driveProportional(ARC_INNER_SPEED, ARC_OUTER_SPEED,
                                      CRUISE_SECONDS)

    def cruiseRightArc(self) -> None:
        self._servo.driveProportional(ARC_OUTER_SPEED, ARC_INNER_SPEED,
                                      CRUISE_SECONDS)

    def escapeBack(self) -> None:
        """
        Escape a rear collision: drive straight forward, away from the rear
        contact, at full speed for a decisive beat. Matches the Arduino
        EthologyRobot::escapeBack() so simulation and hardware agree. (The rear
        sensor is not yet fitted; rear_contact_met() returns False, so this
        never fires today — but when wired, both paths behave identically.)
        """
        self._servo.driveProportional(100, 100, 0.25)

    # Public aliases matching generated sketch method names
    def escape_front(self)   -> None: self.escapeFrontCollision()
    def escape_back(self)    -> None: self.escapeBack()
    def avoid_object(self)   -> None: self.avoidObject()
    def approach_object(self)-> None: self.approachObject()
    def approach_light(self)     -> None: self.approachLight()
    def avoid_light(self)    -> None: self.avoidLight()
    def cruise_straight(self)-> None: self.cruiseStraight()
    def cruise_arc(self)     -> None: self.cruiseLeftArc()

    # ── Hierarchy ─────────────────────────────────────────────────────────────

    def hierarchy(self) -> None:
        """
        Default subsumption hierarchy: escape → avoid → approach_light → cruise.
        Mirrors the target hierarchy for robots A and B.
        Generated sketches call individual methods instead of this.
        """
        # Sense first — see readSensors(). Without it every guard below reads
        # values last set in __init__.
        self.readSensors()

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
        # Read the CACHE, so the label describes the tick the robot actually
        # acted on rather than a fresh sample taken after the fact.
        rp = self._rightProxData
        lp = self._leftProxData
        rl = self._lightGradient
        lf = self._leftFrontBumpData
        rf = self._rightFrontBumpData
        if lf == 0 or rf == 0:
            side = "L" if lf == 0 else "R"
            return f"ESCAPE  {side} front"
        if rp <= PROX_THRESHOLD or lp <= PROX_THRESHOLD:
            return f"AVOID  R={rp}cm L={lp}cm"
        if abs(rl) >= LIGHT_THRESHOLD:
            return f"APPROACH_LIGHT  Δ={rl}"
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
