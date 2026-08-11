#!/usr/bin/env python3
"""
tft_gauge_examples.py
=====================
Worked example gauges for the ESP8266 TCP TFT Terminal.

Usage
-----
::

    python3 tft_gauge_examples.py <host> [options]

    python3 tft_gauge_examples.py 192.168.1.42
    python3 tft_gauge_examples.py 192.168.1.42 --demo 1
    python3 tft_gauge_examples.py 192.168.1.42 --display st7735 --rotation 1
    python3 tft_gauge_examples.py 192.168.1.42 --require-responses
    python3 tft_gauge_examples.py --list

Demo index
----------
 1  Dashboard        - bar gauges plus circular gauges
 2  Bar gauges       - horizontal and vertical bars
 3  Arc gauges       - circular/arc gauges with needles
 4  Warning levels   - gauges changing colour at thresholds
 5  Live sweep       - animated readings without full redraws
"""

from __future__ import annotations

import argparse
import math
import sys
import time

try:
    from tft_gauge import ArcGauge, BarGauge, GaugeStyle
except ImportError:
    sys.exit(
        "tft_gauge.py not found. Place it in the same directory as this script."
    )


def _screen_size(tft) -> tuple[int, int]:
    return int(getattr(tft, "width", 320)), int(getattr(tft, "height", 240))


def _clear(tft, color: str = "#000820") -> None:
    tft.fill_screen(color)


def _sleep(delay: float) -> None:
    if delay > 0:
        time.sleep(delay)


def demo_dashboard(tft, *, steps: int = 30, delay: float = 0.08) -> None:
    """Mixed dashboard layout with incremental updates."""
    w, h = _screen_size(tft)
    style = GaugeStyle(bg_color="#000820", fill_color="#00D0FF")
    _clear(tft, style.bg_color)

    tft.text(8, 6, "GAUGE DASHBOARD", color="#FFFFFF", size=1)

    left_w = max(90, min(150, w // 2 - 22))
    bar1 = BarGauge(
        tft, 10, 34, left_w, 16,
        label="TEMP", units="C", min_value=0, max_value=100,
        warning_at=70, danger_at=85, style=style,
    )
    bar2 = BarGauge(
        tft, 10, 74, left_w, 16,
        label="BAT", units="%", min_value=0, max_value=100,
        warning_at=80, danger_at=92, style=style,
    )
    bar3 = BarGauge(
        tft, 10, 114, left_w, 16,
        label="LOAD", units="%", min_value=0, max_value=100,
        warning_at=65, danger_at=90, style=style,
    )

    arc_r = max(28, min(58, min(w - left_w - 44, h - 54) // 2))
    arc_x = min(w - arc_r - 12, left_w + 54)
    arc_y = max(arc_r + 18, min(h - arc_r - 8, h // 2 + 8))
    arc1 = ArcGauge(
        tft, arc_x, arc_y, arc_r,
        label="FAN", units="%", min_value=0, max_value=100,
        warning_at=75, danger_at=92, style=style,
    )

    bar1.draw(22)
    bar2.draw(55)
    bar3.draw(18)
    arc1.draw(35)

    for i in range(steps):
        phase = i / max(1, steps - 1)
        bar1.update(22 + 58 * phase)
        bar2.update(55 + 40 * abs(math.sin(phase * math.pi)))
        bar3.update(18 + 75 * phase)
        arc1.update(35 + 55 * abs(math.sin(phase * math.pi * 1.4)))
        _sleep(delay)


def demo_bar_gauges(tft, *, steps: int = 40, delay: float = 0.06) -> None:
    """Horizontal and vertical bar gauges."""
    w, h = _screen_size(tft)
    style = GaugeStyle(bg_color="#020610", fill_color="#44FF88")
    _clear(tft, style.bg_color)
    tft.text(8, 6, "BAR GAUGES", color="#FFFFFF", size=1)

    bar_w = max(90, min(w - 80, 190))
    horizontal = BarGauge(
        tft, 12, 36, bar_w, 18,
        label="HORIZONTAL", units="%", min_value=0, max_value=100,
        warning_at=70, danger_at=90, style=style,
    )
    vertical = BarGauge(
        tft, min(w - 36, 220), 48, 22, max(70, h - 72),
        label="VERT", units="%", min_value=0, max_value=100,
        vertical=True, warning_at=70, danger_at=90,
        value_box=(min(w - 70, 186), h - 18, 48, 10),
        style=style,
    )

    horizontal.draw(0)
    vertical.draw(0)
    for i in range(steps):
        value = 100 * i / max(1, steps - 1)
        horizontal.update(value)
        vertical.update(value)
        _sleep(delay)


def demo_arc_gauges(tft, *, steps: int = 36, delay: float = 0.07) -> None:
    """Two circular/arc gauges with different sweep ranges."""
    w, h = _screen_size(tft)
    style = GaugeStyle(bg_color="#000820", fill_color="#FFD700")
    _clear(tft, style.bg_color)
    tft.text(8, 6, "ARC GAUGES", color="#FFFFFF", size=1)

    r = max(28, min(55, (min(w, h) - 34) // 3))
    left = ArcGauge(
        tft, max(r + 10, w // 3), max(r + 28, h // 2), r,
        label="RPM", units="k", min_value=0, max_value=8,
        warning_at=5.8, danger_at=7.0, style=style,
    )
    right = ArcGauge(
        tft, min(w - r - 10, 2 * w // 3), max(r + 28, h // 2), r,
        label="PSI", units="", min_value=0, max_value=60,
        start_angle=180, end_angle=0,
        warning_at=45, danger_at=55, style=style,
    )

    left.draw(0)
    right.draw(0)
    for i in range(steps):
        phase = i / max(1, steps - 1)
        left.update(8 * phase)
        right.update(60 * abs(math.sin(phase * math.pi)))
        _sleep(delay)


def demo_warning_levels(tft, *, steps: int = 45, delay: float = 0.06) -> None:
    """Gauge colours change as warning and danger thresholds are crossed."""
    w, h = _screen_size(tft)
    style = GaugeStyle(
        bg_color="#080808",
        fill_color="#00FF44",
        warning_color="#FFB000",
        danger_color="#FF3030",
    )
    _clear(tft, style.bg_color)
    tft.text(8, 6, "WARNING LEVELS", color="#FFFFFF", size=1)

    bar = BarGauge(
        tft, 12, 38, max(90, w - 74), 18,
        label="PRESS", units=" PSI", min_value=0, max_value=120,
        warning_at=80, danger_at=105, style=style,
    )
    arc = ArcGauge(
        tft, w // 2, min(h - 50, max(86, h // 2 + 28)),
        max(30, min(58, min(w, h) // 4)),
        label="TEMP", units="C", min_value=0, max_value=120,
        warning_at=75, danger_at=100, style=style,
    )

    bar.draw(0)
    arc.draw(0)
    for i in range(steps):
        value = 120 * i / max(1, steps - 1)
        bar.update(value)
        arc.update(value)
        _sleep(delay)


def demo_live_sweep(tft, *, steps: int = 90, delay: float = 0.04) -> None:
    """Continuous sweep demo showing update-only animation."""
    w, h = _screen_size(tft)
    style = GaugeStyle(bg_color="#000820", fill_color="#00FFFF")
    _clear(tft, style.bg_color)
    tft.text(8, 6, "LIVE SWEEP", color="#FFFFFF", size=1)

    radius = max(32, min(70, min(w, h) // 3))
    arc = ArcGauge(
        tft, w // 2, max(radius + 26, h // 2), radius,
        label="SIGNAL", units="%", min_value=0, max_value=100,
        warning_at=70, danger_at=90, style=style,
    )
    bar = BarGauge(
        tft, 12, h - 26, max(80, w - 74), 16,
        label="", units="%", min_value=0, max_value=100,
        warning_at=70, danger_at=90, style=style,
    )

    arc.draw(50)
    bar.draw(50)
    for i in range(steps):
        value = 50 + 50 * math.sin(i * math.tau / max(1, steps - 1))
        arc.update(value)
        bar.update(value)
        _sleep(delay)


DEMOS = [
    (1, "Dashboard", demo_dashboard),
    (2, "Bar gauges", demo_bar_gauges),
    (3, "Arc gauges", demo_arc_gauges),
    (4, "Warning levels", demo_warning_levels),
    (5, "Live sweep", demo_live_sweep),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="TFT gauge examples",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("host", nargs="?", help="ESP8266 IP address or hostname")
    parser.add_argument("--port", type=int, default=8888)
    parser.add_argument("--display", default="ili9341",
                        help="Display profile name (default: ili9341)")
    parser.add_argument("--rotation", type=int, default=3,
                        help="Display rotation 0-3 (default: 3)")
    parser.add_argument("--timeout", type=float, default=5.0,
                        help="Socket timeout in seconds (default: 5)")
    parser.add_argument("--require-responses", action="store_true",
                        help="Wait for TFTTerminal responses/acks after commands.")
    parser.add_argument("--pause", type=float, default=1.0,
                        help="Seconds to hold between demos (default: 1)")
    parser.add_argument("--delay", type=float, default=0.06,
                        help="Animation delay per update in seconds (default: 0.06)")
    parser.add_argument("--steps", type=int, default=40,
                        help="Animation update count per demo (default: 40)")
    parser.add_argument("--demo", type=int, default=None, metavar="N",
                        help="Run only demo N. Omit to run all.")
    parser.add_argument("--list", action="store_true",
                        help="Print all demo names and exit.")
    args = parser.parse_args()

    if args.list:
        for number, name, _ in DEMOS:
            print(f"  {number:2d}  {name}")
        return 0

    if not args.host:
        parser.error("host is required unless --list is used")

    try:
        from tft_terminal import TFTTerminal
    except ImportError:
        print("tft_terminal.py not found. Place it in the same directory.",
              file=sys.stderr)
        return 1

    to_run = DEMOS if args.demo is None else [
        demo for demo in DEMOS if demo[0] == args.demo
    ]
    if not to_run:
        print(f"No demo with number {args.demo}. Use --list to see valid numbers.",
              file=sys.stderr)
        return 1

    print(f"Connecting to {args.host}:{args.port} ...")
    try:
        tft = TFTTerminal(
            args.host,
            port=args.port,
            display=args.display,
            rotation=args.rotation,
            timeout=args.timeout,
            require_responses=args.require_responses,
        )
    except Exception as exc:
        print(f"Connection failed: {exc}", file=sys.stderr)
        return 1

    with tft:
        for index, (number, name, fn) in enumerate(to_run, start=1):
            print(f"[{index}/{len(to_run)}] Demo {number}: {name} ...",
                  end=" ", flush=True)
            try:
                fn(tft, steps=max(1, args.steps), delay=max(0.0, args.delay))
                print("OK")
            except Exception as exc:
                print(f"FAILED: {exc}")
                return 1

            if index < len(to_run):
                _sleep(max(0.0, args.pause))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
