#!/usr/bin/env python3
"""
tft_graph.py
============
X-Y graph plotter for the ESP8266 TCP TFT Terminal.

Draws fully-labelled X-Y graphs directly on the TFT display using only the
primitive drawing commands provided by TFTTerminal — no Pillow required.

Supported displays: ILI9341 (240×320), ST7796 (320×480), ST7735 (128×160 or 128×128).

Features
--------
* **Bar charts** — ``add_bar_series()``; grouped side-by-side when multiple bar series share the same X positions
* **Area charts** — ``add_area_series()``; filled region between the zero baseline and the data line
* **Log scale** — ``log_x=True``, ``log_y=True``, ``log_y2=True``.
  Ticks placed at decade boundaries with optional 2x/5x minor ticks.
  All values on a log axis must be > 0.
* **Second Y axis** — series with ``y_axis=2`` are scaled against an
  independent right-hand axis with its own range, label, and colour.
  ``log_y2=True`` makes the right axis logarithmic independently.

Quick start
-----------
::

    from tft_terminal import TFTTerminal
    from tft_graph import Graph

    with TFTTerminal("192.168.1.42") as tft:
        # Linear
        g = Graph(tft, title="y = x^2", x_label="x", y_label="y")
        g.add_series(xs, ys, color="cyan", label="x^2")
        g.draw()

        # Log X (Bode plot)
        g = Graph(tft, title="Bode", x_label="Hz", y_label="dB", log_x=True)
        g.add_series(freqs, gains, color="cyan")
        g.draw()

        # Dual Y axes
        g = Graph(tft, title="Temp & RH", y_label="degC", y2_label="%RH")
        g.add_series(times, temps, color="red",  label="T",  y_axis=1)
        g.add_series(times, rh,   color="blue", label="RH", y_axis=2)
        g.draw()

Demo
----
::

    python3 tft_graph.py 192.168.1.42
    python3 tft_graph.py 192.168.1.42 --demo 6   # log-X Bode plot
    python3 tft_graph.py 192.168.1.42 --demo 9   # dual Y
    python3 tft_graph.py 192.168.1.42 --width 160 --height 128  # ST7735
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

_DEFAULT_COLOURS = [
    "#00FFFF",   # cyan
    "#FF8800",   # orange
    "#00FF44",   # lime-green
    "#FF4488",   # pink
    "#FFD700",   # gold
    "#8888FF",   # periwinkle
    "#FF4444",   # red
    "#44FF88",   # mint
]

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Series:
    """A single data series.

    Parameters
    ----------
    x_data, y_data : list of float
        Equal-length sequences of data values.
        On log axes all values must be > 0.
    color : str
        Line/marker colour.
    label : str
        Legend label (empty = not shown in legend).
    draw_line : bool
        Connect points with line segments.
    draw_markers : bool
        Draw a filled dot at each point.
    marker_radius : int
        Radius of marker dots in pixels.
    y_axis : int
        1 = left Y axis (default), 2 = right Y axis.
    """
    x_data:        List[float]
    y_data:        List[float]
    color:         str            = "#00FFFF"
    label:         str            = ""
    draw_line:     bool           = True
    draw_markers:  bool           = True
    marker_radius: int            = 2
    y_axis:        int            = 1
    chart_type:    str            = "line"   # 'line', 'bar', 'area'
    outline_color: Optional[str]  = None     # bar/area outline; None = same as color
    bar_gap:       float          = 0.15     # fraction of cluster width left as gap

    def __post_init__(self) -> None:
        if len(self.x_data) != len(self.y_data):
            raise ValueError(
                f"Series '{self.label}': x_data length ({len(self.x_data)}) "
                f"must equal y_data length ({len(self.y_data)})."
            )
        if not self.x_data:
            raise ValueError(f"Series '{self.label}': data must not be empty.")
        if self.y_axis not in (1, 2):
            raise ValueError(
                f"Series '{self.label}': y_axis must be 1 or 2, got {self.y_axis}."
            )
        if self.chart_type not in ("line", "bar", "area"):
            raise ValueError(
                f"Series '{self.label}': chart_type must be 'line', 'bar', or 'area', "
                f"got {self.chart_type!r}."
            )
        if not (0.0 <= self.bar_gap < 1.0):
            raise ValueError(
                f"Series '{self.label}': bar_gap must be in [0, 1), got {self.bar_gap}."
            )


@dataclass
class GraphStyle:
    """Visual style settings.

    Parameters
    ----------
    bg_color : str
        Screen background colour.
    plot_bg_color : str
        Plot-area background colour.
    axis_color : str
        Left/top/bottom axis and tick colour.
    grid_color : str
        Major grid line colour.
    minor_grid_color : str
        Minor grid line colour (log-scale axes between decades).
    label_color : str
        Tick label text colour.
    title_color : str
        Title and axis-label text colour.
    zero_color : str
        Colour of the zero line (linear axes spanning zero).
    y2_axis_color : str
        Right axis line, tick, and label colour.
    grid_x : int
        Number of vertical grid divisions (linear X, default 5).
    grid_y : int
        Number of horizontal grid divisions (linear Y, default 4).
    title_size, label_size, axis_title_size : int
        GFX text size multipliers (1-8).
    """
    bg_color:         str = "#000820"
    plot_bg_color:    str = "#020818"
    axis_color:       str = "#AAAAAA"
    grid_color:       str = "#224466"
    minor_grid_color: str = "#112233"
    label_color:      str = "#888888"
    title_color:      str = "#FFFFFF"
    zero_color:       str = "#334455"
    y2_axis_color:    str = "#FFAA44"
    grid_x:           int = 5
    grid_y:           int = 4
    title_size:       int = 1
    label_size:       int = 1
    axis_title_size:  int = 1


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_log10(v: float) -> float:
    """log10 guarded against non-positive values."""
    return math.log10(v) if v > 0 else float("-inf")


def _log_axis_range(
    values: List[float],
    explicit_min: Optional[float],
    explicit_max: Optional[float],
) -> Tuple[float, float]:
    """Compute a log-axis range snapped to decade boundaries.

    Raises ValueError if any values are <= 0.
    """
    bad = [v for v in values if v <= 0]
    if bad:
        raise ValueError(
            f"Log-scale axis requires all values > 0; "
            f"found: {bad[:5]}{'...' if len(bad) > 5 else ''}"
        )
    lo_exp = math.floor(_safe_log10(
        explicit_min if explicit_min is not None else min(values)))
    hi_exp = math.ceil(_safe_log10(
        explicit_max if explicit_max is not None else max(values)))
    if lo_exp == hi_exp:
        hi_exp += 1
    return 10.0 ** lo_exp, 10.0 ** hi_exp


def _linear_axis_range(
    values: List[float],
    explicit_min: Optional[float],
    explicit_max: Optional[float],
    pad_frac: float = 0.05,
) -> Tuple[float, float]:
    """Compute a linear axis range with optional 5% padding."""
    lo = explicit_min if explicit_min is not None else min(values)
    hi = explicit_max if explicit_max is not None else max(values)
    if lo == hi:
        lo -= 1.0; hi += 1.0
    if explicit_min is None or explicit_max is None:
        span = hi - lo
        if explicit_min is None: lo -= span * pad_frac
        if explicit_max is None: hi += span * pad_frac
    return lo, hi


def _fmt_num(val: float, log_scale: bool = False) -> str:
    """Format a numeric tick label compactly."""
    if val == 0:
        return "0"
    if log_scale:
        exp = _safe_log10(val)
        if abs(exp - round(exp)) < 0.01:
            n = int(round(exp))
            return "1" if n == 0 else f"10^{n}"
        mag = abs(val)
        if mag >= 10: return f"{val:.0f}"
        return f"{val:.3g}"
    if val == int(val) and abs(val) < 10000:
        return str(int(val))
    mag = abs(val)
    if mag >= 100: return f"{val:.0f}"
    if mag >= 10:  return f"{val:.1f}"
    if mag >= 1:   return f"{val:.2f}"
    return f"{val:.2g}"


def _log_decade_ticks(lo: float, hi: float) -> List[Tuple[float, bool]]:
    """Return (value, is_major) tick positions for a log axis.

    Major ticks at decade boundaries (1, 10, 100 …).
    Minor ticks at 2x and 5x within each decade.
    """
    lo_exp = math.floor(_safe_log10(lo))
    hi_exp = math.ceil(_safe_log10(hi))
    ticks: List[Tuple[float, bool]] = []
    for exp in range(int(lo_exp), int(hi_exp) + 1):
        decade = 10.0 ** exp
        if lo <= decade <= hi:
            ticks.append((decade, True))
        for mult in (2, 5):
            v = mult * decade
            if lo < v < hi:
                ticks.append((v, False))
    return sorted(ticks, key=lambda t: t[0])


# ---------------------------------------------------------------------------
# Graph class
# ---------------------------------------------------------------------------

class Graph:
    """X-Y graph renderer for the TFT TCP terminal.

    Parameters
    ----------
    tft
        A connected TFTTerminal instance.
    title : str
        Optional graph title.
    x_label : str
        X-axis label.
    y_label : str
        Left Y-axis label.
    y2_label : str
        Right Y-axis label.  Only drawn when series with y_axis=2 exist.
    x_min, x_max : float or None
        Explicit X range; None = auto-scale from data.
    y_min, y_max : float or None
        Explicit left-Y range.
    y2_min, y2_max : float or None
        Explicit right-Y range.
    log_x : bool
        Logarithmic X axis (all X values must be > 0).
    log_y : bool
        Logarithmic left Y axis.
    log_y2 : bool
        Logarithmic right Y axis.
    style : GraphStyle or None
        Visual style; None = use defaults.
    margin_left, margin_bottom, margin_top, margin_right : int or None
        Pixel margins; None = auto.
    """

    _CHAR_W = 6
    _CHAR_H = 8

    def __init__(
        self,
        tft,
        *,
        title:         str   = "",
        x_label:       str   = "X",
        y_label:       str   = "Y",
        y2_label:      str   = "",
        x_min:         Optional[float] = None,
        x_max:         Optional[float] = None,
        y_min:         Optional[float] = None,
        y_max:         Optional[float] = None,
        y2_min:        Optional[float] = None,
        y2_max:        Optional[float] = None,
        log_x:         bool  = False,
        log_y:         bool  = False,
        log_y2:        bool  = False,
        style:         Optional[GraphStyle] = None,
        margin_left:   Optional[int] = None,
        margin_bottom: Optional[int] = None,
        margin_top:    Optional[int] = None,
        margin_right:  Optional[int] = None,
    ) -> None:
        self._tft     = tft
        self.title    = title
        self.x_label  = x_label
        self.y_label  = y_label
        self.y2_label = y2_label
        self.x_min = x_min;  self.x_max  = x_max
        self.y_min = y_min;  self.y_max  = y_max
        self.y2_min= y2_min; self.y2_max = y2_max
        self.log_x  = log_x
        self.log_y  = log_y
        self.log_y2 = log_y2
        self.style  = style or GraphStyle()
        self._series: List[Series] = []

        cw, ch = self._CHAR_W, self._CHAR_H
        W, H   = tft.width, tft.height

        self._ml = margin_left   if margin_left   is not None else cw * 7 + 2
        self._mb = margin_bottom if margin_bottom is not None else ch * 2 + 4
        self._mt = margin_top    if margin_top    is not None else (ch + 4 if title else 2)
        self._mr = margin_right  if margin_right  is not None else (
            cw * 6 + 4 if y2_label else cw * 5 + 2
        )

        self._px0 = self._ml
        self._py0 = self._mt
        self._px1 = W - 1 - self._mr
        self._py1 = H - 1 - self._mb

        if self._px1 - self._px0 < 20 or self._py1 - self._py0 < 20:
            raise ValueError(
                f"Plot area too small ({self._px1-self._px0}x"
                f"{self._py1-self._py0} px) — reduce margins."
            )

    # ── Public API ─────────────────────────────────────────────────────────────

    def add_series(
        self,
        x_data: Sequence[float],
        y_data: Sequence[float],
        *,
        color:         Optional[str] = None,
        label:         str  = "",
        draw_line:     bool = True,
        draw_markers:  bool = True,
        marker_radius: int  = 2,
        y_axis:        int  = 1,
    ) -> "Graph":
        """Add a data series and return self for chaining.

        Parameters
        ----------
        x_data, y_data
            Equal-length numeric sequences.
        color
            Line colour; auto-chosen from palette if None.
        label
            Legend label.
        draw_line
            Connect points with lines.
        draw_markers
            Draw dots at data points.
        marker_radius
            Dot radius in pixels.
        y_axis
            1 = left Y axis (default), 2 = right Y axis.
        """
        if color is None:
            color = _DEFAULT_COLOURS[len(self._series) % len(_DEFAULT_COLOURS)]
        self._series.append(Series(
            x_data=list(x_data), y_data=list(y_data),
            color=color, label=label,
            draw_line=draw_line, draw_markers=draw_markers,
            marker_radius=marker_radius, y_axis=y_axis,
            chart_type="line",
        ))
        return self

    def add_bar_series(
        self,
        x_data: Sequence[float],
        y_data: Sequence[float],
        *,
        color:         Optional[str]  = None,
        outline_color: Optional[str]  = None,
        label:         str   = "",
        bar_gap:       float = 0.15,
        y_axis:        int   = 1,
    ) -> "Graph":
        """Add a bar-chart series and return self for chaining.

        Each data point is rendered as a vertical filled rectangle from the
        zero baseline (or Y-axis minimum when the range is all-positive or
        all-negative) to the data value.  Positive values bar upward,
        negative values bar downward.

        When multiple bar series are added, bars at the same X position are
        automatically grouped side-by-side.

        Parameters
        ----------
        x_data, y_data
            Equal-length numeric sequences.
        color
            Bar fill colour; auto-chosen from palette if None.
        outline_color
            Bar outline colour; None = same as fill colour.
        label
            Legend label.
        bar_gap
            Fraction of each bar-cluster width to leave as empty space
            between clusters (default 0.15).  Must be in [0, 1).
        y_axis
            1 = left Y axis (default), 2 = right Y axis.
        """
        if color is None:
            color = _DEFAULT_COLOURS[len(self._series) % len(_DEFAULT_COLOURS)]
        self._series.append(Series(
            x_data=list(x_data), y_data=list(y_data),
            color=color, label=label,
            draw_line=False, draw_markers=False,
            marker_radius=0, y_axis=y_axis,
            chart_type="bar",
            outline_color=outline_color,
            bar_gap=bar_gap,
        ))
        return self

    def add_area_series(
        self,
        x_data: Sequence[float],
        y_data: Sequence[float],
        *,
        color:         Optional[str]  = None,
        outline_color: Optional[str]  = None,
        label:         str   = "",
        draw_markers:  bool  = False,
        marker_radius: int   = 2,
        y_axis:        int   = 1,
    ) -> "Graph":
        """Add an area-chart series and return self for chaining.

        The region between the zero baseline (or Y-axis minimum) and the
        data line is filled with vertical line segments.  A line is drawn
        on top in ``outline_color`` (defaults to ``color``).

        Parameters
        ----------
        x_data, y_data
            Equal-length numeric sequences.
        color
            Fill colour; auto-chosen from palette if None.
        outline_color
            Outline colour drawn on top of the fill.  None = same as fill.
        label
            Legend label.
        draw_markers
            Draw dots at data points on top of the area (default False).
        marker_radius
            Dot radius in pixels.
        y_axis
            1 = left Y axis (default), 2 = right Y axis.
        """
        if color is None:
            color = _DEFAULT_COLOURS[len(self._series) % len(_DEFAULT_COLOURS)]
        self._series.append(Series(
            x_data=list(x_data), y_data=list(y_data),
            color=color, label=label,
            draw_line=True, draw_markers=draw_markers,
            marker_radius=marker_radius, y_axis=y_axis,
            chart_type="area",
            outline_color=outline_color,
        ))
        return self

    def draw(self) -> None:
        """Render the complete graph on the TFT display.

        Raises ValueError if no series have been added, or if log-scale axes
        have non-positive data values.
        """
        if not self._series:
            raise ValueError("No series added — call add_series() first.")

        tft = self._tft
        st  = self.style

        y1_series = [s for s in self._series if s.y_axis == 1]
        y2_series = [s for s in self._series if s.y_axis == 2]
        has_y2    = bool(y2_series)

        # Axis ranges
        all_x  = [v for s in self._series for v in s.x_data]
        all_y1 = [v for s in y1_series    for v in s.y_data]
        all_y2 = [v for s in y2_series    for v in s.y_data]

        if self.log_x:
            x_min, x_max = _log_axis_range(all_x, self.x_min, self.x_max)
        else:
            x_min, x_max = _linear_axis_range(all_x, self.x_min, self.x_max)

        if all_y1:
            if self.log_y:
                y_min, y_max = _log_axis_range(all_y1, self.y_min, self.y_max)
            else:
                y_min, y_max = _linear_axis_range(all_y1, self.y_min, self.y_max)
        else:
            y_min, y_max = 0.0, 1.0

        if has_y2:
            if self.log_y2:
                y2_min, y2_max = _log_axis_range(all_y2, self.y2_min, self.y2_max)
            else:
                y2_min, y2_max = _linear_axis_range(all_y2, self.y2_min, self.y2_max)
        else:
            y2_min, y2_max = 0.0, 1.0

        pw = self._px1 - self._px0 + 1
        ph = self._py1 - self._py0 + 1

        # Background
        tft.fill_screen(st.bg_color)
        tft.fill_rect(self._px0, self._py0, pw, ph, st.plot_bg_color)

        # Title
        if self.title:
            tx = max(0, self._px0 + (pw - len(self.title) * self._CHAR_W) // 2)
            ty = max(0, (self._mt - self._CHAR_H) // 2)
            tft.text(tx, ty, self.title, color=st.title_color, size=st.title_size)

        # Grid
        self._draw_grid(x_min, x_max, y_min, y_max, st)

        # Zero lines (linear only)
        if not self.log_y and y_min < 0 < y_max:
            zy = self._map_y1(0, y_min, y_max)
            tft.hline(self._px0, zy, pw, st.zero_color)
        if not self.log_x and x_min < 0 < x_max:
            zx = self._map_x(0, x_min, x_max)
            tft.vline(zx, self._py0, ph, st.zero_color)

        # Axes
        tft.vline(self._px0, self._py0, ph, st.axis_color)
        tft.hline(self._px0, self._py1, pw, st.axis_color)
        tft.hline(self._px0, self._py0, pw, st.axis_color)
        tft.vline(self._px1, self._py0, ph,
                  st.y2_axis_color if has_y2 else st.axis_color)

        # Ticks
        self._draw_x_ticks(x_min, x_max, st)
        self._draw_y1_ticks(y_min, y_max, st)
        if has_y2:
            self._draw_y2_ticks(y2_min, y2_max, st)

        # Axis labels
        if self.x_label:
            lx = self._px0 + (pw - len(self.x_label) * self._CHAR_W) // 2
            ly = max(self._py1 + 2, tft.height - self._CHAR_H)
            if ly + self._CHAR_H <= tft.height:
                tft.text(lx, ly, self.x_label,
                         color=st.title_color, size=st.axis_title_size)
        if self.y_label:
            ly = max(0, self._py0 - self._CHAR_H - 2)
            tft.text(0, ly, self.y_label,
                     color=st.title_color, size=st.axis_title_size)
        if has_y2 and self.y2_label:
            lx = max(0, self._px1 - len(self.y2_label) * self._CHAR_W)
            ly = max(0, self._py0 - self._CHAR_H - 2)
            tft.text(lx, ly, self.y2_label,
                     color=st.y2_axis_color, size=st.axis_title_size)

        # Compute bar geometry once (shared across bar series)
        bar_series = [s for s in self._series if s.chart_type == "bar"]
        n_bar = len(bar_series)

        # Data — draw areas first, then bars, then lines (painter order)
        for pass_type in ("area", "bar", "line"):
            for bi, series in enumerate(
                [s for s in self._series if s.chart_type == pass_type]):
                if series.y_axis == 2:
                    ym, yM, lg = y2_min, y2_max, self.log_y2
                else:
                    ym, yM, lg = y_min, y_max, self.log_y
                bar_index = bar_series.index(series) if pass_type == "bar" else 0
                if pass_type == "bar":
                    self._draw_bar(series, x_min, x_max, ym, yM,
                                  log_y=lg, bar_index=bar_index, n_bars=n_bar)
                elif pass_type == "area":
                    self._draw_area(series, x_min, x_max, ym, yM, log_y=lg)
                else:
                    self._draw_series(series, x_min, x_max, ym, yM, log_y=lg)

        # Legend
        self._draw_legend(st, has_y2)

    # ── Internal drawing ───────────────────────────────────────────────────────

    def _draw_grid(
        self,
        x_min: float, x_max: float,
        y_min: float, y_max: float,
        st: GraphStyle,
    ) -> None:
        tft = self._tft
        pw  = self._px1 - self._px0 + 1
        ph  = self._py1 - self._py0 + 1

        if self.log_x:
            for val, major in _log_decade_ticks(x_min, x_max):
                gx = self._map_x(val, x_min, x_max)
                if self._px0 < gx < self._px1:
                    tft.vline(gx, self._py0 + 1, ph - 2,
                              st.grid_color if major else st.minor_grid_color)
        else:
            for i in range(1, st.grid_x):
                gx = self._px0 + round(pw * i / st.grid_x)
                if self._px0 < gx < self._px1:
                    tft.vline(gx, self._py0 + 1, ph - 2, st.grid_color)

        if self.log_y:
            for val, major in _log_decade_ticks(y_min, y_max):
                gy = self._map_y1(val, y_min, y_max)
                if self._py0 < gy < self._py1:
                    tft.hline(self._px0 + 1, gy, pw - 2,
                              st.grid_color if major else st.minor_grid_color)
        else:
            for i in range(1, st.grid_y):
                gy = self._py0 + round(ph * i / st.grid_y)
                if self._py0 < gy < self._py1:
                    tft.hline(self._px0 + 1, gy, pw - 2, st.grid_color)

    def _draw_x_ticks(
        self, x_min: float, x_max: float, st: GraphStyle
    ) -> None:
        tft = self._tft
        cw, ch = self._CHAR_W, self._CHAR_H
        if self.log_x:
            for val, major in _log_decade_ticks(x_min, x_max):
                if not major:
                    continue
                px = self._map_x(val, x_min, x_max)
                if self._py1 + 3 < tft.height:
                    tft.vline(px, self._py1, 3, st.axis_color)
                label = _fmt_num(val, log_scale=True)
                lw = len(label) * cw
                lx = max(0, min(px - lw // 2, tft.width - lw - 1))
                if self._py1 + 4 + ch <= tft.height:
                    tft.text(lx, self._py1 + 4, label,
                             color=st.label_color, size=st.label_size)
        else:
            n = st.grid_x
            for i in range(n + 1):
                val = x_min + (x_max - x_min) * i / n
                px  = self._map_x(val, x_min, x_max)
                if self._py1 + 3 < tft.height:
                    tft.vline(px, self._py1, 3, st.axis_color)
                label = _fmt_num(val)
                lw = len(label) * cw
                lx = max(0, min(px - lw // 2, tft.width - lw - 1))
                if self._py1 + 4 + ch <= tft.height:
                    tft.text(lx, self._py1 + 4, label,
                             color=st.label_color, size=st.label_size)

    def _draw_y1_ticks(
        self, y_min: float, y_max: float, st: GraphStyle
    ) -> None:
        tft = self._tft
        cw, ch = self._CHAR_W, self._CHAR_H
        if self.log_y:
            for val, major in _log_decade_ticks(y_min, y_max):
                if not major:
                    continue
                py = self._map_y1(val, y_min, y_max)
                tft.hline(max(0, self._px0 - 3), py, 3, st.axis_color)
                label = _fmt_num(val, log_scale=True)
                lw = len(label) * cw
                lx = max(0, self._px0 - lw - 4)
                ly = max(0, min(py - ch // 2, tft.height - ch - 1))
                tft.text(lx, ly, label, color=st.label_color, size=st.label_size)
        else:
            n = st.grid_y
            for i in range(n + 1):
                val = y_min + (y_max - y_min) * i / n
                py  = self._map_y1(val, y_min, y_max)
                tft.hline(max(0, self._px0 - 3), py, 3, st.axis_color)
                label = _fmt_num(val)
                lw = len(label) * cw
                lx = max(0, self._px0 - lw - 4)
                ly = max(0, min(py - ch // 2, tft.height - ch - 1))
                tft.text(lx, ly, label, color=st.label_color, size=st.label_size)

    def _draw_y2_ticks(
        self, y2_min: float, y2_max: float, st: GraphStyle
    ) -> None:
        tft = self._tft
        cw, ch = self._CHAR_W, self._CHAR_H
        col = st.y2_axis_color
        if self.log_y2:
            for val, major in _log_decade_ticks(y2_min, y2_max):
                if not major:
                    continue
                py = self._map_y2(val, y2_min, y2_max)
                tft.hline(self._px1, py, 3, col)
                label = _fmt_num(val, log_scale=True)
                lx = self._px1 + 4
                ly = max(0, min(py - ch // 2, tft.height - ch - 1))
                if lx + len(label) * cw <= tft.width:
                    tft.text(lx, ly, label, color=col, size=st.label_size)
        else:
            n = st.grid_y
            for i in range(n + 1):
                val = y2_min + (y2_max - y2_min) * i / n
                py  = self._map_y2(val, y2_min, y2_max)
                tft.hline(self._px1, py, 3, col)
                label = _fmt_num(val)
                lx = self._px1 + 4
                ly = max(0, min(py - ch // 2, tft.height - ch - 1))
                if lx + len(label) * cw <= tft.width:
                    tft.text(lx, ly, label, color=col, size=st.label_size)

    def _draw_series(
        self,
        series: Series,
        x_min: float, x_max: float,
        y_min: float, y_max: float,
        log_y: bool = False,
    ) -> None:
        tft   = self._tft
        col   = series.color
        map_y = self._map_y2 if series.y_axis == 2 else self._map_y1
        pts: List[Tuple[int, int]] = []

        for xv, yv in zip(series.x_data, series.y_data):
            if self.log_x and xv <= 0: continue
            if log_y       and yv <= 0: continue
            pts.append((self._map_x(xv, x_min, x_max),
                        map_y(yv, y_min, y_max)))

        if series.draw_line and len(pts) >= 2:
            for i in range(len(pts) - 1):
                tft.line(
                    max(self._px0, min(self._px1, pts[i][0])),
                    max(self._py0, min(self._py1, pts[i][1])),
                    max(self._px0, min(self._px1, pts[i+1][0])),
                    max(self._py0, min(self._py1, pts[i+1][1])),
                    col,
                )

        if series.draw_markers:
            r = series.marker_radius
            for px, py in pts:
                if (self._px0-r <= px <= self._px1+r and
                        self._py0-r <= py <= self._py1+r):
                    tft.fill_circle(
                        max(r, min(tft.width-1-r, px)),
                        max(r, min(tft.height-1-r, py)),
                        r, col,
                    )

    def _draw_bar(
        self,
        series: Series,
        x_min: float, x_max: float,
        y_min: float, y_max: float,
        log_y: bool = False,
        bar_index: int = 0,
        n_bars: int = 1,
    ) -> None:
        """Draw a bar-chart series.

        Bars are grouped side-by-side when n_bars > 1.  Each bar runs from
        the pixel Y at the zero line (clamped to y_min when the axis range
        is entirely positive, or to y_max when entirely negative) to the
        pixel Y at the data value.
        """
        tft    = self._tft
        col    = series.color
        out    = series.outline_color or col
        map_y  = self._map_y2 if series.y_axis == 2 else self._map_y1
        n      = len(series.x_data)
        if n == 0:
            return

        pw = self._px1 - self._px0

        # Cluster width: equal share of the plot width per data point
        cluster_w = pw / max(n, 1)
        gap_px    = max(1, round(cluster_w * series.bar_gap))
        bar_total = max(1, round(cluster_w) - gap_px)
        bar_w     = max(1, bar_total // n_bars)

        # Zero-baseline pixel (clamped to axis range)
        zero_val  = max(y_min, min(0.0, y_max))
        py_zero   = map_y(zero_val, y_min, y_max)

        for i, (xv, yv) in enumerate(zip(series.x_data, series.y_data)):
            if self.log_x and xv <= 0:
                continue
            if log_y and yv <= 0:
                continue

            # Centre of the cluster for this X value
            px_centre = self._map_x(xv, x_min, x_max)
            # Left edge of this particular bar within the cluster
            bx = px_centre - bar_total // 2 + bar_index * bar_w

            py_top  = map_y(yv, y_min, y_max)

            # Rectangle from zero to value (or value to zero for negatives)
            rect_y  = min(py_top, py_zero)
            rect_h  = max(1, abs(py_zero - py_top))

            # Clamp to plot area
            bx_c    = max(self._px0, min(self._px1 - 1, bx))
            bx_end  = max(self._px0, min(self._px1, bx + bar_w - 1))
            rect_w  = max(1, bx_end - bx_c)
            rect_y  = max(self._py0, min(self._py1, rect_y))
            rect_h  = min(rect_h, self._py1 - rect_y + 1)

            if rect_w > 0 and rect_h > 0:
                tft.fill_rect(bx_c, rect_y, rect_w, rect_h, col)
                tft.rect(bx_c, rect_y, rect_w, rect_h, out)

    def _draw_area(
        self,
        series: Series,
        x_min: float, x_max: float,
        y_min: float, y_max: float,
        log_y: bool = False,
    ) -> None:
        """Draw an area-chart series.

        Fills the region between the zero baseline and the data curve by
        drawing a vertical line at each pixel column between adjacent data
        points.  The outline is drawn on top as a polyline.
        """
        tft   = self._tft
        col   = series.color
        out   = series.outline_color or col
        map_y = self._map_y2 if series.y_axis == 2 else self._map_y1

        # Zero-baseline pixel
        zero_val = max(y_min, min(0.0, y_max))
        py_zero  = max(self._py0, min(self._py1, map_y(zero_val, y_min, y_max)))

        # Build valid (px, py) points
        pts: List[Tuple[int, int]] = []
        for xv, yv in zip(series.x_data, series.y_data):
            if self.log_x and xv <= 0: continue
            if log_y       and yv <= 0: continue
            pts.append((self._map_x(xv, x_min, x_max),
                        max(self._py0, min(self._py1,
                            map_y(yv, y_min, y_max)))))

        if len(pts) < 2:
            return

        # Fill pass: for each pair of adjacent points interpolate Y across columns
        for seg in range(len(pts) - 1):
            x0, y0 = pts[seg]
            x1, y1 = pts[seg + 1]
            if x1 == x0:
                # Vertical segment: draw one column
                top = min(y0, y1, py_zero)
                bot = max(y0, y1, py_zero)
                top = max(self._py0, top)
                bot = min(self._py1, bot)
                if bot > top:
                    tft.vline(x0, top, bot - top + 1, col)
                continue
            # Iterate over each pixel column in this segment
            xa, xb = (x0, x1) if x0 <= x1 else (x1, x0)
            ya_at_xa = y0 if x0 <= x1 else y1
            yb_at_xb = y1 if x0 <= x1 else y0
            xa_cl = max(self._px0, xa)
            xb_cl = min(self._px1, xb)
            for px in range(xa_cl, xb_cl + 1):
                t  = (px - xa) / (xb - xa)
                py = round(ya_at_xa + t * (yb_at_xb - ya_at_xa))
                py = max(self._py0, min(self._py1, py))
                top = min(py, py_zero)
                bot = max(py, py_zero)
                top = max(self._py0, top)
                bot = min(self._py1, bot)
                if bot >= top:
                    tft.vline(px, top, bot - top + 1, col)

        # Outline pass: draw the polyline on top of the fill
        for i in range(len(pts) - 1):
            tft.line(
                max(self._px0, min(self._px1, pts[i][0])),
                max(self._py0, min(self._py1, pts[i][1])),
                max(self._px0, min(self._px1, pts[i+1][0])),
                max(self._py0, min(self._py1, pts[i+1][1])),
                out,
            )

        # Markers on top
        if series.draw_markers:
            r = series.marker_radius
            for px, py in pts:
                if (self._px0-r <= px <= self._px1+r and
                        self._py0-r <= py <= self._py1+r):
                    tft.fill_circle(
                        max(r, min(tft.width-1-r, px)),
                        max(r, min(tft.height-1-r, py)),
                        r, out,
                    )

    def _draw_legend(self, st: GraphStyle, has_y2: bool) -> None:
        labelled = [s for s in self._series if s.label]
        if not labelled:
            return
        tft = self._tft
        cw, ch = self._CHAR_W, self._CHAR_H
        swatch_w  = 8
        pad       = 2
        item_h    = ch + pad
        suffix_w  = 4 * cw if has_y2 else 0
        max_len   = max(len(s.label) for s in labelled)
        box_w     = swatch_w + 2 + max_len * cw + suffix_w + pad * 2
        box_h     = len(labelled) * item_h + pad
        bx        = self._px1 - box_w - 2
        by        = self._py0 + 2
        if bx < self._px0 + 10 or by + box_h > self._py1:
            return
        tft.fill_rect(bx, by, box_w, box_h, "#0A1428")
        tft.rect(bx, by, box_w, box_h, st.axis_color)
        for i, s in enumerate(labelled):
            iy = by + pad + i * item_h
            tft.fill_rect(bx + pad, iy + 1, swatch_w, ch - 2, s.color)
            lbl = s.label + (f" Y{s.y_axis}" if has_y2 else "")
            tft.text(bx + pad + swatch_w + 2, iy, lbl,
                     color=st.label_color, size=1)

    # ── Coordinate mapping ─────────────────────────────────────────────────────

    def _map_x(self, val: float, x_min: float, x_max: float) -> int:
        if x_max == x_min:
            return (self._px0 + self._px1) // 2
        if self.log_x:
            lo, hi = _safe_log10(x_min), _safe_log10(x_max)
            t = (_safe_log10(val) - lo) / (hi - lo) if hi != lo else 0.5
        else:
            t = (val - x_min) / (x_max - x_min)
        return round(self._px0 + t * (self._px1 - self._px0))

    def _map_y1(self, val: float, y_min: float, y_max: float) -> int:
        """Map a left-Y value to display pixel Y (Y increases downward)."""
        if y_max == y_min:
            return (self._py0 + self._py1) // 2
        if self.log_y:
            lo, hi = _safe_log10(y_min), _safe_log10(y_max)
            t = (_safe_log10(val) - lo) / (hi - lo) if hi != lo else 0.5
        else:
            t = (val - y_min) / (y_max - y_min)
        return round(self._py1 - t * (self._py1 - self._py0))

    def _map_y2(self, val: float, y2_min: float, y2_max: float) -> int:
        """Map a right-Y value to display pixel Y."""
        if y2_max == y2_min:
            return (self._py0 + self._py1) // 2
        if self.log_y2:
            lo, hi = _safe_log10(y2_min), _safe_log10(y2_max)
            t = (_safe_log10(val) - lo) / (hi - lo) if hi != lo else 0.5
        else:
            t = (val - y2_min) / (y2_max - y2_min)
        return round(self._py1 - t * (self._py1 - self._py0))

    # Back-compat alias
    def _map_y(self, val: float, y_min: float, y_max: float) -> int:
        return self._map_y1(val, y_min, y_max)

    @staticmethod
    def _axis_range(
        values, explicit_min=None, explicit_max=None, pad_frac=0.05
    ):
        return _linear_axis_range(values, explicit_min, explicit_max, pad_frac)

    @staticmethod
    def _fmt(val: float) -> str:
        return _fmt_num(val)


# =============================================================================
#  Demos
# =============================================================================

def _demo_sine_cosine(tft) -> None:
    xs    = [i * 0.2 for i in range(32)]
    g = Graph(tft, title="sin / cos", x_label="Radians", y_label="Amp")
    g.add_series(xs, [math.sin(x) for x in xs], color="#00FFFF", label="sin")
    g.add_series(xs, [math.cos(x) for x in xs], color="#FF8800", label="cos")
    g.draw()


def _demo_quadratic(tft) -> None:
    xs = list(range(-10, 11))
    g = Graph(tft, title="y = x^2", x_label="x", y_label="y")
    g.add_series(xs, [x*x for x in xs], color="#FFD700", label="x^2")
    g.draw()


def _demo_random_scatter(tft) -> None:
    import random; rng = random.Random(42)
    n = 20
    g = Graph(tft, title="Scatter", x_label="x", y_label="y")
    g.add_series([rng.uniform(0,100) for _ in range(n)],
                 [rng.uniform(-50,50) for _ in range(n)],
                 color="#FF4488", label="pts",
                 draw_line=False, draw_markers=True, marker_radius=3)
    g.draw()


def _demo_multi_series(tft) -> None:
    xs = [i * 0.3 for i in range(22)]
    g = Graph(tft, title="3 series", x_label="t", y_label="val")
    g.add_series(xs, [math.sin(x)*10 for x in xs], color="#00FFFF", label="A")
    g.add_series(xs, [math.cos(x)*8  for x in xs], color="#FF8800", label="B")
    g.add_series(xs, [math.sin(2*x)*5 for x in xs], color="#00FF44", label="C")
    g.draw()


def _demo_linear_with_noise(tft) -> None:
    import random; rng = random.Random(7)
    xs = [i * 2.0 for i in range(25)]
    ys = [0.5*x - 10 + rng.gauss(0, 3) for x in xs]
    g = Graph(tft, title="Linear trend", x_label="x", y_label="y")
    g.add_series(xs, ys, color="#8888FF", label="data")
    g.add_series([xs[0], xs[-1]], [0.5*xs[0]-10, 0.5*xs[-1]-10],
                 color="#FF4444", label="trend", draw_markers=False)
    g.draw()


def _demo_log_x(tft) -> None:
    """Bode plot: log X axis, linear Y."""
    fc    = 1000.0
    freqs = [10.0 * (10**(i*4/19)) for i in range(20)]
    gains = [-20*math.log10(math.sqrt(1+(f/fc)**2)) for f in freqs]
    g = Graph(tft, title="Low-pass (1kHz)",
              x_label="Hz", y_label="dB",
              log_x=True, x_min=10, x_max=100000)
    g.add_series(freqs, gains, color="#00FFFF", label="gain")
    g.draw()


def _demo_log_y(tft) -> None:
    """Exponential growth: log Y axis."""
    xs = list(range(0, 11))
    g = Graph(tft, title="2^x (log Y)", x_label="x", y_label="2^x",
              log_y=True)
    g.add_series(xs, [2.0**x for x in xs], color="#FFD700", label="2^x")
    g.draw()


def _demo_log_xy(tft) -> None:
    """Power law: log-log axes (appears as straight line)."""
    xs = [10.0**(i*0.25) for i in range(17)]
    g = Graph(tft, title="y=x^1.5 (log-log)",
              x_label="x", y_label="y",
              log_x=True, log_y=True)
    g.add_series(xs, [x**1.5 for x in xs], color="#FF4488", label="x^1.5")
    g.draw()


def _demo_dual_y(tft) -> None:
    """Temperature + humidity on independent Y axes."""
    times    = list(range(0, 25))
    temps    = [15 + 8*math.sin((t-6)*math.pi/12) for t in times]
    humidity = [75 - 20*math.sin((t-6)*math.pi/12) for t in times]
    g = Graph(tft, title="Temp & Humidity",
              x_label="Hour", y_label="degC", y2_label="%RH",
              y_min=0, y_max=30, y2_min=40, y2_max=100)
    g.add_series(times, temps,    color="#FF4444", label="T",  y_axis=1)
    g.add_series(times, humidity, color="#44AAFF", label="RH", y_axis=2)
    g.draw()


def _demo_dual_y_log(tft) -> None:
    """Voltage (linear Y1) and current (log Y2) — RC discharge."""
    ts    = [i * 0.5 for i in range(21)]
    volts = [5*math.exp(-t/5)        for t in ts]
    amps  = [0.01*math.exp(-t/5)+1e-4 for t in ts]
    g = Graph(tft, title="RC discharge",
              x_label="sec", y_label="V", y2_label="A",
              log_y2=True, y_min=0, y_max=6)
    g.add_series(ts, volts, color="#FFD700", label="V",  y_axis=1)
    g.add_series(ts, amps,  color="#FF8800", label="I",  y_axis=2)
    g.draw()


def _demo_bar_basic(tft) -> None:
    """Monthly rainfall as a simple bar chart."""
    months = list(range(1, 13))
    rain   = [45, 38, 52, 67, 80, 55, 30, 28, 48, 72, 60, 50]
    g = Graph(tft, title="Monthly Rainfall", x_label="Month", y_label="mm",
              y_min=0, y_max=100)
    g.add_bar_series(months, rain, color="#4488FF",
                     outline_color="#8ABAFF", label="rain")
    g.draw()


def _demo_bar_grouped(tft) -> None:
    """Grouped bar chart: two data sets side-by-side."""
    quarters = [1, 2, 3, 4]
    sales_a  = [120, 150, 130, 180]
    sales_b  = [ 90, 110, 160, 140]
    g = Graph(tft, title="Quarterly Sales",
              x_label="Quarter", y_label="Units",
              y_min=0, y_max=200)
    g.add_bar_series(quarters, sales_a, color="#00FFCC",
                     outline_color="#AAFFEE", label="Product A")
    g.add_bar_series(quarters, sales_b, color="#FF8800",
                     outline_color="#FFCC88", label="Product B")
    g.draw()


def _demo_bar_negative(tft) -> None:
    """Bar chart with positive and negative values (profit/loss)."""
    months = list(range(1, 9))
    profit = [20, -10, 35, 15, -5, 40, 25, -8]
    g = Graph(tft, title="Profit / Loss",
              x_label="Month", y_label="$k",
              y_min=-20, y_max=50)
    g.add_bar_series(months, profit, color="#44FF88",
                     outline_color="#AAFFCC", label="profit")
    g.draw()


def _demo_area_basic(tft) -> None:
    """Area chart: CPU usage over time."""
    n    = 20
    ts   = [i * 0.5 for i in range(n)]
    cpu  = [30 + 20*math.sin(t*0.8) + 10*math.sin(t*2.1) for t in ts]
    g = Graph(tft, title="CPU Usage",
              x_label="sec", y_label="%",
              y_min=0, y_max=80)
    g.add_area_series(ts, cpu, color="#224488",
                      outline_color="#4488FF", label="CPU")
    g.draw()


def _demo_area_stacked(tft) -> None:
    """Two area series showing network traffic (different colours)."""
    n   = 24
    ts  = list(range(n))
    rx  = [5 + 8*math.sin(t*math.pi/6) + 3*math.sin(t*math.pi/2) for t in ts]
    tx  = [3 + 4*math.cos(t*math.pi/6) + 2*math.cos(t*math.pi/3) for t in ts]
    rx  = [max(0, v) for v in rx]
    tx  = [max(0, v) for v in tx]
    g = Graph(tft, title="Network Traffic",
              x_label="Hour", y_label="MB/s",
              y_min=0, y_max=20)
    g.add_area_series(ts, rx, color="#004488",
                      outline_color="#0088FF", label="RX")
    g.add_area_series(ts, tx, color="#440044",
                      outline_color="#FF44FF", label="TX")
    g.draw()


def _demo_bar_and_line(tft) -> None:
    """Bar chart with a line series overlay on a second Y axis."""
    months   = list(range(1, 13))
    rainfall = [45, 38, 52, 67, 80, 55, 30, 28, 48, 72, 60, 50]
    temp     = [5, 6, 9, 13, 17, 21, 23, 22, 18, 14, 9, 6]
    g = Graph(tft, title="Rain & Temp",
              x_label="Month", y_label="mm", y2_label="degC",
              y_min=0, y_max=100, y2_min=0, y2_max=30)
    g.add_bar_series(months, rainfall, color="#4488FF",
                     outline_color="#88AAFF", label="Rain", y_axis=1)
    g.add_series(months, temp, color="#FF4444",
                 label="Temp", draw_markers=True, marker_radius=2, y_axis=2)
    g.draw()


_DEMOS = [
    ("Sine / Cosine",          _demo_sine_cosine),
    ("Quadratic y=x^2",        _demo_quadratic),
    ("Random scatter",         _demo_random_scatter),
    ("Three series",           _demo_multi_series),
    ("Linear with noise",      _demo_linear_with_noise),
    ("Log X  (Bode plot)",     _demo_log_x),
    ("Log Y  (exponential)",   _demo_log_y),
    ("Log X+Y (power law)",    _demo_log_xy),
    ("Dual Y axes",            _demo_dual_y),
    ("Dual Y + log Y2",        _demo_dual_y_log),
    ("Bar chart (basic)",       _demo_bar_basic),
    ("Bar chart (grouped)",     _demo_bar_grouped),
    ("Bar chart (neg values)",  _demo_bar_negative),
    ("Area chart (CPU)",        _demo_area_basic),
    ("Area chart (network)",    _demo_area_stacked),
    ("Bar + line overlay",      _demo_bar_and_line),
]


# =============================================================================
#  CLI
# =============================================================================

def main() -> int:
    p = argparse.ArgumentParser(description="TFT graph demo (ESP8266)")
    p.add_argument("host")
    p.add_argument("--port",    type=int,   default=8888)
    p.add_argument("--width",   type=int,   default=320)
    p.add_argument("--height",  type=int,   default=240)
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--pause",   type=float, default=3.0)
    p.add_argument("--demo",    type=int,   default=None, metavar="N",
                   help="Run only demo N (1-based, 1-16)")
    args = p.parse_args()

    try:
        from tft_terminal import TFTTerminal
    except ImportError:
        print("tft_terminal.py not found.", file=sys.stderr); return 1

    print(f"Connecting to {args.host}:{args.port} ({args.width}x{args.height}) ...")
    try:
        tft = TFTTerminal(args.host, args.port,
                          width=args.width, height=args.height,
                          timeout=args.timeout)
    except Exception as exc:
        print(f"Connection failed: {exc}", file=sys.stderr); return 1

    import time
    demos = _DEMOS if args.demo is None else [_DEMOS[args.demo - 1]]
    with tft:
        for i, (name, fn) in enumerate(demos, 1):
            print(f"  [{i}/{len(demos)}] {name} ...", end=" ", flush=True)
            try:
                fn(tft); print("OK")
            except Exception as exc:
                print(f"FAILED: {exc}")
            if i < len(demos):
                time.sleep(args.pause)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
