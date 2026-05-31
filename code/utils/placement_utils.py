from support import Vec2i
from utils.perf_profiler import record_counter_for_world
from utils.occupancy_utils import is_tile_blocked_for_movement, get_obstacle_footprint_tiles_for_origin_tile
from utils.tile_vec_utils import (
    chebyshev_tile_distance,
    manhattan_tile_distance,
    tile_center,
    tiles_crossed_by_segment,
)


def get_entity_placement_tiles(world, tile: Vec2i, entity=None):
    if entity is None:
        return (
            tile,
        )

    return get_obstacle_footprint_tiles_for_origin_tile(
        world,
        entity,
        tile,
    )


def is_tile_valid_for_entity_placement(
    world,
    tile: Vec2i,
    entity=None,
    include_dynamic=True,
):
    record_counter_for_world(
        world,
        "placement.checks",
    )

    footprint_tiles_checked = 0

    for occupied_tile in get_entity_placement_tiles(
        world,
        tile,
        entity=entity,
    ):
        footprint_tiles_checked += 1

        if is_tile_blocked_for_movement(
            world,
            occupied_tile,
            mover_entity=entity,
            include_dynamic=include_dynamic,
        ):
            record_counter_for_world(
                world,
                "placement.foot_tiles",
                footprint_tiles_checked,
            )
            return False

    record_counter_for_world(
        world,
        "placement.foot_tiles",
        footprint_tiles_checked,
    )

    return True


def tile_in_bounds(world, tile: Vec2i) -> bool:
    if tile.y < 0 or tile.y >= len(world.tilemap):
        return False

    if tile.x < 0 or tile.x >= len(world.tilemap[tile.y]):
        return False

    return True


def tile_has_static_collision(world, tile: Vec2i) -> bool:
    if not tile_in_bounds(world, tile):
        return True

    return (tile.x, tile.y) in world.static_collision_tiles


def tile_has_placement_blocker(world, tile: Vec2i, ignore_entity=None) -> bool:
    placement_blockers = getattr(world, "placement_blocker", set())

    for entity in placement_blockers:
        if entity == ignore_entity:
            continue

        transform = world.transform.get(entity)

        if transform is None:
            continue

        if transform.tile == tile:
            return True

    return False


def tile_is_valid_for_placement(world, tile: Vec2i, ignore_entity=None) -> bool:
    if tile_has_static_collision(world, tile):
        return False

    if tile_has_placement_blocker(
        world,
        tile,
        ignore_entity=ignore_entity,
    ):
        print("this guy's gonna get hit!")
#        return False

    return True


def iter_tile_ring(center_tile: Vec2i, radius: int):
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            tile = Vec2i(
                center_tile.x + dx,
                center_tile.y + dy,
            )

            if chebyshev_tile_distance(tile, center_tile) != radius:
                continue

            yield tile


def bias_score(candidate_tile: Vec2i, bias_tile: Vec2i, bias_mode: str):
    if bias_tile is None:
        return 0, 0

    chebyshev = chebyshev_tile_distance(
        candidate_tile,
        bias_tile,
    )

    manhattan = manhattan_tile_distance(
        candidate_tile,
        bias_tile,
    )

    if bias_mode == "toward":
        return chebyshev, manhattan

    if bias_mode == "away":
        return -chebyshev, -manhattan

    if bias_mode == "none":
        return 0, 0

    raise ValueError(f"Unknown placement bias mode: {bias_mode}")


def score_placement_candidate(
    candidate_tile: Vec2i,
    target_tile: Vec2i,
    bias_tile=None,
    bias_mode="toward",
):
    target_distance = chebyshev_tile_distance(
        candidate_tile,
        target_tile,
    )

    bias_chebyshev, bias_manhattan = bias_score(
        candidate_tile,
        bias_tile,
        bias_mode,
    )

    return (
        target_distance,             # closest to intended tile first
        bias_chebyshev,              # then bias toward/away from reference
        bias_manhattan,              # then secondary bias tie-break
        candidate_tile.y,            # stable tie-break
        candidate_tile.x,            # stable tie-break
    )


def find_nearest_valid_placement_tile(
    world,
    target_tile: Vec2i,
    search_radius: int,
    max_miss_tiles: int,
    bias_tile=None,
    bias_mode="toward",
    ignore_entity=None,
):
    max_radius = min(search_radius, max_miss_tiles)

    for radius in range(max_radius + 1):
        candidates = []

        for candidate_tile in iter_tile_ring(target_tile, radius):
            if not tile_is_valid_for_placement(
                world,
                candidate_tile,
                ignore_entity=ignore_entity,
            ):
                continue

            candidates.append((
                score_placement_candidate(
                    candidate_tile=candidate_tile,
                    target_tile=target_tile,
                    bias_tile=bias_tile,
                    bias_mode=bias_mode,
                ),
                candidate_tile,
            ))

        if candidates:
            candidates.sort(key=lambda item: item[0])
            return candidates[0][1]

    return None


def static_line_clear_between_tiles(world, start_tile: Vec2i, end_tile: Vec2i):
    start_cpos = tile_center(start_tile)
    end_cpos = tile_center(end_tile)

    crossed_tiles = tiles_crossed_by_segment(
        start_cpos,
        end_cpos,
    )

    for tile in crossed_tiles:
        if tile_has_static_collision(world, tile):
            return False

    return True


def find_nearest_valid_placement_tile_with_line_of_sight(
    world,
    target_tile: Vec2i,
    search_radius: int,
    max_miss_tiles: int,
    source_tile: Vec2i,
    bias_mode="toward",
    ignore_entity=None,
):
    max_radius = min(search_radius, max_miss_tiles)

    for radius in range(max_radius + 1):
        candidates = []

        for candidate_tile in iter_tile_ring(target_tile, radius):
            if not tile_is_valid_for_placement(
                world,
                candidate_tile,
                ignore_entity=ignore_entity,
            ):
                continue

            if not static_line_clear_between_tiles(
                world,
                source_tile,
                candidate_tile,
            ):
                continue

            candidates.append((
                score_placement_candidate(
                    candidate_tile=candidate_tile,
                    target_tile=target_tile,
                    bias_tile=source_tile,
                    bias_mode=bias_mode,
                ),
                candidate_tile,
            ))

        if candidates:
            candidates.sort(key=lambda item: item[0])
            return candidates[0][1]

    return None