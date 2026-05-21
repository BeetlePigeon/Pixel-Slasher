import math
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
    prev_cpos: Vec2i
    position_mode: str


# CONSTANTS
CIRCLE_LUT_SIZE = 64
DIR_SCALE = 4096
ANGLE_SCALE = 256
AIM_LUT_SIZES = (8, 16, 32, 64, 128, 256)

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


def interp_cpos(prev: Vec2i, current: Vec2i, alpha: float) -> Vec2i:
    return Vec2i(
        round(prev.x + (current.x - prev.x) * alpha),
        round(prev.y + (current.y - prev.y) * alpha),
    )


def scale_normalized_dir(direction: Vec2i, distance: int) -> Vec2i:
    return Vec2i(
        direction.x * distance // DIR_SCALE,
        direction.y * distance // DIR_SCALE,
    )


def normalize_vector_to_dir_scale(vector: Vec2i):
    if vector.x == 0 and vector.y == 0:
        return None

    length = math.isqrt(vector.x * vector.x + vector.y * vector.y)

    if length == 0:
        return None

    return Vec2i(
        vector.x * DIR_SCALE // length,
        vector.y * DIR_SCALE // length,
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


def screen_to_cpos(screen_pos, tile_dimension) -> Vec2i:
    screen_x, screen_y = screen_pos

    half = tile_dimension // 2
    quarter = tile_dimension // 4

    # Inverse of:
    # screen_x = ((cpos.x - cpos.y) * half // TILE_UNITS) + half
    # screen_y = ((cpos.x + cpos.y) * quarter // TILE_UNITS)
    a = (screen_x - half) * TILE_UNITS // half      # cpos.x - cpos.y
    b = screen_y * TILE_UNITS // quarter            # cpos.x + cpos.y

    return Vec2i(
        (a + b) // 2,
        (b - a) // 2,
    )


def lerp_int(a: int, b: int, n: int, d: int) -> int:
    return a + ((b - a) * n) // d


def lerp_vec(a: Vec2i, b: Vec2i, n: int, d: int) -> Vec2i:
    return Vec2i(
        lerp_int(a.x, b.x, n, d),
        lerp_int(a.y, b.y, n, d),
    )


def lerp_cpos(a: Vec2i, b: Vec2i, n: int, d: int) -> Vec2i:
    return Vec2i(
        a.x + (b.x - a.x) * n // d,
        a.y + (b.y - a.y) * n // d,
    )


def close_enough_cpos(a: Vec2i, b: Vec2i, threshold: int) -> bool:
    return (
        abs(a.x - b.x) <= threshold
        and abs(a.y - b.y) <= threshold
    )


def smooth_lerp_axis(current: int, target: int, divisor: int) -> int:
    diff = target - current

    if diff == 0:
        return current

    abs_step = abs(diff) // divisor

    if abs_step == 0:
        abs_step = 1

    if diff > 0:
        return current + abs_step
    else:
        return current - abs_step


def smooth_lerp_cpos(current: Vec2i, target: Vec2i, divisor: int) -> Vec2i:
    return Vec2i(
        smooth_lerp_axis(current.x, target.x, divisor),
        smooth_lerp_axis(current.y, target.y, divisor),
    )


def scale_dir(direction: Vec2i, distance: int) -> Vec2i:
    move_dir = DIRECTION_VECTORS[direction]

    return Vec2i(
        move_dir.x * distance // DIR_SCALE,
        move_dir.y * distance // DIR_SCALE,
    )


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


def build_aim_direction_luts():
    return {
        size: build_direction_lut(size)
        for size in AIM_LUT_SIZES
    }


def quantize_vector_to_lut_direction(vector: Vec2i, lut_size: int):
    if vector.x == 0 and vector.y == 0:
        return None

    if lut_size not in AIM_DIRECTION_LUTS:
        raise ValueError(f"Unsupported aim LUT size: {lut_size}")

    directions = AIM_DIRECTION_LUTS[lut_size]

    best_direction = None
    best_dot = None

    for direction in directions:
        dot = vector.x * direction.x + vector.y * direction.y

        if best_dot is None or dot > best_dot:
            best_dot = dot
            best_direction = direction

    return best_direction


def spiral_pos(
    origin: Vec2i,
    age: int,
    radius_per_tick: int,
    angle_step_fp: int,
    angle_index_fp: int,
) -> Vec2i:
    radius = age * radius_per_tick

    angle_fp = angle_index_fp + age * angle_step_fp
    lut_index = (angle_fp // ANGLE_SCALE) % CIRCLE_LUT_SIZE

    direction = CIRCLE_DIRECTION_LUT[lut_index]
    offset = scale_normalized_dir(direction, radius)

    return origin + offset


def _append_unique_tile(tiles, tile):
    if not tiles or tiles[-1] != tile:
        tiles.append(tile)


def tiles_crossed_by_segment(start_cpos: Vec2i, end_cpos: Vec2i):
    delta = end_cpos - start_cpos

    current_tile = tile_from_cpos(start_cpos)
    target_tile = tile_from_cpos(end_cpos)

    tiles = [current_tile]

    if current_tile == target_tile:
        return tiles

    dx = delta.x
    dy = delta.y

    step_x = sign(dx)
    step_y = sign(dy)

    abs_dx = abs(dx)
    abs_dy = abs(dy)

    if step_x > 0:
        next_x_boundary = (current_tile.x + 1) * TILE_UNITS
        next_cross_x = next_x_boundary - start_cpos.x
    elif step_x < 0:
        next_x_boundary = current_tile.x * TILE_UNITS - 1
        next_cross_x = start_cpos.x - next_x_boundary
    else:
        next_cross_x = None

    if step_y > 0:
        next_y_boundary = (current_tile.y + 1) * TILE_UNITS
        next_cross_y = next_y_boundary - start_cpos.y
    elif step_y < 0:
        next_y_boundary = current_tile.y * TILE_UNITS - 1
        next_cross_y = start_cpos.y - next_y_boundary
    else:
        next_cross_y = None

    while current_tile != target_tile:
        if next_cross_x is None:
            step_axis = "y"
        elif next_cross_y is None:
            step_axis = "x"
        else:
            left = next_cross_x * abs_dy
            right = next_cross_y * abs_dx

            if left < right:
                step_axis = "x"
            elif right < left:
                step_axis = "y"
            else:
                step_axis = "corner"

        if step_axis == "x":
            current_tile = Vec2i(
                current_tile.x + step_x,
                current_tile.y,
            )

            _append_unique_tile(tiles, current_tile)
            next_cross_x += TILE_UNITS

        elif step_axis == "y":
            current_tile = Vec2i(
                current_tile.x,
                current_tile.y + step_y,
            )

            _append_unique_tile(tiles, current_tile)
            next_cross_y += TILE_UNITS

        else:
            side_x_tile = Vec2i(
                current_tile.x + step_x,
                current_tile.y,
            )

            side_y_tile = Vec2i(
                current_tile.x,
                current_tile.y + step_y,
            )

            diagonal_tile = Vec2i(
                current_tile.x + step_x,
                current_tile.y + step_y,
            )

            _append_unique_tile(tiles, side_x_tile)
            _append_unique_tile(tiles, side_y_tile)
            _append_unique_tile(tiles, diagonal_tile)

            current_tile = diagonal_tile

            next_cross_x += TILE_UNITS
            next_cross_y += TILE_UNITS

    return tiles


CIRCLE_DIRECTION_LUT = build_circle_direction_lut()
AIM_DIRECTION_LUTS = build_aim_direction_luts()


@dataclass
class PathFollowController:
    nodes: list
    current_index: int
    speed: int
    created_tick: int
    target_tile: Vec2i

    motion_tag = "path_follow"

    def sample_delta_from(self, current_cpos: Vec2i) -> Vec2i:
        remaining_distance = self.speed
        next_cpos = current_cpos
        next_index = self.current_index

        while remaining_distance > 0 and next_index < len(self.nodes):
            target_cpos = self.nodes[next_index]
            to_target = target_cpos - next_cpos

            distance = math.isqrt(
                to_target.x * to_target.x
                + to_target.y * to_target.y
            )

            if distance == 0:
                next_index += 1
                continue

            if distance <= remaining_distance:
                next_cpos = target_cpos
                remaining_distance -= distance
                next_index += 1
                continue

            step = scale_normalized_dir(
                normalize_vector_to_dir_scale(to_target),
                remaining_distance,
            )

            next_cpos = next_cpos + step
            remaining_distance = 0

        self._pending_index = next_index
        return next_cpos - current_cpos

    def advance(self):
        self.current_index = getattr(
            self,
            "_pending_index",
            self.current_index,
        )

    def finished(self) -> bool:
        return self.current_index >= len(self.nodes)


@dataclass
class DirectionalMoveController:
    aim_vector: Vec2i
    raw_direction: Vec2i
    speed: int

    motion_tag = "directional_move"

    def sample_delta(self) -> Vec2i:
        return scale_normalized_dir(
            self.aim_vector,
            self.speed,
        )

    def advance(self):
        pass

    def finished(self) -> bool:
        return False

    
@dataclass
class GridMoveController:
    start: Vec2i
    end: Vec2i
    progress: int
    duration: int

    motion_tag = "grid_move"

    def sample_delta(self) -> Vec2i:    # LERP style
        prev = lerp_vec(self.start, self.end, self.progress, self.duration)
        next_ = lerp_vec(self.start, self.end, self.progress + 1, self.duration)
        return next_ - prev

    def advance(self):
        self.progress += 1

    def finished(self) -> bool:
        return self.progress >= self.duration


@dataclass
class DashController:
    aim_vector: Vec2i
    age: int
    duration: int
    distance: int
    slide_min_tangent_ratio: tuple
    
    motion_tag = "dash"

    def sample_delta(self) -> Vec2i:
        prev_dist = self.distance * self.age // self.duration
        next_dist = self.distance * (self.age + 1) // self.duration

        step_distance = next_dist - prev_dist

        return scale_normalized_dir(self.aim_vector, step_distance)

    def advance(self):
        self.age += 1

    def finished(self) -> bool:
        return self.age >= self.duration


@dataclass
class SettleToGridController:
    start: Vec2i
    end: Vec2i
    progress: int
    duration: int

    motion_tag = "settle"

    def sample_delta(self) -> Vec2i:
        prev = lerp_vec(self.start, self.end, self.progress, self.duration)
        next_ = lerp_vec(self.start, self.end, self.progress + 1, self.duration)
        return next_ - prev

    def advance(self):
        self.progress += 1

    def finished(self) -> bool:
        return self.progress >= self.duration


@dataclass
class LinearProjectileController:
    aim_vector: Vec2i
    speed: int

    def sample_delta(self) -> Vec2i:
        return scale_normalized_dir(
            self.aim_vector,
            self.speed,
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