#!/usr/bin/env python3
"""Deterministically build the original pixel art used by Codex Pixel Office.

The artwork is intentionally drawn on tiny logical canvases and enlarged with
nearest-neighbour sampling.  That keeps every edge aligned to a real pixel grid
and makes the assets reproducible without storing source artwork elsewhere.
"""

from __future__ import annotations

import argparse
import hashlib
import random
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "static" / "assets"

SEED = 0xC0DE_2026
BG_LOGICAL_SIZE = (320, 180)
BG_SCALE = 4
BG_SIZE = (BG_LOGICAL_SIZE[0] * BG_SCALE, BG_LOGICAL_SIZE[1] * BG_SCALE)
WORKER_LOGICAL_SIZE = (16, 20)
WORKER_SCALE = 3
WORKER_SIZE = (
    WORKER_LOGICAL_SIZE[0] * WORKER_SCALE,
    WORKER_LOGICAL_SIZE[1] * WORKER_SCALE,
)
BOSS_LOGICAL_SIZE = (20, 26)
BOSS_SCALE = 3
BOSS_SIZE = (
    BOSS_LOGICAL_SIZE[0] * BOSS_SCALE,
    BOSS_LOGICAL_SIZE[1] * BOSS_SCALE,
)
ICON_LOGICAL_SIZE = (12, 12)
ICON_SCALE = 3
ICON_SIZE = (ICON_LOGICAL_SIZE[0] * ICON_SCALE, ICON_LOGICAL_SIZE[1] * ICON_SCALE)
WINDOWS_ICON_SIZES = (16, 32, 48, 64, 128, 256)

RGBA = tuple[int, int, int, int]


def c(hex_color: str, alpha: int = 255) -> RGBA:
    """Convert a six-digit hex colour to RGBA."""

    value = hex_color.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"expected RRGGBB colour, got {hex_color!r}")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)


P = {
    "ink": c("3d3441"),
    "deep_ink": c("292738"),
    "wall": c("efd8b5"),
    "wall_light": c("fae8c8"),
    "wall_shadow": c("c99d76"),
    "trim": c("855f59"),
    "floor": c("cfa477"),
    "floor_light": c("ddb889"),
    "floor_dark": c("b98567"),
    "wood": c("a96345"),
    "wood_light": c("d28a5b"),
    "wood_dark": c("704658"),
    "cream": c("ffe4a3"),
    "blue": c("4a7896"),
    "blue_light": c("86bfbd"),
    "teal": c("32716f"),
    "green": c("4d8765"),
    "green_light": c("83ad68"),
    "leaf_dark": c("31594f"),
    "yellow": c("efbf63"),
    "coral": c("dc6b5f"),
    "purple": c("846083"),
    "glass": c("a8d2cf", 175),
    "glass_light": c("d7eeee", 190),
    "server": c("313746"),
    "server_face": c("465260"),
    "screen": c("26384a"),
    "screen_glow": c("73c8bf"),
    "shadow": c("4d3b49", 52),
    "white": c("fff7df"),
}


def nearest(image: Image.Image, scale: int) -> Image.Image:
    return image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)


def draw_plant(draw: ImageDraw.ImageDraw, x: int, y: int, *, tall: bool = False) -> None:
    """Draw a compact leafy office plant; x/y is the pot's top-left."""

    pot_h = 5 if tall else 4
    draw.rectangle((x - 1, y + pot_h - 1, x + 8, y + pot_h + 1), fill=P["shadow"])
    draw.rectangle((x, y, x + 7, y + pot_h), fill=P["ink"])
    draw.rectangle((x + 1, y, x + 6, y + pot_h - 1), fill=P["coral"])
    draw.rectangle((x + 2, y, x + 5, y), fill=P["cream"])
    stem_top = y - (11 if tall else 8)
    draw.rectangle((x + 3, stem_top, x + 4, y), fill=P["leaf_dark"])
    leaves = [
        (x, stem_top + 2, x + 3, stem_top + 5),
        (x + 4, stem_top, x + 7, stem_top + 4),
        (x + 1, stem_top - 2, x + 4, stem_top + 1),
        (x + 4, stem_top + 5, x + 8, stem_top + 8),
    ]
    for index, box in enumerate(leaves):
        draw.rectangle(box, fill=P["green_light"] if index % 2 else P["green"])
    draw.point((x + 2, stem_top - 1), fill=P["cream"])


def draw_desk(draw: ImageDraw.ImageDraw, x: int, y: int, station: int) -> None:
    """Draw one complete workstation on the logical office canvas."""

    # Chair behind the foreground edge, deliberately placed where a worker
    # sprite can cover it when sessions are rendered by the application.
    draw.ellipse((x + 16, y + 12, x + 33, y + 22), fill=P["shadow"])
    draw.rectangle((x + 18, y + 11, x + 31, y + 16), fill=P["ink"])
    chair_colours = (P["blue"], P["teal"], P["purple"], P["coral"])
    chair = chair_colours[station % len(chair_colours)]
    draw.rectangle((x + 20, y + 12, x + 29, y + 15), fill=chair)
    draw.rectangle((x + 21, y + 16, x + 28, y + 19), fill=P["ink"])
    draw.line((x + 24, y + 19, x + 24, y + 21), fill=P["ink"], width=1)
    draw.line((x + 20, y + 21, x + 28, y + 21), fill=P["ink"], width=1)

    # Desk shadow, legs, front edge and warm wooden top.
    draw.rectangle((x + 3, y + 5, x + 48, y + 12), fill=P["shadow"])
    draw.rectangle((x + 5, y + 7, x + 7, y + 16), fill=P["wood_dark"])
    draw.rectangle((x + 43, y + 7, x + 45, y + 16), fill=P["wood_dark"])
    draw.rectangle((x + 3, y + 3, x + 47, y + 9), fill=P["ink"])
    draw.polygon(
        ((x, y + 2), (x + 44, y + 2), (x + 49, y + 6), (x + 5, y + 6)),
        fill=P["wood_light"],
    )
    draw.line((x + 5, y + 6, x + 48, y + 6), fill=P["wood"], width=1)
    draw.line((x + 7, y + 8, x + 46, y + 8), fill=P["wood"], width=1)

    # Monitor, stand, keyboard and a tiny screen variation per station.
    draw.rectangle((x + 15, y - 6, x + 31, y + 2), fill=P["deep_ink"])
    draw.rectangle((x + 17, y - 4, x + 29, y), fill=P["screen"])
    glow = (P["screen_glow"], P["yellow"], P["coral"])[station % 3]
    draw.line((x + 18, y - 3, x + 23 + station % 5, y - 3), fill=glow, width=1)
    draw.line((x + 18, y - 1, x + 21 + (station * 2) % 6, y - 1), fill=P["blue_light"], width=1)
    draw.rectangle((x + 22, y + 3, x + 24, y + 4), fill=P["deep_ink"])
    draw.line((x + 15, y + 4, x + 29, y + 4), fill=P["cream"], width=1)

    # Personal desk items make the twelve stations feel lived in.
    if station % 3 == 0:
        draw.rectangle((x + 38, y, x + 41, y + 3), fill=P["white"])
        draw.point((x + 42, y + 1), fill=P["ink"])
        draw.point((x + 39, y), fill=P["coral"])
    elif station % 3 == 1:
        draw.rectangle((x + 36, y + 1, x + 43, y + 3), fill=P["yellow"])
        draw.line((x + 37, y + 1, x + 42, y + 1), fill=P["white"], width=1)
    else:
        draw.rectangle((x + 39, y - 1, x + 42, y + 3), fill=P["teal"])
        draw.rectangle((x + 40, y - 3, x + 41, y - 1), fill=P["green_light"])


def draw_window(draw: ImageDraw.ImageDraw, x1: int, x2: int) -> None:
    draw.rectangle((x1, 3, x2, 21), fill=P["ink"])
    draw.rectangle((x1 + 2, 5, x2 - 2, 18), fill=P["blue"])
    draw.rectangle((x1 + 3, 6, x2 - 3, 10), fill=P["blue_light"])
    # A tiny, original city silhouette beyond the glass.
    cursor = x1 + 4
    heights = (4, 7, 5, 9, 6, 3, 8, 5, 7, 4, 9, 6)
    for i, height in enumerate(heights):
        width = 4 + (i % 3)
        if cursor + width >= x2 - 3:
            break
        draw.rectangle((cursor, 18 - height, cursor + width, 18), fill=P["purple"])
        if height > 5:
            draw.point((cursor + 1, 20 - height), fill=P["yellow"])
        cursor += width + 2
    mid = (x1 + x2) // 2
    draw.rectangle((mid, 4, mid + 2, 20), fill=P["ink"])
    draw.line((x1 + 2, 19, x2 - 2, 19), fill=P["wall_shadow"], width=1)


def draw_meeting_room(draw: ImageDraw.ImageDraw) -> None:
    # Glazed room shell.
    draw.rectangle((244, 31, 316, 89), fill=c("b7cfc3"))
    for y in range(35, 88, 8):
        draw.line((245, y, 315, y), fill=c("adc5bc"), width=1)
    draw.rectangle((243, 30, 317, 90), outline=P["ink"], width=2)
    draw.line((243, 90, 317, 90), fill=P["wall_shadow"], width=2)

    # Meeting table with a mildly isometric top and six colourful chairs.
    chairs = [
        (255, 39, P["coral"]),
        (276, 37, P["teal"]),
        (297, 39, P["yellow"]),
        (255, 75, P["yellow"]),
        (276, 77, P["purple"]),
        (297, 75, P["teal"]),
    ]
    for x, y, colour in chairs:
        draw.rectangle((x, y, x + 9, y + 7), fill=P["ink"])
        draw.rectangle((x + 1, y + 1, x + 8, y + 5), fill=colour)
    draw.ellipse((254, 45, 307, 79), fill=P["shadow"])
    draw.polygon(((257, 48), (300, 48), (307, 58), (300, 72), (257, 72), (250, 60)), fill=P["ink"])
    draw.polygon(((259, 49), (298, 49), (304, 58), (298, 69), (259, 69), (253, 60)), fill=P["wood_light"])
    draw.line((260, 52, 297, 52), fill=P["cream"], width=1)
    draw.rectangle((273, 56, 284, 63), fill=P["deep_ink"])
    draw.rectangle((275, 57, 282, 60), fill=P["screen_glow"])
    draw.rectangle((263, 58, 268, 62), fill=P["white"])
    draw.rectangle((291, 57, 296, 61), fill=P["yellow"])

    # Glass highlights and door opening stay above the furnishings.
    draw.line((245, 32, 245, 87), fill=P["glass_light"], width=1)
    draw.line((314, 32, 314, 87), fill=P["glass_light"], width=1)
    draw.line((243, 31, 243, 75), fill=P["glass"], width=2)
    draw.line((243, 84, 243, 90), fill=P["glass"], width=2)
    draw.arc((236, 75, 250, 89), 270, 355, fill=P["ink"], width=1)


def draw_coffee_corner(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((244, 94, 317, 133), fill=c("e5c590"))
    draw.rectangle((244, 94, 317, 133), outline=P["ink"], width=2)
    # Warm tiled backsplash.
    for x in range(247, 316, 7):
        draw.line((x, 96, x, 105), fill=P["wall_shadow"], width=1)
    draw.line((245, 101, 316, 101), fill=P["wall_shadow"], width=1)
    # Counter and cupboards.
    draw.rectangle((247, 104, 313, 119), fill=P["ink"])
    draw.rectangle((248, 105, 312, 109), fill=P["wood_light"])
    draw.rectangle((249, 110, 311, 117), fill=P["teal"])
    for x in (264, 281, 298):
        draw.line((x, 110, x, 117), fill=P["ink"], width=1)
        draw.point((x - 2, 113), fill=P["cream"])

    # Coffee machine, kettle, cups and a tiny snack jar.
    draw.rectangle((251, 96, 264, 106), fill=P["deep_ink"])
    draw.rectangle((253, 97, 262, 101), fill=P["server_face"])
    draw.point((255, 99), fill=P["screen_glow"])
    draw.rectangle((255, 102, 260, 105), fill=P["white"])
    draw.rectangle((271, 98, 279, 105), fill=P["coral"])
    draw.rectangle((273, 96, 277, 98), fill=P["ink"])
    draw.rectangle((287, 98, 291, 104), fill=P["white"])
    draw.rectangle((294, 98, 298, 104), fill=P["yellow"])
    draw.rectangle((303, 97, 310, 105), fill=P["glass"])
    draw.point((305, 102), fill=P["coral"])
    draw.point((308, 100), fill=P["yellow"])

    draw.rectangle((251, 122, 309, 128), fill=P["purple"])
    draw.rectangle((254, 123, 306, 126), fill=c("a8809b"))
    draw_plant(draw, 307, 123)


def draw_server_room(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((244, 137, 317, 177), fill=P["server"])
    draw.rectangle((244, 137, 317, 177), outline=P["ink"], width=2)
    # Raised-floor grid.
    for x in range(247, 317, 9):
        draw.line((x, 139, x, 175), fill=c("3a4350"), width=1)
    for y in range(141, 176, 7):
        draw.line((246, y, 315, y), fill=c("3a4350"), width=1)

    for rack, x in enumerate((249, 270, 291)):
        draw.rectangle((x, 141, x + 17, 171), fill=P["deep_ink"])
        draw.rectangle((x + 2, 143, x + 15, 169), fill=P["server_face"])
        for unit in range(5):
            yy = 145 + unit * 5
            draw.line((x + 4, yy, x + 12, yy), fill=P["ink"], width=1)
            light = (P["screen_glow"], P["yellow"], P["coral"])[(rack + unit) % 3]
            draw.point((x + 13, yy), fill=light)
        draw.rectangle((x + 4, 165, x + 12, 167), fill=P["screen"])
    draw.rectangle((247, 173, 314, 175), fill=P["shadow"])


def make_office_background() -> tuple[Image.Image, list[tuple[int, int]]]:
    rng = random.Random(SEED)
    image = Image.new("RGBA", BG_LOGICAL_SIZE, P["floor"])
    draw = ImageDraw.Draw(image, "RGBA")

    # Warm plaster wall and deep base trim.
    draw.rectangle((0, 0, 319, 27), fill=P["wall"])
    draw.rectangle((3, 2, 316, 25), fill=P["wall_light"])
    draw.line((0, 24, 319, 24), fill=P["trim"], width=2)
    draw.line((0, 27, 319, 27), fill=P["wall_shadow"], width=2)

    # Wooden floorboards and occasional knots.  All random choices use a fixed
    # local seed so regenerated images are byte-for-byte stable.
    draw.rectangle((4, 28, 316, 178), fill=P["floor"])
    for y in range(30, 179, 8):
        draw.line((4, y, 316, y), fill=P["floor_dark"], width=1)
        offset = 7 if (y // 8) % 2 else 0
        for x in range(7 + offset, 317, 31):
            draw.line((x, y - 7, x, y), fill=P["floor_light"], width=1)
    for _ in range(32):
        x = rng.randrange(7, 238)
        y = rng.randrange(31, 176)
        draw.point((x, y), fill=P["floor_dark"])

    # A pale central aisle visually separates the desks from shared rooms.
    draw.rectangle((232, 29, 241, 177), fill=c("d9b58b"))
    draw.line((233, 29, 233, 177), fill=P["floor_light"], width=1)
    draw.line((240, 29, 240, 177), fill=P["floor_dark"], width=1)
    for y in range(34, 176, 15):
        draw.rectangle((236, y, 237, y + 4), fill=P["cream"])

    # Windows, wall art and clock.
    draw_window(draw, 13, 105)
    draw_window(draw, 115, 216)
    draw.rectangle((222, 5, 244, 20), fill=P["ink"])
    draw.rectangle((224, 7, 242, 18), fill=P["cream"])
    draw.polygon(((226, 16), (231, 10), (235, 14), (239, 9), (241, 16)), fill=P["green"])
    draw.ellipse((270, 4, 287, 21), fill=P["ink"])
    draw.ellipse((272, 6, 285, 19), fill=P["white"])
    draw.line((278, 12, 278, 8), fill=P["ink"], width=1)
    draw.line((278, 12, 282, 14), fill=P["ink"], width=1)
    draw.point((278, 12), fill=P["coral"])
    draw.rectangle((296, 6, 311, 18), fill=P["ink"])
    draw.rectangle((298, 8, 309, 16), fill=P["yellow"])
    draw.line((300, 14, 304, 10), fill=P["coral"], width=2)
    draw.line((304, 10, 308, 13), fill=P["teal"], width=2)

    # Twelve stations: four columns by three rows, with generous walkways.
    stations = [(x, y) for y in (41, 84, 127) for x in (8, 65, 122, 179)]
    assert len(stations) == 12
    for station, (x, y) in enumerate(stations):
        draw_desk(draw, x, y, station)

    # Shared spaces and plants give the office a small-world, lived-in feel.
    draw_meeting_room(draw)
    draw_coffee_corner(draw)
    draw_server_room(draw)
    draw_plant(draw, 5, 37, tall=True)
    draw_plant(draw, 222, 169, tall=True)

    # Outer room frame and little floor-level corner bolts.
    draw.rectangle((0, 0, 319, 179), outline=P["deep_ink"], width=3)
    for x, y in ((4, 4), (315, 4), (4, 175), (315, 175)):
        draw.rectangle((x, y, x + 1, y + 1), fill=P["yellow"])

    # Background shadows are authored with translucent colours for palette
    # convenience, but the exported room itself must be a fully opaque layer.
    image.putalpha(255)
    return nearest(image, BG_SCALE), stations


WORKERS = [
    # skin, shadow, hair, highlight, shirt, shirt shadow, accent, trousers, shoes
    ("f3c7a5", "c98b72", "4b302f", "80513d", "4a7896", "315a72", "f4c768", "3d4d65", "342e38"),
    ("8c543d", "6c3e35", "211f2b", "473748", "d4665d", "99484e", "f2c66d", "374f55", "242636"),
    ("dca47f", "ad715e", "6a3d29", "a8663e", "528265", "365f52", "e9d58e", "493f56", "332d3c"),
    ("f1bb91", "c27d64", "cf8a36", "f0b64f", "7a5b80", "594361", "79bdb4", "314557", "30303b"),
    ("6f432f", "513229", "332525", "614037", "d5a54f", "9c6f3f", "f1e0aa", "3d4354", "252a33"),
    ("b97455", "8f513f", "2b2633", "574456", "3d8b83", "2d6566", "e36a5d", "40364c", "25232f"),
    ("f0c5a1", "c68567", "9b603d", "d0874b", "d36f68", "9d4e58", "f4d27e", "385969", "2d303c"),
    ("9a5f47", "734333", "382b28", "684339", "557cb3", "3a5682", "efbd59", "4b3b53", "282734"),
    ("e2ae86", "b47762", "242432", "52505c", "759753", "4e713e", "eadb9b", "4d405c", "2f2c39"),
    ("5c392c", "432a25", "151a25", "3a3546", "b85b62", "833f4d", "72b8ae", "3b5360", "252832"),
    ("f3cba9", "cf9071", "84644d", "b28a68", "4f8793", "35646f", "efc65f", "40465d", "2a2d39"),
    ("bb7c5e", "915642", "d3c5b2", "f0dfcb", "885c8e", "62446d", "6fc1b6", "39475a", "282936"),
]


def rgba_palette(row: tuple[str, ...]) -> tuple[RGBA, ...]:
    return tuple(c(value) for value in row)


def draw_hair(
    draw: ImageDraw.ImageDraw,
    style: int,
    hair: RGBA,
    highlight: RGBA,
    ink: RGBA,
    skin: RGBA,
) -> None:
    """Add one of twelve distinct, original pixel hairstyles."""

    if style == 0:  # short side part
        draw.rectangle((4, 2, 11, 5), fill=ink)
        draw.rectangle((5, 2, 10, 4), fill=hair)
        draw.rectangle((5, 2, 7, 2), fill=highlight)
        draw.rectangle((4, 4, 5, 7), fill=hair)
    elif style == 1:  # rounded bob
        draw.rectangle((3, 3, 12, 9), fill=ink)
        draw.rectangle((4, 3, 11, 8), fill=hair)
        draw.rectangle((5, 5, 10, 8), fill=skin)
        draw.rectangle((4, 4, 5, 5), fill=highlight)
    elif style == 2:  # high bun
        draw.rectangle((6, 1, 10, 3), fill=ink)
        draw.rectangle((7, 0, 9, 2), fill=hair)
        draw.rectangle((4, 3, 11, 5), fill=ink)
        draw.rectangle((5, 3, 10, 4), fill=hair)
        draw.rectangle((4, 4, 5, 7), fill=hair)
        draw.point((7, 1), fill=highlight)
    elif style == 3:  # lively curls
        for box in ((3, 3, 6, 6), (6, 2, 9, 5), (9, 3, 12, 6), (3, 6, 5, 9), (10, 6, 12, 9)):
            draw.rectangle(box, fill=ink)
        for x, y in ((4, 3), (7, 2), (10, 4), (4, 7), (11, 7)):
            draw.rectangle((x, y, x + 1, y + 1), fill=hair)
        draw.point((8, 2), fill=highlight)
    elif style == 4:  # close crop
        draw.rectangle((4, 3, 11, 5), fill=ink)
        draw.rectangle((5, 3, 10, 4), fill=hair)
        draw.line((6, 3, 9, 3), fill=highlight, width=1)
    elif style == 5:  # ponytail
        draw.rectangle((4, 2, 11, 5), fill=ink)
        draw.rectangle((5, 2, 10, 4), fill=hair)
        draw.rectangle((11, 4, 13, 8), fill=ink)
        draw.rectangle((12, 5, 14, 10), fill=hair)
        draw.point((6, 2), fill=highlight)
    elif style == 6:  # soft waves
        draw.rectangle((3, 3, 12, 8), fill=ink)
        draw.rectangle((4, 3, 11, 7), fill=hair)
        draw.rectangle((5, 5, 10, 8), fill=skin)
        draw.rectangle((3, 7, 5, 10), fill=hair)
        draw.rectangle((10, 7, 12, 10), fill=hair)
        draw.line((5, 3, 8, 3), fill=highlight, width=1)
    elif style == 7:  # cap
        draw.rectangle((4, 2, 11, 5), fill=ink)
        draw.rectangle((5, 2, 10, 4), fill=hair)
        draw.rectangle((3, 4, 12, 5), fill=ink)
        draw.rectangle((4, 3, 10, 4), fill=c("4f7ca6"))
        draw.rectangle((9, 4, 13, 5), fill=c("4f7ca6"))
        draw.point((6, 3), fill=c("f0c766"))
    elif style == 8:  # head scarf
        draw.rectangle((3, 2, 12, 10), fill=ink)
        scarf = c("5b8d70")
        scarf_hi = c("8eb278")
        draw.rectangle((4, 2, 11, 9), fill=scarf)
        draw.rectangle((5, 4, 10, 8), fill=skin)
        draw.rectangle((4, 8, 5, 11), fill=scarf)
        draw.rectangle((10, 8, 11, 11), fill=scarf)
        draw.line((5, 2, 8, 2), fill=scarf_hi, width=1)
    elif style == 9:  # rounded natural hair
        for box in ((3, 2, 6, 5), (6, 1, 9, 4), (9, 2, 12, 5), (3, 5, 5, 8), (10, 5, 12, 8)):
            draw.rectangle(box, fill=ink)
        draw.rectangle((4, 3, 11, 6), fill=hair)
        draw.point((5, 2), fill=highlight)
        draw.point((9, 2), fill=highlight)
    elif style == 10:  # swept fringe
        draw.rectangle((4, 2, 11, 5), fill=ink)
        draw.polygon(((5, 2), (11, 2), (11, 5), (8, 4), (6, 6), (5, 6)), fill=hair)
        draw.line((6, 2, 9, 2), fill=highlight, width=1)
        draw.rectangle((4, 4, 5, 7), fill=hair)
    else:  # silver textured crop
        draw.rectangle((4, 3, 11, 5), fill=ink)
        draw.polygon(((4, 4), (5, 2), (7, 3), (9, 1), (10, 3), (12, 3), (11, 6), (5, 5)), fill=hair)
        draw.point((6, 2), fill=highlight)
        draw.point((9, 2), fill=highlight)


def draw_accessory(draw: ImageDraw.ImageDraw, worker: int, ink: RGBA, accent: RGBA) -> None:
    """Give each character a readable office-life prop or detail."""

    kind = worker % 6
    if kind == 0:  # tablet
        draw.rectangle((10, 11, 14, 16), fill=ink)
        draw.rectangle((11, 12, 13, 14), fill=c("75bbb2"))
    elif kind == 1:  # coffee mug
        draw.rectangle((1, 13, 4, 16), fill=c("fff1d0"))
        draw.point((4, 14), fill=ink)
        draw.point((2, 12), fill=c("d8c9b0", 180))
    elif kind == 2:  # notebook
        draw.rectangle((1, 11, 5, 16), fill=ink)
        draw.rectangle((2, 12, 4, 15), fill=c("f1d675"))
        draw.line((2, 13, 4, 13), fill=c("d06b64"), width=1)
    elif kind == 3:  # headphones
        draw.arc((3, 3, 12, 11), 180, 360, fill=accent, width=1)
        draw.rectangle((3, 6, 4, 9), fill=accent)
        draw.rectangle((11, 6, 12, 9), fill=accent)
    elif kind == 4:  # lanyard badge
        draw.line((6, 10, 8, 14), fill=accent, width=1)
        draw.line((9, 10, 8, 14), fill=accent, width=1)
        draw.rectangle((7, 13, 9, 15), fill=c("fff0bf"))
    else:  # slim messenger strap
        draw.line((5, 10, 10, 15), fill=accent, width=1)
        draw.rectangle((9, 14, 12, 16), fill=ink)


def make_worker(worker: int) -> Image.Image:
    skin, skin_shadow, hair, highlight, shirt, shirt_shadow, accent, trousers, shoes = rgba_palette(
        WORKERS[worker]
    )
    ink = P["deep_ink"]
    image = Image.new("RGBA", WORKER_LOGICAL_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")

    # Soft, pixel-aligned grounding shadow.
    draw.ellipse((2, 17, 13, 19), fill=c("2d2837", 72))

    # Legs and shoes.
    draw.rectangle((4, 13, 7, 18), fill=ink)
    draw.rectangle((9, 13, 12, 18), fill=ink)
    draw.rectangle((5, 14, 7, 17), fill=trousers)
    draw.rectangle((9, 14, 11, 17), fill=trousers)
    draw.rectangle((4, 17, 7, 18), fill=shoes)
    draw.rectangle((9, 17, 12, 18), fill=shoes)
    draw.point((5, 17), fill=c("686278"))
    draw.point((10, 17), fill=c("686278"))

    # Arms, hands, torso and collar.
    draw.rectangle((2, 9, 4, 15), fill=ink)
    draw.rectangle((11, 9, 13, 15), fill=ink)
    draw.rectangle((3, 10, 4, 13), fill=shirt_shadow)
    draw.rectangle((11, 10, 12, 13), fill=shirt_shadow)
    draw.rectangle((3, 14, 4, 15), fill=skin)
    draw.rectangle((11, 14, 12, 15), fill=skin)
    draw.rectangle((4, 8, 11, 15), fill=ink)
    draw.polygon(((5, 9), (10, 9), (11, 11), (10, 14), (5, 14), (4, 11)), fill=shirt)
    draw.line((5, 14, 10, 14), fill=shirt_shadow, width=1)
    draw.rectangle((7, 8, 8, 9), fill=skin_shadow)
    draw.point((6, 9), fill=c("fff1d2"))
    draw.point((9, 9), fill=c("fff1d2"))
    if worker % 3 == 0:
        draw.line((8, 10, 8, 13), fill=accent, width=1)
        draw.point((8, 14), fill=accent)
    elif worker % 3 == 1:
        draw.line((5, 10, 10, 10), fill=accent, width=1)
    else:
        draw.rectangle((5, 11, 6, 12), fill=accent)

    # Face with ears and a subtle top-down forehead highlight.
    draw.rectangle((4, 3, 11, 9), fill=ink)
    draw.rectangle((3, 5, 4, 7), fill=skin_shadow)
    draw.rectangle((11, 5, 12, 7), fill=skin_shadow)
    draw.rectangle((5, 4, 10, 8), fill=skin)
    draw.line((6, 4, 9, 4), fill=c("ffd8b6"), width=1)
    draw.point((6, 6), fill=ink)
    draw.point((9, 6), fill=ink)
    draw.point((8, 7), fill=skin_shadow)
    if worker % 2:
        draw.line((7, 8, 9, 8), fill=c("8c4f4c"), width=1)
    else:
        draw.point((8, 8), fill=c("8c4f4c"))

    draw_hair(draw, worker, hair, highlight, ink, skin)

    # Glasses on a few workers, then their individual office prop.
    if worker in (0, 4, 7, 11):
        draw.rectangle((5, 5, 7, 7), outline=c("433846"))
        draw.rectangle((8, 5, 10, 7), outline=c("433846"))
        draw.line((7, 6, 8, 6), fill=c("433846"), width=1)
        draw.point((6, 5), fill=c("cde7df"))
    draw_accessory(draw, worker, ink, accent)

    return nearest(image, WORKER_SCALE)


def make_boss() -> Image.Image:
    """Create the fixed meeting-room boss NPC in the office sprite style."""

    image = Image.new("RGBA", BOSS_LOGICAL_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    ink = P["deep_ink"]
    skin = c("dca17d")
    skin_shadow = c("a96855")
    hair = c("382c32")
    hair_light = c("6b4a47")
    suit = c("40537d")
    suit_shadow = c("293653")
    shirt = c("f7ead0")
    tie = c("8d3e50")
    clipboard = c("79556f")
    clipboard_light = c("a77b9a")
    gold = c("efc45f")

    # Grounding shadow, tailored trousers and dark office shoes.
    draw.ellipse((3, 23, 17, 25), fill=c("2d2837", 76))
    draw.rectangle((6, 18, 9, 23), fill=ink)
    draw.rectangle((11, 18, 14, 23), fill=ink)
    draw.rectangle((7, 18, 9, 22), fill=suit_shadow)
    draw.rectangle((11, 18, 13, 22), fill=suit_shadow)
    draw.rectangle((6, 22, 9, 23), fill=c("252936"))
    draw.rectangle((11, 22, 14, 23), fill=c("252936"))

    # Broad suit shoulders, white shirt and a burgundy tie read clearly at 20px.
    draw.rectangle((4, 11, 7, 18), fill=ink)
    draw.rectangle((13, 11, 16, 18), fill=ink)
    draw.rectangle((5, 12, 7, 17), fill=suit_shadow)
    draw.rectangle((13, 12, 15, 17), fill=suit_shadow)
    draw.polygon(((6, 10), (14, 10), (16, 13), (15, 19), (5, 19), (4, 13)), fill=ink)
    draw.polygon(((7, 11), (13, 11), (15, 13), (14, 18), (6, 18), (5, 13)), fill=suit)
    draw.polygon(((7, 11), (10, 14), (9, 17), (6, 13)), fill=suit_shadow)
    draw.polygon(((13, 11), (10, 14), (11, 17), (14, 13)), fill=suit_shadow)
    draw.polygon(((9, 11), (11, 11), (12, 14), (10, 17), (8, 14)), fill=shirt)
    draw.polygon(((10, 12), (11, 14), (10, 17), (9, 14)), fill=tie)
    draw.point((13, 14), fill=gold)
    draw.point((5, 17), fill=skin)

    # Slim clipboard remains at his side so the existing review animations fit.
    draw.rectangle((14, 13, 19, 20), fill=ink)
    draw.rectangle((15, 14, 18, 19), fill=clipboard)
    draw.rectangle((16, 13, 17, 14), fill=gold)
    draw.line((16, 16, 18, 16), fill=shirt, width=1)
    draw.line((16, 18, 17, 18), fill=clipboard_light, width=1)
    draw.point((14, 17), fill=skin)

    # Face and a neat short side-part hairstyle replace the former long hair.
    draw.rectangle((6, 5, 14, 11), fill=ink)
    draw.rectangle((7, 5, 13, 10), fill=skin)
    draw.line((8, 5, 12, 5), fill=c("ffd5b0"), width=1)
    draw.line((7, 6, 9, 6), fill=hair, width=1)
    draw.line((11, 6, 13, 6), fill=hair, width=1)
    draw.point((8, 7), fill=c("594038"))
    draw.point((12, 7), fill=c("594038"))
    draw.point((10, 8), fill=skin_shadow)
    draw.line((9, 9, 11, 9), fill=c("87504b"), width=1)
    draw.rectangle((6, 3, 14, 6), fill=ink)
    draw.polygon(((7, 3), (14, 3), (14, 5), (11, 5), (9, 6), (7, 5)), fill=hair)
    draw.line((8, 3, 11, 3), fill=hair_light, width=1)
    draw.rectangle((6, 5, 7, 7), fill=hair)

    return nearest(image, BOSS_SCALE)


def make_status_icon(kind: str) -> Image.Image:
    image = Image.new("RGBA", ICON_LOGICAL_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    ink = P["deep_ink"]

    if kind == "working":
        draw.rectangle((1, 2, 10, 8), fill=ink)
        draw.rectangle((2, 3, 9, 7), fill=P["screen"])
        draw.line((3, 4, 7, 4), fill=P["screen_glow"], width=1)
        draw.line((3, 6, 6, 6), fill=P["yellow"], width=1)
        draw.rectangle((4, 9, 7, 9), fill=ink)
        draw.line((2, 10, 9, 10), fill=P["ink"], width=1)
    elif kind == "thinking":
        draw.ellipse((1, 1, 10, 8), fill=ink)
        draw.rectangle((2, 2, 9, 7), fill=P["white"])
        draw.point((4, 5), fill=P["purple"])
        draw.point((6, 5), fill=P["purple"])
        draw.point((8, 5), fill=P["purple"])
        draw.rectangle((3, 8, 4, 9), fill=ink)
        draw.point((2, 10), fill=ink)
    elif kind == "waiting":
        draw.rectangle((2, 4, 8, 9), fill=ink)
        draw.rectangle((3, 5, 7, 8), fill=P["white"])
        draw.rectangle((8, 5, 10, 8), outline=ink)
        draw.point((4, 2), fill=P["glass"])
        draw.point((6, 1), fill=P["glass"])
        draw.line((1, 10, 10, 10), fill=ink, width=1)
    elif kind == "done":
        draw.ellipse((1, 1, 10, 10), fill=ink)
        draw.ellipse((2, 2, 9, 9), fill=P["green"])
        draw.line((3, 6, 5, 8), fill=P["white"], width=2)
        draw.line((5, 8, 9, 3), fill=P["white"], width=2)
    elif kind == "error":
        draw.polygon(((6, 1), (11, 10), (1, 10)), fill=ink)
        draw.polygon(((6, 2), (10, 9), (2, 9)), fill=P["coral"])
        draw.rectangle((5, 4, 6, 7), fill=P["white"])
        draw.rectangle((5, 8, 6, 8), fill=P["white"])
    else:
        raise ValueError(f"unknown status icon: {kind}")

    return nearest(image, ICON_SCALE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_nearest_blocks(image: Image.Image, scale: int, label: str) -> None:
    """Ensure every source pixel became one uniform scale-by-scale block."""

    if image.width % scale or image.height % scale:
        raise AssertionError(f"{label}: dimensions are not divisible by scale {scale}")
    pixels = image.load()
    for y in range(0, image.height, scale):
        for x in range(0, image.width, scale):
            expected = pixels[x, y]
            for yy in range(y, y + scale):
                for xx in range(x, x + scale):
                    if pixels[xx, yy] != expected:
                        raise AssertionError(f"{label}: non-nearest pixel block at {x},{y}")


def validate_assets() -> list[Path]:
    background_path = ASSET_DIR / "office-bg.png"
    worker_paths = [ASSET_DIR / f"worker-{index:02d}.png" for index in range(12)]
    icon_paths = [
        ASSET_DIR / f"status-{kind}.png"
        for kind in ("working", "thinking", "waiting", "done", "error")
    ]
    boss_path = ASSET_DIR / "boss.png"
    windows_icon_path = ASSET_DIR / "app-icon.ico"
    paths = [background_path, *worker_paths, *icon_paths, boss_path, windows_icon_path]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise AssertionError(f"missing generated assets: {', '.join(map(str, missing))}")

    with Image.open(background_path) as background:
        background.load()
        if background.mode != "RGBA" or background.size != BG_SIZE:
            raise AssertionError(f"office-bg.png: expected RGBA {BG_SIZE}, got {background.mode} {background.size}")
        alpha = background.getchannel("A").getextrema()
        if alpha != (255, 255):
            raise AssertionError(f"office-bg.png: background must be opaque, got alpha {alpha}")
        assert_nearest_blocks(background, BG_SCALE, "office-bg.png")

    worker_hashes: set[str] = set()
    for index, path in enumerate(worker_paths):
        with Image.open(path) as worker:
            worker.load()
            if worker.mode != "RGBA" or worker.size != WORKER_SIZE:
                raise AssertionError(f"{path.name}: expected RGBA {WORKER_SIZE}, got {worker.mode} {worker.size}")
            alpha = worker.getchannel("A")
            extrema = alpha.getextrema()
            if extrema[0] != 0 or extrema[1] == 0:
                raise AssertionError(f"{path.name}: sprite needs transparent background and visible pixels")
            for corner in ((0, 0), (worker.width - 1, 0), (0, worker.height - 1), (worker.width - 1, worker.height - 1)):
                if worker.getpixel(corner)[3] != 0:
                    raise AssertionError(f"{path.name}: corner {corner} is not transparent")
            assert_nearest_blocks(worker, WORKER_SCALE, path.name)
        worker_hashes.add(sha256(path))
    if len(worker_hashes) != 12:
        raise AssertionError("worker sprites must all be visually distinct files")

    for path in icon_paths:
        with Image.open(path) as icon:
            icon.load()
            if icon.mode != "RGBA" or icon.size != ICON_SIZE:
                raise AssertionError(f"{path.name}: expected RGBA {ICON_SIZE}, got {icon.mode} {icon.size}")
            if icon.getchannel("A").getextrema()[0] != 0:
                raise AssertionError(f"{path.name}: icon background is not transparent")
            assert_nearest_blocks(icon, ICON_SCALE, path.name)

    with Image.open(boss_path) as boss:
        boss.load()
        if boss.mode != "RGBA" or boss.size != BOSS_SIZE:
            raise AssertionError(f"boss.png: expected RGBA {BOSS_SIZE}, got {boss.mode} {boss.size}")
        alpha = boss.getchannel("A")
        extrema = alpha.getextrema()
        if extrema[0] != 0 or extrema[1] == 0:
            raise AssertionError("boss.png: sprite needs transparent background and visible pixels")
        for corner in ((0, 0), (boss.width - 1, 0), (0, boss.height - 1), (boss.width - 1, boss.height - 1)):
            if boss.getpixel(corner)[3] != 0:
                raise AssertionError(f"boss.png: corner {corner} is not transparent")
        assert_nearest_blocks(boss, BOSS_SCALE, boss_path.name)

    with Image.open(windows_icon_path) as windows_icon:
        windows_icon.load()
        sizes = windows_icon.info.get("sizes", set())
        if windows_icon.format != "ICO" or (256, 256) not in sizes:
            raise AssertionError(
                f"app-icon.ico: expected a Windows icon containing 256x256, got {sizes}"
            )

    return paths


def generate_assets() -> list[Path]:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    background, stations = make_office_background()
    if len(stations) != 12:
        raise AssertionError("office background must contain exactly twelve workstation anchors")
    background.save(ASSET_DIR / "office-bg.png", format="PNG", optimize=False)

    for index in range(12):
        make_worker(index).save(ASSET_DIR / f"worker-{index:02d}.png", format="PNG", optimize=False)

    make_boss().save(ASSET_DIR / "boss.png", format="PNG", optimize=False)

    for kind in ("working", "thinking", "waiting", "done", "error"):
        make_status_icon(kind).save(ASSET_DIR / f"status-{kind}.png", format="PNG", optimize=False)

    app_icon_path = ASSET_DIR / "app-icon.png"
    if not app_icon_path.is_file():
        raise AssertionError(f"missing source application icon: {app_icon_path}")
    with Image.open(app_icon_path) as app_icon:
        app_icon.convert("RGBA").save(
            ASSET_DIR / "app-icon.ico",
            format="ICO",
            sizes=[(size, size) for size in WINDOWS_ICON_SIZES],
        )

    return validate_assets()


def print_summary(paths: Iterable[Path]) -> None:
    paths = list(paths)
    print(f"Validated {len(paths)} deterministic pixel assets in {ASSET_DIR}")
    print(f"  office-bg.png: {BG_SIZE[0]}x{BG_SIZE[1]} (logical {BG_LOGICAL_SIZE[0]}x{BG_LOGICAL_SIZE[1]} @ {BG_SCALE}x)")
    print(f"  worker-00.png .. worker-11.png: {WORKER_SIZE[0]}x{WORKER_SIZE[1]} transparent ({WORKER_SCALE}x)")
    print(f"  boss.png: {BOSS_SIZE[0]}x{BOSS_SIZE[1]} transparent ({BOSS_SCALE}x)")
    print(f"  status-*.png: {ICON_SIZE[0]}x{ICON_SIZE[1]} transparent ({ICON_SCALE}x)")
    print(f"  app-icon.ico: Windows icon sizes {', '.join(map(str, WINDOWS_ICON_SIZES))}")
    print(f"  office-bg sha256: {sha256(ASSET_DIR / 'office-bg.png')[:16]}...")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="validate existing assets without regenerating them",
    )
    args = parser.parse_args()
    paths = validate_assets() if args.check_only else generate_assets()
    print_summary(paths)


if __name__ == "__main__":
    main()
