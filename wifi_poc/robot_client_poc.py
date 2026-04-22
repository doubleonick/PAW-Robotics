"""
robot_client_poc.py
--------------------
Proof-of-concept Python client for the Arduino WiFi robot server.

Tests the full comms stack:
  1. Ping  — confirm Arduino is reachable and idle
  2. Run   — send a hierarchy, receive session token
  3. Stop  — end the run using the session token
  4. Busy  — try to send a second hierarchy while first is running (expect 503)

NO robosim dependency.  Run this standalone after:
  - Uploading robot_poc.ino to the Arduino
  - Connecting your laptop's WiFi to ROBOT_AP (password: robotpass)

Usage:
  python robot_client_poc.py              # runs all tests against 192.168.4.1
  python robot_client_poc.py 10.0.0.5    # custom IP if your AP assigned differently

The script prints a clear PASS / FAIL for each step.
"""

import sys
import json
import time
import urllib.request
import urllib.error

# ── Config ─────────────────────────────────────────────────────────────────

ROBOT_IP   = sys.argv[1] if len(sys.argv) > 1 else "192.168.4.1"
ROBOT_PORT = 80
BASE_URL   = f"http://{ROBOT_IP}:{ROBOT_PORT}"
TIMEOUT    = 5   # seconds per request

# Example hierarchy — same string keys used by robosim's BEHAVIOR_MAP
EXAMPLE_HIERARCHY = [
    "escape_front",
    "avoid_object",
    "seek_light",
    "cruise_straight",
]

# ── HTTP helpers ────────────────────────────────────────────────────────────

def get(path: str) -> dict:
    """HTTP GET, returns parsed JSON body."""
    url = BASE_URL + path
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def post(path: str, body: dict) -> tuple[int, dict]:
    """
    HTTP POST with JSON body.
    Returns (status_code, parsed_response_body).
    Does NOT raise on 4xx/5xx — caller inspects the code.
    """
    url  = BASE_URL + path
    data = json.dumps(body).encode()
    req  = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "Content-Length": str(len(data))})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body_bytes = e.read()
            return e.code, json.loads(body_bytes.decode())
        except Exception:
            return e.code, {"error": str(e)}

# ── Test helpers ────────────────────────────────────────────────────────────

_passed = 0
_failed = 0

def check(label: str, condition: bool, detail: str = ""):
    global _passed, _failed
    icon = "✓ PASS" if condition else "✗ FAIL"
    print(f"  {icon}  {label}")
    if detail:
        print(f"         {detail}")
    if condition:
        _passed += 1
    else:
        _failed += 1

# ── Tests ───────────────────────────────────────────────────────────────────

def test_ping_idle():
    print("\n[1] Ping — expect idle")
    try:
        resp = get("/ping")
        check("HTTP 200 received",    True,  str(resp))
        check("status == idle",       resp.get("status") == "idle",
              f"got: {resp.get('status')}")
        check("no session token",     resp.get("session", "") == "",
              f"got: {resp.get('session')}")
    except Exception as e:
        check("reachable", False, str(e))


def test_run() -> str:
    """Send a hierarchy, return the session token."""
    print("\n[2] POST /run — send hierarchy")
    code, resp = post("/run", {"hierarchy": EXAMPLE_HIERARCHY})
    check("HTTP 200",              code == 200,    f"got HTTP {code}")
    check("status == running",     resp.get("status") == "running",
          f"got: {resp.get('status')}")
    token = resp.get("session", "")
    check("session token present", bool(token),    f"got: {repr(token)}")
    print(f"         token = {repr(token)}")
    print(f"         hierarchy sent: {EXAMPLE_HIERARCHY}")
    return token


def test_busy_rejected():
    """Try to send a second /run while Arduino is occupied."""
    print("\n[3] POST /run again — expect 503 busy")
    code, resp = post("/run", {"hierarchy": ["cruise_straight"]})
    check("HTTP 503",          code == 503,   f"got HTTP {code}")
    check("error == busy",     resp.get("error") == "busy",
          f"got: {resp.get('error')}")


def test_ping_busy():
    print("\n[4] Ping — expect busy")
    try:
        resp = get("/ping")
        check("status == busy",    resp.get("status") == "busy",
              f"got: {resp.get('status')}")
        check("session token set", bool(resp.get("session")),
              f"got: {resp.get('session')}")
    except Exception as e:
        check("reachable", False, str(e))


def test_stop_bad_token():
    print("\n[5] POST /stop with wrong token — expect 403")
    code, resp = post("/stop", {"session": "wrong_token_xyz"})
    check("HTTP 403",               code == 403,   f"got HTTP {code}")
    check("error == invalid session", "invalid" in resp.get("error", ""),
          f"got: {resp.get('error')}")


def test_stop(token: str):
    print(f"\n[6] POST /stop with correct token ({repr(token)})")
    code, resp = post("/stop", {"session": token})
    check("HTTP 200",          code == 200,   f"got HTTP {code}")
    check("status == idle",    resp.get("status") == "idle",
          f"got: {resp.get('status')}")


def test_ping_after_stop():
    print("\n[7] Ping — expect idle again")
    try:
        resp = get("/ping")
        check("status == idle",    resp.get("status") == "idle",
              f"got: {resp.get('status')}")
        check("session cleared",   resp.get("session", "") == "",
              f"got: {resp.get('session')}")
    except Exception as e:
        check("reachable", False, str(e))


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print(f"  Robot WiFi POC — target {BASE_URL}")
    print("=" * 55)
    print("\nMake sure your WiFi is connected to ROBOT_AP before running.")
    print("Waiting 1s for any previous connection to settle...")
    time.sleep(1)

    test_ping_idle()
    token = test_run()

    if token:
        time.sleep(0.5)          # give Arduino a moment (Uno R4 is slow to recover)
        test_busy_rejected()
        test_ping_busy()
        test_stop_bad_token()
        test_stop(token)
        time.sleep(0.5)
        test_ping_after_stop()
    else:
        print("\n  [skipping tests 3-7: no session token received from /run]")

    print("\n" + "=" * 55)
    print(f"  Results: {_passed} passed, {_failed} failed")
    print("=" * 55 + "\n")
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
