#!/usr/bin/python
# -*- coding:utf-8 -*-
"""Procedurally drawn flower garden on Waveshare 2.13" e-Paper HAT (V4).

Place this file in the SAME directory as the working Waveshare demo
(the one that does `sys.path.append(libdir)` to find `waveshare_epd`).
It reuses that same lib/ path trick.
"""
import os
import sys
import math
import random
import time
import logging
import traceback

libdir = '/home/ethan/e-Paper/RaspberryPi_JetsonNano/python/lib'
if os.path.exists(libdir):
    sys.path.append(libdir)

from waveshare_epd import epd2in13_V4
from PIL import Image, ImageDraw

logging.basicConfig(level=logging.INFO)

CYCLE_SECONDS = 60
PARTIAL_REFRESHES_BEFORE_FULL = 10


def draw_petal_flower(draw, cx, cy, radius, petals, petal_len):
    for i in range(petals):
        a = (2 * math.pi * i) / petals
        px = cx + math.cos(a) * petal_len
        py = cy + math.sin(a) * petal_len
        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=0, outline=0)
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=255, outline=0)


def draw_daisy(draw, cx, cy):
    draw_petal_flower(draw, cx, cy, radius=8, petals=8, petal_len=14)
    draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=0)


def draw_tulip(draw, cx, cy):
    draw.polygon(
        [(cx - 14, cy), (cx, cy - 22), (cx + 14, cy),
         (cx + 8, cy + 6), (cx, cy - 4), (cx - 8, cy + 6)],
        fill=0,
    )


def draw_sunflower(draw, cx, cy):
    draw_petal_flower(draw, cx, cy, radius=6, petals=12, petal_len=18)
    draw.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), fill=0)


def draw_stem_and_leaves(draw, cx, cy_top, cy_bottom):
    draw.line((cx, cy_top, cx, cy_bottom), fill=0, width=2)
    mid = (cy_top + cy_bottom) // 2
    draw.chord((cx, mid - 6, cx + 20, mid + 6), 180, 360, fill=0)
    draw.chord((cx - 20, mid + 4, cx, mid + 16), 0, 180, fill=0)


FLOWERS = [draw_daisy, draw_tulip, draw_sunflower]


def make_scene(width, height, seed):
    rng = random.Random(seed)
    img = Image.new('1', (width, height), 255)
    draw = ImageDraw.Draw(img)
    count = rng.randint(3, 5)
    spacing = width // (count + 1)
    for i in range(count):
        cx = spacing * (i + 1) + rng.randint(-6, 6)
        ground = height - 8
        flower_y = rng.randint(30, 50)
        draw_stem_and_leaves(draw, cx, flower_y, ground)
        rng.choice(FLOWERS)(draw, cx, flower_y)
    draw.line((0, height - 6, width, height - 6), fill=0, width=1)
    return img


def main():
    try:
        logging.info("flowers_epaper: init")
        epd = epd2in13_V4.EPD()
        epd.init()
        epd.Clear(0xFF)

        # landscape: (epd.height, epd.width) matches the working demo
        w, h = epd.height, epd.width

        first = make_scene(w, h, seed=0)
        epd.displayPartBaseImage(epd.getbuffer(first))

        seed = 1
        partials = 0
        while True:
            img = make_scene(w, h, seed)
            if partials >= PARTIAL_REFRESHES_BEFORE_FULL:
                logging.info("full refresh")
                epd.init()
                epd.display(epd.getbuffer(img))
                epd.displayPartBaseImage(epd.getbuffer(img))
                partials = 0
            else:
                epd.displayPartial(epd.getbuffer(img))
                partials += 1
            seed += 1
            time.sleep(CYCLE_SECONDS)

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
