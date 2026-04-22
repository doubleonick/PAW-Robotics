# Robot WiFi — Development Kit

End-to-end WiFi communication between a Python game (robosim) and a
WiFi-capable Arduino robot.  Developed in stages so each piece can be
tested independently.

---

## File map

```
wifi_poc/
│
│  ── Arduino firmware ─────────────────────────────────────
├── robot_poc/
│   └── robot_poc.ino           Upload to Arduino for hardware testing
│
│  ── Python development stack ─────────────────────────────
├── mock_robot_server.py        Pretends to be the Arduino (no hardware needed)
├── robot_wifi_client.py        The client class robosim will import
├── test_robot_client.py        Test suite — 35 checks, runs in ~4 seconds
│
│  ── Original POC scripts (keep for reference) ────────────
└── robot_client_poc.py         First-pass throw-away test script
```

---

## Development workflow (no hardware)

### Terminal 1 — start the mock server

```
python mock_robot_server.py
```

Output:
```
=======================================================
  Mock Robot Server
  Listening on http://127.0.0.1:8080
  ...
```

### Terminal 2 — run the test suite

```
python test_robot_client.py
```

Expected: **35 passed, 0 failed**

---

## Switching to real hardware

1. Upload `robot_poc/robot_poc.ino` to the Arduino
   (see board selection comment near the top of the sketch)
2. Connect your laptop WiFi to **ROBOT_AP** (password: `robotpass`)
3. Run tests against the Arduino:

```
python test_robot_client.py --host 192.168.4.1 --port 80
```

Two tests will report ok=False against real hardware (expected):
- `get_state` — no `/state` endpoint on Arduino
- `reset`     — no `/reset` endpoint on Arduino

All other 31 checks should pass identically.

---

## Using the client in your own code

```python
from robot_wifi_client import RobotWiFiClient

client = RobotWiFiClient("127.0.0.1", port=8080)   # mock
# client = RobotWiFiClient("192.168.4.1")           # real Arduino

result = client.ping()
if result["status"] == "busy":
    client.wait_until_idle(timeout=30.0)

result = client.send_hierarchy([
    "escape_front", "avoid_object", "seek_light", "cruise_straight"
])
if result["ok"]:
    token = result["session"]
    # ... game timer runs ...
    client.stop(token)
```

---

## What comes next

- [ ] Arduino dispatch table — parse received hierarchy into function pointers
- [ ] Real behavior execution on the robot
- [ ] STOP triggers motor halt
- [ ] Reveal mode — Arduino streams telemetry; Python renders live HUD
- [ ] Integration into robosim hierarchy_builder_dev.py
