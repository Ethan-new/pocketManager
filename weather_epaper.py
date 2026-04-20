#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Current weather on Waveshare 2.13" e-Paper HAT (V4).

Fetches current conditions from Open-Meteo (no API key required), renders
the display, then puts the panel to sleep. Refreshes once per hour.

Edit LAT, LON, LOCATION_NAME, and UNITS below for your location.
"""
import os
import sys
import time
import logging
import traceback
import json
import urllib.request
import urllib.parse
import socket
import subprocess
from datetime import datetime, timedelta

libdir = '/home/ethan/e-Paper/RaspberryPi_JetsonNano/python/lib'
if os.path.exists(libdir):
    sys.path.append(libdir)

from PIL import Image, ImageDraw, ImageFont

# EPD_WIDTH/HEIGHT match Waveshare 2.13" V4 in landscape.
EPD_W, EPD_H = 250, 122

logging.basicConfig(level=logging.INFO)

# ---- CONFIG ----------------------------------------------------------------
LAT = 43.6532
LON = -79.3832
LOCATION_NAME = "Toronto"
UNITS = "celsius"      # "fahrenheit" or "celsius"
WIND_UNITS = "kmh"     # "mph", "kmh", "ms", "kn"
# Wait for network after boot (systemd can start before wifi associates).
NETWORK_WAIT_SECONDS = 30
# Seconds between refreshes.
REFRESH_INTERVAL_SECONDS = 180
# PiSugar RTC daemon (pisugar-server) TCP socket.
PISUGAR_ADDR = ("127.0.0.1", 8423)
# ----------------------------------------------------------------------------

# WMO weather codes → (short label, icon key)
# https://open-meteo.com/en/docs  (search "WMO Weather interpretation codes")
WMO = {
    0:  ("Clear",          "sun"),
    1:  ("Mostly clear",   "sun"),
    2:  ("Partly cloudy",  "partly"),
    3:  ("Overcast",       "cloud"),
    45: ("Fog",            "fog"),
    48: ("Rime fog",       "fog"),
    51: ("Light drizzle",  "rain"),
    53: ("Drizzle",        "rain"),
    55: ("Heavy drizzle",  "rain"),
    61: ("Light rain",     "rain"),
    63: ("Rain",           "rain"),
    65: ("Heavy rain",     "rain"),
    66: ("Freezing rain",  "rain"),
    67: ("Freezing rain",  "rain"),
    71: ("Light snow",     "snow"),
    73: ("Snow",           "snow"),
    75: ("Heavy snow",     "snow"),
    77: ("Snow grains",    "snow"),
    80: ("Rain showers",   "rain"),
    81: ("Rain showers",   "rain"),
    82: ("Heavy showers",  "rain"),
    85: ("Snow showers",   "snow"),
    86: ("Snow showers",   "snow"),
    95: ("Thunderstorm",   "storm"),
    96: ("Thunderstorm",   "storm"),
    99: ("Thunderstorm",   "storm"),
}


def fetch_weather():
    params = urllib.parse.urlencode({
        "latitude": LAT,
        "longitude": LON,
        "current": "temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m",
        "temperature_unit": UNITS,
        "wind_speed_unit": WIND_UNITS,
        "timezone": "auto",
    })
    url = f"https://api.open-meteo.com/v1/forecast?{params}"
    logging.info("fetching %s", url)
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode())


def _pisugar_send(cmd, timeout=3):
    with socket.create_connection(PISUGAR_ADDR, timeout=timeout) as s:
        s.sendall((cmd + "\n").encode())
        return s.recv(1024).decode(errors="replace")


def schedule_pisugar_wake(seconds_from_now):
    """Set the PiSugar RTC alarm `seconds_from_now` from now. Returns True on success."""
    wake = datetime.now().astimezone() + timedelta(seconds=seconds_from_now)
    iso = wake.strftime("%Y-%m-%dT%H:%M:%S%z")
    iso = iso[:-2] + ":" + iso[-2:]  # +0000 -> +00:00
    try:
        sync_resp = _pisugar_send("rtc_pi2rtc").strip()
        logging.info("pisugar rtc_pi2rtc -> %s", sync_resp)
        resp = _pisugar_send(f"rtc_alarm_set {iso} 127").strip()
        logging.info("pisugar rtc_alarm_set -> %s", resp)
        # pisugar-server replies with the echoed command on success and a line
        # containing "error"/"fail" on failure. Treat anything that looks like
        # an error as a failure so we don't shut down into the dark.
        lowered = resp.lower()
        if "error" in lowered or "fail" in lowered or "invalid" in lowered:
            logging.error("pisugar rejected alarm: %s", resp)
            return False
        return True
    except Exception as e:
        logging.error("pisugar wake schedule failed: %s", e)
        return False


def wifi_status():
    """Return (connected, bars) where bars is 0..4. Uses /proc/net/wireless
    on Linux; falls back to a socket reachability probe elsewhere."""
    try:
        with open("/proc/net/wireless") as f:
            lines = f.readlines()
        for line in lines[2:]:
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                quality = float(parts[2].rstrip("."))
            except ValueError:
                continue
            if quality >= 55:
                bars = 4
            elif quality >= 40:
                bars = 3
            elif quality >= 25:
                bars = 2
            elif quality > 0:
                bars = 1
            else:
                bars = 0
            return (True, bars)
    except Exception:
        pass
    try:
        import socket
        s = socket.create_connection(("8.8.8.8", 53), timeout=1)
        s.close()
        return (True, 3)
    except Exception:
        return (False, 0)


def draw_wifi_icon(draw, x, y, connected, bars):
    """Draw a small 4-bar wifi icon with top-left at (x, y). ~12x9 px."""
    if not connected:
        draw.rectangle((x, y + 1, x + 11, y + 9), outline=0)
        draw.line((x + 1, y + 2, x + 10, y + 8), fill=0)
        draw.line((x + 1, y + 8, x + 10, y + 2), fill=0)
        return
    heights = (3, 5, 7, 9)
    for i, h in enumerate(heights):
        bx = x + i * 3
        top = y + (9 - h)
        if i < bars:
            draw.rectangle((bx, top, bx + 2, y + 9), fill=0)
        else:
            draw.rectangle((bx, top, bx + 2, y + 9), outline=0)


def wait_for_network():
    deadline = time.time() + NETWORK_WAIT_SECONDS
    while time.time() < deadline:
        try:
            urllib.request.urlopen("https://api.open-meteo.com", timeout=3)
            return True
        except urllib.error.HTTPError:
            # Got an HTTP response (e.g. 404 on root) — network is up.
            return True
        except Exception:
            time.sleep(2)
    return False


_FONT_PATHS = (
    # Linux / Raspberry Pi
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    # macOS (for preview rendering)
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    # macOS Homebrew DejaVu (if installed)
    "/opt/homebrew/share/fonts/dejavu/DejaVuSans-Bold.ttf",
)


def _load_font(size):
    for path in _FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


import math


def _cloud(draw, cx, cy, r, width=2):
    # Fluffy cloud built from four overlapping disks with a flat base,
    # then a single outline traced around the top bumps. Filled white first
    # to erase internal strokes.
    # Three bumps + a base.
    bumps = [
        (cx - int(r * 0.7), cy, int(r * 0.55)),
        (cx - int(r * 0.1), cy - int(r * 0.25), int(r * 0.65)),
        (cx + int(r * 0.55), cy, int(r * 0.5)),
    ]
    base_top = cy + int(r * 0.15)
    base_bot = cy + int(r * 0.55)
    base_left = cx - int(r * 0.85)
    base_right = cx + int(r * 0.9)

    # Fill interiors (white) to erase, then stroke (black).
    for bx, by, br in bumps:
        draw.ellipse((bx - br, by - br, bx + br, by + br), fill=255, outline=0, width=width)
    # White rectangle to hide the lower halves of the bumps and create a flat bottom.
    draw.rectangle((base_left, base_top, base_right, base_bot + 3), fill=255)
    # Bottom line.
    draw.line((base_left, base_bot, base_right, base_bot), fill=0, width=width)
    # Tiny arcs to close the sides.
    draw.line((base_left, base_top + 2, base_left, base_bot), fill=0, width=width)
    draw.line((base_right, base_top + 2, base_right, base_bot), fill=0, width=width)
    return base_bot


def draw_icon(draw, cx, cy, r, kind):
    if kind == "sun":
        rr = int(r * 0.55)
        draw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=255, outline=0, width=2)
        for i in range(8):
            a = i * math.pi / 4
            x0 = cx + int(math.cos(a) * (rr + 3))
            y0 = cy + int(math.sin(a) * (rr + 3))
            x1 = cx + int(math.cos(a) * r)
            y1 = cy + int(math.sin(a) * r)
            draw.line((x0, y0, x1, y1), fill=0, width=2)
    elif kind == "partly":
        # sun peeking out behind a cloud
        rr = int(r * 0.45)
        sx, sy = cx - int(r * 0.35), cy - int(r * 0.25)
        draw.ellipse((sx - rr, sy - rr, sx + rr, sy + rr), fill=255, outline=0, width=2)
        for i in range(8):
            a = i * math.pi / 4
            x0 = sx + int(math.cos(a) * (rr + 2))
            y0 = sy + int(math.sin(a) * (rr + 2))
            x1 = sx + int(math.cos(a) * (rr + 7))
            y1 = sy + int(math.sin(a) * (rr + 7))
            draw.line((x0, y0, x1, y1), fill=0, width=2)
        _cloud(draw, cx + int(r * 0.15), cy + int(r * 0.15), int(r * 0.8))
    elif kind == "cloud":
        _cloud(draw, cx, cy, r)
    elif kind == "rain":
        base = _cloud(draw, cx, cy - int(r * 0.25), int(r * 0.85))
        for x in (cx - int(r * 0.5), cx - int(r * 0.1), cx + int(r * 0.35)):
            draw.line((x, base + 3, x - 4, base + 12), fill=0, width=2)
    elif kind == "snow":
        base = _cloud(draw, cx, cy - int(r * 0.25), int(r * 0.85))
        for x in (cx - int(r * 0.5), cx - int(r * 0.05), cx + int(r * 0.4)):
            y = base + 8
            draw.line((x - 4, y, x + 4, y), fill=0, width=1)
            draw.line((x, y - 4, x, y + 4), fill=0, width=1)
            draw.line((x - 3, y - 3, x + 3, y + 3), fill=0, width=1)
            draw.line((x - 3, y + 3, x + 3, y - 3), fill=0, width=1)
    elif kind == "storm":
        base = _cloud(draw, cx, cy - int(r * 0.25), int(r * 0.85))
        # lightning bolt
        draw.polygon(
            [(cx - 2, base + 1), (cx + 5, base + 1),
             (cx + 1, base + 8), (cx + 6, base + 8),
             (cx - 4, base + 18), (cx, base + 10),
             (cx - 5, base + 10)],
            fill=0,
        )
    elif kind == "fog":
        _cloud(draw, cx, cy - int(r * 0.35), int(r * 0.75))
        for dy in (int(r * 0.55), int(r * 0.8)):
            draw.line((cx - r + 2, cy + dy, cx + r - 2, cy + dy), fill=0, width=2)


def recommend_jacket(temp_f, code, wind_mph):
    """Return (label, jacket_kind) given weather inputs.

    jacket_kind is one of: "none", "light", "wind", "rain", "winter", "heavy".
    Inputs always in °F and mph regardless of display units (caller converts).
    """
    raining = code in (51, 53, 55, 61, 63, 65, 66, 67, 80, 81, 82)
    snowing = code in (71, 73, 75, 77, 85, 86)
    storm = code in (95, 96, 99)

    if snowing or temp_f <= 28:
        return ("Winter coat", "winter")
    if storm:
        return ("Rain + hood", "heavy")
    if raining:
        return ("Rain jacket", "rain")
    if temp_f <= 45:
        return ("Heavy jacket", "heavy")
    if temp_f <= 58:
        if wind_mph >= 15:
            return ("Windbreaker", "wind")
        return ("Light jacket", "light")
    if temp_f <= 70:
        if wind_mph >= 18:
            return ("Windbreaker", "wind")
        return ("Sweater", "light")
    return ("No jacket", "none")


def draw_jacket(draw, cx, cy, r, kind):
    """Draw a garment silhouette as a single continuous outline.

    Origin at roughly the collar-center; sized ~2r wide by ~2r tall.
    """
    # Proportions
    neck_w = int(r * 0.22)
    shoulder_w = int(r * 1.5)
    shoulder_dy = int(r * 0.15)   # how far shoulders drop from collar
    sleeve_w = int(r * 0.55)      # horizontal sleeve thickness
    sleeve_dy = int(r * 1.0)      # sleeve length
    armpit_in = int(r * 0.25)     # how far sleeve inside-line cuts toward body
    body_w = int(r * 1.05)
    body_h = int(r * 1.25)

    # Anchor: top-center of collar at cy - r + small offset
    top_y = cy - r + 2

    # Short sleeves for the t-shirt case
    if kind == "none":
        sleeve_dy = int(r * 0.35)
        sleeve_w = int(r * 0.35)

    # Build the outline polygon, going clockwise from the left side of the collar.
    neck_left  = (cx - neck_w, top_y)
    neck_right = (cx + neck_w, top_y)
    neck_dip   = (cx, top_y + int(r * 0.18))

    l_shoulder = (cx - shoulder_w // 2,           top_y + shoulder_dy)
    l_cuff_out = (cx - shoulder_w // 2 - 2,       top_y + shoulder_dy + sleeve_dy)
    l_cuff_in  = (cx - shoulder_w // 2 + sleeve_w, top_y + shoulder_dy + sleeve_dy)
    l_armpit   = (cx - body_w // 2,               top_y + shoulder_dy + armpit_in)
    l_hem      = (cx - body_w // 2 - 4,           top_y + shoulder_dy + body_h)

    r_hem      = (cx + body_w // 2 + 4,           top_y + shoulder_dy + body_h)
    r_armpit   = (cx + body_w // 2,               top_y + shoulder_dy + armpit_in)
    r_cuff_in  = (cx + shoulder_w // 2 - sleeve_w, top_y + shoulder_dy + sleeve_dy)
    r_cuff_out = (cx + shoulder_w // 2 + 2,       top_y + shoulder_dy + sleeve_dy)
    r_shoulder = (cx + shoulder_w // 2,           top_y + shoulder_dy)

    outline = [
        neck_left, l_shoulder, l_cuff_out, l_cuff_in, l_armpit, l_hem,
        r_hem, r_armpit, r_cuff_in, r_cuff_out, r_shoulder, neck_right,
        neck_dip,
    ]

    # Hood behind (drawn first so body covers bottom of the hood arc)
    has_hood = kind in ("winter", "rain", "heavy")
    if has_hood:
        hood_r = int(r * 0.55)
        hx = cx
        hy = top_y + int(r * 0.1)
        draw.chord((hx - hood_r, hy - hood_r, hx + hood_r, hy + hood_r),
                   180, 360, fill=255, outline=0)

    draw.polygon(outline, fill=255, outline=0)

    # Zipper (not on t-shirt)
    if kind != "none":
        draw.line((cx, neck_dip[1], cx, l_hem[1] - 2), fill=0, width=1)

    # --- Variant details ---
    if kind == "winter":
        # quilting bands across body
        body_top = neck_dip[1] + 4
        body_bot = l_hem[1] - 3
        for fy in range(body_top + 6, body_bot, 9):
            draw.line((cx - body_w // 2 + 2, fy, cx - 2, fy), fill=0, width=1)
            draw.line((cx + 2, fy, cx + body_w // 2 - 2, fy), fill=0, width=1)
    elif kind == "rain":
        # raindrops falling around the jacket
        for (dx, dy) in ((-shoulder_w // 2 - 8, 2), (shoulder_w // 2 + 6, 10),
                         (-shoulder_w // 2 - 6, 16), (shoulder_w // 2 + 10, 22)):
            rx = cx + dx
            ry = cy + dy
            draw.line((rx, ry, rx - 3, ry + 5), fill=0, width=1)
    elif kind == "heavy":
        # heavier quilting + collar emphasis
        body_top = neck_dip[1] + 6
        body_bot = l_hem[1] - 3
        for fy in range(body_top + 4, body_bot, 11):
            draw.line((cx - body_w // 2 + 3, fy, cx - 3, fy), fill=0, width=1)
            draw.line((cx + 3, fy, cx + body_w // 2 - 3, fy), fill=0, width=1)
    elif kind == "wind":
        # horizontal gust streaks to the left of the jacket
        for (y_off, length) in ((-8, 14), (2, 18), (12, 12)):
            y = cy + y_off
            draw.line((cx - shoulder_w // 2 - length - 4, y,
                       cx - shoulder_w // 2 - 4, y), fill=0, width=1)
    elif kind == "light":
        # two angled pocket slits
        body_mid_y = (neck_dip[1] + l_hem[1]) // 2 + 4
        draw.line((cx - body_w // 3, body_mid_y,
                   cx - 4, body_mid_y + 5), fill=0, width=1)
        draw.line((cx + 4, body_mid_y + 5,
                   cx + body_w // 3, body_mid_y), fill=0, width=1)
    elif kind == "none":
        # small sun above the t-shirt to signal "nice out"
        sx = cx + shoulder_w // 2 + 8
        sy = cy - r + 4
        sr = 4
        draw.ellipse((sx - sr, sy - sr, sx + sr, sy + sr), outline=0, width=1)
        for a in range(8):
            import math as _m
            ang = a * _m.pi / 4
            x0 = sx + int(_m.cos(ang) * (sr + 1))
            y0 = sy + int(_m.sin(ang) * (sr + 1))
            x1 = sx + int(_m.cos(ang) * (sr + 4))
            y1 = sy + int(_m.sin(ang) * (sr + 4))
            draw.line((x0, y0, x1, y1), fill=0, width=1)


def make_frame(width, height, data, wifi=(True, 4)):
    img = Image.new('1', (width, height), 255)
    draw = ImageDraw.Draw(img)
    wifi_connected, wifi_bars = wifi

    cur = data.get("current", {})
    code = cur.get("weather_code", 0)
    temp = cur.get("temperature_2m")
    wind = cur.get("wind_speed_10m")
    humidity = cur.get("relative_humidity_2m")
    label, icon_kind = WMO.get(code, ("Unknown", "cloud"))

    font_big = _load_font(58)
    font_mid = _load_font(14)
    font_sm = _load_font(11)

    deg_char = "°F" if UNITS == "fahrenheit" else "°C"
    temp_text = f"{round(temp)}" if temp is not None else "--"

    # Header strip: location + time
    header_h = 14
    now = datetime.now().strftime("%a %b %d  %H:%M")
    draw.text((4, 1), LOCATION_NAME, fill=0, font=font_sm)
    tw = draw.textlength(now, font=font_sm)
    time_x = width - tw - 4
    draw.text((time_x, 1), now, fill=0, font=font_sm)
    draw_wifi_icon(draw, time_x - 16, 2, wifi_connected, wifi_bars)
    draw.line((0, header_h, width, header_h), fill=0, width=1)

    # Vertical split: left = temp + condition, right = jacket recommendation.
    body_top = header_h
    body_bot = height
    split_x = int(width * 0.55)
    draw.line((split_x, body_top + 3, split_x, body_bot - 3), fill=0, width=1)

    # --- LEFT pane ---
    left_w = split_x
    # Temperature: big number + small unit, treated as one visual block and
    # vertically centered in the upper ~60% of the left pane.
    temp_box = draw.textbbox((0, 0), temp_text, font=font_big)
    temp_w = temp_box[2] - temp_box[0]
    temp_h = temp_box[3] - temp_box[1]
    unit_w = draw.textlength(deg_char, font=font_mid)
    unit_h = 14  # font_mid pixel height, approx
    block_w = temp_w + 2 + unit_w

    # Target Y: center temp in left pane, but leave room for condition at bottom.
    cond_h = 14
    temp_area_top = body_top + 2
    temp_area_bot = body_bot - cond_h - 2
    temp_cy = (temp_area_top + temp_area_bot) // 2

    temp_x = max(4, (left_w - block_w) // 2)
    temp_y = temp_cy - temp_h // 2 - temp_box[1]
    draw.text((temp_x, temp_y), temp_text, fill=0, font=font_big)
    # Unit sits at the top-right of the big number (superscript-style).
    unit_x = temp_x + temp_w + 2
    unit_y = temp_cy - temp_h // 2 + 4  # near top of big-number cap height
    draw.text((unit_x, unit_y), deg_char, fill=0, font=font_mid)

    # Condition label, centered along the bottom of the left pane.
    cond_w = draw.textlength(label, font=font_sm)
    draw.text(((left_w - cond_w) // 2, body_bot - cond_h), label, fill=0, font=font_sm)

    # --- RIGHT: jacket recommendation ---
    # Jacket icon + label ("Wear:" header + type)
    if temp is not None:
        temp_f = temp if UNITS == "fahrenheit" else temp * 9 / 5 + 32
    else:
        temp_f = 60
    if wind is not None:
        wind_mph = wind if WIND_UNITS == "mph" else wind * 0.621371
    else:
        wind_mph = 0
    rec_label, rec_kind = recommend_jacket(temp_f, code, wind_mph)

    right_x0 = split_x + 1
    right_w = width - right_x0
    right_cx = right_x0 + right_w // 2

    # Jacket icon — centered in available right pane, as large as fits.
    # Hooded variants have extra vertical height (hood arc ~0.45r above the
    # body top), so they need a tighter r. Total vertical span:
    #   no hood : ~2.0 r
    #   hooded  : ~2.45 r
    label_reserve = 14  # space for the recommendation label at the bottom
    pane_top = body_top + 4
    pane_bot = body_bot - label_reserve
    pane_h = pane_bot - pane_top
    vertical_factor = 2.45 if rec_kind in ("winter", "rain", "heavy") else 2.05
    jacket_r = int(min(right_w // 2 - 4, pane_h / vertical_factor))
    # Anchor so the total silhouette (including hood) is vertically centered.
    top_extra = int(jacket_r * 0.45) if rec_kind in ("winter", "rain", "heavy") else 0
    jacket_cy = pane_top + top_extra + jacket_r
    draw_jacket(draw, right_cx, jacket_cy, jacket_r, rec_kind)

    # Recommendation label under jacket
    lw = draw.textlength(rec_label, font=font_sm)
    # if it doesn't fit, drop to a shorter rendering
    if lw > right_w - 4:
        short = rec_label.split()[0]
        lw = draw.textlength(short, font=font_sm)
        rec_label = short
    draw.text((right_cx - lw // 2, body_bot - 13), rec_label, fill=0, font=font_sm)

    return img


def make_error_frame(width, height, message):
    img = Image.new('1', (width, height), 255)
    draw = ImageDraw.Draw(img)
    draw.text((6, 6), "Weather unavailable", fill=0, font=_load_font(16))
    draw.text((6, 28), message[:60], fill=0, font=_load_font(12))
    draw.text((6, height - 14), datetime.now().strftime("%a %b %d  %H:%M"),
              fill=0, font=_load_font(12))
    return img


def main():
    # Preview mode: render a grid of scenarios to preview.png and exit.
    if "--preview" in sys.argv:
        scenarios = [
            ("Clear warm",    {"weather_code": 0,  "temperature_2m": 26, "wind_speed_10m": 8,  "relative_humidity_2m": 40}),
            ("Cool mild",     {"weather_code": 2,  "temperature_2m": 17, "wind_speed_10m": 13, "relative_humidity_2m": 55}),
            ("Cool windy",    {"weather_code": 3,  "temperature_2m": 16, "wind_speed_10m": 32, "relative_humidity_2m": 60}),
            ("Rainy",         {"weather_code": 63, "temperature_2m": 11, "wind_speed_10m": 16, "relative_humidity_2m": 90}),
            ("Thunderstorm",  {"weather_code": 95, "temperature_2m": 14, "wind_speed_10m": 35, "relative_humidity_2m": 85}),
            ("Snowy",         {"weather_code": 73, "temperature_2m": -4, "wind_speed_10m": 19, "relative_humidity_2m": 75}),
            ("Cold clear",    {"weather_code": 1,  "temperature_2m":  3, "wind_speed_10m": 10, "relative_humidity_2m": 50}),
            ("Foggy",         {"weather_code": 45, "temperature_2m":  9, "wind_speed_10m":  6, "relative_humidity_2m": 95}),
        ]
        scale = 3
        label_h = 16
        gap = 10
        cols = 2
        rows = (len(scenarios) + cols - 1) // cols
        cell_w = EPD_W * scale
        cell_h = EPD_H * scale + label_h
        grid_w = cols * cell_w + (cols + 1) * gap
        grid_h = rows * cell_h + (rows + 1) * gap
        grid = Image.new("L", (grid_w, grid_h), 220)
        try:
            label_font = ImageFont.truetype(
                "/System/Library/Fonts/Helvetica.ttc", 14)
        except Exception:
            label_font = ImageFont.load_default()
        gdraw = ImageDraw.Draw(grid)
        for i, (name, cur) in enumerate(scenarios):
            r, c = divmod(i, cols)
            x = gap + c * (cell_w + gap)
            y = gap + r * (cell_h + gap)
            img = make_frame(EPD_W, EPD_H, {"current": cur})
            big = img.convert("L").resize((cell_w, EPD_H * scale), Image.NEAREST)
            grid.paste(big, (x, y))
            gdraw.text((x + 4, y + EPD_H * scale + 2), name, fill=0, font=label_font)
        grid.save("preview.png")
        logging.info("wrote preview.png (%dx%d, %d scenarios)", grid_w, grid_h, len(scenarios))
        return

    shutdown_after = "--no-shutdown" not in sys.argv

    from waveshare_epd import epd2in13_V4
    epd = epd2in13_V4.EPD()
    try:
        logging.info("weather_epaper: refresh")
        epd.init()
        epd.Clear(0xFF)
        w, h = epd.height, epd.width  # landscape

        if not wait_for_network():
            logging.warning("network not ready, rendering error frame")
            epd.display(epd.getbuffer(make_error_frame(w, h, "no network")))
        else:
            try:
                data = fetch_weather()
                epd.display(epd.getbuffer(make_frame(w, h, data, wifi=wifi_status())))
            except Exception as e:
                logging.error("fetch failed: %s", e)
                epd.display(epd.getbuffer(make_error_frame(w, h, str(e))))

        # Hold the image with no power.
        epd.sleep()
    except Exception:
        logging.error(traceback.format_exc())

    if shutdown_after:
        if schedule_pisugar_wake(REFRESH_INTERVAL_SECONDS):
            logging.info("shutting down; PiSugar will wake in %ds", REFRESH_INTERVAL_SECONDS)
            result = subprocess.run(
                ["sudo", "-n", "shutdown", "-h", "now"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                return
            logging.error(
                "shutdown failed (rc=%s): stdout=%r stderr=%r; "
                "falling back to in-process sleep loop",
                result.returncode, result.stdout.strip(), result.stderr.strip(),
            )
        else:
            logging.warning("deep sleep unavailable; falling back to in-process sleep loop")

    # Fallback: keep the process alive and refresh on interval.
    try:
        while True:
            time.sleep(REFRESH_INTERVAL_SECONDS)
            try:
                epd.init()
                if not wait_for_network():
                    epd.display(epd.getbuffer(make_error_frame(w, h, "no network")))
                else:
                    data = fetch_weather()
                    epd.display(epd.getbuffer(make_frame(w, h, data, wifi=wifi_status())))
                epd.sleep()
            except Exception:
                logging.error(traceback.format_exc())
    except KeyboardInterrupt:
        epd.init()
        epd.Clear(0xFF)
        epd.sleep()
        epd2in13_V4.epdconfig.module_exit(cleanup=True)


if __name__ == "__main__":
    main()
