"""
wifi_poc/test_robot_hardware.py
--------------------------------
Integration tests against a real Arduino running robot_wifi_ethology.ino.

Runs a focused subset of the protocol tests — enough to confirm the full
comms stack is working without exhausting the Arduino's memory or timing out.

Usage:
    python test_robot_hardware.py --ip 192.168.x.x
    python test_robot_hardware.py --ip 192.168.x.x --port 80

The Arduino must be:
  1. Flashed with robot_wifi_ethology.ino
  2. Connected to the same WiFi network as this machine
  3. Its IP printed in Serial Monitor after boot

What this tests
---------------
Stage 1 — Connectivity
  T01  /ping responds
  T02  Status is "idle" initially

Stage 2 — Session lifecycle
  T03  POST /run accepts a hierarchy, returns session token
  T04  /ping reports "busy" while running
  T05  POST /stop with correct token returns idle
  T06  /ping reports "idle" after stop
  T07  POST /stop with wrong token → 403
  T08  POST /run while busy → 503

Stage 3 — Dispatch (sensor injection via /tick query params)
  T09  /tick with contact_f=1 fires escape_front
  T10  /tick with ir=600 fires avoid_object (if in hierarchy)
  T11  /tick with no trigger fires cruise_straight (lowest priority)
  T12  escape_front lock: two ticks after contact, still locked
  T13  Lock clears after ESCAPE_MS (2 s) — timed wait

Stage 4 — Reset
  T14  POST /reset returns idle even while running

All tests print PASS / FAIL with detail.
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def get(base_url, path, timeout=5):
    try:
        with urllib.request.urlopen(f"{base_url}{path}", timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception as e:
        return None, {"_error": str(e)}

def post(base_url, path, body=None, timeout=5):
    data = json.dumps(body or {}).encode()
    req  = urllib.request.Request(
        f"{base_url}{path}", data=data,
        headers={"Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body_bytes = e.read()
            return e.code, json.loads(body_bytes.decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return None, {"_error": str(e)}


# ── Test runner ────────────────────────────────────────────────────────────────

_passed = _failed = 0
_session_token = None

def check(label, condition, detail=""):
    global _passed, _failed
    if condition:
        print(f"  PASS  {label}")
        _passed += 1
    else:
        print(f"  FAIL  {label}")
        if detail:
            print(f"        {detail}")
        _failed += 1

def section(title):
    print(f"\n[{title}]")


# ── Test groups ────────────────────────────────────────────────────────────────

def test_connectivity(base):
    section("Stage 1 — Connectivity")
    code, body = get(base, "/ping")
    check("T01  /ping responds",             code == 200, f"code={code} body={body}")
    check("T02  status is idle initially",   body.get("status") == "idle",
          f"body={body}")


def test_session(base):
    global _session_token
    section("Stage 2 — Session lifecycle")

    HIER = ["escape_front", "avoid_object", "seek_light", "cruise_straight"]

    code, body = post(base, "/run", {"hierarchy": HIER})
    check("T03  POST /run accepted",
          code == 200 and body.get("status") == "running",
          f"code={code} body={body}")
    _session_token = body.get("session", "")
    check("T03b session token received",     bool(_session_token),
          f"token={_session_token!r}")

    code, body = get(base, "/ping")
    check("T04  /ping busy while running",   body.get("status") == "busy",
          f"body={body}")

    code, body = post(base, "/stop", {"session": "WRONG_TOKEN"})
    check("T07  wrong token → 403",          code == 403, f"code={code}")

    code2, body2 = post(base, "/run", {"hierarchy": HIER})
    check("T08  double /run → 503",          code2 == 503, f"code={code2}")

    code, body = post(base, "/stop", {"session": _session_token})
    check("T05  POST /stop accepted",
          code == 200 and body.get("status") == "idle",
          f"code={code} body={body}")

    code, body = get(base, "/ping")
    check("T06  /ping idle after stop",      body.get("status") == "idle",
          f"body={body}")


def test_dispatch(base):
    section("Stage 3 — Dispatch via /tick")

    HIER = ["escape_front", "avoid_object", "cruise_straight"]
    code, body = post(base, "/run", {"hierarchy": HIER})
    if code != 200:
        print(f"  SKIP  (could not start run: {code} {body})")
        return
    token = body.get("session", "")

    # T09 — contact triggers escape_front
    code, body = get(base, "/tick?contact_f=1")
    check("T09  contact_f=1 fires escape_front",
          body.get("fired") == "escape_front",
          f"fired={body.get('fired')!r}")

    # T10 — IR triggers avoid_object (lock may still be active from T09)
    # Wait briefly for lock to allow non-timed behavior through
    time.sleep(0.1)
    code, body = get(base, "/tick?contact_f=0&ir=600")
    fired = body.get("fired")
    check("T10  ir=600 fires avoid or lock",
          fired in ("avoid_object", "escape_front"),
          f"fired={fired!r} locked={body.get('locked')}")

    # T11 — no stimulus → cruise_straight (wait for lock to clear first)
    print("        (waiting 2.1 s for escape lock to expire...)")
    time.sleep(2.1)
    code, body = get(base, "/tick?contact_f=0&ir=0")
    check("T11  no stimulus fires cruise_straight",
          body.get("fired") == "cruise_straight",
          f"fired={body.get('fired')!r}")

    # T12 — lock test: trigger escape, then check lock persists next tick
    get(base, "/tick?contact_f=1")   # fire escape, start lock
    code, body = get(base, "/tick?contact_f=0&ir=0")
    check("T12  lock persists next tick after escape",
          body.get("locked") == True or body.get("fired") == "escape_front",
          f"locked={body.get('locked')} fired={body.get('fired')!r}")

    # T13 — lock clears after 2 s
    print("        (waiting 2.1 s for lock to expire...)")
    time.sleep(2.1)
    code, body = get(base, "/tick?contact_f=0&ir=0")
    check("T13  lock clears after 2 s",
          body.get("locked") == False,
          f"locked={body.get('locked')} fired={body.get('fired')!r}")

    # Clean up
    post(base, "/stop", {"session": token})


def test_reset(base):
    section("Stage 4 — Reset")
    HIER = ["cruise_straight"]
    post(base, "/run", {"hierarchy": HIER})

    code, body = post(base, "/reset")
    check("T14  /reset returns idle",
          code == 200 and body.get("status") == "idle",
          f"code={code} body={body}")

    code, body = get(base, "/ping")
    check("T14b /ping idle after reset",     body.get("status") == "idle",
          f"body={body}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Hardware integration tests for robot_wifi_ethology")
    parser.add_argument("--ip",   required=True,  help="Arduino IP address")
    parser.add_argument("--port", default=80, type=int, help="HTTP port (default 80)")
    args = parser.parse_args()

    base = f"http://{args.ip}:{args.port}"
    print(f"\nTesting Arduino at {base}")
    print("=" * 50)

    # First check connectivity — abort if unreachable
    code, body = get(base, "/ping", timeout=3)
    if code is None:
        print(f"\nERROR: Cannot reach {base}")
        print(f"  {body.get('_error', 'unknown error')}")
        print("\nCheck:")
        print("  1. Arduino is on the same network as this machine")
        print("  2. WIFI_SSID / WIFI_PASS are correct in the sketch")
        print("  3. IP address is correct (check Serial Monitor)")
        sys.exit(1)

    # Ensure we start from idle
    post(base, "/reset")
    time.sleep(0.3)

    test_connectivity(base)
    test_session(base)
    test_dispatch(base)
    test_reset(base)

    print(f"\n{'=' * 50}")
    print(f"  Results: {_passed} passed,  {_failed} failed")
    print(f"{'=' * 50}\n")

    # Leave robot in idle/halted state
    post(base, "/reset")
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
