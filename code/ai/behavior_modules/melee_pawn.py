from ai.ai_queries import entity_is_valid_target, get_entity_tile, get_player_if_detectable, tile_distance_between_entities
from utils.tile_vec_utils import tile_center
from ai.ai_queries import (
    entity_is_in_attack_range_of_target,
    entity_is_valid_target,
    find_closest_valid_attack_position,
    get_player_if_detectable,
    tile_distance_between_entities,
)


def think(context):
    world = context.world
    entity = context.entity
    agent = context.agent
    params = agent.get("params", {})

    detect_radius_tiles = params.get("detect_radius_tiles")
    lose_radius_tiles = params.get("lose_radius_tiles")
    desired_range_tiles = params.get("desired_range_tiles")
    path_policy = params.get("path_policy")

    target = agent.get("target_entity")

    if not entity_is_valid_target(
        world,
        entity,
        target,
    ):
        target = None

    if target is None:
        target = get_player_if_detectable(
            world,
            entity,
            detect_radius_tiles,
        )

    if target is None:
        agent["target_entity"] = None
        agent["state"] = "idle"

        return [
            {
                "type": "stop_moving",
            }
        ]

    distance = tile_distance_between_entities(
        world,
        entity,
        target,
    )

    if distance is None or distance > lose_radius_tiles:
        agent["target_entity"] = None
        agent["state"] = "idle"

        return [
            {
                "type": "stop_moving",
            }
        ]

    agent["target_entity"] = target

    if entity_is_in_attack_range_of_target(
            world,
            entity,
            target,
    ):
        agent["state"] = "in_range"

        return [
            {
                "type": "stop_moving",
            }
        ]

    attack_position_tile = find_closest_valid_attack_position(
        world,
        entity,
        target,
    )

    if attack_position_tile is None:
        agent["state"] = "no_valid_attack_position"

        return [
            {
                "type": "stop_moving",
            }
        ]

    agent["state"] = "pursuing"

    return [
        {
            "type": "move_to_tile",
            "target_tile": attack_position_tile,
            "target_cpos": tile_center(attack_position_tile),
            "path_policy": path_policy,
        }
    ]