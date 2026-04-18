"""Display procedurally drawn flowers on a Waveshare 2.13" e-Paper HAT (V4).

Setup on the Pi:
    sudo apt install python3-pil python3-numpy python3-spidev
    sudo raspi-config  # enable SPI
    git clone https://github.com/waveshare/e-Paper
    # add e-Paper/RaspberryPi_JetsonNano/python/lib to PYTHONPATH, or pip install it

For V3 change the import to `epd2in13_V3`, for V2 `epd2in13_V2`.
"""

import math
import random
import time
from PIL import Image, ImageDraw

from waveshare_epd import epd2in13_V4

WIDTH, HEIGHT = 250, 122  # landscape
CYCLE_SECONDS = 60
PARTIAL_REFRESHES_BEFORE_FULL = 10


def draw_petal_flower(draw, cx, cy, radius, petals, petal_len):
    for i in range(petals):
        angle = (2 * math.pi * i) / petals
        px = cx + math.cos(angle) * petal_len
        py = cy + math.sin(angle) * petal_len
        draw.ellipse(
            (px - radius, py - radius, px + radius, py + radius),
            fill=0, outline=0,
        )
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


def make_scene(seed):
    rng = random.Random(seed)
    img = Image.new("1", (WIDTH, HEIGHT), 255)
    draw = ImageDraw.Draw(img)

    count = rng.randint(3, 5)
    spacing = WIDTH // (count + 1)
    for i in range(count):
        cx = spacing * (i + 1) + rng.randint(-6, 6)
        ground = HEIGHT - 8
        flower_y = rng.randint(30, 50)
        draw_stem_and_leaves(draw, cx, flower_y, ground)
        rng.choice(FLOWERS)(draw, cx, flower_y)

    draw.line((0, HEIGHT - 6, WIDTH, HEIGHT - 6), fill=0, width=1)
    return img


def main():
    epd = epd2in13_V4.EPD()
    epd.init()
    epd.Clear(0xFF)
    epd.init_fast()

    seed = 0
    partials = 0
    try:
        while True:
            img = make_scene(seed)
            if partials == 0:
                epd.display(epd.getbuffer(img))
            else:
                epd.displayPartial(epd.getbuffer(img))
            partials = (partials + 1) % PARTIAL_REFRESHES_BEFORE_FULL
            seed += 1
            time.sleep(CYCLE_SECONDS)
    except KeyboardInterrupt:
        epd.init()
        epd.Clear(0xFF)
        epd.sleep()


if __name__ == "__main__":
    main()
