#!/usr/bin/env python3
"""
tft_graph_examples.py
=====================
Sixteen worked example graphs for the TFT terminal, exercising every feature
of :mod:`tft_graph_lib`.

Usage
-----
::

    python3 tft_graph_examples.py <host> [options]

    python3 tft_graph_examples.py 192.168.1.42
    python3 tft_graph_examples.py 192.168.1.42 --width 160 --height 128  # ST7735
    python3 tft_graph_examples.py 192.168.1.42 --demo 6   # log-X Bode plot
    python3 tft_graph_examples.py 192.168.1.42 --demo 9   # dual Y axes
    python3 tft_graph_examples.py 192.168.1.42 --demo 11  # bar chart (basic)
    python3 tft_graph_examples.py 192.168.1.42 --demo 14  # area chart
    python3 tft_graph_examples.py 192.168.1.42 --list     # show all demo names
    python3 tft_graph_examples.py 192.168.1.42 --require-responses

Demo index
----------
 1  Sine / Cosine          — two overlapping waves, legend
 2  Quadratic y=x^2        — positive-only range, markers
 3  Random scatter         — markers-only, no connecting lines
 4  Three series           — shared X axis, legend with 3 entries
 5  Linear with noise      — noisy data + clean trend line overlay
 6  Log X  (Bode plot)     — first-order low-pass filter, 10 Hz–100 kHz
 7  Log Y  (exponential)   — 2^x growth appears as a straight line
 8  Log X+Y (power law)    — y=x^1.5 appears as a straight line on log-log
 9  Dual Y axes            — temperature (left) and humidity (right)
10  Dual Y + log Y2        — voltage (linear left) and current (log right)
11  Bar chart (basic)      — monthly rainfall, single bar series
12  Bar chart (grouped)    — quarterly sales, two series side by side
13  Bar chart (neg values) — profit/loss, bars in both directions
14  Area chart (CPU)       — filled CPU usage over time
15  Area chart (network)   — two overlapping area series (RX and TX)
16  Bar + line overlay     — rainfall bars with temperature line on Y2
"""

from __future__ import annotations

import argparse
import math
import sys
from typing import List

# ── Library import ─────────────────────────────────────────────────────────────
try:
    from tft_graph_lib import Graph, GraphStyle, Series
except ImportError:
    sys.exit(
        "tft_graph_lib.py not found — place it in the same directory as this script."
    )


# =============================================================================
#  Example functions
#  Each function accepts a connected TFTTerminal instance and draws one graph.
# =============================================================================

# ── Line / scatter examples ────────────────────────────────────────────────────

def demo_sine_cosine(tft) -> None:
    """Two overlapping sine/cosine waves — legend, multiple series."""
    xs    = [i * 0.2 for i in range(32)]
    g = Graph(tft, title="sin / cos", x_label="Radians", y_label="Amp")
    g.add_series(xs, [math.sin(x) for x in xs], color="#00FFFF", label="sin")
    g.add_series(xs, [math.cos(x) for x in xs], color="#FF8800", label="cos")
    g.draw()


def demo_quadratic(tft) -> None:
    """y = x^2 — positive-only Y range, dot markers."""
    xs = list(range(-10, 11))
    g = Graph(tft, title="y = x^2", x_label="x", y_label="y")
    g.add_series(xs, [x * x for x in xs], color="#FFD700", label="x^2")
    g.draw()


def demo_random_scatter(tft) -> None:
    """Pseudo-random scatter plot — markers only, no connecting lines."""
    import random
    rng = random.Random(42)
    n   = 20
    g = Graph(tft, title="Scatter", x_label="x", y_label="y")
    g.add_series(
        [rng.uniform(0, 100) for _ in range(n)],
        [rng.uniform(-50, 50) for _ in range(n)],
        color="#FF4488", label="pts",
        draw_line=False, draw_markers=True, marker_radius=3,
    )
    g.draw()


def demo_multi_series(tft) -> None:
    """Three series sharing one X axis — legend with three entries."""
    xs = [i * 0.3 for i in range(22)]
    g = Graph(tft, title="3 series", x_label="t", y_label="val")
    g.add_series(xs, [math.sin(x) * 10 for x in xs], color="#00FFFF", label="A")
    g.add_series(xs, [math.cos(x) * 8  for x in xs], color="#FF8800", label="B")
    g.add_series(xs, [math.sin(2*x) * 5 for x in xs], color="#00FF44", label="C")
    g.draw()


def demo_linear_with_noise(tft) -> None:
    """Noisy linear data with a clean trend line overlay."""
    import random
    rng = random.Random(7)
    xs  = [i * 2.0 for i in range(25)]
    ys  = [0.5 * x - 10 + rng.gauss(0, 3) for x in xs]
    g = Graph(tft, title="Linear trend", x_label="x", y_label="y")
    g.add_series(xs, ys, color="#8888FF", label="data")
    g.add_series(
        [xs[0], xs[-1]],
        [0.5 * xs[0] - 10, 0.5 * xs[-1] - 10],
        color="#FF4444", label="trend", draw_markers=False,
    )
    g.draw()


# ── Log-scale examples ─────────────────────────────────────────────────────────

def demo_log_x(tft) -> None:
    """Bode-style magnitude plot: log X axis, linear Y.

    Models a first-order low-pass filter with a 1 kHz corner frequency.
    """
    fc    = 1000.0
    freqs = [10.0 * (10 ** (i * 4 / 19)) for i in range(20)]
    gains = [-20 * math.log10(math.sqrt(1 + (f / fc) ** 2)) for f in freqs]
    g = Graph(
        tft,
        title="Low-pass (1 kHz)",
        x_label="Hz", y_label="dB",
        log_x=True,
        x_min=10, x_max=100_000,
    )
    g.add_series(freqs, gains, color="#00FFFF", label="gain")
    g.draw()


def demo_log_y(tft) -> None:
    """Exponential growth (2^x) on a log Y axis — appears as a straight line."""
    xs = list(range(0, 11))
    g = Graph(tft, title="2^x (log Y)", x_label="x", y_label="2^x", log_y=True)
    g.add_series(xs, [2.0 ** x for x in xs], color="#FFD700", label="2^x")
    g.draw()


def demo_log_xy(tft) -> None:
    """Power law y = x^1.5 on log-log axes — appears as a straight line."""
    xs = [10.0 ** (i * 0.25) for i in range(17)]
    g = Graph(
        tft,
        title="y=x^1.5 (log-log)",
        x_label="x", y_label="y",
        log_x=True, log_y=True,
    )
    g.add_series(xs, [x ** 1.5 for x in xs], color="#FF4488", label="x^1.5")
    g.draw()


# ── Dual Y-axis examples ───────────────────────────────────────────────────────

def demo_dual_y(tft) -> None:
    """Daily temperature and relative humidity on independent Y axes."""
    times    = list(range(0, 25))
    temps    = [15 + 8  * math.sin((t - 6) * math.pi / 12) for t in times]
    humidity = [75 - 20 * math.sin((t - 6) * math.pi / 12) for t in times]
    g = Graph(
        tft,
        title="Temp & Humidity",
        x_label="Hour", y_label="degC", y2_label="%RH",
        y_min=0, y_max=30,
        y2_min=40, y2_max=100,
    )
    g.add_series(times, temps,    color="#FF4444", label="T",  y_axis=1)
    g.add_series(times, humidity, color="#44AAFF", label="RH", y_axis=2)
    g.draw()


def demo_dual_y_log(tft) -> None:
    """RC discharge: voltage on linear Y1, current on log Y2."""
    ts    = [i * 0.5 for i in range(21)]
    volts = [5 * math.exp(-t / 5)           for t in ts]
    amps  = [0.01 * math.exp(-t / 5) + 1e-4 for t in ts]
    g = Graph(
        tft,
        title="RC discharge",
        x_label="sec", y_label="V", y2_label="A",
        log_y2=True,
        y_min=0, y_max=6,
    )
    g.add_series(ts, volts, color="#FFD700", label="V", y_axis=1)
    g.add_series(ts, amps,  color="#FF8800", label="I", y_axis=2)
    g.draw()


# ── Bar chart examples ─────────────────────────────────────────────────────────

def demo_bar_basic(tft) -> None:
    """Monthly rainfall — single bar series."""
    months = list(range(1, 13))
    rain   = [45, 38, 52, 67, 80, 55, 30, 28, 48, 72, 60, 50]
    g = Graph(
        tft,
        title="Monthly Rainfall",
        x_label="Month", y_label="mm",
        y_min=0, y_max=100,
    )
    g.add_bar_series(months, rain, color="#4488FF",
                     outline_color="#8ABAFF", label="rain")
    g.draw()


def demo_bar_grouped(tft) -> None:
    """Quarterly sales — two bar series grouped side by side."""
    quarters = [1, 2, 3, 4]
    sales_a  = [120, 150, 130, 180]
    sales_b  = [ 90, 110, 160, 140]
    g = Graph(
        tft,
        title="Quarterly Sales",
        x_label="Quarter", y_label="Units",
        y_min=0, y_max=200,
    )
    g.add_bar_series(quarters, sales_a, color="#00FFCC",
                     outline_color="#AAFFEE", label="Product A")
    g.add_bar_series(quarters, sales_b, color="#FF8800",
                     outline_color="#FFCC88", label="Product B")
    g.draw()


def demo_bar_negative(tft) -> None:
    """Profit / loss — bars extend both upward and downward from zero."""
    months = list(range(1, 9))
    profit = [20, -10, 35, 15, -5, 40, 25, -8]
    g = Graph(
        tft,
        title="Profit / Loss",
        x_label="Month", y_label="$k",
        y_min=-20, y_max=50,
    )
    g.add_bar_series(months, profit, color="#44FF88",
                     outline_color="#AAFFCC", label="profit")
    g.draw()


# ── Area chart examples ────────────────────────────────────────────────────────

def demo_area_basic(tft) -> None:
    """CPU usage over time — filled area from the zero baseline."""
    n   = 20
    ts  = [i * 0.5 for i in range(n)]
    cpu = [30 + 20 * math.sin(t * 0.8) + 10 * math.sin(t * 2.1) for t in ts]
    g = Graph(
        tft,
        title="CPU Usage",
        x_label="sec", y_label="%",
        y_min=0, y_max=80,
    )
    g.add_area_series(ts, cpu, color="#224488",
                      outline_color="#4488FF", label="CPU")
    g.draw()


def demo_area_stacked(tft) -> None:
    """Network traffic — two overlapping area series (RX and TX)."""
    n  = 24
    ts = list(range(n))
    rx = [max(0, 5 + 8 * math.sin(t * math.pi / 6) + 3 * math.sin(t * math.pi / 2))
          for t in ts]
    tx = [max(0, 3 + 4 * math.cos(t * math.pi / 6) + 2 * math.cos(t * math.pi / 3))
          for t in ts]
    g = Graph(
        tft,
        title="Network Traffic",
        x_label="Hour", y_label="MB/s",
        y_min=0, y_max=20,
    )
    g.add_area_series(ts, rx, color="#004488", outline_color="#0088FF", label="RX")
    g.add_area_series(ts, tx, color="#440044", outline_color="#FF44FF", label="TX")
    g.draw()


# ── Mixed chart type example ───────────────────────────────────────────────────

def demo_bar_and_line(tft) -> None:
    """Rainfall bars (Y1) with temperature line overlay (Y2).

    Combines bar and line series on independent axes.
    """
    months   = list(range(1, 13))
    rainfall = [45, 38, 52, 67, 80, 55, 30, 28, 48, 72, 60, 50]
    temp     = [ 5,  6,  9, 13, 17, 21, 23, 22, 18, 14,  9,  6]
    g = Graph(
        tft,
        title="Rain & Temp",
        x_label="Month", y_label="mm", y2_label="degC",
        y_min=0, y_max=100,
        y2_min=0, y2_max=30,
    )
    g.add_bar_series(months, rainfall, color="#4488FF",
                     outline_color="#88AAFF", label="Rain", y_axis=1)
    g.add_series(months, temp, color="#FF4444",
                 label="Temp", draw_markers=True, marker_radius=2, y_axis=2)
    g.draw()


# =============================================================================
#  Demo registry
# =============================================================================

DEMOS = [
    ( 1, "Sine / Cosine",          demo_sine_cosine),
    ( 2, "Quadratic y=x^2",        demo_quadratic),
    ( 3, "Random scatter",         demo_random_scatter),
    ( 4, "Three series",           demo_multi_series),
    ( 5, "Linear with noise",      demo_linear_with_noise),
    ( 6, "Log X  (Bode plot)",     demo_log_x),
    ( 7, "Log Y  (exponential)",   demo_log_y),
    ( 8, "Log X+Y (power law)",    demo_log_xy),
    ( 9, "Dual Y axes",            demo_dual_y),
    (10, "Dual Y + log Y2",        demo_dual_y_log),
    (11, "Bar chart (basic)",      demo_bar_basic),
    (12, "Bar chart (grouped)",    demo_bar_grouped),
    (13, "Bar chart (neg values)", demo_bar_negative),
    (14, "Area chart (CPU)",       demo_area_basic),
    (15, "Area chart (network)",   demo_area_stacked),
    (16, "Bar + line overlay",     demo_bar_and_line),
]


# =============================================================================
#  CLI
# =============================================================================

def main() -> int:
    p = argparse.ArgumentParser(
        description="TFT graph examples",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("host", nargs="?",
                   help="ESP8266 IP address or hostname")
    p.add_argument("--port",    type=int,   default=8888)
    p.add_argument("--width",   type=int,   default=320,
                   help="Display width in pixels  (default 320 for ILI9341 landscape)")
    p.add_argument("--height",  type=int,   default=240,
                   help="Display height in pixels (default 240 for ILI9341 landscape)")
    p.add_argument("--timeout", type=float, default=5.0,
                   help="Socket timeout in seconds (default 5)")
    p.add_argument("--require-responses", action="store_true",
                   help="Wait for TFTTerminal responses/acks after commands.")
    p.add_argument("--pause",   type=float, default=3.0,
                   help="Seconds to hold each graph on screen (default 3)")
    p.add_argument("--demo",    type=int,   default=None, metavar="N",
                   help="Run only demo N (1-16).  Omit to run all.")
    p.add_argument("--list",    action="store_true",
                   help="Print all demo names and exit.")
    args = p.parse_args()

    if args.list:
        for n, name, _ in DEMOS:
            print(f"  {n:2d}  {name}")
        return 0

    if not args.host:
        p.error("host is required unless --list is used")

    try:
        from tft_terminal import TFTTerminal
    except ImportError:
        print("tft_terminal.py not found — place it in the same directory.",
              file=sys.stderr)
        return 1

    print(f"Connecting to {args.host}:{args.port} ({args.width}x{args.height}) ...")
    try:
        tft = TFTTerminal(
            args.host, args.port,
            width=args.width, height=args.height,
            timeout=args.timeout,
            require_responses=args.require_responses,
        )
    except Exception as exc:
        print(f"Connection failed: {exc}", file=sys.stderr)
        return 1

    import time
    to_run = DEMOS if args.demo is None else [d for d in DEMOS if d[0] == args.demo]
    if not to_run:
        print(f"No demo with number {args.demo}.  Use --list to see valid numbers.",
              file=sys.stderr)
        return 1

    with tft:
        for i, (n, name, fn) in enumerate(to_run, 1):
            print(f"  [{i}/{len(to_run)}] Demo {n}: {name} ...", end=" ", flush=True)
            try:
                fn(tft)
                print("OK")
            except Exception as exc:
                print(f"FAILED: {exc}")
            if i < len(to_run):
                time.sleep(args.pause)

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
