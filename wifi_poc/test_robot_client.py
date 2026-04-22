"""
test_robot_client.py
---------------------
Test suite for RobotWiFiClient against mock_robot_server.py.

The mock server must be running before you run this script.
Start it in a separate terminal:

    python mock_robot_server.py

Then run:

    python test_robot_client.py

To test against the real Arduino instead, pass its IP:

    python test_robot_client.py --host 192.168.4.1 --port 80

All tests are self-contained and leave the server in idle state
when done (even if they fail midway).
"""

import argparse
import sys
import time
from robot_wifi_client import RobotWiFiClient


# ── Test infrastructure ───────────────────────────────────────────────────────

_passed = 0
_failed = 0
_current_section = ""


def section(title: str):
    global _current_section
    _current_section = title
    print(f"\n[{title}]")


def check(label: str, condition: bool, detail: str = ""):
    global _passed, _failed
    icon = "✓ PASS" if condition else "✗ FAIL"
    print(f"  {icon}  {label}")
    if detail:
        indent = "         "
        for line in str(detail).splitlines():
            print(f"{indent}{line}")
    if condition:
        _passed += 1
    else:
        _failed += 1


def ensure_idle(client: RobotWiFiClient, label: str = "cleanup"):
    """Best-effort reset to idle between tests."""
    client.reset()


# ── Test cases ────────────────────────────────────────────────────────────────

HIERARCHY_A = ["escape_front", "avoid_object", "seek_light", "cruise_straight"]
HIERARCHY_B = ["cruise_straight"]


def test_ping_idle(client: RobotWiFiClient):
    section("ping — idle state")
    result = client.ping()
    check("reachable",       result.get("reachable") is True,   str(result))
    check("status == idle",  result.get("status") == "idle",    str(result))
    check("no session",      result.get("session", "") == "",    str(result))


def test_run_basic(client: RobotWiFiClient) -> str:
    section("send_hierarchy — basic run")
    result = client.send_hierarchy(HIERARCHY_A)
    check("ok == True",         result.get("ok") is True,          str(result))
    check("session token set",  bool(result.get("session", "")),    str(result))
    token = result.get("session", "")
    print(f"         token = {token!r}")
    return token


def test_ping_busy(client: RobotWiFiClient, expected_token: str):
    section("ping — busy state")
    result = client.ping()
    check("reachable",          result.get("reachable") is True,         str(result))
    check("status == busy",     result.get("status") == "busy",          str(result))
    check("session matches",    result.get("session") == expected_token,  str(result))


def test_run_rejected_busy(client: RobotWiFiClient):
    section("send_hierarchy — rejected when busy")
    result = client.send_hierarchy(HIERARCHY_B)
    check("ok == False",        result.get("ok") is False,       str(result))
    check("error == busy",      result.get("error") == "busy",   str(result))


def test_stop_bad_token(client: RobotWiFiClient):
    section("stop — bad token rejected")
    result = client.stop("completely_wrong_token")
    check("ok == False",            result.get("ok") is False,           str(result))
    check("error mentions session", "session" in result.get("error", ""),
          str(result))


def test_stop_good_token(client: RobotWiFiClient, token: str):
    section(f"stop — correct token")
    result = client.stop(token)
    check("ok == True",    result.get("ok") is True,   str(result))


def test_ping_idle_after_stop(client: RobotWiFiClient):
    section("ping — idle after stop")
    result = client.ping()
    check("reachable",      result.get("reachable") is True,   str(result))
    check("status == idle", result.get("status") == "idle",    str(result))
    check("session cleared",result.get("session", "") == "",   str(result))


def test_stop_already_idle(client: RobotWiFiClient, old_token: str):
    section("stop — token no longer valid after run ended")
    result = client.stop(old_token)
    check("ok == False",   result.get("ok") is False,   str(result))


def test_sequential_runs(client: RobotWiFiClient):
    section("sequential runs — stop then run again")
    r1 = client.send_hierarchy(HIERARCHY_A)
    check("first run ok",      r1.get("ok") is True,    str(r1))
    token1 = r1.get("session", "")

    s1 = client.stop(token1)
    check("first stop ok",     s1.get("ok") is True,    str(s1))

    r2 = client.send_hierarchy(HIERARCHY_B)
    check("second run ok",     r2.get("ok") is True,    str(r2))
    token2 = r2.get("session", "")
    check("new token issued",  token2 != token1,         f"{token1!r} vs {token2!r}")

    s2 = client.stop(token2)
    check("second stop ok",    s2.get("ok") is True,    str(s2))


def test_empty_hierarchy(client: RobotWiFiClient):
    section("send_hierarchy — empty list rejected")
    result = client.send_hierarchy([])
    check("ok == False",       result.get("ok") is False,   str(result))


def test_wait_until_idle_immediate(client: RobotWiFiClient):
    section("wait_until_idle — already idle")
    # Server is idle; should return True immediately
    t0     = time.monotonic()
    result = client.wait_until_idle(timeout=5.0, poll_interval=0.25)
    elapsed = time.monotonic() - t0
    check("returned True",     result is True,       f"elapsed={elapsed:.2f}s")
    check("returned quickly",  elapsed < 2.0,        f"elapsed={elapsed:.2f}s")


def test_wait_until_idle_timeout(client: RobotWiFiClient):
    section("wait_until_idle — times out while busy")
    r = client.send_hierarchy(HIERARCHY_A)
    check("run started",       r.get("ok") is True,   str(r))
    token = r.get("session", "")

    t0     = time.monotonic()
    result = client.wait_until_idle(timeout=1.5, poll_interval=0.4)
    elapsed = time.monotonic() - t0
    check("returned False",    result is False,       f"elapsed={elapsed:.2f}s")
    check("timed out ~1.5s",   1.0 < elapsed < 3.0,  f"elapsed={elapsed:.2f}s")

    # Cleanup
    client.stop(token)


def test_get_state(client: RobotWiFiClient):
    section("get_state — mock debug endpoint")
    r = client.send_hierarchy(HIERARCHY_A)
    token = r.get("session", "")

    state = client.get_state()
    check("ok == True",           state.get("ok") is True,                    str(state))
    check("occupied == True",     state.get("occupied") is True,              str(state))
    check("hierarchy present",    state.get("hierarchy") == HIERARCHY_A,      str(state))
    check("elapsed_s present",    isinstance(state.get("elapsed_s"), float),  str(state))

    client.stop(token)


def test_tick_no_run(client: RobotWiFiClient):
    section("tick — rejected when no run active")
    result = client.tick()
    check("ok == False",     result.get("ok") is False,   str(result))
    check("error present",   bool(result.get("error")),   str(result))


def test_tick_cruise(client: RobotWiFiClient):
    section("tick — all sensors quiet → cruise fires")
    r = client.send_hierarchy(HIERARCHY_A)
    check("run started",     r.get("ok") is True,         str(r))
    token = r.get("session", "")

    # All sensors at default (no contact, no IR, flat LDR)
    result = client.tick(contact_f=0, contact_r=0, ir=0, ldr_l=512, ldr_r=512)
    check("ok == True",      result.get("ok") is True,    str(result))
    check("cruise fires",    result.get("fired") == "cruise_straight",
          f"fired={result.get('fired')}")
    check("not locked",      result.get("locked") is False, str(result))

    client.stop(token)


def test_tick_avoid(client: RobotWiFiClient):
    section("tick — IR above threshold → avoid_object fires")
    r = client.send_hierarchy(HIERARCHY_A)
    token = r.get("session", "")

    result = client.tick(ir=600)
    check("ok == True",         result.get("ok") is True,         str(result))
    check("avoid fires",        result.get("fired") == "avoid_object",
          f"fired={result.get('fired')}")
    check("escape_front skipped", "escape_front" in result.get("skipped", []),
          str(result.get("skipped")))

    client.stop(token)


def test_tick_escape_locks(client: RobotWiFiClient):
    section("tick — front contact → escape fires and locks")
    r = client.send_hierarchy(HIERARCHY_A)
    token = r.get("session", "")

    # Tick 1: contact triggers escape + lock
    result = client.tick(contact_f=1, ir=600)
    check("escape fires",        result.get("fired") == "escape_front",
          f"fired={result.get('fired')}")
    check("lock active",         result.get("locked") is True,    str(result))
    check("lock_remaining > 0",  result.get("lock_remaining_ms", 0) > 0,
          str(result.get("lock_remaining_ms")))

    # Tick 2: clear contact + high IR — lock should keep escape running
    result2 = client.tick(contact_f=0, ir=600)
    check("still locked",        result2.get("locked") is True,   str(result2))
    check("escape still owner",  result2.get("fired") == "escape_front",
          f"fired={result2.get('fired')}")
    check("avoid suppressed",    "avoid_object" not in result2.get("skipped", []),
          "avoid should be suppressed by lock, not evaluated")

    client.stop(token)


def test_tick_seek_light(client: RobotWiFiClient):
    section("tick — LDR gradient → seek_light fires")
    r = client.send_hierarchy(HIERARCHY_A)
    token = r.get("session", "")

    result = client.tick(contact_f=0, ir=0, ldr_l=400, ldr_r=200)
    check("ok == True",          result.get("ok") is True,        str(result))
    check("seek_light fires",    result.get("fired") == "seek_light",
          f"fired={result.get('fired')}")

    client.stop(token)


def test_tick_priority_order(client: RobotWiFiClient):
    section("tick — contact + IR both active → escape wins (highest priority)")
    r = client.send_hierarchy(HIERARCHY_A)
    token = r.get("session", "")

    result = client.tick(contact_f=1, ir=800, ldr_l=400, ldr_r=100)
    check("escape wins over avoid", result.get("fired") == "escape_front",
          f"fired={result.get('fired')}")
    check("avoid in skipped",       "avoid_object" not in result.get("skipped", []),
          "avoid should not appear in skipped when lock is set")

    client.stop(token)


def test_tick_sensors_persist(client: RobotWiFiClient):
    section("tick — sensor values persist across ticks")
    r = client.send_hierarchy(HIERARCHY_A)
    token = r.get("session", "")

    # Set IR high on first tick
    client.tick(ir=700)
    # Second tick with no overrides — IR should still be 700
    result = client.tick()
    check("avoid still fires",   result.get("fired") == "avoid_object",
          f"fired={result.get('fired')} (expected ir still 700)")
    check("sensors reflect ir",  result.get("sensors", {}).get("ir_raw") == 700,
          str(result.get("sensors")))

    client.stop(token)


def test_reset(client: RobotWiFiClient):
    section("reset — mock force-idle endpoint")
    r = client.send_hierarchy(HIERARCHY_A)
    check("run started",        r.get("ok") is True,      str(r))

    rst = client.reset()
    check("reset ok",           rst.get("ok") is True,    str(rst))

    p = client.ping()
    check("idle after reset",   p.get("status") == "idle", str(p))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    client = RobotWiFiClient(host=args.host, port=args.port, timeout=5.0)

    print("=" * 55)
    print(f"  RobotWiFiClient test suite")
    print(f"  Target: {client}")
    print("=" * 55)

    # Ensure clean state before we start
    client.reset()

    # ── Run all tests ──────────────────────────────────────────────────────
    test_ping_idle(client)

    token = test_run_basic(client)
    if token:
        test_ping_busy(client, token)
        test_run_rejected_busy(client)
        test_stop_bad_token(client)
        test_stop_good_token(client, token)
        test_ping_idle_after_stop(client)
        test_stop_already_idle(client, token)
    else:
        print("  [skipping busy/stop tests — no token from /run]")

    ensure_idle(client)
    test_sequential_runs(client)

    ensure_idle(client)
    test_empty_hierarchy(client)

    ensure_idle(client)
    test_wait_until_idle_immediate(client)

    ensure_idle(client)
    test_wait_until_idle_timeout(client)

    ensure_idle(client)
    test_get_state(client)

    ensure_idle(client)
    test_tick_no_run(client)

    ensure_idle(client)
    test_tick_cruise(client)

    ensure_idle(client)
    test_tick_avoid(client)

    ensure_idle(client)
    test_tick_escape_locks(client)

    ensure_idle(client)
    test_tick_seek_light(client)

    ensure_idle(client)
    test_tick_priority_order(client)

    ensure_idle(client)
    test_tick_sensors_persist(client)

    ensure_idle(client)
    test_reset(client)

    # ── Summary ────────────────────────────────────────────────────────────
    ensure_idle(client)
    print("\n" + "=" * 55)
    print(f"  Results: {_passed} passed,  {_failed} failed")
    print("=" * 55 + "\n")
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
