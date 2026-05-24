import math
from support import Vec2i
from constants import DIR_SCALE, TILE_UNITS, CIRCLE_LUT_SIZE, ANGLE_SCALE
from data.tables_dirs import AIM_DIRECTION_LUTS, CIRCLE_DIRECTION_LUT, DIRECTION_VECTORS



def chebyshev_tile_distance(a: Vec2i, b: Vec2i) -> int:
    return max(
        abs(a.x - b.x),
        abs(a.y - b.y),
    )


def manhattan_tile_distance(a: Vec2i, b: Vec2i) -> int:
    return abs(a.x - b.x) + abs(a.y - b.y)


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


def sign(value: int) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def clamp(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(value, max_value))


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
    spawn_angle_step_offset: int,
    angle_index_fp: int,
) -> Vec2i:
    radius = age * radius_per_tick

    angle_fp = angle_index_fp + age * angle_step_fp
    lut_index = (
        (angle_fp // ANGLE_SCALE)
        + spawn_angle_step_offset
    ) % CIRCLE_LUT_SIZE

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