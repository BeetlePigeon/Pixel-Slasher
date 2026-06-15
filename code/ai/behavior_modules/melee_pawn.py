from utils.tile_vec_utils import tile_center
from ai.ai_queries import (
    entity_is_in_attack_range_of_target,
    entity_is_valid_target,
    find_closest_valid_attack_position,
    get_player_if_detectable,
    tile_distance_between_entities,
)


DEBUG_DEFAULT_IMAGE_KEY = "enemy_normal"
DEBUG_IN_RANGE_IMAGE_KEY = "enemy_angry"


def set_melee_pawn_debug_info(
    agent,
    target_entity=None,
    in_attack_range=None,
    attack_position_tile=None,
):
    agent["debug_target_entity"] = target_entity
    agent["debug_in_attack_range"] = in_attack_range
    agent["debug_attack_position_tile"] = attack_position_tile


def set_debug_engagement_sprite(world, entity, in_range):
    sprite = world.sprite.get(entity)

    if sprite is None:
        return

    image_key = (
        DEBUG_IN_RANGE_IMAGE_KEY
        if in_range
        else DEBUG_DEFAULT_IMAGE_KEY
    )

    image = world.game.assets.images.get(image_key)

    if image is None:
        return

    sprite["image"] = image



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

        set_melee_pawn_debug_info(
            agent,
            target_entity=None,
            in_attack_range=False,
            attack_position_tile=None,
        )

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

        set_melee_pawn_debug_info(
            agent,
            target_entity=None,
            in_attack_range=False,
            attack_position_tile=None,
        )

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

        set_melee_pawn_debug_info(
            agent,
            target_entity=target,
            in_attack_range=True,
            attack_position_tile=None,
        )

        set_debug_engagement_sprite(world, entity, True)

        return [
            {
                "type": "stop_moving",
            }
        ]
    else:
        set_debug_engagement_sprite(world, entity, False)

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

    set_melee_pawn_debug_info(
        agent,
        target_entity=target,
        in_attack_range=False,
        attack_position_tile=attack_position_tile,
    )

    agent["state"] = "pursuing"

    return [
        {
            "type": "move_to_tile",
            "target_tile": attack_position_tile,
            "target_cpos": tile_center(attack_position_tile),
            "path_policy": path_policy,
        }
    ]