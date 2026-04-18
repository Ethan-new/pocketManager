#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Tamagotchi face on Waveshare 2.13" e-Paper HAT (V4).

Cycles through a set of facial expressions every CYCLE_SECONDS.
Same libdir/lifecycle pattern as flowers_epaper.py.
"""
import os
import sys
import time
import logging
import traceback

libdir = '/home/ethan/e-Paper/RaspberryPi_JetsonNano/python/lib'
if os.path.exists(libdir):
    sys.path.append(libdir)

from waveshare_epd import epd2in13_V4
from PIL import Image, ImageDraw

logging.basicConfig(level=logging.INFO)

CYCLE_SECONDS = 5
PARTIAL_REFRESHES_BEFORE_FULL = 20


def _face_bounds(w, h):
    # Centered face, leaves a small margin.
    margin = 6
    size = min(w, h) - margin * 2
    cx, cy = w // 2, h // 2
    return cx, cy, size // 2  # center + radius


def _draw_head(draw, cx, cy, r):
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255, outline=0, width=3)


def _draw_eye(draw, x, y, kind, size=10):
    s = size
    if kind == "open":
        draw.ellipse((x - s, y - s, x + s, y + s), fill=0)
    elif kind == "closed":
        draw.line((x - s, y, x + s, y), fill=0, width=3)
    elif kind == "happy":  # ^ ^
        draw.line((x - s, y + s // 2, x, y - s // 2), fill=0, width=3)
        draw.line((x, y - s // 2, x + s, y + s // 2), fill=0, width=3)
    elif kind == "dead":  # X X
        draw.line((x - s, y - s, x + s, y + s), fill=0, width=3)
        draw.line((x - s, y + s, x + s, y - s), fill=0, width=3)
    elif kind == "wink_left":
        draw.line((x - s, y, x + s, y), fill=0, width=3)
    elif kind == "heart":
        # two small circles + triangle
        draw.ellipse((x - s, y - s, x, y), fill=0)
        draw.ellipse((x, y - s, x + s, y), fill=0)
        draw.polygon([(x - s, y - 1), (x + s, y - 1), (x, y + s)], fill=0)
    elif kind == "surprised":
        draw.ellipse((x - s - 2, y - s - 2, x + s + 2, y + s + 2), outline=0, width=3)
    elif kind == "sleepy":
        draw.arc((x - s, y - s, x + s, y + s), 200, 340, fill=0, width=3)


def _draw_mouth(draw, cx, cy, kind, w=40, h=20):
    x0, y0 = cx - w // 2, cy - h // 2
    x1, y1 = cx + w // 2, cy + h // 2
    if kind == "smile":
        draw.arc((x0, y0 - h, x1, y1), 0, 180, fill=0, width=3)
    elif kind == "grin":
        draw.chord((x0, y0 - h // 2, x1, y1), 0, 180, fill=0)
    elif kind == "frown":
        draw.arc((x0, y0, x1, y1 + h), 180, 360, fill=0, width=3)
    elif kind == "flat":
        draw.line((x0, cy, x1, cy), fill=0, width=3)
    elif kind == "o":
        draw.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), outline=0, width=3)
    elif kind == "tongue":
        draw.arc((x0, y0 - h, x1, y1), 0, 180, fill=0, width=3)
        draw.ellipse((cx - 4, cy + 2, cx + 6, cy + 12), fill=0)
    elif kind == "zzz":
        draw.line((x0, cy, x1, cy), fill=0, width=3)


def _draw_extras(draw, cx, cy, r, kind):
    if kind == "zzz":
        # little "z z Z" above head
        zx, zy = cx + r - 10, cy - r - 4
        for i, size in enumerate((4, 6, 9)):
            x = zx + i * (size + 2)
            y = zy - i * 4
            draw.line((x, y, x + size, y), fill=0, width=2)
            draw.line((x + size, y, x, y + size), fill=0, width=2)
            draw.line((x, y + size, x + size, y + size), fill=0, width=2)
    elif kind == "sweat":
        sx, sy = cx + r - 6, cy - r // 2
        draw.polygon([(sx, sy), (sx - 5, sy + 10), (sx + 5, sy + 10)], fill=0)


# name, left-eye, right-eye, mouth, extras
EXPRESSIONS = [
    ("happy",     "happy",     "happy",     "smile",  None),
    ("neutral",   "open",      "open",      "flat",   None),
    ("surprised", "surprised", "surprised", "o",      None),
    ("wink",      "wink_left", "open",      "smile",  None),
    ("love",      "heart",     "heart",     "smile",  None),
    ("sleepy",    "sleepy",    "sleepy",    "zzz",    "zzz"),
    ("sad",       "open",      "open",      "frown",  "sweat"),
    ("silly",     "closed",    "open",      "tongue", None),
    ("dead",      "dead",      "dead",      "flat",   None),
    ("grin",      "happy",     "happy",     "grin",   None),
]


def make_face(width, height, index):
    name, le, re_, mouth, extras = EXPRESSIONS[index % len(EXPRESSIONS)]
    img = Image.new('1', (width, height), 255)
    draw = ImageDraw.Draw(img)

    cx, cy, r = _face_bounds(width, height)
    _draw_head(draw, cx, cy, r)

    eye_dx = r // 2
    eye_y = cy - r // 4
    _draw_eye(draw, cx - eye_dx, eye_y, le)
    _draw_eye(draw, cx + eye_dx, eye_y, re_)

    _draw_mouth(draw, cx, cy + r // 2, mouth, w=r, h=r // 3)

    if extras:
        _draw_extras(draw, cx, cy, r, extras)

    # small label so you can tell which one is up
    draw.text((4, height - 12), name, fill=0)
    return img


def main():
    try:
        logging.info("tamagotchi_epaper: init")
        epd = epd2in13_V4.EPD()
        epd.init()
        epd.Clear(0xFF)

        w, h = epd.height, epd.width  # landscape

        first = make_face(w, h, 0)
        epd.displayPartBaseImage(epd.getbuffer(first))

        i = 1
        partials = 0
        while True:
            time.sleep(CYCLE_SECONDS)
            img = make_face(w, h, i)
            if partials >= PARTIAL_REFRESHES_BEFORE_FULL:
                logging.info("full refresh")
                epd.init()
                epd.display(epd.getbuffer(img))
                epd.displayPartBaseImage(epd.getbuffer(img))
                partials = 0
            else:
                epd.displayPartial(epd.getbuffer(img))
                partials += 1
            i += 1

    except KeyboardInterrupt:
        logging.info("ctrl+c: clearing and sleeping display")
        epd.init()
        epd.Clear(0xFF)
        epd.sleep()
        epd2in13_V4.epdconfig.module_exit(cleanup=True)
    except Exception:
        logging.error(traceback.format_exc())


if __name__ == "__main__":
    main()
