import math
from dataclasses import dataclass
from constants import DIR_SCALE, CIRCLE_LUT_SIZE, AIM_LUT_SIZES


@dataclass(frozen=True)
class Vec2i:
    x: int
    y: int

    def __add__(self, other):
        return Vec2i(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Vec2i(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: int):
        return Vec2i(self.x * scalar, self.y * scalar)

    def __floordiv__(self, scalar: int):
        return Vec2i(self.x // scalar, self.y // scalar)


@dataclass
class Transform:
    tile: Vec2i
    cpos: Vec2i
    prev_cpos: Vec2i
    position_mode: str




def build_aim_direction_luts():
    return {
        size: build_direction_lut(size)
        for size in AIM_LUT_SIZES
    }


def build_direction_lut(size: int):
    directions = []

    for i in range(size):
        angle = (2 * math.pi * i) / size

        directions.append(
            Vec2i(
                round(math.cos(angle) * DIR_SCALE),
                round(math.sin(angle) * DIR_SCALE),
            )
        )

    return tuple(directions)


def build_circle_direction_lut():
    directions = []

    for i in range(CIRCLE_LUT_SIZE):
        angle = (2 * math.pi * i) / CIRCLE_LUT_SIZE

        directions.append(
            Vec2i(
                round(math.cos(angle) * DIR_SCALE),
                round(-math.sin(angle) * DIR_SCALE),
            )
        )

    return tuple(directions)