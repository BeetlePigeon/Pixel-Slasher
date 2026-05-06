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
        return Vec2i(
            self.direction.x * self.speed,
            self.direction.y * self.speed,
        )

    def advance(self):
        pass

    def finished(self) -> bool:
        return False