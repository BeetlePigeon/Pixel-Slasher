from combat_ops import entity_is_hittable, entities_are_enemies, get_entity_current_tile
from utils.occupancy_utils import get_movement_body_tiles_for_origin_tile
from support import Vec2i
from utils.placement_utils import is_tile_valid_for_entity_placement
from utils.tile_vec_utils import (
    chebyshev_tile_distance,
    manhattan_tile_distance,
)


def get_player_entity(world):
    player = getattr(world, "player", None)

    if player is None:
        return None

    if player not in world.transform:
        return None

    return player


def entity_is_valid_ai_actor(world, entity):
    if entity not in world.transform:
        return False

    if entity not in world.motion_state:
        return False

    if entity not in world.locomotion:
        return False

    if entity not in world.ai_agent:
        return False

    if not entity_is_alive(world, entity):
        return False

    return True


def entity_is_alive(world, entity):
    health = world.health.get(entity)

    if health is None:
        return True

    return health.get("current", 0) > 0


def entity_is_valid_target(world, source, target):
    if target is None:
        return False

    if target == source:
        return False

    if target not in world.transform:
        return False

    if not entity_is_alive(world, target):
        return False

    if not entity_is_hittable(world, target):
        return False

    if not entities_are_enemies(world, source, target):
        return False

    return True


def get_entity_tile(world, entity):
    return get_entity_current_tile(world, entity)


def tile_distance_between_entities(world, a, b):
    a_tile = get_entity_tile(world, a)
    b_tile = get_entity_tile(world, b)

    if a_tile is None or b_tile is None:
        return None

    return chebyshev_tile_distance(a_tile, b_tile)


def target_within_radius(world, source, target, radius_tiles):
    distance = tile_distance_between_entities(
        world,
        source,
        target,
    )

    if distance is None:
        return False

    return distance <= radius_tiles


def get_player_if_detectable(world, entity, detect_radius_tiles):
    player = get_player_entity(world)

    if not entity_is_valid_target(
        world,
        entity,
        player,
    ):
        return None

    if not target_within_radius(
        world,
        entity,
        player,
        detect_radius_tiles,
    ):
        return None

    return player


def get_entity_attack_range_tiles(world, entity):
    combat_attack = world.combat_attack.get(entity)

    if combat_attack is None:
        return 1

    return max(0, combat_attack.get("range_tiles", 1))


def get_entity_movement_footprint_tiles(world, entity):
    center_tile = get_entity_tile(world, entity)
    if center_tile is None:
        return ()

    return tuple(
        get_movement_body_tiles_for_origin_tile(
            world,
            entity,
            center_tile,
        )
    )


def distance_to_tile_set(tile, tiles):
    if not tiles:
        return None

    return min(
        chebyshev_tile_distance(tile, other_tile)
        for other_tile in tiles
    )


def entity_is_in_attack_range_of_target(world, source, target):
    source_tile = get_entity_tile(world, source)

    if source_tile is None:
        return False

    target_movement_tiles = get_entity_movement_footprint_tiles(
        world,
        target,
    )

    distance = distance_to_tile_set(
        source_tile,
        target_movement_tiles,
    )

    if distance is None:
        return False

    return distance <= get_entity_attack_range_tiles(world, source)


def iter_attack_position_candidates(target_movement_tiles, range_tiles):
    min_x = min(tile.x for tile in target_movement_tiles) - range_tiles
    max_x = max(tile.x for tile in target_movement_tiles) + range_tiles
    min_y = min(tile.y for tile in target_movement_tiles) - range_tiles
    max_y = max(tile.y for tile in target_movement_tiles) + range_tiles

    for y in range(min_y, max_y + 1):
        for x in range(min_x, max_x + 1):
            tile = Vec2i(x, y)

            distance = distance_to_tile_set(
                tile,
                target_movement_tiles,
            )

            if distance is None:
                continue

            if distance > range_tiles:
                continue

            yield tile


def find_closest_valid_attack_position(
    world,
    source,
    target,
):
    source_tile = get_entity_tile(world, source)

    if source_tile is None:
        return None

    target_movement_tiles = get_entity_movement_footprint_tiles(
        world,
        target,
    )

    if not target_movement_tiles:
        return None

    range_tiles = get_entity_attack_range_tiles(world, source)

    candidates = []
    for candidate_tile in iter_attack_position_candidates(
        target_movement_tiles,
        range_tiles,
    ):
        if not is_tile_valid_for_entity_placement(
            world,
            candidate_tile,
            entity=source,
            include_dynamic=False,
        ):
            continue

        distance_to_target = distance_to_tile_set(
            candidate_tile,
            target_movement_tiles,
        )

        candidates.append(
            (
                (
                    chebyshev_tile_distance(source_tile, candidate_tile),
                    manhattan_tile_distance(source_tile, candidate_tile),
                    distance_to_target,
                    candidate_tile.y,
                    candidate_tile.x,
                ),
                candidate_tile,
            )
        )

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]