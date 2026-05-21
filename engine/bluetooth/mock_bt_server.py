"""
engine/bluetooth/mock_bt_server.py
-------------------------------------
Mock Bluetooth serial server — structural parallel to mock_robot_server.py.

Impersonates an Arduino running robot_bt_poc.ino over a virtual serial port
pair, so the full Bluetooth integration can be developed without hardware.

Uses a TCP socket to simulate the serial port connection so no virtual
serial port driver is needed.  RobotBTClient connects to this server by
pointing at a loopback address via a thin adapter.

Usage
-----
    # Terminal 1 — start the mock server
    python engine/bluetooth/mock_bt_server.py

    # Terminal 2 — connect with the BT client via TCP adapter
    from engine.bluetooth.mock_bt_server import MockBTAdapter
    client = MockBTAdapter.make_client()   # returns RobotBTClient-compatible object
    print(client.ping())

Wire protocol (identical to real Arduino BT sketch)
----------------------------------------------------
    Client sends: {"cmd": "ping"|"run"|"stop"|"reset"} + optional fields + \\n
    Server sends: JSON response + \\n

Behavior dispatch
-----------------
    Same dispatch_tick() engine as mock_robot_server.py.
    Sensor state injected via "inject" command (development only):
        {"cmd": "inject", "prox_r": 25, "light_l": 80, "bump_l": 0}
"""

import argparse
import json
import socket
import threading
import time
import random
import string

# ── Reuse dispatch engine from WiFi mock ─────────────────────────────────────
# Rather than duplicate, import the core dispatch logic.
# This ensures both transports stay in sync automatically.
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

# ── Inlined from engine/wifi/mock_robot_server.py ──────────────────────────
PROX_THRESHOLD  = 15    # cm — proximityThreshold() fires when getData() <= 15
LIGHT_THRESHOLD = 10    # getData() units — lightGradientThreshold() fires when
class SensorState:
    """
    Sensor values in processed getData() units — matching physical robot output.

    Proximity (rightProx, leftProx):
        Raw ADC clamped [120,720] then mapped [60,18] cm.
        Default 60 cm = nothing nearby.
        Inject via query params: prox_r=<cm>  prox_l=<cm>  (range 18..60)

    Light (rightLight, leftLight):
        Raw ADC [0,1023] mapped to [0,100].
        Default 50 = ambient mid-level.
        Inject via query params: light_r=<0..100>  light_l=<0..100>

    Collision (rightFrontBump, leftFrontBump):
        INPUT_PULLUP logic: 1=not pressed, 0=pressed.
        Default 1 = no collision.
        Inject via query params: bump_r=0|1  bump_l=0|1

    Legacy params (ir=, ldr_l=, ldr_r=, contact_f=) are still accepted
    for backwards compatibility and translated to the new units.
    """
    def __init__(self):
        self.prox_right    = 60    # cm, nothing nearby
        self.prox_left     = 60
        self.light_right   = 50    # 0..100, ambient
        self.light_left    = 50
        self.bump_right    = 1     # INPUT_PULLUP: 1=not pressed
        self.bump_left     = 1

    def update(self, params: dict):
        """Update from query string params (string key → string value)."""
        # Primary params (processed units)
        if "prox_r"   in params: self.prox_right  = int(params["prox_r"])
        if "prox_l"   in params: self.prox_left   = int(params["prox_l"])
        if "light_r"  in params: self.light_right = int(params["light_r"])
        if "light_l"  in params: self.light_left  = int(params["light_l"])
        if "bump_r"   in params: self.bump_right  = int(params["bump_r"])
        if "bump_l"   in params: self.bump_left   = int(params["bump_l"])

        # Legacy params — translate to processed units
        if "ir" in params:
            raw = int(params["ir"])
            clamped = max(120, min(720, raw))
            cm = int(60 - (clamped - 120) / (720 - 120) * (60 - 18))
            self.prox_right = cm
            self.prox_left  = cm
        if "ldr_r" in params:
            self.light_right = int(int(params["ldr_r"]) * 100 / 1023)
        if "ldr_l" in params:
            self.light_left  = int(int(params["ldr_l"]) * 100 / 1023)
        if "contact_f" in params:
            pressed = params["contact_f"] not in ("0", "false", "False")
            self.bump_right = 0 if pressed else 1
            self.bump_left  = 0 if pressed else 1

    def as_dict(self) -> dict:
        return {
            "prox_right":  self.prox_right,
            "prox_left":   self.prox_left,
            "light_right": self.light_right,
            "light_left":  self.light_left,
            "bump_right":  self.bump_right,
            "bump_left":   self.bump_left,
            # Derived convenience fields
            "prox_gradient":  self.prox_right - self.prox_left,
            "light_gradient": self.light_right - self.light_left,
        }



class BehaviorLock:
    def __init__(self):
        self.owner_idx  = -1
        self.until_time = 0.0   # monotonic seconds

    def set(self, owner_idx: int):
        self.owner_idx  = owner_idx
        self.until_time = time.monotonic() + ESCAPE_MS

    def clear(self):
        self.owner_idx  = -1
        self.until_time = 0.0

    @property
    def active(self) -> bool:
        return self.owner_idx >= 0 and time.monotonic() < self.until_time

    @property
    def remaining_ms(self) -> int:
        return max(0, int((self.until_time - time.monotonic()) * 1000))


# Condition functions — mirror EthologyRobot.cpp threshold checks exactly
def cond_front_contact(s: SensorState)  -> bool:
    return s.bump_left == 0 or s.bump_right == 0
def cond_rear_contact(s: SensorState)   -> bool:
    return False   # no rear bumpers on this robot
def cond_proximity(s: SensorState)      -> bool:
    return s.prox_right <= PROX_THRESHOLD or s.prox_left <= PROX_THRESHOLD
def cond_light_gradient(s: SensorState) -> bool:
    return abs(s.light_right - s.light_left) >= LIGHT_THRESHOLD
def cond_always(s: SensorState)         -> bool: return True


# Registry — identical ordering and names to the Arduino sketch
REGISTRY = [
    {"name": "escape_front",    "condition": cond_front_contact,  "timed": True},
    {"name": "escape_rear",     "condition": cond_rear_contact,   "timed": True},
    {"name": "avoid_object",    "condition": cond_proximity,      "timed": False},
    {"name": "approach_object", "condition": cond_proximity,      "timed": False},
    {"name": "seek_light",      "condition": cond_light_gradient, "timed": False},
    {"name": "avoid_light",     "condition": cond_light_gradient, "timed": False},
    {"name": "cruise_straight", "condition": cond_always,         "timed": False},
    {"name": "cruise_arc",      "condition": cond_always,         "timed": False},
]
REGISTRY_BY_NAME = {e["name"]: e for e in REGISTRY}


def dispatch_tick(hierarchy: list[str],
                  sensors:   SensorState,
                  lock:      BehaviorLock) -> dict:
    """
    Run one tick of the hierarchy dispatcher.
    Mirrors run_one_tick() in hierarchy_serial.ino exactly.

    Returns a dict describing what happened:
    {
        "fired":       str | None,    behavior name that fired, or null
        "reason":      str,           human-readable explanation
        "locked":      bool,          was a lock active?
        "lock_owner":  str | None,    name of lock owner if locked
        "lock_remaining_ms": int,     ms left on lock (0 if not locked)
        "skipped":     [str],         behaviors evaluated but not fired
    }
    """
    skipped = []

    # Lock active — owner continues running
    if lock.active:
        owner_name = hierarchy[lock.owner_idx] if lock.owner_idx < len(hierarchy) else None
        return {
            "fired":            owner_name,
            "reason":           "lock active — owner continues",
            "locked":           True,
            "lock_owner":       owner_name,
            "lock_remaining_ms": lock.remaining_ms,
            "skipped":          [],
        }

    # Lock expired — clear it
    if lock.owner_idx >= 0:
        lock.clear()

    # Normal evaluation
    for i, name in enumerate(hierarchy):
        entry = REGISTRY_BY_NAME.get(name)
        if entry is None:
            skipped.append(f"{name} (unknown)")
            continue
        if entry["condition"](sensors):
            if entry["timed"]:
                lock.set(i)
            return {
                "fired":             name,
                "reason":            "condition met",
                "locked":            entry["timed"],
                "lock_owner":        name if entry["timed"] else None,
                "lock_remaining_ms": lock.remaining_ms if entry["timed"] else 0,
                "skipped":           skipped,
            }
        skipped.append(name)

    return {
        "fired":             None,
        "reason":            "no conditions met",
        "locked":            False,
        "lock_owner":        None,
        "lock_remaining_ms": 0,
        "skipped":           skipped,
    }


# ── Server state ─────────────────────────────────────────────────────────────
# Shared across all requests; protected by _lock.


# Condition functions — mirror EthologyRobot.cpp threshold checks exactly
def cond_front_contact(s: SensorState)  -> bool:
    return s.bump_left == 0 or s.bump_right == 0
def cond_rear_contact(s: SensorState)   -> bool:
    return False   # no rear bumpers on this robot
def cond_proximity(s: SensorState)      -> bool:
    return s.prox_right <= PROX_THRESHOLD or s.prox_left <= PROX_THRESHOLD
def cond_light_gradient(s: SensorState) -> bool:
    return abs(s.light_right - s.light_left) >= LIGHT_THRESHOLD
def cond_always(s: SensorState)         -> bool: return True


# Registry — identical ordering and names to the Arduino sketch
REGISTRY = [
    {"name": "escape_front",    "condition": cond_front_contact,  "timed": True},
    {"name": "escape_rear",     "condition": cond_rear_contact,   "timed": True},
    {"name": "avoid_object",    "condition": cond_proximity,      "timed": False},
    {"name": "approach_object", "condition": cond_proximity,      "timed": False},
    {"name": "seek_light",      "condition": cond_light_gradient, "timed": False},
    {"name": "avoid_light",     "condition": cond_light_gradient, "timed": False},
    {"name": "cruise_straight", "condition": cond_always,         "timed": False},
    {"name": "cruise_arc",      "condition": cond_always,         "timed": False},
]
REGISTRY_BY_NAME = {e["name"]: e for e in REGISTRY}


def dispatch_tick(hierarchy: list[str],
                  sensors:   SensorState,
                  lock:      BehaviorLock) -> dict:
    """
    Run one tick of the hierarchy dispatcher.
    Mirrors run_one_tick() in hierarchy_serial.ino exactly.

    Returns a dict describing what happened:
    {
        "fired":       str | None,    behavior name that fired, or null
        "reason":      str,           human-readable explanation
        "locked":      bool,          was a lock active?
        "lock_owner":  str | None,    name of lock owner if locked
        "lock_remaining_ms": int,     ms left on lock (0 if not locked)
        "skipped":     [str],         behaviors evaluated but not fired
    }
    """
    skipped = []

    # Lock active — owner continues running
    if lock.active:
        owner_name = hierarchy[lock.owner_idx] if lock.owner_idx < len(hierarchy) else None
        return {
            "fired":            owner_name,
            "reason":           "lock active — owner continues",
            "locked":           True,
            "lock_owner":       owner_name,
            "lock_remaining_ms": lock.remaining_ms,
            "skipped":          [],
        }

    # Lock expired — clear it
    if lock.owner_idx >= 0:
        lock.clear()

    # Normal evaluation
    for i, name in enumerate(hierarchy):
        entry = REGISTRY_BY_NAME.get(name)
        if entry is None:
            skipped.append(f"{name} (unknown)")
            continue
        if entry["condition"](sensors):
            if entry["timed"]:
                lock.set(i)
            return {
                "fired":             name,
                "reason":            "condition met",
                "locked":            entry["timed"],
                "lock_owner":        name if entry["timed"] else None,
                "lock_remaining_ms": lock.remaining_ms if entry["timed"] else 0,
                "skipped":           skipped,
            }
        skipped.append(name)

    return {
        "fired":             None,
        "reason":            "no conditions met",
        "locked":            False,
        "lock_owner":        None,
        "lock_remaining_ms": 0,
        "skipped":           skipped,
    }


# ── Server state ─────────────────────────────────────────────────────────────
# Shared across all requests; protected by _lock.


def dispatch_tick(hierarchy: list[str],
                  sensors:   SensorState,
                  lock:      BehaviorLock) -> dict:
    """
    Run one tick of the hierarchy dispatcher.
    Mirrors run_one_tick() in hierarchy_serial.ino exactly.

    Returns a dict describing what happened:
    {
        "fired":       str | None,    behavior name that fired, or null
        "reason":      str,           human-readable explanation
        "locked":      bool,          was a lock active?
        "lock_owner":  str | None,    name of lock owner if locked
        "lock_remaining_ms": int,     ms left on lock (0 if not locked)
        "skipped":     [str],         behaviors evaluated but not fired
    }
    """
    skipped = []

    # Lock active — owner continues running
    if lock.active:
        owner_name = hierarchy[lock.owner_idx] if lock.owner_idx < len(hierarchy) else None
        return {
            "fired":            owner_name,
            "reason":           "lock active — owner continues",
            "locked":           True,
            "lock_owner":       owner_name,
            "lock_remaining_ms": lock.remaining_ms,
            "skipped":          [],
        }

    # Lock expired — clear it
    if lock.owner_idx >= 0:
        lock.clear()

    # Normal evaluation
    for i, name in enumerate(hierarchy):
        entry = REGISTRY_BY_NAME.get(name)
        if entry is None:
            skipped.append(f"{name} (unknown)")
            continue
        if entry["condition"](sensors):
            if entry["timed"]:
                lock.set(i)
            return {
                "fired":             name,
                "reason":            "condition met",
                "locked":            entry["timed"],
                "lock_owner":        name if entry["timed"] else None,
                "lock_remaining_ms": lock.remaining_ms if entry["timed"] else 0,
                "skipped":           skipped,
            }
        skipped.append(name)

    return {
        "fired":             None,
        "reason":            "no conditions met",
        "locked":            False,
        "lock_owner":        None,
        "lock_remaining_ms": 0,
        "skipped":           skipped,
    }


# ── Server state ─────────────────────────────────────────────────────────────
# Shared across all requests; protected by _lock.

class RobotState:
    def __init__(self):
        self._lock      = threading.Lock()
        self.sensors    = SensorState()
        self.beh_lock   = BehaviorLock()
        self.occupied   = False
        self.session    = ""
        self.hierarchy  = []
        self.run_start  = 0.0
        self._counter   = 0

    def make_token(self) -> str:
        self._counter += 1
        rnd = "".join(random.choices(string.ascii_lowercase, k=4))
        return f"s{int(time.monotonic()*1000)}_{self._counter}_{rnd}"

    def start_run(self, hierarchy: list) -> str:
        with self._lock:
            token          = self.make_token()
            self.occupied  = True
            self.session   = token
            self.hierarchy = hierarchy
            self.run_start = time.monotonic()
            return token

    def stop_run(self, token: str) -> bool:
        """Returns True if token matched and run was stopped."""
        with self._lock:
            if not self.occupied or token != self.session:
                return False
            self.occupied  = False
            self.session   = ""
            self.hierarchy = []
            return True

    def snapshot(self) -> dict:
        with self._lock:
            elapsed = (time.monotonic() - self.run_start) if self.occupied else 0.0
            return {
                "occupied":  self.occupied,
                "session":   self.session,
                "hierarchy": list(self.hierarchy),
                "elapsed_s": round(elapsed, 2),
                "sensors":   self.sensors.as_dict(),
            }


_state = RobotState()


# ── Request handler ───────────────────────────────────────────────────────────

class RobotHandler(BaseHTTPRequestHandler):

    # Silence the default per-request log line — we print our own.
    def log_message(self, fmt, *args):
        pass

    # ── Response helpers ──────────────────────────────────────────────────

    def _send_json(self, code: int, body: dict):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> dict | None:
        """Read and parse the JSON request body. Returns None on failure."""
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            raw = self.rfile.read(length)
            return json.loads(raw.decode())
        except Exception as e:
            print(f"  [mock] body parse error: {e}")
            return None

    # ── Route handlers ────────────────────────────────────────────────────

    def _handle_ping(self):
        snap = _state.snapshot()
        resp = {
            "status":  "busy" if snap["occupied"] else "idle",
            "session": snap["session"],
        }
        self._send_json(200, resp)
        print(f"  PING  → status={resp['status']}")

    def _handle_run(self):
        body = self._read_body()
        if body is None:
            self._send_json(400, {"error": "invalid JSON body"})
            return

        snap = _state.snapshot()
        if snap["occupied"]:
            self._send_json(503, {"error": "busy"})
            print(f"  RUN   → rejected (busy, session={snap['session']})")
            return

        hierarchy = body.get("hierarchy")
        if not isinstance(hierarchy, list) or len(hierarchy) == 0:
            self._send_json(400, {"error": "missing or empty hierarchy"})
            return

        token = _state.start_run(hierarchy)
        self._send_json(200, {"status": "running", "session": token})
        print(f"  RUN   → started  session={token}")
        print(f"          hierarchy={hierarchy}")

    def _handle_stop(self):
        body = self._read_body()
        if body is None:
            self._send_json(400, {"error": "invalid JSON body"})
            return

        token = body.get("session", "")
        if not token:
            self._send_json(400, {"error": "missing session"})
            return

        ok = _state.stop_run(token)
        if ok:
            self._send_json(200, {"status": "idle"})
            print(f"  STOP  → accepted  session={token}")
        else:
            snap = _state.snapshot()
            self._send_json(403, {"error": "invalid session"})
            print(f"  STOP  → rejected  bad token={token!r} "
                  f"(current={snap['session']!r})")

    def _handle_tick(self, query_params: dict):
        """
        Mock-only: inject sensor values and run one dispatch tick.
        Returns which behavior fired and full reasoning.
        """
        # Update sensors from query params (single values from parse_qs)
        flat = {k: v[0] for k, v in query_params.items()}
        _state.sensors.update(flat)

        snap = _state.snapshot()
        if not snap["occupied"]:
            self._send_json(400, {"error": "no run active — POST /run first"})
            print("  TICK  → rejected (not running)")
            return

        result = dispatch_tick(snap["hierarchy"], _state.sensors, _state.beh_lock)
        result["sensors"]   = _state.sensors.as_dict()
        result["hierarchy"] = snap["hierarchy"]
        self._send_json(200, result)

        fired = result["fired"] or "none"
        print(f"  TICK  → fired={fired}  reason={result['reason']}")
        if result["skipped"]:
            print(f"          skipped={result['skipped']}")

    def _handle_state(self):
        """Mock-only debug endpoint — full internal state."""
        snap = _state.snapshot()
        snap["beh_lock"] = {
            "active":       _state.beh_lock.active,
            "owner_idx":    _state.beh_lock.owner_idx,
            "remaining_ms": _state.beh_lock.remaining_ms,
        }
        self._send_json(200, snap)
        print(f"  STATE → {snap}")

    def _handle_reset(self):
        """Mock-only — force server back to idle, clear sensors and lock."""
        with _state._lock:
            _state.occupied  = False
            _state.session   = ""
            _state.hierarchy = []
            _state.sensors   = SensorState()
            _state.beh_lock.clear()
        self._send_json(200, {"status": "idle", "note": "forced reset"})
        print("  RESET → forced idle")

    # ── Dispatch ──────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        params = parse_qs(parsed.query)
        print(f"-- GET  {self.path}")
        if path == "/ping":
            self._handle_ping()
        elif path == "/state":
            self._handle_state()
        elif path == "/tick":
            self._handle_tick(params)
        else:
            self._send_json(404, {"error": "not found"})
            print(f"  404")

    def do_POST(self):
        print(f"-- POST {self.path}")
        if self.path == "/run":
            self._handle_run()
        elif self.path == "/stop":
            self._handle_stop()
        elif self.path == "/reset":
            self._handle_reset()
        else:
            self._send_json(404, {"error": "not found"})
            print(f"  404")


# ── Entry point ───────────────────────────────────────────────────────────────


# ── End inlined ─────────────────────────────────────────────────────────────



# ── Server state (parallel to WiFi mock RobotState) ───────────────────────────

class BTRobotState:
    def __init__(self):
        self._lock     = threading.Lock()
        self.sensors   = SensorState()
        self.beh_lock  = BehaviorLock()
        self.occupied  = False
        self.session   = ""
        self.hierarchy = []
        self._counter  = 0

    def make_token(self) -> str:
        self._counter += 1
        rnd = "".join(random.choices(string.ascii_lowercase, k=4))
        return f"bt{int(time.monotonic()*1000)}_{self._counter}_{rnd}"

    def start_run(self, hierarchy: list) -> str:
        with self._lock:
            token         = self.make_token()
            self.occupied = True
            self.session  = token
            self.hierarchy= hierarchy
            return token

    def stop_run(self, token: str) -> bool:
        with self._lock:
            if not self.occupied or token != self.session:
                return False
            self.occupied  = False
            self.session   = ""
            self.hierarchy = []
            return True

    def force_reset(self):
        with self._lock:
            self.occupied  = False
            self.session   = ""
            self.hierarchy = []
            self.sensors   = SensorState()
            self.beh_lock.clear()


_state = BTRobotState()


# ── Command dispatcher ────────────────────────────────────────────────────────

def handle_command(obj: dict) -> dict:
    """Process one parsed JSON command. Returns response dict."""
    cmd = obj.get("cmd", "")

    if cmd == "ping":
        return {
            "status":  "busy" if _state.occupied else "idle",
            "session": _state.session,
        }

    elif cmd == "run":
        if _state.occupied:
            return {"status": "busy", "session": _state.session}
        h = obj.get("hierarchy")
        if not isinstance(h, list) or not h:
            return {"error": "missing or empty hierarchy"}
        token = _state.start_run(h)
        print(f"  RUN   → session={token}  hierarchy={h}")
        return {"status": "running", "session": token}

    elif cmd == "stop":
        token = obj.get("session", "")
        if _state.stop_run(token):
            print(f"  STOP  → accepted  session={token}")
            return {"ok": True}
        print(f"  STOP  → rejected  bad token={token!r}")
        return {"ok": False, "error": "invalid session"}

    elif cmd == "reset":
        _state.force_reset()
        print("  RESET → forced idle")
        return {"ok": True, "note": "forced reset"}

    elif cmd == "inject":
        # Development only — inject sensor values
        params = {k: str(v) for k, v in obj.items() if k != "cmd"}
        _state.sensors.update(params)
        return {"ok": True, "sensors": _state.sensors.as_dict()}

    elif cmd == "tick":
        # Run one dispatch tick (development/test use)
        params = {k: str(v) for k, v in obj.items() if k != "cmd"}
        if params:
            _state.sensors.update(params)
        if not _state.occupied:
            return {"error": "no run active — send 'run' first"}
        result = dispatch_tick(_state.hierarchy, _state.sensors,
                               _state.beh_lock)
        result["sensors"]   = _state.sensors.as_dict()
        result["hierarchy"] = _state.hierarchy
        print(f"  TICK  → fired={result.get('fired')}  "
              f"reason={result.get('reason')}")
        return result

    else:
        return {"error": f"unknown command: {cmd!r}"}


# ── TCP session handler ───────────────────────────────────────────────────────

def handle_client(conn: socket.socket, addr):
    """Handle one BT client connection (one line per command)."""
    print(f"  [BT] connected from {addr}")
    buf = b""
    try:
        while True:
            chunk = conn.recv(1024)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                print(f"-- CMD  {line.decode(errors='replace')}")
                try:
                    obj      = json.loads(line.decode("utf-8"))
                    response = handle_command(obj)
                except json.JSONDecodeError as e:
                    response = {"error": f"JSON parse error: {e}"}
                out = json.dumps(response) + "\n"
                conn.sendall(out.encode("utf-8"))
    except Exception as e:
        print(f"  [BT] session error: {e}")
    finally:
        conn.close()
        print(f"  [BT] disconnected {addr}")


# ── TCP adapter for RobotBTClient ─────────────────────────────────────────────

class _TCPSerialAdapter:
    """
    A minimal serial-like object wrapping a TCP socket,
    accepted by RobotBTClient in place of pyserial.
    Used only for testing against the mock BT server.
    """
    def __init__(self, host: str, port: int, timeout: float = 3.0):
        self._sock    = socket.create_connection((host, port), timeout=timeout)
        self._timeout = timeout
        self._sock.settimeout(timeout)
        self._buf     = b""

    @property
    def is_open(self) -> bool:
        return self._sock.fileno() != -1

    def write(self, data: bytes) -> int:
        self._sock.sendall(data)
        return len(data)

    def flush(self) -> None:
        pass

    def readline(self) -> bytes:
        while b"\n" not in self._buf:
            chunk = self._sock.recv(1024)
            if not chunk:
                break
            self._buf += chunk
        if b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            return line + b"\n"
        return self._buf

    def reset_input_buffer(self) -> None:
        self._sock.settimeout(0.0)
        try:
            while self._sock.recv(4096):
                pass
        except Exception:
            pass
        self._sock.settimeout(self._timeout)
        self._buf = b""

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass


class MockBTAdapter:
    """Factory for connecting RobotBTClient to the mock BT server via TCP."""

    @staticmethod
    def make_client(host: str = "127.0.0.1",
                    port: int = 9090,
                    timeout: float = 3.0):
        """
        Return a RobotBTClient pre-wired to the mock BT server.

        The client uses a TCP socket adapter instead of a real serial port.
        Requires the mock server to be running on host:port.

        Example
        -------
        server: python engine/bluetooth/mock_bt_server.py
        client: client = MockBTAdapter.make_client()
                print(client.ping())
        """
        from engine.bluetooth.robot_bt_client import RobotBTClient
        adapter = _TCPSerialAdapter(host, port, timeout)
        client  = RobotBTClient.__new__(RobotBTClient)
        client._port    = f"tcp://{host}:{port}"
        client._baud    = 0
        client._timeout = timeout
        client._serial  = adapter
        time.sleep(0.1)
        return client


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Mock Bluetooth robot server (TCP) for development.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9090)
    args = ap.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(5)

    print("=" * 55)
    print("  Mock Bluetooth Robot Server (TCP)")
    print(f"  Listening on {args.host}:{args.port}")
    print("  Commands: ping  run  stop  reset  inject  tick")
    print("  Ctrl-C to quit")
    print("=" * 55)
    print()

    try:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(target=handle_client,
                                 args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\n  Shutting down.")
    finally:
        server.close()


if __name__ == "__main__":
    main()
