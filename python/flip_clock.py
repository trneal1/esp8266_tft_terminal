#!/usr/bin/env python3
"""
flip_clock.py
=============
Flip clock style display for the ESP8266 TCP TFT Terminal.

Usage
-----
::

    python flip_clock.py <host>
    python flip_clock.py 192.168.1.42 --theme light
    python flip_clock.py 192.168.1.42 --theme yellow --rotation 1
    python flip_clock.py 192.168.1.42 --display st7796 --rotation 1
    python flip_clock.py 192.168.1.42 --require-responses

The display is updated once per second, but the screen is redrawn only when
the minute or date changes.
"""

from __future__ import annotations

import argparse
import calendar
import sys
import time
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime

try:
    from tft_terminal import TFTTerminal
except ImportError:
    sys.exit("tft_terminal.py not found. Place this script in the same directory.")


FONT_W = 6
FONT_H = 8


@dataclass(frozen=True)
class Theme:
    background: str
    card: str
    card_top: str
    text: str
    dim_text: str
    divider: str
    edge: str
    shadow: str


THEMES = {
    "dark": Theme(
        background="#F3B400",
        card="#111318",
        card_top="#1B1E25",
        text="#8FEFFF",
        dim_text="#8FEFFF",
        divider="#050607",
        edge="#242833",
        shadow="#8D6800",
    ),
    "light": Theme(
        background="#9EA69C",
        card="#EEF6F2",
        card_top="#F8FFFC",
        text="#17252C",
        dim_text="#17252C",
        divider="#7C8A86",
        edge="#B6C9CF",
        shadow="#666D68",
    ),
    "yellow": Theme(
        background="#F3B400",
        card="#111318",
        card_top="#1B1E25",
        text="#8FEFFF",
        dim_text="#8FEFFF",
        divider="#050607",
        edge="#242833",
        shadow="#8D6800",
    ),
}


def _screen_size(tft: TFTTerminal) -> tuple[int, int]:
    return int(getattr(tft, "width", 320)), int(getattr(tft, "height", 240))


def _text_size(text: str, size: int) -> tuple[int, int]:
    return len(text) * FONT_W * size, FONT_H * size


def _fit_size(text: str, max_w: int, max_h: int, preferred: int) -> int:
    size = max(1, preferred)
    while size > 1:
        tw, th = _text_size(text, size)
        if tw <= max_w and th <= max_h:
            return size
        size -= 1
    return 1


def _center_text(
    tft: TFTTerminal,
    x: int,
    y: int,
    w: int,
    h: int,
    text: str,
    color: str,
    preferred_size: int,
) -> None:
    size = _fit_size(text, max(1, w - 8), max(1, h - 6), preferred_size)
    tw, th = _text_size(text, size)
    tx = x + max(0, (w - tw) // 2)
    ty = y + max(0, (h - th) // 2)
    tft.text(tx, ty, text, color=color, size=size)


def _draw_card(
    tft: TFTTerminal,
    x: int,
    y: int,
    w: int,
    h: int,
    r: int,
    text: str,
    theme: Theme,
    preferred_size: int,
    *,
    text_color: str | None = None,
) -> None:
    text_color = text_color or theme.text

    tft.fill_rounded_rect(x + 3, y + 3, w, h, r, theme.shadow)
    tft.fill_rounded_rect(x, y, w, h, r, theme.card)
    tft.fill_rounded_rect(x + 1, y + 1, max(1, w - 2), max(1, h // 2), r, theme.card_top)
    tft.rounded_rect(x, y, w, h, r, theme.edge)

    split_y = y + h // 2
    tft.hline(x + 2, split_y, max(1, w - 4), theme.divider)
    tft.hline(x + 2, split_y + 1, max(1, w - 4), theme.edge)

    _center_text(tft, x, y, w, h, text, text_color, preferred_size)


def _draw_layout(tft: TFTTerminal, now: datetime, theme: Theme, use_12_hour: bool) -> None:
    w, h = _screen_size(tft)
    scale = min(w / 320.0, h / 240.0)
    pad = max(4, int(10 * scale))
    gap = max(6, int(14 * scale))

    tft.fill_screen(theme.background)

    clock_y = max(6, int(14 * scale))
    clock_h = max(42, int(84 * scale))
    clock_w = min((w - 2 * pad - gap) // 2, int(112 * scale))
    clock_gap = max(gap, w - 2 * pad - 2 * clock_w)
    clock_x = max(pad, (w - 2 * clock_w - clock_gap) // 2)
    radius = max(5, int(16 * scale))

    hour = now.hour
    if use_12_hour:
        hour = hour % 12 or 12
    hour_text = f"{hour:02d}" if not use_12_hour else str(hour)
    minute_text = f"{now.minute:02d}"
    digit_size = max(2, int(8 * scale))

    _draw_card(tft, clock_x, clock_y, clock_w, clock_h, radius, hour_text, theme, digit_size)
    _draw_card(
        tft,
        clock_x + clock_w + clock_gap,
        clock_y,
        clock_w,
        clock_h,
        radius,
        minute_text,
        theme,
        digit_size,
    )

    day_y = clock_y + clock_h + max(12, int(18 * scale))
    day_h = max(28, int(50 * scale))
    day_w = min(w - 2 * pad - 12, int(244 * scale))
    day_x = (w - day_w) // 2
    day_text = calendar.day_name[now.weekday()].upper()
    _draw_card(tft, day_x, day_y, day_w, day_h, max(5, int(9 * scale)),
               day_text, theme, max(2, int(5 * scale)), text_color=theme.dim_text)

    date_y = day_y + day_h + max(12, int(18 * scale))
    date_h = max(28, int(48 * scale))
    date_gap = max(8, int(16 * scale))
    day_num_w = max(44, int(66 * scale))
    month_w = max(74, int(126 * scale))
    total_date_w = day_num_w + date_gap + month_w
    date_x = (w - total_date_w) // 2
    if date_y + date_h + 4 > h:
        date_h = max(20, h - date_y - 4)

    month_text = calendar.month_abbr[now.month].upper()
    _draw_card(tft, date_x, date_y, day_num_w, date_h, max(5, int(9 * scale)),
               str(now.day), theme, max(2, int(5 * scale)), text_color=theme.dim_text)
    _draw_card(
        tft,
        date_x + day_num_w + date_gap,
        date_y,
        month_w,
        date_h,
        max(5, int(9 * scale)),
        month_text,
        theme,
        max(2, int(5 * scale)),
        text_color=theme.dim_text,
    )


def _animate_minute_flip(
    tft: TFTTerminal,
    now: datetime,
    theme: Theme,
    use_12_hour: bool,
    delay: float,
) -> None:
    if delay <= 0:
        _draw_layout(tft, now, theme, use_12_hour)
        return

    w, h = _screen_size(tft)
    scale = min(w / 320.0, h / 240.0)
    pad = max(4, int(10 * scale))
    gap = max(6, int(14 * scale))
    clock_y = max(6, int(14 * scale))
    clock_h = max(42, int(84 * scale))
    clock_w = min((w - 2 * pad - gap) // 2, int(112 * scale))
    clock_gap = max(gap, w - 2 * pad - 2 * clock_w)
    clock_x = max(pad, (w - 2 * clock_w - clock_gap) // 2)
    minute_x = clock_x + clock_w + clock_gap
    radius = max(5, int(16 * scale))

    _draw_card(tft, minute_x, clock_y, clock_w, clock_h, radius, "  ", theme, max(2, int(8 * scale)))
    time.sleep(delay)
    _draw_layout(tft, now, theme, use_12_hour)


def run_clock(args: argparse.Namespace) -> int:
    theme = THEMES[args.theme]

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

    last_stamp = ""
    last_minute = ""
    try:
        with tft:
            if args.require_responses:
                tft.sync()

            while True:
                now = datetime.now()
                stamp = now.strftime("%Y-%m-%d %H:%M")
                minute = now.strftime("%H:%M")
                if stamp != last_stamp:
                    ack_context = nullcontext(tft) if args.require_responses else tft.ack_disabled()
                    with ack_context:
                        if last_minute and minute != last_minute:
                            _animate_minute_flip(
                                tft, now, theme, args.twelve_hour, args.flip_delay
                            )
                        else:
                            _draw_layout(tft, now, theme, args.twelve_hour)
                    last_stamp = stamp
                    last_minute = minute
                time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nClock stopped.")
        return 0
    except Exception as exc:
        print(f"Clock failed: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Flip clock display for the ESP8266 TFT terminal."
    )
    parser.add_argument("host", help="ESP8266 IP address or hostname")
    parser.add_argument("--port", type=int, default=8888)
    parser.add_argument("--display", default="ili9341",
                        help="Display profile name (default: ili9341)")
    parser.add_argument("--rotation", type=int, default=1,
                        help="Display rotation 0-3 (default: 1, landscape)")
    parser.add_argument("--timeout", type=float, default=5.0,
                        help="Socket timeout in seconds (default: 5)")
    parser.add_argument("--require-responses", action="store_true",
                        help="Wait for firmware responses/acks.")
    parser.add_argument("--theme", choices=sorted(THEMES), default="light",
                        help="Clock color theme (default: light)")
    parser.add_argument("--twelve-hour", action="store_true",
                        help="Show 12-hour time instead of 24-hour time.")
    parser.add_argument("--flip-delay", type=float, default=0.08,
                        help="Simple minute-flip blanking delay in seconds.")
    return run_clock(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
