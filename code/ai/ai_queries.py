from utils.tile_vec_utils import chebyshev_tile_distance
from combat_ops import entity_is_hittable, entities_are_enemies, get_entity_current_tile


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