"""
tft_terminal.py  —  ESP8266 Edition
======================================
Python 3 client library for the ESP8266 TCP TFT Terminal firmware.

Works with ``esp8266_tcp_terminal.ino`` (v9  — ESP8266).

Provides :class:`TFTTerminal` — a class that communicates with the ESP8266
over TCP using newline-delimited JSON commands.

All parameters are validated *before* the JSON is sent:

* Type errors   →  :exc:`TypeError`
* Value / range errors  →  :exc:`ValueError`
* Network or server errors  →  :exc:`TFTError`

The server's JSON response is checked on every call; a ``{"ok":false,...}``
reply raises :exc:`TFTError` containing the firmware's own error message.


Display types and default sizes
--------------------------------
Pass a ``display`` keyword to :class:`TFTTerminal` so that the Python client
automatically uses the correct default width and height.

Supported display names (case-insensitive) and their default portrait
resolutions:

+------------------+----------+--------+--------+------------------+
| Name             | Driver   | W (px) | H (px) | Notes            |
+==================+==========+========+========+==================+
| ``ili9341``      | ILI9341  |   240  |   320  | SPI colour TFT   |
+------------------+----------+--------+--------+------------------+
| ``st7796``       | ST7796S  |   320  |   480  | SPI colour TFT   |
+------------------+----------+--------+--------+------------------+
| ``st7735``       | ST7735   |   128  |   160  | SPI colour TFT   |
+------------------+----------+--------+--------+------------------+
| ``st7735_128``   | ST7735   |   128  |   128  | square variant   |
+------------------+----------+--------+--------+------------------+

The firmware initialises the display in the rotation set by ``TFT_ROTATION``
(default ``1`` = landscape).  Call :meth:`TFTTerminal.sync` after connecting
to read the live width/height from the device.


Colour notation
---------------
Colors may be supplied in any of the following forms:

* ``"#RGB"``      e.g. ``"#F00"``  (expands to ``"#FF0000"``)
* ``"#RRGGBB"``   e.g. ``"#FF0000"``
* ``"#RRGGBBAA"`` — alpha is silently stripped (display is opaque)
* A plain name from the built-in :data:`COLORS` palette, e.g. ``"red"``
* An ``(r, g, b)`` tuple of ints 0-255
* A raw ``int`` 0-65535 (RGB-565 value forwarded as-is)


JSON COMMAND REFERENCE
-----------------------
Every command is a single-line JSON object terminated with ``\\n``.
Responses:  ``{"ok":true}``  or  ``{"ok":false,"error":"<message>"}``

::

    {"cmd":"text","x":10,"y":20,"text":"Hello","color":"#FF0000","size":2}
    {"cmd":"clear"}
    {"cmd":"bg","color":"#001122"}
    {"cmd":"fill_rect","x":10,"y":10,"w":100,"h":50,"color":"#00FF00"}
    {"cmd":"rect","x":10,"y":10,"w":100,"h":50,"color":"#00FF00"}
    {"cmd":"fill_circle","x":120,"y":160,"r":40,"color":"#0000FF"}
    {"cmd":"circle","x":120,"y":160,"r":40,"color":"#0000FF"}
    {"cmd":"hline","x":0,"y":60,"len":200,"color":"#FFFFFF"}
    {"cmd":"vline","x":60,"y":0,"len":120,"color":"#FFFFFF"}
    {"cmd":"line","x0":0,"y0":0,"x1":319,"y1":239,"color":"#FFFFFF"}
    {"cmd":"fill_screen","color":"#001830"}
    {"cmd":"rotation","r":1}   →  {"ok":true,"w":<w>,"h":<h>}
    {"cmd":"pixel","x":120,"y":160,"color":"#FF0000"}
    {"cmd":"triangle","x0":10,"y0":10,"x1":50,"y1":80,"x2":90,"y2":10,"color":"#FFFFFF"}
    {"cmd":"fill_triangle","x0":10,"y0":10,"x1":50,"y1":80,"x2":90,"y2":10,"color":"#FFFFFF"}
    {"cmd":"rounded_rect","x":10,"y":10,"w":100,"h":60,"r":8,"color":"#00FF00"}
    {"cmd":"fill_rounded_rect","x":10,"y":10,"w":100,"h":60,"r":8,"color":"#00FF00"}
    {"cmd":"brightness","v":128}
    {"cmd":"ping"}             →  {"ok":true,"uptime_ms":<ms>}
    {"cmd":"query"}            →  {"ok":true,"w":…,"h":…,"rotation":…,"bg":…,"free_heap":…}


Usage example
-------------
::

    from tft_terminal import TFTTerminal

    with TFTTerminal("192.168.1.42", display="ili9341") as tft:
        tft.sync()
        tft.set_background("#001830")
        tft.clear()
        tft.fill_rect(0, 0, 80, 60, "red")
        tft.text(4, 10, "Hello ESP8266!", color="cyan", size=2)
        state = tft.query()
        print(f"free heap: {state['free_heap']} B")


Buffered / fire-and-forget mode
---------------------------------
By default every command waits for a ``{"ok":true}`` acknowledgement from the
firmware before returning.  Call :meth:`TFTTerminal.set_ack` to disable
acknowledgement checking::

    with TFTTerminal("192.168.1.42") as tft:
        tft.set_ack(False)
        tft.clear()
        tft.fill_rect(0, 0, 80, 60, "red")
        tft.set_ack(True)

Or use the context manager form::

    with tft.ack_disabled():
        tft.clear()
        tft.fill_rect(0, 0, 80, 60, "red")

.. note::
    :meth:`set_rotation`, :meth:`ping`, :meth:`query`, and :meth:`sync`
    **always** read their firmware response regardless of the ack setting,
    because they depend on the data returned.
"""

from __future__ import annotations

import json
import re
import socket
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Generator, Optional, Tuple, Union

# ─── Public types ─────────────────────────────────────────────────────────────

#: Any value accepted wherever a colour is expected.
ColorSpec = Union[str, Tuple[int, int, int], int]


class TFTError(Exception):
    """Raised when the firmware returns ``{"ok": false, ...}``
    or when a network-level problem occurs."""


# ─── Display profile registry ─────────────────────────────────────────────────

class DisplayProfile:
    """Metadata for one supported display type.

    Attributes
    ----------
    driver:
        Short driver name as it appears in firmware (e.g. ``"ILI9341"``).
    portrait_w, portrait_h:
        Native portrait-mode pixel dimensions.
    """
    __slots__ = ("driver", "portrait_w", "portrait_h")

    def __init__(
        self,
        driver: str,
        portrait_w: int,
        portrait_h: int,
    ) -> None:
        self.driver     = driver
        self.portrait_w = portrait_w
        self.portrait_h = portrait_h

    def dimensions_for_rotation(self, rotation: int) -> Tuple[int, int]:
        """Return ``(width, height)`` after applying *rotation* (0-3)."""
        if rotation in (1, 3):  # landscape orientations
            return self.portrait_h, self.portrait_w
        return self.portrait_w, self.portrait_h

    def __repr__(self) -> str:
        return (
            f"DisplayProfile({self.driver!r}, "
            f"{self.portrait_w}×{self.portrait_h}, spi)"
        )


#: Registry of all display types supported by the firmware.
DISPLAY_PROFILES: Dict[str, DisplayProfile] = {
    "ili9341":    DisplayProfile("ILI9341",  240, 320),
    "st7796":     DisplayProfile("ST7796",   320, 480),
    "st7735":     DisplayProfile("ST7735",   128, 160),
    "st7735_128": DisplayProfile("ST7735",   128, 128),   # square variant
}

#: Default display — matches firmware default ``#define DISPLAY_ILI9341``.
_DEFAULT_DISPLAY = "ili9341"
#: Default rotation — matches firmware ``#define TFT_ROTATION 1`` (landscape).
_DEFAULT_ROTATION = 1

#: Greeting substring recognised as the ESP8266 firmware.
_VALID_GREETING = "ESP8266 TCP terminal"


def _profile_for(name: str) -> DisplayProfile:
    """Look up a :class:`DisplayProfile` by name (case-insensitive).

    Raises
    ------
    ValueError
        If *name* is not a recognised display name.
    """
    key = name.strip().lower()
    if key not in DISPLAY_PROFILES:
        known = ", ".join(sorted(DISPLAY_PROFILES))
        raise ValueError(
            f"Unknown display type {name!r}.  Known types: {known}"
        )
    return DISPLAY_PROFILES[key]


# ─── Named colour palette ─────────────────────────────────────────────────────

#: Convenient named colours.  Extend or replace as needed.
COLORS: Dict[str, str] = {
    "black":    "#000000",
    "white":    "#FFFFFF",
    "red":      "#FF0000",
    "green":    "#00FF00",
    "blue":     "#0000FF",
    "yellow":   "#FFFF00",
    "cyan":     "#00FFFF",
    "magenta":  "#FF00FF",
    "orange":   "#FF8800",
    "purple":   "#880088",
    "pink":     "#FF69B4",
    "gold":     "#FFD700",
    "silver":   "#C0C0C0",
    "navy":     "#000080",
    "teal":     "#008080",
    "lime":     "#00FF80",
    "maroon":   "#800000",
    "olive":    "#808000",
    "gray":     "#808080",
    "grey":     "#808080",
    "darkgray": "#404040",
    "darkgrey": "#404040",
}

# ─── Internal colour helpers ──────────────────────────────────────────────────

_HEX_RE = re.compile(r'^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$')


def _normalise_color(value: ColorSpec, param_name: str = "color") -> Union[str, int]:
    """Validate and normalise *value* to a ``"#RRGGBB"`` string or raw int."""
    # ── raw int (RGB-565) ────────────────────────────────────────────────────
    if isinstance(value, int) and not isinstance(value, bool):
        if not (0 <= value <= 0xFFFF):
            raise ValueError(
                f"Parameter '{param_name}': raw int colour {value!r} must be "
                f"in range 0-65535 (RGB-565)."
            )
        return value

    # ── (r, g, b) tuple ─────────────────────────────────────────────────────
    if isinstance(value, (tuple, list)):
        if len(value) != 3:
            raise ValueError(
                f"Parameter '{param_name}': colour tuple must have exactly 3 "
                f"components (r, g, b), got {len(value)}."
            )
        r, g, b = value
        for component, label in ((r, "r"), (g, "g"), (b, "b")):
            if not isinstance(component, int) or isinstance(component, bool):
                raise TypeError(
                    f"Parameter '{param_name}': tuple component '{label}' must "
                    f"be an int, got {type(component).__name__}."
                )
            if not (0 <= component <= 255):
                raise ValueError(
                    f"Parameter '{param_name}': tuple component '{label}'={component} "
                    f"must be in range 0-255."
                )
        return f"#{r:02X}{g:02X}{b:02X}"

    # ── string ───────────────────────────────────────────────────────────────
    if isinstance(value, str):
        lower = value.lower()
        if lower in COLORS:
            return COLORS[lower]
        if not _HEX_RE.match(value):
            names = ", ".join(sorted(COLORS))
            raise ValueError(
                f"Parameter '{param_name}': colour string {value!r} is not a valid "
                f"#RGB / #RRGGBB hex string and is not a known colour name.\n"
                f"Known names: {names}"
            )
        digits = value[1:]
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        elif len(digits) == 8:
            digits = digits[:6]   # drop alpha
        return f"#{digits.upper()}"

    raise TypeError(
        f"Parameter '{param_name}': expected a colour string, (r,g,b) tuple, or int; "
        f"got {type(value).__name__}."
    )


# ─── Internal parameter validators ───────────────────────────────────────────

def _check_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(
            f"Parameter '{name}' must be an int, got {type(value).__name__}."
        )
    return value  # type: ignore[return-value]


def _check_coord(value: object, name: str, maximum: int) -> int:
    v = _check_int(value, name)
    if not (0 <= v < maximum):
        raise ValueError(
            f"Parameter '{name}'={v} is outside the display bounds [0, {maximum - 1}]."
        )
    return v


def _check_dim(value: object, name: str) -> int:
    v = _check_int(value, name)
    if v <= 0:
        raise ValueError(
            f"Parameter '{name}'={v} must be a positive integer (> 0)."
        )
    return v


def _check_size(value: object) -> int:
    v = _check_int(value, "size")
    if not (1 <= v <= 8):
        raise ValueError(
            f"Parameter 'size'={v} must be in the range [1, 8]."
        )
    return v


def _check_text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(
            f"Parameter 'text' must be a str, got {type(value).__name__}."
        )
    if not value:
        raise ValueError("Parameter 'text' must not be an empty string.")
    return value


# ─── Ack context manager ──────────────────────────────────────────────────────

class _AckDisabledContext:
    __slots__ = ("_terminal", "_saved")

    def __init__(self, terminal: "TFTTerminal") -> None:
        self._terminal = terminal
        self._saved: bool = True

    def __enter__(self) -> "TFTTerminal":
        self._saved = self._terminal.ack_enabled
        self._terminal._ack_enabled = False
        return self._terminal

    def __exit__(self, *_) -> None:
        self._terminal._ack_enabled = self._saved


# ─── Main class ───────────────────────────────────────────────────────────────

class TFTTerminal:
    """TCP client for the ESP8266 TFT Terminal firmware.

    Parameters
    ----------
    host:
        IP address or hostname of the device.
    port:
        TCP port the firmware listens on (default ``8888``).
    display:
        Display type name (case-insensitive) from :data:`DISPLAY_PROFILES`,
        e.g. ``"ili9341"``, ``"st7796"``, ``"st7735"``.  Determines the
        default portrait-mode resolution used for bounds checking before
        :meth:`sync` is called.  Defaults to ``"ili9341"``.
    rotation:
        Initial rotation (0-3, default ``1`` = landscape) used to derive the
        starting width/height from the display profile.
    width:
        Override width in pixels.  When given together with *height*, the
        display profile dimensions are ignored for bounds checking.
    height:
        Override height in pixels.  Must be supplied together with *width*.
    timeout:
        Socket timeout in seconds (default ``5.0``).
    auto_connect:
        If ``True`` (default), connect immediately on construction.

    Examples
    --------
    ::

        with TFTTerminal("192.168.1.42", display="ili9341") as tft:
            tft.sync()
            tft.clear()
            tft.text(0, 0, "Hello!")

    Manual width/height override::

        tft = TFTTerminal("192.168.1.42", width=320, height=240)
    """

    def __init__(
        self,
        host: str,
        port: int = 8888,
        *,
        display:      Optional[str] = None,
        rotation:     int = _DEFAULT_ROTATION,
        width:        Optional[int] = None,
        height:       Optional[int] = None,
        timeout:      Optional[float] = None,
        auto_connect: bool = True,
    ) -> None:
        if not isinstance(host, str) or not host:
            raise ValueError("'host' must be a non-empty string.")
        if not isinstance(port, int) or not (1 <= port <= 65535):
            raise ValueError(f"'port' must be an integer in [1, 65535], got {port!r}.")

        self._timeout = float(timeout) if timeout is not None else 5.0

        # ── Resolve display profile and initial dimensions ────────────────────
        if display is not None:
            self._profile: Optional[DisplayProfile] = _profile_for(display)
        else:
            self._profile = DISPLAY_PROFILES[_DEFAULT_DISPLAY]

        if rotation not in (0, 1, 2, 3):
            raise ValueError(f"'rotation' must be 0, 1, 2, or 3; got {rotation!r}.")

        if width is not None or height is not None:
            if not isinstance(width, int) or width <= 0:
                raise ValueError(f"'width' must be a positive int, got {width!r}.")
            if not isinstance(height, int) or height <= 0:
                raise ValueError(f"'height' must be a positive int, got {height!r}.")
            self._width  = width
            self._height = height
        else:
            self._width, self._height = self._profile.dimensions_for_rotation(rotation)

        self._host  = host
        self._port  = port
        self._sock: Optional[socket.socket] = None
        self._fh:   Optional[object] = None
        self._ack_enabled: bool = True

        if auto_connect:
            self.connect()

    # ── Connection management ─────────────────────────────────────────────────

    def connect(self) -> None:
        """Open the TCP connection to the device.

        Reads and validates the firmware greeting.

        Raises
        ------
        TFTError
            If the connection cannot be established.
        """
        if self._sock is not None:
            return  # already connected
        try:
            self._sock = socket.create_connection(
                (self._host, self._port), timeout=self._timeout
            )
            self._fh = self._sock.makefile("r", encoding="utf-8")
            greeting = self._readline()
            self._handle_greeting(greeting)
        except OSError as exc:
            self._sock = None
            self._fh   = None
            raise TFTError(
                f"Cannot connect to {self._host}:{self._port} — {exc}"
            ) from exc

    def _handle_greeting(self, greeting: dict) -> None:
        """Parse and validate the firmware greeting."""
        info = greeting.get("info", "")

        if not info:
            # No info field — old or custom firmware; warn and continue.
            if any(k in greeting for k in ("ok", "error")):
                warnings.warn(
                    f"Firmware sent a non-greeting first line: {greeting!r}. "
                    f"Continuing — protocol may still be compatible.",
                    stacklevel=3,
                )
            return

        if _VALID_GREETING not in info:
            warnings.warn(
                f"Unexpected firmware greeting: {info!r}. "
                f"Expected a greeting containing: {_VALID_GREETING!r}. "
                f"Continuing — protocol may still be compatible.",
                stacklevel=3,
            )

    def disconnect(self) -> None:
        """Close the TCP connection gracefully."""
        if self._fh is not None:
            try:
                self._fh.close()  # type: ignore[union-attr]
            except OSError:
                pass
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self._fh   = None

    @property
    def connected(self) -> bool:
        """``True`` if the socket appears to be open."""
        return self._sock is not None

    def __enter__(self) -> "TFTTerminal":
        if not self.connected:
            self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    def __repr__(self) -> str:
        state   = "connected" if self.connected else "disconnected"
        profile = self._profile.driver if self._profile else "custom"
        return (
            f"TFTTerminal({self._host!r}, port={self._port}, "
            f"display={profile!r}, "
            f"size={self._width}×{self._height}, {state})"
        )

    # ── Display geometry ──────────────────────────────────────────────────────

    @property
    def width(self) -> int:
        """Display width used for bounds checking."""
        return self._width

    @property
    def height(self) -> int:
        """Display height used for bounds checking."""
        return self._height

    @property
    def profile(self) -> Optional[DisplayProfile]:
        """The :class:`DisplayProfile` for this display, or ``None`` if custom."""
        return self._profile

    def set_display_size(self, width: int, height: int) -> None:
        """Update the locally-known display dimensions without sending any command.

        Normally you should call :meth:`sync` instead; this method exists for
        cases where you know the size from out-of-band information.
        """
        if not isinstance(width, int) or width <= 0:
            raise ValueError(f"'width' must be a positive int, got {width!r}.")
        if not isinstance(height, int) or height <= 0:
            raise ValueError(f"'height' must be a positive int, got {height!r}.")
        self._width  = width
        self._height = height

    def sync(self) -> dict:
        """Query the firmware and synchronise local width/height state.

        Calls :meth:`query` internally and updates :attr:`width` and
        :attr:`height` from the device's authoritative reply.  Call this once
        after connecting to ensure bounds checks match the live rotation.

        Returns
        -------
        dict
            The same dictionary returned by :meth:`query`.
        """
        return self.query()

    # ── Acknowledgement mode ──────────────────────────────────────────────────

    @property
    def ack_enabled(self) -> bool:
        """``True`` if acknowledgements are being read after each command."""
        return self._ack_enabled

    def set_ack(self, enabled: bool) -> None:
        """Enable or disable firmware acknowledgement checking.

        Parameters
        ----------
        enabled:
            ``True``  — block until ``{"ok":true}`` or raise on error.
            ``False`` — fire-and-forget (do not read any response).
        """
        if not isinstance(enabled, bool):
            raise TypeError(
                f"'enabled' must be a bool, got {type(enabled).__name__}."
            )
        self._ack_enabled = enabled

    def ack_disabled(self) -> _AckDisabledContext:
        """Context manager that temporarily disables acknowledgement checking.

        Saves and restores the previous :attr:`ack_enabled` state on exit.

        Example
        -------
        ::

            with tft.ack_disabled():
                tft.clear()
                tft.fill_rect(0, 0, 80, 60, "red")
        """
        return _AckDisabledContext(self)

    # ── Low-level I/O ─────────────────────────────────────────────────────────

    def _readline(self) -> dict:
        """Read one newline-terminated JSON object from the socket."""
        if self._fh is None:
            raise TFTError("Not connected.")
        try:
            raw = self._fh.readline()   # type: ignore[union-attr]
        except OSError as exc:
            raise TFTError(f"Read error: {exc}") from exc
        if not raw:
            raise TFTError("Connection closed by remote host.")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TFTError(
                f"Invalid JSON received from firmware: {raw!r} — {exc}"
            ) from exc

    def _send_raw_always(self, payload: dict) -> dict:
        """Send *payload* and **always** block for the response (ignores ack flag)."""
        if self._sock is None:
            raise TFTError("Not connected — call connect() first.")
        line = json.dumps(payload, separators=(",", ":")) + "\n"
        try:
            self._sock.sendall(line.encode("utf-8"))
        except OSError as exc:
            raise TFTError(f"Send error: {exc}") from exc
        return self._readline()

    def _send_raw(self, payload: dict) -> dict:
        """Send *payload*; respect :attr:`ack_enabled` (returns ``{}`` when off)."""
        if self._sock is None:
            raise TFTError("Not connected — call connect() first.")
        line = json.dumps(payload, separators=(",", ":")) + "\n"
        try:
            self._sock.sendall(line.encode("utf-8"))
        except OSError as exc:
            raise TFTError(f"Send error: {exc}") from exc
        if not self._ack_enabled:
            return {}
        return self._readline()

    def _send(self, payload: dict) -> None:
        """Serialise, send, and (when ack enabled) check the firmware response.

        Raises :exc:`TFTError` on ``{"ok":false,...}``.
        """
        resp = self._send_raw(payload)
        if self._ack_enabled and not resp.get("ok", False):
            raise TFTError(
                f"Firmware error for command {payload.get('cmd')!r}: "
                f"{resp.get('error', 'unknown error')}"
            )

    # ── Raw pass-through ──────────────────────────────────────────────────────

    def send_raw_text(
        self,
        text: str,
        *,
        validate_json:   bool = True,
        expect_response: bool = True,
    ) -> dict:
        """Send a raw text string directly over the TCP stream.

        A newline is appended automatically.  Pass ``validate_json=False`` to
        bypass JSON checking.

        Parameters
        ----------
        text:
            Non-empty string to transmit.
        validate_json:
            If ``True`` (default), parse *text* as JSON before sending.
        expect_response:
            If ``True`` (default), read and return the firmware's response.

        Returns
        -------
        dict
            Parsed response, or ``{}`` when *expect_response* is ``False``.
        """
        if not isinstance(text, str):
            raise TypeError(f"'text' must be a str, got {type(text).__name__}.")
        if not text.strip():
            raise ValueError("'text' must not be empty or whitespace-only.")

        if validate_json:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"'text' is not valid JSON: {exc}\n"
                    f"Pass validate_json=False to skip this check."
                ) from exc
            if not isinstance(parsed, (dict, list)):
                raise ValueError(
                    f"'text' must be a JSON object {{…}} or array [{{…}}, …]; "
                    f"got {type(parsed).__name__}.\n"
                    f"Pass validate_json=False to send non-JSON text."
                )

        if self._sock is None:
            raise TFTError("Not connected — call connect() first.")
        wire = text if text.endswith("\n") else text + "\n"
        try:
            self._sock.sendall(wire.encode("utf-8"))
        except OSError as exc:
            raise TFTError(f"Send error: {exc}") from exc

        if not expect_response or not self._ack_enabled:
            return {}
        resp = self._readline()
        if not resp.get("ok", False):
            raise TFTError(
                f"Firmware error for raw command: {resp.get('error', 'unknown error')}"
            )
        return resp

    def send_raw_bytes(
        self,
        data: bytes,
        *,
        expect_response: bool = False,
    ) -> dict:
        """Send pre-encoded bytes directly over the TCP stream (no framing added).

        Parameters
        ----------
        data:
            Non-empty bytes to write to the socket verbatim.
        expect_response:
            If ``True``, read and return the firmware's response.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(
                f"'data' must be bytes or bytearray, got {type(data).__name__}."
            )
        if not data:
            raise ValueError("'data' must not be empty.")
        if self._sock is None:
            raise TFTError("Not connected — call connect() first.")
        try:
            self._sock.sendall(bytes(data))
        except OSError as exc:
            raise TFTError(f"Send error: {exc}") from exc
        if not expect_response or not self._ack_enabled:
            return {}
        resp = self._readline()
        if not resp.get("ok", False):
            raise TFTError(
                f"Firmware error for raw bytes: {resp.get('error', 'unknown error')}"
            )
        return resp

    # ── Public display commands ───────────────────────────────────────────────

    def clear(self) -> None:
        """Fill the screen with the current background colour."""
        self._send({"cmd": "clear"})

    def set_background(self, color: ColorSpec) -> None:
        """Set the background colour used by :meth:`clear`.

        Does **not** immediately repaint the screen.

        Parameters
        ----------
        color:
            New background colour.
        """
        c = _normalise_color(color, "color")
        self._send({"cmd": "bg", "color": c})

    def text(
        self,
        x: int,
        y: int,
        text: str,
        *,
        color: ColorSpec = "white",
        size: int = 1,
    ) -> None:
        """Draw a text string at pixel position *(x, y)*.

        Parameters
        ----------
        x, y:
            Top-left pixel coordinates.
        text:
            Non-empty string to render.
        color:
            Text colour (default white).
        size:
            GFX text size multiplier 1-8 (default 1).
        """
        self._send({
            "cmd":   "text",
            "x":     _check_coord(x, "x", self._width),
            "y":     _check_coord(y, "y", self._height),
            "text":  _check_text(text),
            "size":  _check_size(size),
            "color": _normalise_color(color, "color"),
        })

    # ── Rectangles ────────────────────────────────────────────────────────────

    def fill_rect(self, x: int, y: int, w: int, h: int, color: ColorSpec) -> None:
        """Draw a filled rectangle."""
        self._send(self._build_rect("fill_rect", x, y, w, h, color))

    def rect(self, x: int, y: int, w: int, h: int, color: ColorSpec) -> None:
        """Draw an outline rectangle (unfilled)."""
        self._send(self._build_rect("rect", x, y, w, h, color))

    def _build_rect(
        self, cmd: str, x: int, y: int, w: int, h: int, color: ColorSpec
    ) -> dict:
        return {
            "cmd":   cmd,
            "x":     _check_coord(x, "x", self._width),
            "y":     _check_coord(y, "y", self._height),
            "w":     _check_dim(w, "w"),
            "h":     _check_dim(h, "h"),
            "color": _normalise_color(color, "color"),
        }

    # ── Circles ───────────────────────────────────────────────────────────────

    def fill_circle(self, x: int, y: int, r: int, color: ColorSpec) -> None:
        """Draw a filled circle centred at *(x, y)* with radius *r*."""
        self._send(self._build_circle("fill_circle", x, y, r, color))

    def circle(self, x: int, y: int, r: int, color: ColorSpec) -> None:
        """Draw an outline circle centred at *(x, y)* with radius *r*."""
        self._send(self._build_circle("circle", x, y, r, color))

    def _build_circle(
        self, cmd: str, x: int, y: int, r: int, color: ColorSpec
    ) -> dict:
        return {
            "cmd":   cmd,
            "x":     _check_coord(x, "x", self._width),
            "y":     _check_coord(y, "y", self._height),
            "r":     _check_dim(r, "r"),
            "color": _normalise_color(color, "color"),
        }

    # ── Lines ─────────────────────────────────────────────────────────────────

    def hline(self, x: int, y: int, length: int, color: ColorSpec) -> None:
        """Draw a horizontal line (hardware-accelerated ``drawFastHLine``)."""
        self._send({
            "cmd":   "hline",
            "x":     _check_coord(x, "x", self._width),
            "y":     _check_coord(y, "y", self._height),
            "len":   _check_dim(length, "length"),
            "color": _normalise_color(color, "color"),
        })

    def vline(self, x: int, y: int, length: int, color: ColorSpec) -> None:
        """Draw a vertical line (hardware-accelerated ``drawFastVLine``)."""
        self._send({
            "cmd":   "vline",
            "x":     _check_coord(x, "x", self._width),
            "y":     _check_coord(y, "y", self._height),
            "len":   _check_dim(length, "length"),
            "color": _normalise_color(color, "color"),
        })

    def line(
        self, x0: int, y0: int, x1: int, y1: int, color: ColorSpec
    ) -> None:
        """Draw an arbitrary line between two points (Bresenham).

        For perfectly horizontal/vertical lines prefer :meth:`hline` /
        :meth:`vline` — they use faster hardware paths.
        """
        self._send({
            "cmd":   "line",
            "x0":    _check_coord(x0, "x0", self._width),
            "y0":    _check_coord(y0, "y0", self._height),
            "x1":    _check_coord(x1, "x1", self._width),
            "y1":    _check_coord(y1, "y1", self._height),
            "color": _normalise_color(color, "color"),
        })

    # ── Fill ──────────────────────────────────────────────────────────────────

    def fill_screen(self, color: ColorSpec) -> None:
        """Fill the entire screen without altering the background colour."""
        self._send({
            "cmd":   "fill_screen",
            "color": _normalise_color(color, "color"),
        })

    # ── Pixel ─────────────────────────────────────────────────────────────────

    def pixel(self, x: int, y: int, color: ColorSpec) -> None:
        """Draw a single pixel at *(x, y)*."""
        self._send({
            "cmd":   "pixel",
            "x":     _check_coord(x, "x", self._width),
            "y":     _check_coord(y, "y", self._height),
            "color": _normalise_color(color, "color"),
        })

    # ── Triangles ─────────────────────────────────────────────────────────────

    def triangle(
        self,
        x0: int, y0: int,
        x1: int, y1: int,
        x2: int, y2: int,
        color: ColorSpec,
    ) -> None:
        """Draw an outline triangle defined by three vertices."""
        self._send(
            self._build_triangle("triangle", x0, y0, x1, y1, x2, y2, color)
        )

    def fill_triangle(
        self,
        x0: int, y0: int,
        x1: int, y1: int,
        x2: int, y2: int,
        color: ColorSpec,
    ) -> None:
        """Draw a filled triangle defined by three vertices."""
        self._send(
            self._build_triangle("fill_triangle", x0, y0, x1, y1, x2, y2, color)
        )

    def _build_triangle(
        self,
        cmd: str,
        x0: int, y0: int,
        x1: int, y1: int,
        x2: int, y2: int,
        color: ColorSpec,
    ) -> dict:
        return {
            "cmd":   cmd,
            "x0":    _check_coord(x0, "x0", self._width),
            "y0":    _check_coord(y0, "y0", self._height),
            "x1":    _check_coord(x1, "x1", self._width),
            "y1":    _check_coord(y1, "y1", self._height),
            "x2":    _check_coord(x2, "x2", self._width),
            "y2":    _check_coord(y2, "y2", self._height),
            "color": _normalise_color(color, "color"),
        }

    # ── Rounded rectangles ────────────────────────────────────────────────────

    def rounded_rect(
        self, x: int, y: int, w: int, h: int, r: int, color: ColorSpec
    ) -> None:
        """Draw an outline rectangle with rounded corners."""
        self._send(
            self._build_rounded_rect("rounded_rect", x, y, w, h, r, color)
        )

    def fill_rounded_rect(
        self, x: int, y: int, w: int, h: int, r: int, color: ColorSpec
    ) -> None:
        """Draw a filled rectangle with rounded corners."""
        self._send(
            self._build_rounded_rect("fill_rounded_rect", x, y, w, h, r, color)
        )

    def _build_rounded_rect(
        self, cmd: str, x: int, y: int, w: int, h: int, r: int, color: ColorSpec
    ) -> dict:
        return {
            "cmd":   cmd,
            "x":     _check_coord(x, "x", self._width),
            "y":     _check_coord(y, "y", self._height),
            "w":     _check_dim(w, "w"),
            "h":     _check_dim(h, "h"),
            "r":     _check_dim(r, "r"),
            "color": _normalise_color(color, "color"),
        }

    # ── Convenience helpers ───────────────────────────────────────────────────

    def border(self, color: ColorSpec, thickness: int = 1) -> None:
        """Draw a rectangular border around the entire screen.

        Parameters
        ----------
        color:
            Border colour.
        thickness:
            Number of concentric outline rectangles (default 1).
        """
        t  = _check_dim(thickness, "thickness")
        cv = _normalise_color(color, "color")
        for i in range(t):
            self._send({
                "cmd":   "rect",
                "x":     i,
                "y":     i,
                "w":     self._width  - 2 * i,
                "h":     self._height - 2 * i,
                "color": cv,
            })

    # ── Rotation ──────────────────────────────────────────────────────────────

    def set_rotation(self, r: int) -> None:
        """Set the display rotation and update local width/height bounds.

        The firmware responds with ``{"ok":true,"w":<W>,"h":<H>}``; this
        method parses those values and updates :attr:`width` and :attr:`height`.

        Parameters
        ----------
        r:
            0 = portrait, 1 = landscape, 2 = portrait-flip, 3 = landscape-flip.
        """
        rv = _check_int(r, "r")
        if rv not in (0, 1, 2, 3):
            raise ValueError(
                f"Parameter 'r'={rv} is invalid; must be 0, 1, 2, or 3."
            )
        resp = self._send_raw_always({"cmd": "rotation", "r": rv})
        if not resp.get("ok", False):
            raise TFTError(
                f"Firmware error for rotation={rv}: {resp.get('error', 'unknown')}"
            )
        try:
            self._width  = int(resp["w"])
            self._height = int(resp["h"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TFTError(
                f"rotation response missing 'w'/'h' fields: {resp}"
            ) from exc

    @property
    def rotation_map(self) -> dict:
        """Mapping of rotation index → human-readable description."""
        return {
            0: "portrait",
            1: "landscape",
            2: "portrait-flip",
            3: "landscape-flip",
        }

    # ── Utility commands ──────────────────────────────────────────────────────

    def ping(self) -> int:
        """Send a no-op round-trip to measure latency and keep the connection alive.

        Returns
        -------
        int
            The device's ``millis()`` value when the ping was processed.
        """
        resp = self._send_raw_always({"cmd": "ping"})
        if not resp.get("ok", False):
            raise TFTError(
                f"Firmware error for ping: {resp.get('error', 'unknown')}"
            )
        try:
            return int(resp["uptime_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TFTError(
                f"ping response missing 'uptime_ms' field: {resp}"
            ) from exc

    def query(self) -> dict:
        """Query the current display state and synchronise local dimensions.

        The firmware replies with::

            {"ok":true,"w":<w>,"h":<h>,"rotation":<0-3>,"bg":<uint16>,"free_heap":<bytes>}

        This method updates :attr:`width` and :attr:`height` from the
        device's authoritative values.

        Returns
        -------
        dict
            Keys: ``w``, ``h``, ``rotation``, ``bg``, ``free_heap``.
        """
        resp = self._send_raw_always({"cmd": "query"})
        if not resp.get("ok", False):
            raise TFTError(
                f"Firmware error for query: {resp.get('error', 'unknown')}"
            )
        try:
            result = {
                "w":         int(resp["w"]),
                "h":         int(resp["h"]),
                "rotation":  int(resp["rotation"]),
                "bg":        int(resp["bg"]),
                "free_heap": int(resp["free_heap"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise TFTError(
                f"query response missing expected fields: {resp}"
            ) from exc

        self._width  = result["w"]
        self._height = result["h"]
        return result

    def set_brightness(self, value: int) -> None:
        """Set the backlight brightness (0-255).

        The firmware calls ``analogWrite(TFT_BL_PIN, value)``.  The firmware
        must have been compiled with ``TFT_BL_PIN`` set to a valid GPIO (not
        ``-1``); otherwise :exc:`TFTError` is raised.

        Parameters
        ----------
        value:
            PWM duty cycle: 0 = off, 255 = full brightness.
        """
        v = _check_int(value, "value")
        if not (0 <= v <= 255):
            raise ValueError(
                f"Parameter 'value'={v} must be in the range [0, 255]."
            )
        self._send({"cmd": "brightness", "v": v})
