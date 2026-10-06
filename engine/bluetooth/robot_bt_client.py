"""
engine/bluetooth/robot_bt_client.py
-------------------------------------
Python client for the Arduino robot Bluetooth server.

Structural parallel to engine/wifi/robot_wifi_client.py.
Transport is serial-over-Bluetooth (RFCOMM / BLE serial) instead of HTTP,
but the public API is identical so callers can swap WiFi for Bluetooth
by changing one line:

    from engine.wifi.robot_wifi_client import RobotWiFiClient
    client = RobotWiFiClient("192.168.4.1")

    # becomes:

    from engine.bluetooth.robot_bt_client import RobotBTClient
    client = RobotBTClient("AA:BB:CC:DD:EE:FF")   # robot BT MAC address
    # or on macOS / Windows where the OS assigns a port:
    client = RobotBTClient.from_port("/dev/tty.usbmodem-XXXX")

Wire protocol
-------------
Each message is a single line of JSON terminated by \\n.
The Arduino responds with a single line of JSON terminated by \\n.

Command → Arduino:
    {"cmd": "ping"}
    {"cmd": "run",  "hierarchy": ["escape_front", "avoid_object", ...]}
    {"cmd": "stop", "session": "<token>"}

Response ← Arduino:
    {"status": "idle"}
    {"status": "running", "session": "<token>"}
    {"status": "busy",    "session": "<token>"}
    {"ok": true}
    {"ok": false, "error": "invalid session"}
    {"error": "..."}

Public API (identical to RobotWiFiClient)
-----------------------------------------
    client.ping()             -> {"reachable": bool, "status": str, ...}
    client.send_hierarchy([]) -> {"ok": bool, "session": str, ...}
    client.stop(session)      -> {"ok": bool, ...}
    client.wait_until_idle()  -> bool
    client.reset()            -> {"ok": bool}   # mock only

All methods return plain dicts — no exceptions propagate.

Dependencies
------------
    PySerial >= 3.5  (pip install pyserial)
    For BLE serial on Linux: rfcomm bind + standard serial port
    For BLE serial on macOS: system assigns /dev/tty.DEVICE-SerialPort
    For BLE serial on Windows: COM port assigned by device manager

Bluetooth adapter setup (HC-05 / HC-06 classic BT on Arduino)
--------------------------------------------------------------
    Arduino sketch must call Serial.begin(9600) or Serial.begin(115200)
    and read/write JSON lines over Serial.
    The HC-05/HC-06 module bridges UART ↔ RFCOMM transparently.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any


class RobotBTClient:
    """
    Serial-over-Bluetooth client for the Arduino robot.

    Parameters
    ----------
    port : str
        Serial port path, e.g.:
          Linux:   "/dev/rfcomm0" or "/dev/ttyUSB0"
          macOS:   "/dev/tty.HC-05-DevB"
          Windows: "COM5"
    baud : int
        Baud rate — must match the HC-05/HC-06 and Arduino Serial.begin().
        Default 9600; use 115200 for faster response.
    timeout : float
        Read timeout in seconds per line. Default 3.0.
    """

    def __init__(self, port: str,
                 baud: int = 9600,
                 timeout: float = 3.0):
        self._port    = port
        self._baud    = baud
        self._timeout = timeout
        self._serial  = None   # opened lazily

    # ── Alternative constructors ──────────────────────────────────────────────

    @classmethod
    def from_port(cls, port: str, **kwargs) -> "RobotBTClient":
        """Explicit port path constructor — same as __init__ but clearer name."""
        return cls(port, **kwargs)

    @classmethod
    def from_mac(cls, mac: str, channel: int = 1, **kwargs) -> "RobotBTClient":
        """
        Linux only — bind RFCOMM channel and return a client on the
        resulting /dev/rfcommN port.

        Requires: sudo rfcomm bind <N> <MAC> <channel>
        Run once before using this constructor, or use from_port() directly.
        """
        raise NotImplementedError(
            "from_mac() requires manual rfcomm bind on Linux. "
            "Use: sudo rfcomm bind 0 AA:BB:CC:DD:EE:FF 1\n"
            "Then: RobotBTClient.from_port('/dev/rfcomm0')"
        )

    # ── Connection management ─────────────────────────────────────────────────

    def connect(self) -> bool:
        """
        Open the serial port. Called automatically by any API method
        if not already connected.

        Returns True on success, False on failure.
        """
        if self._serial and self._serial.is_open:
            return True
        try:
            import serial
            self._serial = serial.Serial(
                self._port,
                baudrate=self._baud,
                timeout=self._timeout
            )
            time.sleep(2.0)   # HC-05/HC-06 needs ~2s after connection
            self._serial.reset_input_buffer()
            return True
        except Exception as e:
            self._serial = None
            return False

    def disconnect(self) -> None:
        """Close the serial port."""
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    # ── Low-level transport ───────────────────────────────────────────────────

    def _send(self, obj: dict) -> dict:
        """
        Send a JSON object as a line and read back a JSON response line.
        Opens connection if not already open.
        """
        if not self.connect():
            return {"error": f"could not open port {self._port}"}
        try:
            line = json.dumps(obj) + "\n"
            self._serial.write(line.encode("utf-8"))
            self._serial.flush()
            response_line = self._serial.readline()
            if not response_line:
                return {"error": "timeout — no response from robot"}
            return json.loads(response_line.decode("utf-8").strip())
        except json.JSONDecodeError as e:
            return {"error": f"bad JSON from robot: {e}"}
        except Exception as e:
            return {"error": str(e)}

    # ── Public API (matches RobotWiFiClient exactly) ──────────────────────────

    def ping(self) -> dict:
        """
        Check whether the robot is reachable and get its current status.

        Returns
        -------
        {
            "reachable": True | False,
            "status":    "idle" | "busy",
            "session":   str,
            "error":     str,   # only if not reachable
        }
        """
        resp = self._send({"cmd": "ping"})
        if "error" in resp:
            return {"reachable": False, "error": resp["error"]}
        return {
            "reachable": True,
            "status":    resp.get("status", "unknown"),
            "session":   resp.get("session", ""),
        }

    def send_hierarchy(self, hierarchy: list[str]) -> dict:
        """
        Send a behavior hierarchy and start a run.

        Parameters
        ----------
        hierarchy : list of str
            Ordered behavior keys, highest priority first.
            e.g. ["escape_front", "avoid_object", "approach_light", "cruise_straight"]

        Returns
        -------
        {
            "ok":      True | False,
            "session": str,
            "error":   str,   # only if ok=False
        }
        """
        resp = self._send({"cmd": "run", "hierarchy": hierarchy})
        if "error" in resp:
            return {"ok": False, "error": resp["error"]}
        if resp.get("status") == "busy":
            return {"ok": False, "error": "busy",
                    "session": resp.get("session", "")}
        if resp.get("status") == "running":
            return {"ok": True, "session": resp.get("session", "")}
        return {"ok": False, "error": f"unexpected response: {resp}"}

    def stop(self, session: str) -> dict:
        """
        Stop the current run.

        Parameters
        ----------
        session : str
            Session token returned by send_hierarchy().

        Returns
        -------
        {"ok": True | False, "error": str}
        """
        resp = self._send({"cmd": "stop", "session": session})
        if "error" in resp:
            return {"ok": False, "error": resp["error"]}
        if resp.get("ok") is True:
            return {"ok": True}
        return {"ok": False,
                "error": resp.get("error", f"unexpected response: {resp}")}

    def wait_until_idle(self, timeout: float = 30.0,
                        poll_interval: float = 1.0) -> bool:
        """
        Poll ping() until the robot reports idle or timeout expires.

        Returns True if robot became idle within timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.ping()
            if result.get("reachable") and result.get("status") == "idle":
                return True
            time.sleep(poll_interval)
        return False

    def reset(self) -> dict:
        """
        Force the mock BT server back to idle.
        No-op against a real Arduino — returns ok=False gracefully.
        """
        resp = self._send({"cmd": "reset"})
        if resp.get("ok") is True:
            return {"ok": True}
        return {"ok": False,
                "error": resp.get("error", "reset not supported on this device")}

    def __repr__(self) -> str:
        status = "connected" if self.is_connected() else "disconnected"
        return f"RobotBTClient({self._port!r}, baud={self._baud}, {status})"

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()


# ── BLE GATT client (bleak-based) ────────────────────────────────────────────

class RobotBLEClient:
    """
    BLE GATT client for robots running ethology_ble_robot.ino.

    Uses bleak for cross-platform BLE GATT access — no COM port, no pairing.
    Public API is identical to RobotBTClient so the two are interchangeable.

    BLE UUIDs (must match ethology_ble_robot.ino / CogBluetooth.h):
        Service:  19B20000-E8F2-537E-4F6C-D104768A1214
        CMD char: 19B20001-E8F2-537E-4F6C-D104768A1214  (write)
        DATA char:19B20002-E8F2-537E-4F6C-D104768A1214  (notify)

    Usage
    -----
        import asyncio
        from engine.bluetooth.robot_bt_client import RobotBLEClient

        # Synchronous wrapper (runs its own event loop):
        client = RobotBLEClient("RobotA")   # device name or MAC
        print(client.ping())
        print(client.send_hierarchy(["escape_front", "cruise_straight"]))
        ...
        print(client.stop(session))

    Dependencies
    ------------
        pip install bleak
    """

    SERVICE_UUID = "19b20000-e8f2-537e-4f6c-d104768a1214"
    CMD_UUID     = "19b20001-e8f2-537e-4f6c-d104768a1214"
    DATA_UUID    = "19b20002-e8f2-537e-4f6c-d104768a1214"

    SCAN_TIMEOUT = 8.0    # seconds to scan for device

    def __init__(self, device_name_or_address: str, timeout: float = 10.0):
        """
        Parameters
        ----------
        device_name_or_address : str
            BLE device name (e.g. "RobotA") or MAC address.
            Name matching is case-insensitive and substring-based.
        timeout : float
            Per-operation timeout in seconds.
        """
        self._target  = device_name_or_address
        self._timeout = timeout
        self._address = None    # resolved after first scan
        self._inbox: list = []  # responses received via notify

    def _run(self, coro):
        """Run an async coroutine synchronously."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in an async context — use run_coroutine_threadsafe
                import concurrent.futures
                fut = asyncio.run_coroutine_threadsafe(coro, loop)
                return fut.result(self._timeout + 2)
        except RuntimeError:
            pass
        return asyncio.run(coro)

    async def _scan_for_device(self):
        """Scan for BLE device by name or address. Returns address string."""
        try:
            from bleak import BleakScanner
        except ImportError:
            raise RuntimeError(
                "bleak is required.  Install with:  pip install bleak")

        async with BleakScanner() as scanner:
            await asyncio.sleep(self.SCAN_TIMEOUT)
            for d in scanner.discovered_devices:
                name = (d.name or "").upper()
                addr = (d.address or "").upper()
                t    = self._target.upper()
                if t in name or t == addr:
                    return d.address
        raise RuntimeError(
            f"BLE device '{self._target}' not found after "
            f"{self.SCAN_TIMEOUT}s scan.  "
            f"Make sure the Arduino is powered on and advertising."
        )

    async def _send_recv(self, obj: dict) -> dict:
        """Send a command and receive the response via BLE GATT."""
        import asyncio
        try:
            from bleak import BleakClient
        except ImportError:
            raise RuntimeError("bleak is required.  pip install bleak")

        if self._address is None:
            self._address = await self._scan_for_device()

        received: list = []

        def on_notify(_handle, data: bytearray):
            text = data.decode("utf-8", errors="replace").strip()
            for line in text.split("\n"):
                line = line.strip()
                if line:
                    try:
                        received.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        async with BleakClient(self._address,
                               timeout=self._timeout) as client:
            await client.start_notify(self.DATA_UUID, on_notify)
            cmd = json.dumps(obj) + "\n"
            await client.write_gatt_char(
                self.CMD_UUID, cmd.encode("utf-8"), response=True)
            # Wait up to timeout for a response
            deadline = asyncio.get_event_loop().time() + self._timeout
            while not received:
                if asyncio.get_event_loop().time() > deadline:
                    return {"error": "timeout — no response from robot"}
                await asyncio.sleep(0.05)
            await client.stop_notify(self.DATA_UUID)
            return received[0]

    def _cmd(self, obj: dict) -> dict:
        """Synchronous send-and-receive wrapper.
        Runs the async coroutine in a background thread with its own
        event loop — avoids conflicts with existing loops and works
        reliably on Windows with the WinRT BLE stack.
        """
        result_holder = []
        error_holder  = []

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result_holder.append(loop.run_until_complete(
                    self._send_recv(obj)))
            except Exception as e:
                error_holder.append(e)
            finally:
                loop.close()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=self._timeout + self.SCAN_TIMEOUT + 5)
        if error_holder:
            return {"error": str(error_holder[0])}
        if not result_holder:
            return {"error": "BLE operation timed out"}
        return result_holder[0]

    # ── Public API (identical to RobotBTClient) ───────────────────────────────

    def ping(self) -> dict:
        resp = self._cmd({"cmd": "ping"})
        if "error" in resp:
            return {"reachable": False, "error": resp["error"]}
        return {
            "reachable": True,
            "status":    resp.get("status", "unknown"),
            "session":   resp.get("session", ""),
        }

    def send_hierarchy(self, hierarchy: list) -> dict:
        resp = self._cmd({"cmd": "run", "hierarchy": hierarchy})
        if "error" in resp:
            return {"ok": False, "error": resp["error"]}
        if resp.get("status") == "busy":
            return {"ok": False, "error": "busy",
                    "session": resp.get("session", "")}
        if resp.get("status") == "running":
            return {"ok": True, "session": resp.get("session", "")}
        return {"ok": False, "error": f"unexpected response: {resp}"}

    def stop(self, session: str) -> dict:
        resp = self._cmd({"cmd": "stop", "session": session})
        if resp.get("ok") is True:
            return {"ok": True}
        return {"ok": False, "error": resp.get("error", str(resp))}

    def reset(self) -> dict:
        resp = self._cmd({"cmd": "reset"})
        if resp.get("ok") is True:
            return {"ok": True}
        return {"ok": False, "error": resp.get("error", str(resp))}

    def wait_until_idle(self, timeout: float = 30.0,
                        poll_interval: float = 1.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r = self.ping()
            if r.get("reachable") and r.get("status") == "idle":
                return True
            time.sleep(poll_interval)
        return False

    def __repr__(self) -> str:
        return f"RobotBLEClient({self._target!r})"


# ── Robot discovery (for the A/B picker) ─────────────────────────────────────
def scan_paw_robots(prefix: str = "Robot", timeout: float = 8.0) -> list:
    """Scan for PAW robots advertising over BLE and return a list of
    (name, address) for every device whose name starts with `prefix`.

    Used by the Hierarchy Builder's scan→pick→connect flow so the instructor
    can choose Robot A vs Robot B when both are powered on. Each robot's
    firmware advertises a distinct name (RobotA / RobotB) via
    BLE.setLocalName(); this enumerates whichever are in range.

    Returns [] if none found (caller shows a timeout / "make sure the robot is
    on and near the computer" message). Requires bleak (pip install bleak).

    IMPORTANT (Windows): bleak's WinRT backend needs the COM threading model to
    be MTA, but pygame/SDL puts the main thread in STA, which makes bleak fail
    with "Thread is configured for Windows GUI but callbacks are not working."
    So we run the whole scan on a DEDICATED worker thread (which defaults to
    MTA), never on pygame's STA main thread.
    """
    async def _scan():
        try:
            from bleak import BleakScanner
        except ImportError:
            raise RuntimeError("bleak is required.  Install: pip install bleak")
        found = {}
        async with BleakScanner() as scanner:
            await asyncio.sleep(timeout)
            for d in scanner.discovered_devices:
                name = d.name or ""
                if name.upper().startswith(prefix.upper()):
                    found[d.address] = name      # dedupe by address
        # sort by name so RobotA lists before RobotB
        return sorted(((n, a) for a, n in found.items()), key=lambda t: t[0])

    # Run on a separate thread with its own fresh event loop. A new (non-main)
    # thread is MTA by default on Windows, which is what bleak/WinRT requires.
    import concurrent.futures

    def _runner():
        # Some imported package (pywin32 / pythoncom, pulled in indirectly) may
        # have initialised this process's COM threading model to STA, which makes
        # bleak's WinRT backend fail with "Thread is configured for Windows GUI
        # but callbacks are not working." bleak provides uninitialize_sta() to
        # undo that side effect; call it before any bleak API. No-op / ImportError
        # on non-Windows or older bleak, which we ignore.
        try:
            from bleak.backends.winrt.util import uninitialize_sta
            uninitialize_sta()
        except Exception:
            pass
        return asyncio.run(_scan())

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_runner)
        return fut.result(timeout + 6)
