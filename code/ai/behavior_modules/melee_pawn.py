from utils.action_order_utils import set_action_order
from ai.ai_queries import (
    entity_is_valid_target,
    get_player_if_detectable,
)


DEBUG_DEFAULT_IMAGE_KEY = "enemy_normal"
DEBUG_IN_RANGE_IMAGE_KEY = "enemy_angry"
AI_DEBUG_SLASH_SLOT = 0
AI_DEBUG_SLASH_SKILL_ID = "debug_slash"


def think(context):
    world = context.world
    entity = context.entity
    agent = context.agent
    params = agent.get("params", {})

    if entity in world.action_order:
        agent["state"] = "executing_action_order"
        return []

    detect_radius_tiles = params.get("detect_radius_tiles")
    lose_radius_tiles = params.get("lose_radius_tiles")

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
        return []

    agent["target_entity"] = target
    agent["state"] = "issuing_debug_slash_order"
    set_melee_pawn_debug_info(
        agent,
        target_entity=target,
        in_attack_range=None,
        attack_position_tile=None,
    )

    set_action_order(
        world,
        entity,
        build_debug_slash_player_order(
            world,
            entity,
            target,
        ),
    )


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


def build_debug_slash_player_order(world, entity, target):
    return {
        "type": "use_skill_on_entity",
        "actor": entity,
        "target": target,
        "target_kind": "enemy",
        "skill_id": AI_DEBUG_SLASH_SKILL_ID,
        "slot": AI_DEBUG_SLASH_SLOT,
        "input_kind": "ai",
        "target_lock": "hard",
        "created_tick": world.tick,
        "fired_once": False,
        "allow_approach": True,
    }