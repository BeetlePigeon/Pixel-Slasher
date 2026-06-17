from utils.action_order_utils import (
    entities_are_within_tile_range,
    get_skill_use_range_tiles,
    set_action_order,
)
from ai.ai_queries import (
    entity_is_valid_target,
    get_player_if_detectable,
)


DEBUG_DEFAULT_IMAGE_KEY = "enemy_normal"
DEBUG_IN_RANGE_IMAGE_KEY = "enemy_angry"
DEBUG_USING_SKILL_IMAGE_KEY = "enemy_attack"
AI_DEBUG_SLASH_SLOT = 0
AI_DEBUG_SLASH_SKILL_ID = "debug_slash"


def think(context):
    world = context.world
    entity = context.entity
    agent = context.agent
    params = agent.get("params", {})

    if entity in world.action_order:
        agent["state"] = "executing_action_order"

        set_debug_engagement_sprite(
            world,
            entity,
            agent.get("target_entity"),
        )
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

        set_debug_engagement_sprite(
            world,
            entity,
            None,
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

    set_debug_engagement_sprite(
        world,
        entity,
        target,
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


def set_debug_engagement_sprite(world, entity, target):
    sprite = world.sprite.get(entity)
    if sprite is None:
        return

    visual_state = get_debug_engagement_visual_state(
        world,
        entity,
        target,
    )

    image_key = get_debug_engagement_image_key(visual_state)
    image = world.game.assets.images.get(image_key)

    if image is None:
        return

    sprite["image"] = image


def get_debug_engagement_visual_state(world, entity, target):
    if not entity_is_valid_target(
        world,
        entity,
        target,
    ):
        return "not_in_range"

    if not entity_is_in_debug_slash_range(
        world,
        entity,
        target,
    ):
        return "not_in_range"

    if entity_is_using_debug_slash(
        world,
        entity,
    ):
        return "using_skill"

    return "in_range"


def get_debug_engagement_image_key(visual_state):
    if visual_state == "using_skill":
        return DEBUG_USING_SKILL_IMAGE_KEY

    if visual_state == "in_range":
        return DEBUG_IN_RANGE_IMAGE_KEY

    return DEBUG_DEFAULT_IMAGE_KEY


def entity_is_in_debug_slash_range(world, entity, target):
    use_range_tiles = get_skill_use_range_tiles(
        AI_DEBUG_SLASH_SKILL_ID,
    )

    if use_range_tiles is None:
        return False

    return entities_are_within_tile_range(
        world,
        entity,
        target,
        use_range_tiles,
    )


def entity_is_using_debug_slash(world, entity):
    action_state = world.action_state.get(entity)

    if action_state is None:
        return False

    return action_state.get("skill_id") == AI_DEBUG_SLASH_SKILL_ID


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