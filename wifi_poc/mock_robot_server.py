"""
mock_robot_server.py
---------------------
A Python program that faithfully impersonates the Arduino HTTP server
defined in robot_poc.ino.  Run this on your laptop to develop and test
the full robosim WiFi integration without any hardware.

When the real Arduino is ready, swap the IP address — everything else
stays the same.

Usage:
    python mock_robot_server.py                  # listens on 127.0.0.1:8080
    python mock_robot_server.py --port 80        # match Arduino default
    python mock_robot_server.py --host 0.0.0.0  # reachable from other machines

The server prints every transaction to stdout, just like the Arduino's
Serial Monitor output, so you can watch what's happening during tests.

Endpoints (identical to robot_poc.ino):
    GET  /ping          — returns status and current session token (if busy)
    POST /run           — accepts hierarchy + starts run, returns session token
                          returns 503 if already occupied
    POST /stop          — ends run, requires valid session token
                          returns 403 on bad/missing token

Extras (not on real Arduino — mock only):
    GET  /state         — full internal state dump for debugging
    POST /reset         — force back to idle (useful during test development)
    GET  /tick?<sensors> — run one dispatch tick with injected sensor values,
                          returns which behavior fired and why.
                          Query params (all optional, retain previous value):
                            contact_f=0|1
                            contact_r=0|1
                            ir=0..1023
                            ldr_l=0..1023
                            ldr_r=0..1023
                          Example:
                            GET /tick?contact_f=1
                            GET /tick?ir=600&ldr_l=300&ldr_r=150
"""

import argparse
import json
import time
import threading
import random
import string
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer


# ── Behavior dispatch engine ──────────────────────────────────────────────────
# Mirrors hierarchy_serial.ino exactly so the two can be compared tick-for-tick.

IR_THRESHOLD = 400      # raw ADC, same as sketch
LDR_DIFF_MIN = 30       # minimum L/R difference to trigger gradient behaviors
ESCAPE_MS    = 2.0      # seconds (sketch uses 2000ms)


class SensorState:
    def __init__(self):
        self.contact_front = False
        self.contact_rear  = False
        self.ir_raw        = 0
        self.ldr_left      = 512
        self.ldr_right     = 512

    def update(self, params: dict):
        """Update from a dict of string key → string value (from query string)."""
        if "contact_f" in params:
            self.contact_front = params["contact_f"] not in ("0", "false", "False")
        if "contact_r" in params:
            self.contact_rear  = params["contact_r"] not in ("0", "false", "False")
        if "ir"    in params: self.ir_raw    = int(params["ir"])
        if "ldr_l" in params: self.ldr_left  = int(params["ldr_l"])
        if "ldr_r" in params: self.ldr_right = int(params["ldr_r"])

    def as_dict(self) -> dict:
        return {
            "contact_front": self.contact_front,
            "contact_rear":  self.contact_rear,
            "ir_raw":        self.ir_raw,
            "ldr_left":      self.ldr_left,
            "ldr_right":     self.ldr_right,
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


# Condition functions — each takes a SensorState, returns bool
def cond_front_contact(s: SensorState)  -> bool: return s.contact_front
def cond_rear_contact(s: SensorState)   -> bool: return s.contact_rear
def cond_proximity(s: SensorState)      -> bool: return s.ir_raw >= IR_THRESHOLD
def cond_light_gradient(s: SensorState) -> bool:
    return abs(s.ldr_left - s.ldr_right) >= LDR_DIFF_MIN
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

def main():
    ap = argparse.ArgumentParser(
        description="Mock Arduino robot HTTP server for robosim development.")
    ap.add_argument("--host", default="127.0.0.1",
                    help="Address to listen on (default: 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8080,
                    help="Port to listen on (default: 8080)")
    args = ap.parse_args()

    server = HTTPServer((args.host, args.port), RobotHandler)

    print("=" * 55)
    print("  Mock Robot Server")
    print(f"  Listening on http://{args.host}:{args.port}")
    print("  Endpoints: GET /ping  POST /run  POST /stop")
    print("  Debug:     GET /state  POST /reset")
    print("  Ctrl-C to quit")
    print("=" * 55)
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
