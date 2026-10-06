# PAW Robot Calibration

Closed-loop BLE calibration system for correlating physical sensor readings
with real-world values and validating the simulation model.

## Files

```
tools/calibration/
├── README.md                    this file
├── calibration_receiver.py      Python BLE receiver + analyser
├── robot_calibration/
│   └── robot_calibration.ino   Arduino sketch for the Uno R4 WiFi
└── sessions/                   saved calibration sessions (auto-generated)
```

## How it works

The Arduino sketch runs a fixed sequence of five calibration phases and
streams sensor samples over BLE as JSON lines.  The Python receiver
collects the data, prompts for physical measurements at the right moments,
computes calibration constants, and can optionally write them back to
`engine/sensors/sensor_models.py`.

## Dependencies

**Arduino side:**
- Arduino IDE with the Uno R4 WiFi board package installed
- ArduinoBLE library (install via Library Manager)

**Python side:**
```
pip install bleak
```
`bleak` provides cross-platform BLE GATT access (Windows, macOS, Linux).
No classic Bluetooth pairing or COM port is needed.

## Sensor placement (EthologyBot V2)

Sensor geometry is defined in `robots/ethology_v2.json`.
All positions are relative to the drive axle midpoint (centre of robot).
Angles: 0° = straight forward, positive = left, negative = right.

**Chassis:** regular octagon, 155mm bounding square, 64mm sides.

| Sensor         | Pin | X from centreline | Y from axle | Angle       |
|----------------|-----|-------------------|-------------|-------------|
| leftProx       | A0  | 54.8mm left       | 54.8mm fwd  | 45° left    |
| rightProx      | A1  | 54.8mm right      | 54.8mm fwd  | 45° right   |
| leftLight      | A2  | 54.8mm left       | 54.8mm fwd  | 45° left    |
| rightLight     | A3  | 54.8mm right      | 54.8mm fwd  | 45° right   |
| frontBump      | D2  | centreline        | 87.5mm fwd  | 0° (forward)|

IR and LDR sensors are mounted at the midpoints of the two front diagonal
edges of the octagon, flush with the chassis surface.  The bumper is on the
centreline, protruding 10mm beyond the front edge.

**Consequences for calibration setup:**

1. **Phase 3 (approach-to-contact):** Sensors are angled 45° outward.
   A wall directly ahead registers as X / cos(45°) ≈ X × 1.414 cm along
   the sensor ray.  The analyser accounts for this — enter the perpendicular
   distance from the robot front edge to the wall.  Do not compensate manually.
   Aim the robot squarely at the wall centre so both sensors are equidistant.

2. **Phase 4 (LDR calibration):** Place the light source on the centreline
   directly ahead.  Both LDR sensors are angled 45° outward, so a centred
   light gives the symmetric baseline — the gradient calibration relies on
   off-axis positioning which you will observe naturally during experiment runs.

3. **Single bumper:** The front bumper is on the centreline (pin D2).
   Both `leftFrontBump` and `rightFrontBump` in the code read pin 2 — the
   robot detects contact but cannot distinguish left from right until a
   second bumper is added.

## Physical setup

Before running, you will need:
1. A flat wall the robot can drive into squarely (Phase 3 and 5)
2. A ruler or tape measure — measure from the **front of the robot body**
   to the wall surface (perpendicular distance)
3. A light source at a known position (Phase 4) — place it on the centreline
   directly in front of the robot
4. The wheel radius of your robot in mm — measure from the axle centre to
   the tyre contact patch (not the outer edge of the wheel)

Edit `WHEEL_RADIUS_MM` in `robot_calibration.ino` before flashing.

## Running the calibration

### Step 0 — Tune servo neutral (first time only)

Continuous rotation servos stop at a specific PWM pulse width, which the
Servo library maps to an angle. The standard neutral is 90° but individual
servos vary. If `halt()` causes slow drift after flashing:

1. Note which direction the drift goes (forward or backward)
2. Open `robot_calibration/robot_calibration.ino`
3. Find `static const int NEUTRAL_ANGLE = 90;` near the top
4. Increase by 1–2 if drifting backward, decrease if drifting forward
5. Reflash and test until both servos stop cleanly on halt

Your Sweep test showed the dead zone is 80–100°. If 90° drifts backward,
try 93 or 95 first.

### Step 1 — Flash the Arduino

Open `tools/calibration/robot_calibration/robot_calibration.ino` in the Arduino IDE.
Install the ArduinoBLE library if not already present:
  Sketch → Include Library → Manage Libraries → search "ArduinoBLE"

Flash to the Uno R4 WiFi.  The board will advertise as `PAW-Calibration`.

### Step 2 — Run the Python receiver

No pairing is required.  `bleak` connects directly over BLE GATT.

```bash
# From the project root:
python tools/calibration/calibration_receiver.py --port "PAW-Calibration"

# On Linux, use the BLE MAC address if name scan is unreliable:
python tools/calibration/calibration_receiver.py --port "AA:BB:CC:DD:EE:FF"
```

The script scans for the device (5 second window), connects, and waits
for you to confirm the start distance before sending the start command.

### Step 3 — Follow the prompts

- **Before start:** confirm the Phase 3 start distance (default 60cm)
- **After Phase 1 ends:** enter the number of wheel rotations you counted
- **Before Phase 5:** enter the second start distance
- **During Phase 4:** move the light source to known distances — the script
  will ask you to enter which burst corresponds to which distance afterward

### Step 4 — Review the results

The analyser prints:
- Wheel speed in mm/s at the cruise proportion
- IR raw values at known distances
- Suggested `RAW_MIN` / `RAW_MAX` for `engine/sensors/sensor_models.py`
- Cross-validation error between predicted and actual contact time

Results are saved to `tools/calibration/sessions/results_YYYYMMDD_HHMMSS.json`.

### Step 5 — Apply calibration constants

```bash
# Dry run first (default — shows what would change):
python tools/calibration/calibration_receiver.py \
    --load tools/calibration/sessions/session_YYYYMMDD_HHMMSS.json

# Apply to engine/sensors/sensor_models.py:
python tools/calibration/calibration_receiver.py \
    --load tools/calibration/sessions/session_YYYYMMDD_HHMMSS.json \
    --patch
```

## What the phases measure

| Phase | Motion | Measures |
|-------|--------|----------|
| 1 | Spin in place | Servo proportion → wheel speed (mm/s) |
| 2 | Straight, open space | IR baseline at maximum range |
| 3 | Approach wall from 60cm | Full IR raw vs distance curve |
| 4 | Stationary | LDR raw vs light distance |
| 5 | Approach wall from Xcm | Cross-validation of wheel speed + IR |

## Interpreting the results

**RAW_MIN / RAW_MAX:** The Sharp IR sensor's raw ADC at 18cm (close) and
60cm (far).  The simulation uses these in `engine/sensors/sensor_models.py`
to scale `IRSensor`.  If your robot's values differ from the defaults
(120 / 720), the `--patch` flag updates them automatically.

**Wheel speed:** The simulation uses `max_speed = 0.25 m/s`.  If your
measured speed differs significantly, update `_CRUISE_SPEED_MS` in
`engine/hal/ethology_robot.py`.

**Threshold distance:** The receiver reports the physical distance at which
`proximityThreshold()` fires given the current `PROX_THRESHOLD = 35`.
If this doesn't match where you want avoidance to start, adjust
`PROX_THRESHOLD` in `engine/hal/ethology_robot.py`.
