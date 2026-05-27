from support import Vec2i
from utils.tile_vec_utils import tile_from_cpos, sign, chebyshev_tile_distance, manhattan_tile_distance, tile_center, tiles_crossed_by_segment
from utils.occupancy_utils import mark_dynamic_occupancy_dirty
from utils.placement_utils import is_tile_valid_for_entity_placement


def teleport_entity_to_tile(world, entity, target_tile):
    transform = world.transform[entity]

    old_tile = tile_from_cpos(transform.cpos)
    target_cpos = tile_center(target_tile)

    # Face in the direction of the actual teleport displacement from
    # the actor's current cpos-derived tile, not stale committed tile.
    facing_direction = Vec2i(
        sign(target_tile.x - old_tile.x),
        sign(target_tile.y - old_tile.y),
    )

    if entity in world.facing:
        if facing_direction.x != 0 or facing_direction.y != 0:
            world.facing[entity] = facing_direction

    motion_state = world.motion_state.get(entity)

    if motion_state is not None:
        motion_state["controller"] = None
        motion_state["influence_mode"] = "normal"
        motion_state["last_delta"] = target_cpos - transform.cpos
        motion_state.pop("controller_source", None)

        # Prevent movement_arbiter_system from starting a new voluntary
        # movement later in this same tick using stale move_intent.
        motion_state["suppress_move_start_tick"] = world.tick

    # Clear pending voluntary movement requests.
    world.move_intent.pop(entity, None)

    if hasattr(world, "buffered_move_intent"):
        world.buffered_move_intent.pop(entity, None)

    if hasattr(world, "move_target"):
        world.move_target.pop(entity, None)

    transform.tile = target_tile
    transform.cpos = target_cpos

    # Prevent render interpolation from drawing teleport as a slide.
    transform.prev_cpos = target_cpos

    mark_dynamic_occupancy_dirty(world)

    return True


def is_tile_valid_for_teleport(world, entity, tile: Vec2i, placement_policy) -> bool:
    if placement_policy == "nearest_valid_unblocked":
        return is_tile_valid_for_entity_placement(world, tile, entity=entity, include_dynamic=True)

    raise ValueError(
        f"Unknown teleport placement policy: {placement_policy!r}"
    )


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
    entity,
    start_tile: Vec2i,
    target_tile: Vec2i,
    target_snap_radius_tiles: int,
    min_progress_tiles: int,
    placement_policy,
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

            if not is_tile_valid_for_teleport(world, entity, candidate_tile, placement_policy):
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

                # Important tie-break:
                # if two candidates are equally close to the clicked tile,
                # prefer the one closer to the caster/start tile.
                chebyshev_tile_distance(candidate_tile, start_tile),
                manhattan_tile_distance(candidate_tile, start_tile),

                candidate_tile.y,
                candidate_tile.x,
                candidate_tile,
            ))

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            item[0],  # closest Chebyshev distance to clicked tile
            item[1],  # closest Manhattan distance to clicked tile
            item[2],  # then closer to caster/start tile
            item[3],  # secondary caster/start tie-break
            item[4],  # stable y tie-break
            item[5],  # stable x tie-break
        )
    )

    return candidates[0][6]


def resolve_ray_fallback_tile(
    world,
    entity,
    start_tile: Vec2i,
    target_tile: Vec2i,
    ray_fallback_max_miss_tiles: int,
    ray_fallback_min_progress_tiles: int,
    placement_policy,
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

        if not is_tile_valid_for_teleport(world, entity, tile, placement_policy):
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
    entity,
    start_tile: Vec2i,
    target_tile: Vec2i,
    target_snap_radius_tiles: int,
    ray_fallback_max_miss_tiles: int,
    ray_fallback_min_progress_tiles: int,
    placement_policy,
):
    # Case 1:
    # Clicked tile is already open. Use it directly.
    if is_tile_valid_for_teleport(world, entity, target_tile, placement_policy):
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
        entity=entity,
        start_tile=start_tile,
        target_tile=target_tile,
        target_snap_radius_tiles=target_snap_radius_tiles,
        min_progress_tiles=ray_fallback_min_progress_tiles,
        placement_policy=placement_policy,
    )

    if snap_tile is not None:
        return snap_tile

    # Case 3:
    # No nearby target correction. Fall back along the ray,
    # but only if the fallback is close enough to the clicked tile.
    return resolve_ray_fallback_tile(
        world,
        entity,
        start_tile=start_tile,
        target_tile=target_tile,
        ray_fallback_max_miss_tiles=ray_fallback_max_miss_tiles,
        ray_fallback_min_progress_tiles=ray_fallback_min_progress_tiles,
        placement_policy=placement_policy,
    )