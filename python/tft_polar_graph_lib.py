#!/usr/bin/env python3
"""
tft_polar_graph_lib.py
======================
Reusable polar graph renderer for the ESP8266 TCP TFT Terminal.

The library draws directly through ``TFTTerminal`` primitives, so it does not
need Pillow, NumPy, matplotlib, or any firmware changes.

Usage::

    import math
    from tft_terminal import TFTTerminal
    from tft_polar_graph_lib import PolarGraph

    theta = [i * 2 * math.pi / 120 for i in range(121)]
    radius = [1.0 + 0.35 * math.sin(5 * t) for t in theta]

    with TFTTerminal("192.168.1.42") as tft:
        g = PolarGraph(tft, title="Rose", theta_units="rad",
                       r_min=0, r_max=1.4)
        g.add_series(theta, radius, color="#00FFFF", label="r")
        g.draw()
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple, Union


_DEFAULT_COLOURS = [
    "#00FFFF",
    "#FF8800",
    "#00FF44",
    "#FF4488",
    "#FFD700",
    "#8888FF",
    "#FF4444",
    "#44FF88",
]

_ANGLE_ZEROES = {
    "E": 0.0,
    "NE": math.pi / 4.0,
    "N": math.pi / 2.0,
    "NW": 3.0 * math.pi / 4.0,
    "W": math.pi,
    "SW": 5.0 * math.pi / 4.0,
    "S": 3.0 * math.pi / 2.0,
    "SE": 7.0 * math.pi / 4.0,
}


@dataclass
class PolarSeries:
    """A single polar data series.

    Parameters
    ----------
    theta_data:
        Angle values. Interpreted as degrees or radians by ``PolarGraph``.
    r_data:
        Radius values. Must be the same length as ``theta_data``.
    color:
        Line and marker colour.
    label:
        Legend label. Empty labels are not shown.
    draw_line:
        Connect adjacent points with line segments.
    draw_markers:
        Draw a filled marker at each point.
    marker_radius:
        Marker radius in pixels.
    close:
        Connect the final point back to the first point.
    """
    theta_data: List[float]
    r_data: List[float]
    color: str = "#00FFFF"
    label: str = ""
    draw_line: bool = True
    draw_markers: bool = False
    marker_radius: int = 2
    close: bool = False

    def __post_init__(self) -> None:
        if len(self.theta_data) != len(self.r_data):
            raise ValueError(
                f"PolarSeries '{self.label}': theta_data length "
                f"({len(self.theta_data)}) must equal r_data length "
                f"({len(self.r_data)})."
            )
        if not self.theta_data:
            raise ValueError(f"PolarSeries '{self.label}': data must not be empty.")
        if self.marker_radius < 1:
            raise ValueError(
                f"PolarSeries '{self.label}': marker_radius must be >= 1."
            )


@dataclass
class PolarGraphStyle:
    """Visual style settings for a polar graph."""
    bg_color: str = "#000820"
    plot_bg_color: str = "#020818"
    axis_color: str = "#AAAAAA"
    grid_color: str = "#224466"
    label_color: str = "#888888"
    title_color: str = "#FFFFFF"
    legend_bg_color: str = "#000820"
    radial_ticks: int = 4
    angle_spokes: int = 12
    title_size: int = 1
    label_size: int = 1


def _fmt_num(value: float) -> str:
    av = abs(value)
    if av >= 1000 or (0 < av < 0.01):
        return f"{value:.1e}"
    if av >= 100:
        return f"{value:.0f}"
    if av >= 10:
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _normalise_angle_zero(value: Union[str, float, int], units: str) -> float:
    if isinstance(value, str):
        key = value.strip().upper()
        if key not in _ANGLE_ZEROES:
            raise ValueError(
                "angle_zero must be one of E, NE, N, NW, W, SW, S, SE, "
                "or a numeric angle."
            )
        return _ANGLE_ZEROES[key]
    return math.radians(float(value)) if units == "deg" else float(value)


def _axis_range(
    values: Sequence[float],
    explicit_min: Optional[float],
    explicit_max: Optional[float],
) -> Tuple[float, float]:
    lo = min(values) if explicit_min is None else float(explicit_min)
    hi = max(values) if explicit_max is None else float(explicit_max)
    if lo == hi:
        pad = abs(lo) * 0.1 or 1.0
        lo -= pad
        hi += pad
    if explicit_min is None and explicit_max is None:
        pad = (hi - lo) * 0.05
        lo -= pad
        hi += pad
    return lo, hi


class PolarGraph:
    """Polar graph renderer for the TFT TCP terminal.

    ``PolarGraph`` maps radius values onto concentric rings and angle values
    onto radial spokes. It supports multiple series, optional markers, simple
    legends, configurable angle units, clockwise or counter-clockwise angle
    direction, and explicit or automatic radius ranges.
    """
    _CHAR_W = 6
    _CHAR_H = 8

    def __init__(
        self,
        tft,
        *,
        title: str = "",
        r_label: str = "",
        theta_units: str = "deg",
        angle_zero: Union[str, float, int] = "E",
        clockwise: bool = False,
        r_min: Optional[float] = None,
        r_max: Optional[float] = None,
        margin_left: int = 22,
        margin_right: int = 16,
        margin_top: int = 18,
        margin_bottom: int = 18,
        style: Optional[PolarGraphStyle] = None,
    ) -> None:
        units = theta_units.lower()
        if units not in ("deg", "rad"):
            raise ValueError("theta_units must be 'deg' or 'rad'.")

        self._tft = tft
        self.title = title
        self.r_label = r_label
        self.theta_units = units
        self.angle_zero = _normalise_angle_zero(angle_zero, units)
        self.clockwise = bool(clockwise)
        self.r_min = r_min
        self.r_max = r_max
        self.style = style or PolarGraphStyle()
        self._series: List[PolarSeries] = []

        self._x0 = max(0, margin_left)
        self._y0 = max(0, margin_top)
        self._x1 = max(self._x0 + 1, tft.width - margin_right - 1)
        self._y1 = max(self._y0 + 1, tft.height - margin_bottom - 1)
        self._cx = (self._x0 + self._x1) // 2
        self._cy = (self._y0 + self._y1) // 2
        self._radius_px = max(
            1,
            min(self._x1 - self._x0, self._y1 - self._y0) // 2,
        )

    def add_series(
        self,
        theta_data: Sequence[float],
        r_data: Sequence[float],
        *,
        color: Optional[str] = None,
        label: str = "",
        draw_line: bool = True,
        draw_markers: bool = False,
        marker_radius: int = 2,
        close: bool = False,
    ) -> "PolarGraph":
        """Add a polar data series and return ``self`` for chaining."""
        if color is None:
            color = _DEFAULT_COLOURS[len(self._series) % len(_DEFAULT_COLOURS)]
        self._series.append(PolarSeries(
            theta_data=[float(v) for v in theta_data],
            r_data=[float(v) for v in r_data],
            color=color,
            label=label,
            draw_line=draw_line,
            draw_markers=draw_markers,
            marker_radius=marker_radius,
            close=close,
        ))
        return self

    def add_function(
        self,
        fn: Callable[[float], float],
        *,
        theta_start: float = 0.0,
        theta_stop: Optional[float] = None,
        samples: int = 181,
        color: Optional[str] = None,
        label: str = "",
        draw_markers: bool = False,
        close: bool = True,
    ) -> "PolarGraph":
        """Sample ``fn(theta)`` into a series.

        ``theta_start`` and ``theta_stop`` use the graph's ``theta_units``.
        When omitted, ``theta_stop`` is one full turn after ``theta_start``.
        """
        if samples < 2:
            raise ValueError("samples must be >= 2.")
        full_turn = 360.0 if self.theta_units == "deg" else 2.0 * math.pi
        stop = theta_start + full_turn if theta_stop is None else theta_stop
        theta = [
            theta_start + (stop - theta_start) * i / (samples - 1)
            for i in range(samples)
        ]
        r = [float(fn(v)) for v in theta]
        return self.add_series(
            theta,
            r,
            color=color,
            label=label,
            draw_markers=draw_markers,
            close=close,
        )

    def draw(self) -> None:
        """Render the polar graph on the TFT display."""
        if not self._series:
            raise ValueError("No series added. Call add_series() first.")

        st = self.style
        all_r = [value for series in self._series for value in series.r_data]
        r_min, r_max = _axis_range(all_r, self.r_min, self.r_max)
        if r_min < 0 < r_max:
            origin_r = 0.0
        else:
            origin_r = r_min

        self._tft.fill_screen(st.bg_color)
        self._tft.fill_circle(self._cx, self._cy, self._radius_px, st.plot_bg_color)

        if self.title:
            tx = max(0, (self._tft.width - len(self.title) * self._CHAR_W) // 2)
            self._tft.text(tx, 3, self.title, color=st.title_color,
                           size=st.title_size)

        self._draw_grid(r_min, r_max, origin_r)

        for series in self._series:
            self._draw_series(series, r_min, r_max)

        self._draw_labels(r_min, r_max)
        self._draw_legend()

    def _draw_grid(self, r_min: float, r_max: float, origin_r: float) -> None:
        st = self.style
        tft = self._tft
        ticks = max(1, st.radial_ticks)
        spokes = max(4, st.angle_spokes)

        for i in range(1, ticks + 1):
            value = r_min + (r_max - r_min) * i / ticks
            radius = self._map_radius(value, r_min, r_max)
            if radius > 0:
                tft.circle(self._cx, self._cy, radius, st.grid_color)

        origin_radius = self._map_radius(origin_r, r_min, r_max)
        if origin_radius > 0:
            tft.circle(self._cx, self._cy, origin_radius, st.axis_color)

        for i in range(spokes):
            theta = i * 2.0 * math.pi / spokes
            x, y = self._point_from_math_angle(theta, self._radius_px)
            tft.line(self._cx, self._cy, x, y, st.grid_color)

        tft.circle(self._cx, self._cy, self._radius_px, st.axis_color)

    def _draw_labels(self, r_min: float, r_max: float) -> None:
        st = self.style
        ticks = max(1, st.radial_ticks)
        for i in range(1, ticks + 1):
            value = r_min + (r_max - r_min) * i / ticks
            label = _fmt_num(value)
            radius = self._map_radius(value, r_min, r_max)
            lx = min(self._tft.width - len(label) * self._CHAR_W - 1,
                     self._cx + radius + 2)
            ly = max(0, min(self._cy - self._CHAR_H // 2,
                            self._tft.height - self._CHAR_H - 1))
            if lx >= 0:
                self._tft.text(lx, ly, label, color=st.label_color,
                               size=st.label_size)

        if self.r_label:
            lx = max(0, self._cx - self._radius_px)
            ly = max(0, self._cy + self._radius_px + 2)
            if ly + self._CHAR_H <= self._tft.height:
                self._tft.text(lx, ly, self.r_label, color=st.title_color,
                               size=st.label_size)

        spoke_count = max(4, self.style.angle_spokes)
        for i in range(spoke_count):
            raw = i * (360.0 / spoke_count)
            label = f"{int(raw)}"
            angle_delta = math.radians(raw)
            angle = (
                self.angle_zero - angle_delta
                if self.clockwise
                else self.angle_zero + angle_delta
            )
            x, y = self._point_from_math_angle(angle, self._radius_px + 9)
            lx = max(0, min(x - len(label) * self._CHAR_W // 2,
                            self._tft.width - len(label) * self._CHAR_W - 1))
            ly = max(0, min(y - self._CHAR_H // 2,
                            self._tft.height - self._CHAR_H - 1))
            self._tft.text(lx, ly, label, color=st.label_color,
                           size=st.label_size)

    def _draw_series(
        self,
        series: PolarSeries,
        r_min: float,
        r_max: float,
    ) -> None:
        points = [
            self._map_point(theta, radius, r_min, r_max)
            for theta, radius in zip(series.theta_data, series.r_data)
        ]

        if series.draw_line and len(points) >= 2:
            line_points = points + [points[0]] if series.close else points
            for (x0, y0), (x1, y1) in zip(line_points, line_points[1:]):
                self._tft.line(x0, y0, x1, y1, series.color)

        if series.draw_markers:
            for x, y in points:
                if self._point_can_hold_marker(x, y, series.marker_radius):
                    self._tft.fill_circle(x, y, series.marker_radius, series.color)

    def _draw_legend(self) -> None:
        labels = [s for s in self._series if s.label]
        if not labels:
            return
        st = self.style
        x = 2
        y = self._tft.height - len(labels) * (self._CHAR_H + 2) - 2
        y = max(2, y)
        width = max(len(s.label) for s in labels) * self._CHAR_W + 16
        height = len(labels) * (self._CHAR_H + 2) + 2
        if x + width < self._tft.width and y + height < self._tft.height:
            self._tft.fill_rect(x, y, width, height, st.legend_bg_color)
            self._tft.rect(x, y, width, height, st.grid_color)
        for i, series in enumerate(labels):
            yy = y + 2 + i * (self._CHAR_H + 2)
            self._tft.fill_rect(x + 3, yy + 3, 8, 3, series.color)
            self._tft.text(x + 14, yy, series.label, color=st.label_color,
                           size=st.label_size)

    def _map_point(
        self,
        theta: float,
        radius: float,
        r_min: float,
        r_max: float,
    ) -> Tuple[int, int]:
        theta_rad = math.radians(theta) if self.theta_units == "deg" else theta
        if self.clockwise:
            math_angle = self.angle_zero - theta_rad
        else:
            math_angle = self.angle_zero + theta_rad
        return self._point_from_math_angle(
            math_angle,
            self._map_radius(radius, r_min, r_max),
        )

    def _map_radius(self, value: float, r_min: float, r_max: float) -> int:
        if r_max == r_min:
            return 0
        frac = (value - r_min) / (r_max - r_min)
        frac = max(0.0, min(1.0, frac))
        return int(round(frac * self._radius_px))

    def _point_from_math_angle(self, angle: float, radius_px: int) -> Tuple[int, int]:
        x = int(round(self._cx + math.cos(angle) * radius_px))
        y = int(round(self._cy - math.sin(angle) * radius_px))
        return (
            max(0, min(self._tft.width - 1, x)),
            max(0, min(self._tft.height - 1, y)),
        )

    def _point_can_hold_marker(self, x: int, y: int, radius: int) -> bool:
        return (
            radius <= x < self._tft.width - radius
            and radius <= y < self._tft.height - radius
        )


def _demo_rose(tft) -> None:
    g = PolarGraph(tft, title="Polar Rose", theta_units="deg",
                   r_min=0, r_max=1.1)
    g.add_function(
        lambda deg: abs(math.sin(math.radians(4 * deg))),
        samples=241,
        color="#00FFFF",
        label="sin(4t)",
    )
    g.draw()


def _demo_limacon(tft) -> None:
    g = PolarGraph(tft, title="Limacon", theta_units="rad",
                   angle_zero="E", r_min=0, r_max=1.6)
    g.add_function(
        lambda theta: 0.65 + 0.55 * math.cos(theta),
        samples=241,
        color="#FF8800",
        label="0.65+0.55cos",
    )
    g.draw()


def _demo_spiral(tft) -> None:
    g = PolarGraph(tft, title="Spiral", theta_units="rad",
                   r_min=0, r_max=1.0, angle_zero="N", clockwise=True)
    theta = [i * 4.0 * math.pi / 220 for i in range(221)]
    radius = [t / (4.0 * math.pi) for t in theta]
    g.add_series(theta, radius, color="#00FF44", label="r=t",
                 draw_markers=False)
    g.draw()


_DEMOS = [
    ("Polar rose", _demo_rose),
    ("Limacon", _demo_limacon),
    ("Spiral", _demo_spiral),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="TFT polar graph demos")
    parser.add_argument("host", nargs="?", help="ESP8266 IP address or hostname")
    parser.add_argument("--port", type=int, default=8888)
    parser.add_argument("--display", default="ili9341")
    parser.add_argument("--rotation", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--demo", type=int, default=1,
                        help=f"Demo number 1-{len(_DEMOS)}")
    parser.add_argument("--list", action="store_true",
                        help="List available demos and exit")
    args = parser.parse_args()

    if args.list:
        for i, (name, _) in enumerate(_DEMOS, start=1):
            print(f"{i:2d}  {name}")
        return 0

    if not args.host:
        parser.error("host is required unless --list is used")

    if args.demo < 1 or args.demo > len(_DEMOS):
        print(f"--demo must be in 1..{len(_DEMOS)}", file=sys.stderr)
        return 2

    try:
        from tft_terminal import TFTTerminal
    except ImportError:
        print("tft_terminal.py not found. Place it beside this script.",
              file=sys.stderr)
        return 1

    _, demo = _DEMOS[args.demo - 1]
    with TFTTerminal(
        args.host,
        port=args.port,
        display=args.display,
        rotation=args.rotation,
        timeout=args.timeout,
    ) as tft:
        demo(tft)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
