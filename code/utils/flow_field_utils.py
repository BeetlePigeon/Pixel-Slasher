from collections import deque

from support import Vec2i
from utils.occupancy_utils import (
    get_entity_movement_footprint_name,
    get_movement_body_tiles_for_origin_tile,
)
from utils.placement_utils import (
    is_tile_statically_valid_for_entity_placement_cached,
)
from utils.perf_profiler import (
    profiled,
    record_counter_for_world,
)
from utils.tile_vec_utils import (
    chebyshev_tile_distance,
    tile_from_cpos,
)


FLOW_DIRECTIONS_8 = (
    Vec2i(-1, -1),
    Vec2i(0, -1),
    Vec2i(1, -1),
    Vec2i(-1, 0),
    Vec2i(1, 0),
    Vec2i(-1, 1),
    Vec2i(0, 1),
    Vec2i(1, 1),
)

FLOW_DIRECTIONS_4 = (
    Vec2i(0, -1),
    Vec2i(-1, 0),
    Vec2i(1, 0),
    Vec2i(0, 1),
)


def tile_is_inside_map(world, tile):
    if tile.y < 0 or tile.y >= len(world.tilemap):
        return False

    row = world.tilemap[tile.y]

    if tile.x < 0 or tile.x >= len(row):
        return False

    return True


def get_direction_line_error(
    direction,
    from_tile,
    target_tile,
):
    if target_tile is None:
        return 0

    target_dx = target_tile.x - from_tile.x
    target_dy = target_tile.y - from_tile.y

    return abs(
        target_dx * direction.y
        - target_dy * direction.x
    )


def get_direction_facing_penalty(
    world,
    entity,
    direction,
):
    facing = getattr(
        world,
        "facing",
        {},
    ).get(entity)

    if facing is None:
        return 0

    if facing == direction:
        return 0

    return 1


def get_flow_field_cache(world):
    cache = getattr(
        world,
        "flow_field_cache",
        None,
    )

    if cache is None:
        cache = {}
        world.flow_field_cache = cache

    return cache


def get_flow_field_area_id(world):
    current_area = getattr(
        world,
        "current_area",
        None,
    )

    if current_area is None:
        return None

    return current_area.area_id


def get_entity_tile(world, entity):
    transform = world.transform.get(entity)

    if transform is None:
        return None

    return tile_from_cpos(transform.cpos)


def sign_int(value):
    if value < 0:
        return -1

    if value > 0:
        return 1

    return 0


def get_tile_target_side_key(tile, target_tile):
    return (
        sign_int(tile.x - target_tile.x),
        sign_int(tile.y - target_tile.y),
    )


def get_flow_field_side_pressure_counts(
    world,
    mover_entity,
    target_entity,
    target_tile,
    pressure_radius_tiles,
):
    mover_team = world.team.get(mover_entity)
    counts = {}
    total_entities = 0

    for other_entity in sorted(world.transform):
        if other_entity == mover_entity:
            continue

        if other_entity == target_entity:
            continue

        if mover_team is not None and world.team.get(other_entity) != mover_team:
            continue

        occupier = world.space_occupier.get(other_entity)

        if occupier is None:
            continue

        if not occupier["blocks_movement"]:
            continue

        other_tile = get_entity_tile(
            world,
            other_entity,
        )

        if other_tile is None:
            continue

        distance = chebyshev_tile_distance(
            other_tile,
            target_tile,
        )

        if distance > pressure_radius_tiles:
            continue

        side_key = get_tile_target_side_key(
            other_tile,
            target_tile,
        )

        counts[side_key] = counts.get(side_key, 0) + 1
        total_entities += 1

    if total_entities > 0:
        record_counter_for_world(
            world,
            "flow_field.pressure.entities",
            total_entities,
        )

    return counts


def get_flow_directions(can_move_8way):
    if can_move_8way:
        return FLOW_DIRECTIONS_8

    return FLOW_DIRECTIONS_4


def distance_to_tile_set(tile, tiles):
    if not tiles:
        return None

    return min(
        chebyshev_tile_distance(tile, other_tile)
        for other_tile in tiles
    )


def iter_flow_goal_tiles(
    world,
    mover_entity,
    target_entity,
    desired_range_tiles,
):
    target_tile = get_entity_tile(
        world,
        target_entity,
    )

    if target_tile is None:
        return

    target_body_tiles = tuple(
        get_movement_body_tiles_for_origin_tile(
            world,
            target_entity,
            target_tile,
        )
    )
    target_body_tile_set = set(target_body_tiles)

    min_x = min(tile.x for tile in target_body_tiles) - desired_range_tiles
    max_x = max(tile.x for tile in target_body_tiles) + desired_range_tiles
    min_y = min(tile.y for tile in target_body_tiles) - desired_range_tiles
    max_y = max(tile.y for tile in target_body_tiles) + desired_range_tiles

    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            tile = Vec2i(x, y)

            if not tile_is_inside_map(world, tile):
                continue

            if (
                desired_range_tiles > 0
                and tile in target_body_tile_set
            ):
                continue

            distance = distance_to_tile_set(
                tile,
                target_body_tiles,
            )

            if distance is None:
                continue

            if distance > desired_range_tiles:
                continue

            if not is_tile_statically_valid_for_entity_placement_cached(
                world,
                tile,
                entity=mover_entity,
            ):
                continue

            yield tile


def make_flow_field_cache_key(
    world,
    mover_entity,
    target_entity,
    desired_range_tiles,
    max_radius_tiles,
    can_move_8way,
):
    target_tile = get_entity_tile(
        world,
        target_entity,
    )

    if target_tile is None:
        return None

    return (
        get_flow_field_area_id(world),
        target_entity,
        get_entity_movement_footprint_name(
            world,
            mover_entity,
        ),
        desired_range_tiles,
        max_radius_tiles,
        can_move_8way,
    )


def get_flow_field_anchor_tile(flow_field):
    return flow_field["anchor_target_tile"]


def flow_field_should_rebuild(
    world,
    flow_field,
    current_target_tile,
    rebuild_interval_ticks,
    rebuild_distance_tiles,
):
    anchor_tile = get_flow_field_anchor_tile(flow_field)

    target_distance = chebyshev_tile_distance(
        anchor_tile,
        current_target_tile,
    )

    if target_distance <= rebuild_distance_tiles:
        record_counter_for_world(
            world,
            "flow_field.cache.fresh_distance",
        )
        return False

    age_ticks = world.tick - flow_field["built_tick"]

    if age_ticks < rebuild_interval_ticks:
        record_counter_for_world(
            world,
            "flow_field.cache.rebuild_deferred_age",
        )
        return False

    record_counter_for_world(
        world,
        "flow_field.cache.stale_distance",
    )

    return True


@profiled("flow_field.build")
def build_flow_field(
    world,
    mover_entity,
    target_entity,
    desired_range_tiles,
    max_radius_tiles,
    can_move_8way=True,
):
    record_counter_for_world(
        world,
        "flow_field.build",
    )

    directions = get_flow_directions(can_move_8way)

    target_tile = get_entity_tile(
        world,
        target_entity,
    )

    distances = {}
    queue = deque()

    for goal_tile in iter_flow_goal_tiles(
        world,
        mover_entity,
        target_entity,
        desired_range_tiles,
    ):
        if goal_tile in distances:
            continue

        distances[goal_tile] = 0
        queue.append(goal_tile)

    record_counter_for_world(
        world,
        "flow_field.goal_tiles",
        len(queue),
    )

    while queue:
        tile = queue.popleft()
        distance = distances[tile]

        if (
            max_radius_tiles is not None
            and distance >= max_radius_tiles
        ):
            continue

        for direction in directions:
            neighbor = tile + direction

            if neighbor in distances:
                continue

            if not tile_is_inside_map(world, neighbor):
                continue

            if not is_tile_statically_valid_for_entity_placement_cached(
                world,
                neighbor,
                entity=mover_entity,
            ):
                continue

            distances[neighbor] = distance + 1
            queue.append(neighbor)

    record_counter_for_world(
        world,
        "flow_field.tiles",
        len(distances),
    )

    return {
        "distances": distances,
        "target_tile": target_tile,
        "anchor_target_tile": target_tile,
        "built_tick": world.tick,
        "desired_range_tiles": desired_range_tiles,
        "max_radius_tiles": max_radius_tiles,
        "can_move_8way": can_move_8way,
    }


def get_or_build_flow_field(
    world,
    mover_entity,
    target_entity,
    desired_range_tiles,
    max_radius_tiles,
    can_move_8way,
    rebuild_interval_ticks,
    rebuild_distance_tiles,
):
    current_target_tile = get_entity_tile(
        world,
        target_entity,
    )

    if current_target_tile is None:
        return None

    cache_key = make_flow_field_cache_key(
        world,
        mover_entity,
        target_entity,
        desired_range_tiles,
        max_radius_tiles,
        can_move_8way,
    )

    if cache_key is None:
        return None

    cache = get_flow_field_cache(world)

    cached_field = cache.get(cache_key)

    if cached_field is not None:
        if not flow_field_should_rebuild(
            world,
            cached_field,
            current_target_tile,
            rebuild_interval_ticks,
            rebuild_distance_tiles,
        ):
            record_counter_for_world(
                world,
                "flow_field.cache.hit",
            )
            return cached_field

        record_counter_for_world(
            world,
            "flow_field.cache.rebuild",
        )

    else:
        record_counter_for_world(
            world,
            "flow_field.cache.miss",
        )

    flow_field = build_flow_field(
        world,
        mover_entity,
        target_entity,
        desired_range_tiles,
        max_radius_tiles,
        can_move_8way=can_move_8way,
    )

    cache[cache_key] = flow_field

    return flow_field


def iter_flow_step_candidates(entity):
    # Stable but slightly varied tie-breaking to reduce perfect columns.
    if entity % 2 == 0:
        return FLOW_DIRECTIONS_8

    return (
        Vec2i(1, 1),
        Vec2i(0, 1),
        Vec2i(-1, 1),
        Vec2i(1, 0),
        Vec2i(-1, 0),
        Vec2i(1, -1),
        Vec2i(0, -1),
        Vec2i(-1, -1),
    )


def get_flow_field_step_candidates_from_tile(
    world,
    entity,
    flow_field,
    current_tile,
    include_sideways,
    side_pressure_counts,
    side_pressure_weight,
):
    if current_tile is None:
        return []

    distances = flow_field["distances"]
    current_distance = distances.get(current_tile)

    candidates = []

    for order_index, direction in enumerate(iter_flow_step_candidates(entity)):
        candidate_tile = current_tile + direction
        candidate_distance = distances.get(candidate_tile)

        if candidate_distance is None:
            continue

        if current_distance is not None:
            if include_sideways:
                if candidate_distance > current_distance:
                    continue

            else:
                if candidate_distance >= current_distance:
                    continue

        move_class = 0

        if (
            current_distance is not None
            and candidate_distance == current_distance
        ):
            move_class = 1

        target_tile = flow_field["target_tile"]

        if target_tile is None:
            side_pressure_penalty = 0
            line_error = 0
            target_distance = 0

        else:
            side_key = get_tile_target_side_key(
                candidate_tile,
                target_tile,
            )
            side_pressure_penalty = (
                side_pressure_counts.get(side_key, 0)
                * side_pressure_weight
            )
            line_error = get_direction_line_error(
                direction,
                current_tile,
                target_tile,
            )
            target_distance = chebyshev_tile_distance(
                candidate_tile,
                target_tile,
            )

        facing_penalty = get_direction_facing_penalty(
            world,
            entity,
            direction,
        )

        candidates.append(
            (
                candidate_distance,
                move_class,
                side_pressure_penalty,
                line_error,
                target_distance,
                facing_penalty,
                order_index,
                direction,
            )
        )

    if not candidates:
        record_counter_for_world(
            world,
            "flow_field.step.no_candidate",
        )
        return []

    candidates.sort()

    if include_sideways:
        record_counter_for_world(
            world,
            "flow_field.step.candidate_sideways_allowed",
            len(candidates),
        )

    else:
        record_counter_for_world(
            world,
            "flow_field.step.candidate",
            len(candidates),
        )

    return [
        candidate[-1]
        for candidate in candidates
    ]


def get_flow_field_step_candidates(
    world,
    entity,
    flow_field,
    include_sideways,
    side_pressure_counts,
    side_pressure_weight,
):
    current_tile = get_entity_tile(
        world,
        entity,
    )

    return get_flow_field_step_candidates_from_tile(
        world,
        entity,
        flow_field,
        current_tile,
        include_sideways=include_sideways,
        side_pressure_counts=side_pressure_counts,
        side_pressure_weight=side_pressure_weight,
    )


def get_flow_field_step_direction(
    world,
    entity,
    flow_field,
    side_pressure_counts,
    side_pressure_weight,
):
    candidates = get_flow_field_step_candidates(
        world,
        entity,
        flow_field,
        include_sideways=False,
        side_pressure_counts=side_pressure_counts,
        side_pressure_weight=side_pressure_weight,
    )