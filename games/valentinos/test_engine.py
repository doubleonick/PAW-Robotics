"""
valentinos/test_engine.py
--------------------------
Unit tests for the analog signal engine.
No pygame, no display — pure logic.

Run with:
    python test_engine.py
"""

import math
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.signals import Connection, Neuron
from engine.vehicle import (
    VehicleConfig, VehicleEvaluator, SensorReadings, MotorCommand
)
from engine.robot_body import (
    ir_reading, ldr_reading, RobotState, WHEEL_TRACK,
    IR_CONFIGS, LDR_MOUNTS
)

# ── Test infrastructure ────────────────────────────────────────────────────────

_passed = _failed = 0

def check(label, condition, detail=""):
    global _passed, _failed
    icon = "✓" if condition else "✗ FAIL"
    print(f"  {icon}  {label}")
    if detail and not condition:
        print(f"       {detail}")
    if condition: _passed += 1
    else:         _failed += 1

def section(title):
    print(f"\n[{title}]")

def near(a, b, tol=1e-4):
    return abs(a - b) <= tol

# ── IR sensor model ────────────────────────────────────────────────────────────

def test_ir_model():
    section("IR sensor model")
    check("full scale at 4in (0.102m)",    near(ir_reading(0.102), 1.0, 0.01))
    check("below 4in → 1.0",              ir_reading(0.05) == 1.0)
    check("at 18in → 0.1",                near(ir_reading(0.457), 0.1, 0.05))
    check("beyond 18in → 0.0",            ir_reading(0.5) == 0.0)
    check("at 0 → 1.0",                   ir_reading(0.0) == 1.0)
    check("monotonically decreasing",
          ir_reading(0.05) >= ir_reading(0.15) >= ir_reading(0.30))

# ── LDR sensor model ───────────────────────────────────────────────────────────

def test_ldr_model():
    section("LDR sensor model")
    check("bright light → 1.0",    ldr_reading(1.0) == 1.0)
    check("darkness → 0.0",        ldr_reading(0.0) == 0.0)
    check("ambient ~0.3",          near(ldr_reading(0.3), 0.3, 0.01))
    check("gain doubles output",   near(ldr_reading(0.4, gain=2.0), 0.8, 0.01))
    check("clamped at 1.0",        ldr_reading(0.8, gain=2.0) == 1.0)

# ── Neuron continuous output ───────────────────────────────────────────────────

def test_neuron_N():
    section("Neuron continuous output (N)")
    n = Neuron(index=1)

    n.evaluate(excitatory=0.5, inhibitory=0.0, dt=0.05)
    check("exc=0.5 inh=0 → N=0.5",        near(n.N, 0.5))

    n.evaluate(excitatory=1.5, inhibitory=0.0, dt=0.05)
    check("exc=1.5 → N clamped at 1.0",   near(n.N, 1.0))

    n.evaluate(excitatory=0.0, inhibitory=0.5, dt=0.05)
    check("inh > exc → N clamped at 0.0", near(n.N, 0.0))

    n.bias = 0.3
    n.evaluate(excitatory=0.0, inhibitory=0.0, dt=0.05)
    check("bias=0.3 with no inputs → N=0.3", near(n.N, 0.3))

    n.bias = -1.0
    n.evaluate(excitatory=0.5, inhibitory=0.0, dt=0.05)
    check("bias=-1.0 + exc=0.5 → N=0.0",  near(n.N, 0.0))

# ── Neuron threshold output ────────────────────────────────────────────────────

def test_neuron_T():
    section("Neuron threshold output (T) timing")
    n = Neuron(index=1, has_threshold=True)

    # sum=1.0 → should turn ON after 0.2s
    # Tick in 0.05s steps — need 4 ticks to reach 0.2s
    for _ in range(3):
        n.evaluate(1.0, 0.0, dt=0.05)
    check("T still OFF before 0.2s (3×0.05=0.15s)", n.T == 0.0)
    n.evaluate(1.0, 0.0, dt=0.06)
    check("T turns ON after ~0.2s total",             n.T == 1.0)

    # sum=0 → should turn OFF after 0.2s
    n.reset()
    n.evaluate(1.0, 0.0, dt=0.25)   # force ON quickly
    check("T is ON after strong excitation",  n.T == 1.0)
    n.evaluate(0.0, 0.0, dt=0.15)
    check("T still ON at 0.15s with sum=0",   n.T == 1.0)
    n.evaluate(0.0, 0.0, dt=0.06)
    check("T turns OFF after ~0.2s",          n.T == 0.0)

def test_neuron_T_speed():
    section("Neuron threshold timing speed")
    # sum=2.0 → turn-on should be twice as fast (0.1s)
    n = Neuron(index=2, has_threshold=True)
    n.evaluate(2.0, 0.0, dt=0.08)
    check("sum=2.0: T still OFF at 0.08s",  n.T == 0.0)
    n.evaluate(2.0, 0.0, dt=0.03)
    check("sum=2.0: T ON after 0.11s total", n.T == 1.0)

    # sum=-1.0 → turn-off twice as fast (0.1s)
    n2 = Neuron(index=3, has_threshold=True)
    n2.evaluate(2.0, 0.0, dt=0.25)  # force ON
    check("forced ON",  n2.T == 1.0)
    n2.evaluate(0.0, 1.0, dt=0.08)  # sum = -1.0 (inhibited)
    check("sum=-1: T still ON at 0.08s",   n2.T == 1.0)
    n2.evaluate(0.0, 1.0, dt=0.03)
    check("sum=-1: T OFF after ~0.1s",     n2.T == 0.0)

def test_neuron_no_threshold():
    section("Neuron without threshold (neurons 5, 6)")
    n = Neuron(index=5, has_threshold=False)
    n.evaluate(0.8, 0.0, dt=0.1)
    check("N=0.8 works normally",  near(n.N, 0.8))
    check("T is 0.0 (not valid)",  n.T == 0.0)

# ── Wire weights ───────────────────────────────────────────────────────────────

def test_wire_weights():
    section("Wire weights (blue=1, green=2, red=3)")
    cfg = VehicleConfig(connections=[
        Connection("RL", "FL", "blue"),
    ])
    ev = VehicleEvaluator(cfg)
    s  = SensorReadings(RL=0.5)
    mc = ev.tick(s, 0.05)
    check("blue 1×: RL=0.5 → FL=0.5 → left=0.5",  near(mc.left, 0.5))

    cfg2 = VehicleConfig(connections=[Connection("RL", "FL", "green")])
    ev2  = VehicleEvaluator(cfg2)
    mc2  = ev2.tick(s, 0.05)
    check("green 2×: RL=0.5 → FL=1.0 → left=1.0", near(mc2.left, 1.0))

    cfg3 = VehicleConfig(connections=[Connection("RL", "FL", "red")])
    ev3  = VehicleEvaluator(cfg3)
    mc3  = ev3.tick(s, 0.05)
    check("red 3×: RL=0.5 → FL clamped=1.0",       near(mc3.left, 1.0))

# ── Classical Braitenberg vehicles ─────────────────────────────────────────────

def test_vehicle_2a_cowardice():
    """
    Vehicle 2a — Cowardice (ipsilateral excitatory).
    PL → FL (left light → left motor speed up)
    PR → FR (right light → right motor speed up)
    Robot turns AWAY from light and accelerates.
    """
    section("Vehicle 2a — Cowardice (ipsilateral excitatory, LDR)")
    cfg = VehicleConfig(connections=[
        Connection("PL", "FL", "blue"),
        Connection("PR", "FR", "blue"),
    ])
    ev = VehicleEvaluator(cfg)

    # Light on the left → PL > PR → left motor faster → turns right (away)
    s = SensorReadings(PL=0.8, PR=0.3)
    mc = ev.tick(s, 0.05)
    check("left light: left motor > right motor",  mc.left > mc.right)
    check("both motors positive (moving)",         mc.left > 0 and mc.right > 0)

def test_vehicle_2b_aggression():
    """
    Vehicle 2b — Aggression (contralateral excitatory).
    PL → FR, PR → FL
    Robot turns TOWARD light and accelerates.
    """
    section("Vehicle 2b — Aggression (contralateral excitatory, LDR)")
    cfg = VehicleConfig(connections=[
        Connection("PL", "FR", "blue"),
        Connection("PR", "FL", "blue"),
    ])
    ev = VehicleEvaluator(cfg)

    # Light on the left → PL > PR → FR faster → turns left (toward light)
    s  = SensorReadings(PL=0.8, PR=0.3)
    mc = ev.tick(s, 0.05)
    check("left light: right motor > left motor",  mc.right > mc.left)

def test_vehicle_3a_love():
    """
    Vehicle 3a — Love (ipsilateral inhibitory via neuron).
    PL → I_N1, bias → N1 → FL
    More light → inhibited → slower → turns toward light, stops near it.
    Simplified: direct inhibitory wiring PL → BL (backward left)
    Effect: more left light → left motor slows → turns left (toward light).
    """
    section("Vehicle 3a — Love (ipsilateral inhibitory)")
    # Simplified love: PL inhibits left forward motion
    # High PL → BL signal → net left = FL - BL reduced
    cfg = VehicleConfig(connections=[
        Connection("PL", "BL", "blue"),   # left light inhibits left forward
        Connection("PR", "BR", "blue"),   # right light inhibits right forward
    ])
    # Add constant forward drive via bias on a neuron routed to FL/FR
    # For simplicity, set a fixed base forward drive using neuron bias
    cfg2 = VehicleConfig(
        connections=[
            Connection("N1", "FL", "blue"),
            Connection("N1", "FR", "blue"),
            Connection("PL", "BL", "blue"),
            Connection("PR", "BR", "blue"),
        ],
        neuron_biases={"N1": 0.7},   # constant forward drive ~0.7
    )
    ev = VehicleEvaluator(cfg2)

    # Light on the left → PL high → BL high → net left reduced
    s  = SensorReadings(PL=0.6, PR=0.1)
    mc = ev.tick(s, 0.05)
    check("left light: left net < right net (turns toward light)",
          mc.left < mc.right)

def test_motor_forward_backward():
    section("Motor forward/backward subtraction")
    cfg = VehicleConfig(connections=[
        Connection("RL", "FL", "blue"),
        Connection("RL", "BL", "blue"),   # same signal to both
    ])
    ev = VehicleEvaluator(cfg)
    s  = SensorReadings(RL=0.8)
    mc = ev.tick(s, 0.05)
    check("FL=BL=0.8 → net left = 0.0",  near(mc.left, 0.0))

def test_neuron_chain():
    section("Neuron feeding neuron (N1 → E2 → N2 → FL)")
    cfg = VehicleConfig(connections=[
        Connection("RL", "E1", "blue"),   # RL excites N1
        Connection("N1", "E2", "blue"),   # N1 excites N2
        Connection("N2", "FL", "blue"),   # N2 drives left motor
    ])
    ev = VehicleEvaluator(cfg)
    s  = SensorReadings(RL=0.6)
    mc = ev.tick(s, 0.05)
    # RL=0.6 → N1≈0.6 → N2≈0.6 → FL≈0.6 → left≈0.6
    check("RL → N1 → N2 → FL chain works",  near(mc.left, 0.6, tol=0.05))
    check("right motor zero (no wiring)",    near(mc.right, 0.0))

def test_gain():
    section("GAIN trimpot scaling")
    cfg = VehicleConfig(
        connections=[Connection("RL", "FL", "blue")],
        gain=0.5)
    ev  = VehicleEvaluator(cfg)
    s   = SensorReadings(RL=1.0)
    mc  = ev.tick(s, 0.05)
    check("gain=0.5: RL=1.0 → left=0.5",  near(mc.left, 0.5))

def test_validation():
    section("VehicleConfig validation")
    cfg = VehicleConfig(connections=[
        Connection("RL", "FL", "blue"),
        Connection("INVALID", "FL", "blue"),
        Connection("RL", "BADSINK", "blue"),
    ])
    errors = cfg.validate()
    check("two errors detected",               len(errors) == 2)
    check("bad source caught",
          any("INVALID" in e for e in errors))
    check("bad dest caught",
          any("BADSINK" in e for e in errors))

# ── Physics ────────────────────────────────────────────────────────────────────

def test_physics_straight():
    section("Robot physics — straight line")
    r = RobotState(x=0.0, y=0.0, heading=0.0)
    for _ in range(20):
        r.step(1.0, 1.0, dt=0.05)
    check("moved forward in x",    r.x > 0.2)
    check("stayed on y=0 line",    abs(r.y) < 0.001)
    check("heading unchanged",     abs(r.heading) < 0.001)

def test_physics_turn():
    section("Robot physics — turning")
    r = RobotState(x=0.0, y=0.0, heading=0.0)
    # Right motor faster → turn left
    for _ in range(20):
        r.step(0.0, 1.0, dt=0.05)
    check("turned left (heading > 0)",   r.heading > 0.5)

def test_sensor_world_pos():
    section("Sensor world position transform")
    r  = RobotState(x=0.0, y=0.0, heading=0.0)
    rl_mount = IR_CONFIGS["standard"][0]   # left IR
    wx, wy, wa = r.sensor_world_pos(rl_mount)
    check("sensor forward of axle",  wx > 0)
    check("left sensor is left",     wy > 0)

# ── Recording ──────────────────────────────────────────────────────────────────

def test_recording():
    section("Recording and playback")
    import tempfile, os
    from engine.recorder import Recorder, load_recording
    from engine.vehicle import MotorCommand

    r = Recorder()
    r.start()
    state = RobotState(0.1, 0.2, 0.3)
    sigs  = {"RL": 0.5, "N1": 0.3}
    mc    = MotorCommand(0.6, 0.4)

    for i in range(5):
        state.x += 0.01
        r.record(state, sigs, mc)

    r.stop()
    check("5 frames recorded",     len(r.frames) == 5)
    check("duration > 0",          r.duration > 0)

    with tempfile.NamedTemporaryFile(suffix=".vvrec", delete=False, mode='w') as f:
        path = f.name
    r.save(path)
    check("file created",          os.path.exists(path))

    frames = load_recording(path)
    check("5 frames loaded back",  len(frames) == 5)
    check("signals preserved",     frames[0].signals.get("RL") == 0.5)
    check("motors preserved",      near(frames[0].motors[0], 0.6))
    os.unlink(path)

# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_ir_model()
    test_ldr_model()
    test_neuron_N()
    test_neuron_T()
    test_neuron_T_speed()
    test_neuron_no_threshold()
    test_wire_weights()
    test_vehicle_2a_cowardice()
    test_vehicle_2b_aggression()
    test_vehicle_3a_love()
    test_motor_forward_backward()
    test_neuron_chain()
    test_gain()
    test_validation()
    test_physics_straight()
    test_physics_turn()
    test_sensor_world_pos()
    test_recording()

    print(f"\n{'='*45}")
    print(f"  Results: {_passed} passed,  {_failed} failed")
    print(f"{'='*45}\n")
    sys.exit(0 if _failed == 0 else 1)
