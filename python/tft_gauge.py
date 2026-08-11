#!/usr/bin/env python3
"""
tft_gauge.py
============
Small gauge widgets for the ESP8266 TCP TFT Terminal.

The gauges draw directly through ``TFTTerminal`` primitives and keep enough
state to update the reading without repainting the full widget.

Usage::

    from tft_terminal import TFTTerminal
    from tft_gauge import BarGauge, ArcGauge

    with TFTTerminal("192.168.1.42", display="ili9341") as tft:
        tft.sync()

        bar = BarGauge(tft, 10, 20, 140, 22, label="TEMP", units="C")
        bar.draw(23.5)
        bar.update(24.1)       # redraws only the changed bar/value pixels

        arc = ArcGauge(tft, 170, 120, 58, label="RH", units="%")
        arc.draw(40)
        arc.update(43)         # redraws only changed arc segments/needle/value
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

Color = Any
Formatter = Callable[[float], str]


@dataclass
class GaugeStyle:
    """Shared colours and text sizes for gauge widgets."""
    bg_color: Color = "#000820"
    track_color: Color = "#1A2A3A"
    fill_color: Color = "#00D0FF"
    frame_color: Color = "#8AA0B8"
    tick_color: Color = "#536B82"
    label_color: Color = "#BFD7EA"
    value_color: Color = "#FFFFFF"
    warning_color: Color = "#FFB000"
    danger_color: Color = "#FF4040"
    label_size: int = 1
    value_size: int = 1


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _default_formatter(value: float) -> str:
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return f"{value:.1f}"


def _text_width(text: str, size: int) -> int:
    return len(text) * 6 * size


def _text_height(size: int) -> int:
    return 8 * size


class BarGauge:
    """Horizontal or vertical bar gauge with incremental value updates.

    ``draw()`` paints the whole widget once. ``update()`` only paints the
    rectangle that changed since the previous value, plus the optional value
    text box.
    """

    def __init__(
        self,
        tft,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        min_value: float = 0.0,
        max_value: float = 100.0,
        label: str = "",
        units: str = "",
        vertical: bool = False,
        show_value: bool = True,
        value_box: Optional[Tuple[int, int, int, int]] = None,
        formatter: Formatter = _default_formatter,
        warning_at: Optional[float] = None,
        danger_at: Optional[float] = None,
        style: GaugeStyle = GaugeStyle(),
    ) -> None:
        if w < 4 or h < 4:
            raise ValueError("BarGauge width and height must be at least 4 pixels.")
        if max_value == min_value:
            raise ValueError("BarGauge max_value must differ from min_value.")
        self.tft = tft
        self.x, self.y, self.w, self.h = int(x), int(y), int(w), int(h)
        self.min_value = float(min_value)
        self.max_value = float(max_value)
        self.label = label
        self.units = units
        self.vertical = vertical
        self.show_value = show_value
        self.value_box = value_box
        self.formatter = formatter
        self.warning_at = warning_at
        self.danger_at = danger_at
        self.style = style
        self._drawn = False
        self._fill_px = 0
        self._fill_color: Optional[Color] = None
        self._value: Optional[float] = None

    def draw(self, value: Optional[float] = None) -> None:
        st = self.style
        tft = self.tft
        tft.fill_rect(self.x, self.y, self.w, self.h, st.track_color)
        tft.rect(self.x, self.y, self.w, self.h, st.frame_color)
        if self.label:
            tft.text(self.x, max(0, self.y - _text_height(st.label_size) - 2),
                     self.label, color=st.label_color, size=st.label_size)
        self._drawn = True
        self._fill_px = 0
        if value is None:
            value = self.min_value
        self.update(value, force=True)

    def update(self, value: float, *, force: bool = False) -> None:
        if not self._drawn:
            self.draw(value)
            return

        value = _clamp(float(value), min(self.min_value, self.max_value),
                       max(self.min_value, self.max_value))
        new_fill = self._value_to_pixels(value)
        fill_color = self._color_for_value(value)

        if force:
            self._paint_fill_range(0, self._track_length(), self.style.track_color)
            if new_fill:
                self._paint_fill_range(0, new_fill, fill_color)
        elif self._fill_color != fill_color and new_fill:
            self._paint_fill_range(0, new_fill, fill_color)
        elif new_fill > self._fill_px:
            self._paint_fill_range(self._fill_px, new_fill, fill_color)
        elif new_fill < self._fill_px:
            self._paint_fill_range(new_fill, self._fill_px, self.style.track_color)

        self._fill_px = new_fill
        self._fill_color = fill_color
        self._value = value
        if self.show_value:
            self._draw_value(value)

    def _track_length(self) -> int:
        return (self.h - 2) if self.vertical else (self.w - 2)

    def _value_to_pixels(self, value: float) -> int:
        frac = (value - self.min_value) / (self.max_value - self.min_value)
        frac = _clamp(frac, 0.0, 1.0)
        return int(round(frac * self._track_length()))

    def _paint_fill_range(self, start: int, end: int, color: Color) -> None:
        if end <= start:
            return
        if self.vertical:
            inner_bottom = self.y + self.h - 1
            y = inner_bottom - end
            self.tft.fill_rect(self.x + 1, y, self.w - 2, end - start, color)
        else:
            self.tft.fill_rect(self.x + 1 + start, self.y + 1,
                               end - start, self.h - 2, color)

    def _draw_value(self, value: float) -> None:
        st = self.style
        text = self.formatter(value) + self.units
        if self.value_box:
            x, y, w, h = self.value_box
        else:
            w = max(36, _text_width(text, st.value_size) + 4)
            h = _text_height(st.value_size) + 2
            x = self.x + self.w + 4
            y = self.y + (self.h - h) // 2
        self.tft.fill_rect(x, y, w, h, st.bg_color)
        self.tft.text(x + 2, y + max(0, (h - _text_height(st.value_size)) // 2),
                      text, color=self._color_for_value(value), size=st.value_size)

    def _color_for_value(self, value: float) -> Color:
        if self.danger_at is not None and value >= self.danger_at:
            return self.style.danger_color
        if self.warning_at is not None and value >= self.warning_at:
            return self.style.warning_color
        return self.style.fill_color


class ArcGauge:
    """Circular/arc gauge with an incremental progress arc and needle.

    The default angle range is a dashboard-style sweep from 225 to -45 degrees.
    ``draw()`` paints the dial frame and ticks once. ``update()`` only changes
    the arc segments whose state changed, erases/redraws the old needle, and
    refreshes the value text box.
    """

    def __init__(
        self,
        tft,
        cx: int,
        cy: int,
        radius: int,
        *,
        min_value: float = 0.0,
        max_value: float = 100.0,
        start_angle: float = 225.0,
        end_angle: float = -45.0,
        label: str = "",
        units: str = "",
        show_value: bool = True,
        formatter: Formatter = _default_formatter,
        ticks: int = 6,
        arc_width: int = 4,
        needle: bool = True,
        warning_at: Optional[float] = None,
        danger_at: Optional[float] = None,
        style: GaugeStyle = GaugeStyle(),
    ) -> None:
        if radius < 8:
            raise ValueError("ArcGauge radius must be at least 8 pixels.")
        if max_value == min_value:
            raise ValueError("ArcGauge max_value must differ from min_value.")
        self.tft = tft
        self.cx, self.cy, self.radius = int(cx), int(cy), int(radius)
        self.min_value = float(min_value)
        self.max_value = float(max_value)
        self.start_angle = float(start_angle)
        self.end_angle = float(end_angle)
        self.label = label
        self.units = units
        self.show_value = show_value
        self.formatter = formatter
        self.ticks = max(0, int(ticks))
        self.arc_width = max(1, int(arc_width))
        self.needle = needle
        self.warning_at = warning_at
        self.danger_at = danger_at
        self.style = style
        self._drawn = False
        self._segments = max(24, int(abs(self.end_angle - self.start_angle) / 3))
        self._filled_segments = 0
        self._fill_color: Optional[Color] = None
        self._needle_end: Optional[Tuple[int, int]] = None
        self._value: Optional[float] = None

    def draw(self, value: Optional[float] = None) -> None:
        self._draw_arc_range(0, self._segments, self.style.track_color)
        self._draw_ticks()
        if self.label:
            x = self.cx - _text_width(self.label, self.style.label_size) // 2
            y = self.cy + self.radius // 2
            self.tft.text(x, y, self.label, color=self.style.label_color,
                          size=self.style.label_size)
        self._drawn = True
        self._filled_segments = 0
        if value is None:
            value = self.min_value
        self.update(value, force=True)

    def update(self, value: float, *, force: bool = False) -> None:
        if not self._drawn:
            self.draw(value)
            return

        value = _clamp(float(value), min(self.min_value, self.max_value),
                       max(self.min_value, self.max_value))
        new_segments = self._value_to_segments(value)
        fill_color = self._color_for_value(value)

        if force:
            self._draw_arc_range(0, self._segments, self.style.track_color)
            self._draw_arc_range(0, new_segments, fill_color)
        elif self._fill_color != fill_color and new_segments:
            self._draw_arc_range(0, new_segments, fill_color)
        elif new_segments > self._filled_segments:
            self._draw_arc_range(self._filled_segments, new_segments, fill_color)
        elif new_segments < self._filled_segments:
            self._draw_arc_range(new_segments, self._filled_segments,
                                 self.style.track_color)

        if self.needle:
            self._erase_needle()
            self._draw_needle(value, fill_color)

        self._filled_segments = new_segments
        self._fill_color = fill_color
        self._value = value
        if self.show_value:
            self._draw_value(value)

    def _value_fraction(self, value: float) -> float:
        return _clamp((value - self.min_value) /
                      (self.max_value - self.min_value), 0.0, 1.0)

    def _value_to_segments(self, value: float) -> int:
        return int(round(self._value_fraction(value) * self._segments))

    def _value_to_angle(self, value: float) -> float:
        frac = self._value_fraction(value)
        return self.start_angle + (self.end_angle - self.start_angle) * frac

    def _point(self, angle_deg: float, radius: int) -> Tuple[int, int]:
        rad = math.radians(angle_deg)
        return (
            int(round(self.cx + math.cos(rad) * radius)),
            int(round(self.cy - math.sin(rad) * radius)),
        )

    def _draw_arc_range(self, start_seg: int, end_seg: int, color: Color) -> None:
        start_seg = max(0, start_seg)
        end_seg = min(self._segments, end_seg)
        if end_seg <= start_seg:
            return
        span = self.end_angle - self.start_angle
        for seg in range(start_seg, end_seg):
            a0 = self.start_angle + span * (seg / self._segments)
            a1 = self.start_angle + span * ((seg + 1) / self._segments)
            for offset in range(self.arc_width):
                r = self.radius - offset
                x0, y0 = self._point(a0, r)
                x1, y1 = self._point(a1, r)
                self.tft.line(x0, y0, x1, y1, color)

    def _draw_ticks(self) -> None:
        if self.ticks <= 0:
            return
        for i in range(self.ticks + 1):
            frac = i / self.ticks
            angle = self.start_angle + (self.end_angle - self.start_angle) * frac
            x0, y0 = self._point(angle, self.radius - self.arc_width - 2)
            x1, y1 = self._point(angle, self.radius - self.arc_width - 7)
            self.tft.line(x0, y0, x1, y1, self.style.tick_color)

    def _draw_needle(self, value: float, color: Color) -> None:
        angle = self._value_to_angle(value)
        x, y = self._point(angle, max(2, self.radius - self.arc_width - 10))
        self.tft.line(self.cx, self.cy, x, y, color)
        self.tft.fill_circle(self.cx, self.cy, 2, color)
        self._needle_end = (x, y)

    def _erase_needle(self) -> None:
        if self._needle_end is None:
            return
        x, y = self._needle_end
        self.tft.line(self.cx, self.cy, x, y, self.style.bg_color)
        self.tft.fill_circle(self.cx, self.cy, 2, self.style.bg_color)
        self._needle_end = None

    def _draw_value(self, value: float) -> None:
        st = self.style
        text = self.formatter(value) + self.units
        w = max(42, _text_width(text, st.value_size) + 4)
        h = _text_height(st.value_size) + 2
        x = self.cx - w // 2
        y = self.cy + 5
        self.tft.fill_rect(x, y, w, h, st.bg_color)
        self.tft.text(x + 2, y + 1, text, color=self._color_for_value(value),
                      size=st.value_size)

    def _color_for_value(self, value: float) -> Color:
        if self.danger_at is not None and value >= self.danger_at:
            return self.style.danger_color
        if self.warning_at is not None and value >= self.warning_at:
            return self.style.warning_color
        return self.style.fill_color


# Spelling aliases for callers who search for "gage" or "guage".
BarGage = BarGauge
ArcGage = ArcGauge
BarGuage = BarGauge
ArcGuage = ArcGauge


__all__ = [
    "GaugeStyle",
    "BarGauge",
    "ArcGauge",
    "BarGage",
    "ArcGage",
    "BarGuage",
    "ArcGuage",
]
