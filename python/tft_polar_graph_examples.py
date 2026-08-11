#!/usr/bin/env python3
"""
tft_polar_graph_examples.py
===========================
Worked example polar graphs for the ESP8266 TCP TFT Terminal.

Usage
-----
::

    python3 tft_polar_graph_examples.py <host> [options]

    python3 tft_polar_graph_examples.py 192.168.1.42
    python3 tft_polar_graph_examples.py 192.168.1.42 --demo 1
    python3 tft_polar_graph_examples.py 192.168.1.42 --display st7735 --rotation 1
    python3 tft_polar_graph_examples.py 192.168.1.42 --require-responses
    python3 tft_polar_graph_examples.py --list

Demo index
----------
 1  Polar rose        - r = |sin(4 theta)|
 2  Cardioid          - r = 1 - cos(theta)
 3  Limacon           - r = 0.65 + 0.55 cos(theta)
 4  Archimedean spiral - r grows with theta
 5  Compass sweep     - clockwise degrees with north as zero
 6  Overlay           - two polar curves on one graph
"""

from __future__ import annotations

import argparse
import math
import sys
import time

try:
    from tft_polar_graph_lib import PolarGraph, PolarGraphStyle
except ImportError:
    sys.exit(
        "tft_polar_graph_lib.py not found. Place it in the same directory "
        "as this script."
    )


def demo_polar_rose(tft) -> None:
    """Classic rose curve using degree input."""
    graph = PolarGraph(
        tft,
        title="Polar Rose",
        r_label="r",
        theta_units="deg",
        r_min=0,
        r_max=1.1,
    )
    graph.add_function(
        lambda deg: abs(math.sin(math.radians(4 * deg))),
        samples=241,
        color="#00FFFF",
        label="sin4t",
    )
    graph.draw()


def demo_cardioid(tft) -> None:
    """Heart-shaped cardioid using radians."""
    graph = PolarGraph(
        tft,
        title="Cardioid",
        theta_units="rad",
        r_min=0,
        r_max=2.1,
    )
    graph.add_function(
        lambda theta: 1.0 - math.cos(theta),
        samples=241,
        color="#FF4488",
        label="1-cos",
    )
    graph.draw()


def demo_limacon(tft) -> None:
    """Limacon with a small inner dimple."""
    graph = PolarGraph(
        tft,
        title="Limacon",
        theta_units="rad",
        r_min=0,
        r_max=1.4,
    )
    graph.add_function(
        lambda theta: 0.65 + 0.55 * math.cos(theta),
        samples=241,
        color="#FF8800",
        label="limacon",
    )
    graph.draw()


def demo_spiral(tft) -> None:
    """Archimedean spiral over two turns."""
    theta = [i * 4.0 * math.pi / 240 for i in range(241)]
    radius = [value / (4.0 * math.pi) for value in theta]

    graph = PolarGraph(
        tft,
        title="Spiral",
        theta_units="rad",
        angle_zero="E",
        r_min=0,
        r_max=1.0,
    )
    graph.add_series(theta, radius, color="#00FF44", label="r=t")
    graph.draw()


def demo_compass_sweep(tft) -> None:
    """Clockwise compass-style plot with zero degrees at north."""
    angles = list(range(0, 360, 15))
    radius = [
        0.35 + 0.55 * (0.5 + 0.5 * math.sin(math.radians(3 * angle)))
        for angle in angles
    ]

    style = PolarGraphStyle(angle_spokes=8, radial_ticks=3)
    graph = PolarGraph(
        tft,
        title="Compass",
        theta_units="deg",
        angle_zero="N",
        clockwise=True,
        r_min=0,
        r_max=1.0,
        style=style,
    )
    graph.add_series(
        angles,
        radius,
        color="#FFD700",
        label="sweep",
        draw_markers=True,
        marker_radius=2,
        close=True,
    )
    graph.draw()


def demo_overlay(tft) -> None:
    """Two polar functions drawn on the same grid."""
    graph = PolarGraph(
        tft,
        title="Overlay",
        theta_units="deg",
        r_min=0,
        r_max=1.3,
    )
    graph.add_function(
        lambda deg: 0.55 + 0.35 * math.sin(math.radians(3 * deg)),
        samples=241,
        color="#00FFFF",
        label="A",
    )
    graph.add_function(
        lambda deg: 0.65 + 0.30 * math.cos(math.radians(5 * deg)),
        samples=241,
        color="#FF8800",
        label="B",
    )
    graph.draw()


DEMOS = [
    (1, "Polar rose", demo_polar_rose),
    (2, "Cardioid", demo_cardioid),
    (3, "Limacon", demo_limacon),
    (4, "Archimedean spiral", demo_spiral),
    (5, "Compass sweep", demo_compass_sweep),
    (6, "Overlay", demo_overlay),
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="TFT polar graph examples",
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
    parser.add_argument("--pause", type=float, default=3.0,
                        help="Seconds to hold each graph (default: 3)")
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
                fn(tft)
                print("OK")
            except Exception as exc:
                print(f"FAILED: {exc}")
                return 1

            if index < len(to_run) and args.pause > 0:
                time.sleep(args.pause)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
