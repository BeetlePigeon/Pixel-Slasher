from support import Vec2i
from tile_vec_utils import chebyshev_tile_distance, manhattan_tile_distance, tile_center, tiles_crossed_by_segment


def is_tile_blocked_for_teleport(world, tile: Vec2i) -> bool:
    if tile.y < 0 or tile.y >= len(world.tilemap):
        return True

    if tile.x < 0 or tile.x >= len(world.tilemap[tile.y]):
        return True

    return (tile.x, tile.y) in world.static_collision_tiles


def has_min_progress(
    start_tile: Vec2i,
    candidate_tile: Vec2i,
    min_progress_tiles: int,
) -> bool:
    return (
        chebyshev_tile_distance(start_tile, candidate_tile)
        >= min_progress_tiles
    )


def find_best_target_snap_tile(
    world,
    start_tile: Vec2i,
    target_tile: Vec2i,
    target_snap_radius_tiles: int,
    min_progress_tiles: int,
):
    candidates = []
    radius = target_snap_radius_tiles

    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            candidate_tile = Vec2i(
                target_tile.x + dx,
                target_tile.y + dy,
            )

            if candidate_tile == target_tile:
                continue

            distance_from_target = chebyshev_tile_distance(
                candidate_tile,
                target_tile,
            )

            if distance_from_target > radius:
                continue

            if is_tile_blocked_for_teleport(world, candidate_tile):
                continue

            if not has_min_progress(
                start_tile,
                candidate_tile,
                min_progress_tiles,
            ):
                continue

            candidates.append((
                distance_from_target,
                manhattan_tile_distance(candidate_tile, target_tile),
                candidate_tile.y,
                candidate_tile.x,
                candidate_tile,
            ))

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            item[0],  # closest Chebyshev distance to clicked tile
            item[1],  # then closest Manhattan distance
            item[2],  # stable y tie-break
            item[3],  # stable x tie-break
        )
    )

    return candidates[0][4]


def resolve_ray_fallback_tile(
    world,
    start_tile: Vec2i,
    target_tile: Vec2i,
    ray_fallback_max_miss_tiles: int,
    ray_fallback_min_progress_tiles: int,
):
    start_cpos = tile_center(start_tile)
    target_cpos = tile_center(target_tile)

    crossed_tiles = tiles_crossed_by_segment(
        start_cpos,
        target_cpos,
    )

    # Search backward from the clicked target toward the player.
    # We want the nearest open tile before the clicked blocked tile.
    for tile in reversed(crossed_tiles[:-1]):
        miss_distance = chebyshev_tile_distance(
            tile,
            target_tile,
        )

        if miss_distance > ray_fallback_max_miss_tiles:
            return None

        if is_tile_blocked_for_teleport(world, tile):
            continue

        if not has_min_progress(
            start_tile,
            tile,
            ray_fallback_min_progress_tiles,
        ):
            return None

        return tile

    return None


def resolve_path_tolerant_teleport_tile(
    world,
    start_tile: Vec2i,
    target_tile: Vec2i,
    target_snap_radius_tiles: int,
    ray_fallback_max_miss_tiles: int,
    ray_fallback_min_progress_tiles: int,
):
    # Case 1:
    # Clicked tile is already open. Use it directly.
    if not is_tile_blocked_for_teleport(world, target_tile):
        if not has_min_progress(
            start_tile,
            target_tile,
            ray_fallback_min_progress_tiles,
        ):
            return None

        return target_tile

    # Case 2:
    # Clicked tile is blocked. First try nearby target correction.
    snap_tile = find_best_target_snap_tile(
        world,
        start_tile=start_tile,
        target_tile=target_tile,
        target_snap_radius_tiles=target_snap_radius_tiles,
        min_progress_tiles=ray_fallback_min_progress_tiles,
    )

    if snap_tile is not None:
        return snap_tile

    # Case 3:
    # No nearby target correction. Fall back along the ray,
    # but only if the fallback is close enough to the clicked tile.
    return resolve_ray_fallback_tile(
        world,
        start_tile=start_tile,
        target_tile=target_tile,
        ray_fallback_max_miss_tiles=ray_fallback_max_miss_tiles,
        ray_fallback_min_progress_tiles=ray_fallback_min_progress_tiles,
    )