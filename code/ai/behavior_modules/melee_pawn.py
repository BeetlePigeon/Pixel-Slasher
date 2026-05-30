from ai.ai_queries import entity_is_valid_target, get_entity_tile, get_player_if_detectable, tile_distance_between_entities
from utils.tile_vec_utils import tile_center


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

    if distance <= desired_range_tiles:
        agent["state"] = "in_range"

        return [
            {
                "type": "stop_moving",
            }
        ]

    target_tile = get_entity_tile(
        world,
        target,
    )

    if target_tile is None:
        agent["target_entity"] = None
        agent["state"] = "idle"

        return [
            {
                "type": "stop_moving",
            }
        ]

    agent["state"] = "pursuing"

    target_transform = world.transform[target]

    return [
        {
            "type": "move_to_tile",
            "target_tile": target_tile,
            "target_cpos": target_transform.cpos,
            "path_policy": path_policy,
        }
    ]