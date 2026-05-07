from dataclasses import dataclass
from settings import TILE_UNITS


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
    position_mode: str


DIR_SCALE = 4096
# Tile-space direction vectors normalized for equal movement speed.
DIRECTION_VECTORS = {
    # visual cardinal directions
    Vec2i(1, -1): Vec2i(2896, -2896),   # visual right
    Vec2i(-1, 1): Vec2i(-2896, 2896),   # visual left
    Vec2i(-1, -1): Vec2i(-2896, -2896), # visual up
    Vec2i(1, 1): Vec2i(2896, 2896),     # visual down
    # visual diagonal directions / tile-axis directions
    Vec2i(1, 0): Vec2i(4096, 0),        # visual down-right
    Vec2i(-1, 0): Vec2i(-4096, 0),      # visual up-left
    Vec2i(0, 1): Vec2i(0, 4096),        # visual down-left
    Vec2i(0, -1): Vec2i(0, -4096),      # visual up-right
}

def sign(value: int) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0

def clamp(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(value, max_value))

def scale_vec(vec: Vec2i, numerator: int, denominator: int) -> Vec2i:
    # Scale vector by rational frac:
    # scale_vec(delta, 1, 2)  # 50%
    # scale_vec(delta, 3, 4)  # 75%
    # scale_vec(delta, 2, 1)  # 200%
    return Vec2i(
        vec.x * numerator // denominator,
        vec.y * numerator // denominator,
    )

def clamp_vec_axis(vec: Vec2i, max_abs: int) -> Vec2i:
    return Vec2i(
        clamp(vec.x, -max_abs, max_abs),
        clamp(vec.y, -max_abs, max_abs),
    )

def tile_center(tile: Vec2i) -> Vec2i:
    return Vec2i(
        tile.x * TILE_UNITS + TILE_UNITS // 2,
        tile.y * TILE_UNITS + TILE_UNITS // 2,
    )

def tile_from_cpos(cpos: Vec2i) -> Vec2i:
    return Vec2i(
        cpos.x // TILE_UNITS,
        cpos.y // TILE_UNITS,
    )

def iso_to_screen(x, y, tile_dimension):
    screen_x = (x - y) * (tile_dimension // 2)
    screen_y = (x + y) * (tile_dimension // 4)
    return screen_x, screen_y

def cpos_to_screen(cpos: Vec2i, tile_dimension: int):
    screen_x = (cpos.x - cpos.y) * (tile_dimension // 2) // TILE_UNITS
    screen_y = (cpos.x + cpos.y) * (tile_dimension // 4) // TILE_UNITS

    # Because tile rendering treats iso_to_screen(tile_x, tile_y)
    # as the top-left of the tile image.
    screen_x += tile_dimension // 2

    return screen_x, screen_y

def lerp_int(a: int, b: int, n: int, d: int) -> int:
    return a + ((b - a) * n) // d

def lerp_vec(a: Vec2i, b: Vec2i, n: int, d: int) -> Vec2i:
    return Vec2i(
        lerp_int(a.x, b.x, n, d),
        lerp_int(a.y, b.y, n, d),
    )

def scale_dir(direction: Vec2i, distance: int) -> Vec2i:
    move_dir = DIRECTION_VECTORS[direction]

    return Vec2i(
        move_dir.x * distance // DIR_SCALE,
        move_dir.y * distance // DIR_SCALE,
    )

SPIRAL_DIRS = [
    Vec2i(1, 0),
    Vec2i(1, -1),
    Vec2i(0, -1),
    Vec2i(-1, -1),
    Vec2i(-1, 0),
    Vec2i(-1, 1),
    Vec2i(0, 1),
    Vec2i(1, 1),
]
ANGLE_SCALE = 256

def spiral_pos(origin: Vec2i, age: int, radius_per_tick: int, angle_step_fp: int, angle_index_fp: int) -> Vec2i:
    radius = age * radius_per_tick
    angle_fp = angle_index_fp + age * angle_step_fp
    dir_index = (angle_fp // ANGLE_SCALE) % len(SPIRAL_DIRS)
    direction = SPIRAL_DIRS[dir_index]
    offset = scale_dir(direction, radius)
    return origin + offset


@dataclass
class GridMoveController:
    start: Vec2i
    end: Vec2i
    progress: int
    duration: int

    def sample_delta(self) -> Vec2i:    # LERP style
        prev = lerp_vec(self.start, self.end, self.progress, self.duration)
        next_ = lerp_vec(self.start, self.end, self.progress + 1, self.duration)
        return next_ - prev

    def advance(self):
        self.progress += 1

    def finished(self) -> bool:
        return self.progress >= self.duration


@dataclass
class LinearProjectileController:
    direction: Vec2i
    speed: int

    def sample_delta(self) -> Vec2i:
        move_dir = DIRECTION_VECTORS[self.direction]

        return Vec2i(
            move_dir.x * self.speed // DIR_SCALE,
            move_dir.y * self.speed // DIR_SCALE,
        )

    def advance(self):
        pass

    def finished(self) -> bool:
        return False

@dataclass
class SpiralProjectileController:
    origin: Vec2i
    age: int
    radius_per_tick: int
    angle_step_fp: int
    angle_index_fp: int = 0

    def sample_delta(self) -> Vec2i:
        prev = spiral_pos(
            self.origin,
            self.age,
            self.radius_per_tick,
            self.angle_step_fp,
            self.angle_index_fp,
        )
        next_ = spiral_pos(
            self.origin,
            self.age + 1,
            self.radius_per_tick,
            self.angle_step_fp,
            self.angle_index_fp,
        )
        return next_ - prev

    def advance(self):
        self.age += 1

    def finished(self) -> bool:
        return False