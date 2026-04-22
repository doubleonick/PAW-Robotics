"""
robot_wifi_client.py
---------------------
Python client for the Arduino robot WiFi server.

This is the production-ready class that robosim will import.
It works against both:
  - mock_robot_server.py  (development, no hardware)
  - robot_poc.ino / the real robot firmware  (hardware)

Swapping between them is one line:
    client = RobotWiFiClient("127.0.0.1", port=8080)  # mock
    client = RobotWiFiClient("192.168.4.1")            # real Arduino

Public API
----------
    client.ping()
        -> {"reachable": bool, "status": "idle"|"busy", "session": str}

    client.send_hierarchy(hierarchy)
        -> {"ok": bool, "session": str, "error": str}
           ok=False + error="busy" if robot is occupied by another game

    client.stop(session_token)
        -> {"ok": bool, "error": str}

    client.wait_until_idle(timeout=30.0, poll_interval=1.0)
        -> True if robot became idle within timeout, False otherwise

    client.reset()   [mock only — no-op against real Arduino]
        -> {"ok": bool}

All methods return plain dicts — no exceptions propagate to the caller.
Network errors are caught and returned as {"ok": False, "error": "..."}.
"""

import json
import urllib.request
import urllib.error
from typing import Any


class RobotWiFiClient:
    """
    HTTP client for the Arduino robot server (real or mock).

    Parameters
    ----------
    host : str
        IP address of the robot (or mock server).
    port : int
        HTTP port (80 for real Arduino, 8080 for mock by default).
    timeout : float
        Per-request timeout in seconds.
    """

    def __init__(self, host: str = "192.168.4.1",
                 port: int = 80,
                 timeout: float = 5.0):
        self._base    = f"http://{host}:{port}"
        self._timeout = timeout

    # ── Low-level HTTP ────────────────────────────────────────────────────

    def _get(self, path: str) -> tuple[int, dict]:
        """GET request. Returns (status_code, body_dict)."""
        url = self._base + path
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, self._parse_error_body(e)
        except Exception as e:
            return 0, {"error": str(e)}

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        """POST JSON request. Returns (status_code, body_dict)."""
        url  = self._base + path
        data = json.dumps(body).encode()
        req  = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type":   "application/json",
                     "Content-Length": str(len(data))})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, self._parse_error_body(e)
        except Exception as e:
            return 0, {"error": str(e)}

    @staticmethod
    def _parse_error_body(e: urllib.error.HTTPError) -> dict:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": str(e)}

    # ── Public API ────────────────────────────────────────────────────────

    def ping(self) -> dict:
        """
        Check whether the robot is reachable and get its current status.

        Returns
        -------
        {
            "reachable": True | False,
            "status":    "idle" | "busy",   # only present if reachable
            "session":   str,               # current session if busy
            "error":     str,               # only present if not reachable
        }
        """
        code, body = self._get("/ping")
        if code == 200:
            return {
                "reachable": True,
                "status":    body.get("status", "unknown"),
                "session":   body.get("session", ""),
            }
        return {
            "reachable": False,
            "error":     body.get("error", f"HTTP {code}"),
        }

    def send_hierarchy(self, hierarchy: list[str]) -> dict:
        """
        Send a behavior hierarchy and start a run.

        Parameters
        ----------
        hierarchy : list of str
            Ordered behavior keys, highest priority first.
            e.g. ["escape_front", "avoid_object", "cruise_straight"]

        Returns
        -------
        {
            "ok":      True | False,
            "session": str,    # session token to use with stop()
            "error":   str,    # present if ok=False
        }
        """
        code, body = self._post("/run", {"hierarchy": hierarchy})

        if code == 200:
            return {
                "ok":      True,
                "session": body.get("session", ""),
            }
        if code == 503:
            return {"ok": False, "error": "busy"}
        if code == 400:
            return {"ok": False, "error": body.get("error", "bad request")}
        if code == 0:
            return {"ok": False, "error": body.get("error", "unreachable")}
        return {"ok": False, "error": f"HTTP {code}: {body.get('error', '')}"}

    def stop(self, session: str) -> dict:
        """
        Stop the current run.

        Parameters
        ----------
        session : str
            The session token returned by send_hierarchy().

        Returns
        -------
        {
            "ok":    True | False,
            "error": str,   # present if ok=False
        }
        """
        code, body = self._post("/stop", {"session": session})

        if code == 200:
            return {"ok": True}
        if code == 403:
            return {"ok": False, "error": "invalid session token"}
        if code == 400:
            return {"ok": False, "error": body.get("error", "bad request")}
        if code == 0:
            return {"ok": False, "error": body.get("error", "unreachable")}
        return {"ok": False, "error": f"HTTP {code}: {body.get('error', '')}"}

    def wait_until_idle(self, timeout: float = 30.0,
                        poll_interval: float = 1.0) -> bool:
        """
        Poll /ping until the robot reports idle or timeout expires.
        Useful when a previous game may still be running.

        Returns True if robot became idle within timeout.
        """
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.ping()
            if result.get("reachable") and result.get("status") == "idle":
                return True
            time.sleep(poll_interval)
        return False

    def tick(self, **sensor_overrides) -> dict:
        """
        Run one dispatch tick on the mock server with optional sensor injection.
        No-op against a real Arduino (returns ok=False gracefully).

        Keyword arguments map directly to sensor query params:
            contact_f=1, contact_r=0, ir=600, ldr_l=300, ldr_r=200

        Returns
        -------
        {
            "ok":                True | False,
            "fired":             str | None,   behavior name that fired
            "reason":            str,
            "locked":            bool,
            "lock_owner":        str | None,
            "lock_remaining_ms": int,
            "skipped":           [str],
            "sensors":           dict,
            "hierarchy":         [str],
        }
        """
        query = "&".join(f"{k}={v}" for k, v in sensor_overrides.items())
        path  = f"/tick?{query}" if query else "/tick"
        code, body = self._get(path)
        if code == 200:
            return {"ok": True, **body}
        return {"ok": False, "error": body.get("error", f"HTTP {code}")}

    def reset(self) -> dict:
        """
        Force the mock server back to idle state.
        No-op against a real Arduino (returns ok=False gracefully).

        Useful in tests and during development.
        """
        code, body = self._post("/reset", {})
        if code == 200:
            return {"ok": True}
        return {"ok": False, "error": body.get("error", f"HTTP {code}")}

    def get_state(self) -> dict:
        """
        Fetch full internal state from mock server (debug use only).
        Returns {"ok": False} against a real Arduino.
        """
        code, body = self._get("/state")
        if code == 200:
            return {"ok": True, **body}
        return {"ok": False, "error": body.get("error", f"HTTP {code}")}

    def __repr__(self) -> str:
        return f"RobotWiFiClient({self._base!r}, timeout={self._timeout})"
