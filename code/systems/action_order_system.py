from utils.action_order_utils import (
    action_order_actor_is_valid,
    action_order_target_is_valid,
    clear_action_order,
    entities_are_within_tile_range,
    get_skill_interact_range_tiles,
    get_skill_trigger_mode,
    get_skill_use_range_tiles,
)
from utils.tile_vec_utils import (
    tile_from_cpos,
)


def action_order_system(world, intents):
    for actor in sorted(list(world.action_order)):
        if not action_order_actor_is_valid(world, actor):
            clear_action_order(world, actor)
            continue

        order = world.action_order[actor]

        if not action_order_target_is_valid(world, order):
            clear_action_order(world, actor)
            continue

        process_action_order(world, intents, actor, order)


def process_action_order(world, intents, actor, order):
    order_type = order["type"]

    if order_type == "interact_with_entity":
        process_interact_with_entity_order(
            world,
            intents,
            actor,
            order,
        )
        return

    if order_type == "use_skill_on_entity":
        process_use_skill_on_entity_order(
            world,
            intents,
            actor,
            order,
        )
        return

    # Kept temporarily so older local debug captures do not crash.
    if order_type == "captured_hard_target":
        return

    raise NotImplementedError(
        f"Action order type not implemented: {order_type!r}"
    )


def process_interact_with_entity_order(world, intents, actor, order):
    target = order["target"]
    skill_id = order.get("skill_id")
    interact_range_tiles = get_skill_interact_range_tiles(skill_id)

    if not entities_are_within_tile_range(
        world,
        actor,
        target,
        interact_range_tiles,
    ):
        append_approach_entity_intent(
            world,
            intents,
            actor,
            target,
        )
        return

    intents.setdefault(actor, []).append(
        {
            "type": "interact",
            "target": target,
            "skill_id": skill_id,
            "button": order.get("button"),
        }
    )

    clear_action_order(world, actor)


def process_use_skill_on_entity_order(world, intents, actor, order):
    target = order["target"]
    skill_id = order.get("skill_id")
    slot = order.get("slot")

    if skill_id is None or slot is None:
        clear_action_order(world, actor)
        return

    use_range_tiles = get_skill_use_range_tiles(skill_id)

    if use_range_tiles is not None:
        if not entities_are_within_tile_range(
            world,
            actor,
            target,
            use_range_tiles,
        ):
            append_approach_entity_intent(
                world,
                intents,
                actor,
                target,
            )
            return

    if not should_emit_order_skill_intent(world, actor, order):
        maybe_clear_completed_skill_order(world, actor, order)
        return

    intents.setdefault(actor, []).append(
        build_order_skill_intent(
            world,
            actor,
            order,
        )
    )

    order["fired_once"] = True
    maybe_clear_completed_skill_order(world, actor, order)


def should_emit_order_skill_intent(world, actor, order):
    skill_id = order.get("skill_id")
    trigger_mode = get_skill_trigger_mode(skill_id)
    fired_once = order.get("fired_once", False)

    if trigger_mode == "press":
        return not fired_once

    if trigger_mode == "held_repeat":
        return (
            order_button_is_held(world, actor, order)
            or not fired_once
        )

    return False


def build_order_skill_intent(world, actor, order):
    trigger_mode = get_skill_trigger_mode(
        order.get("skill_id"),
    )

    if trigger_mode == "press":
        intent_type = "skill_pressed"
    elif trigger_mode == "held_repeat":
        intent_type = "skill_held"
    else:
        raise ValueError(
            f"Unsupported order skill trigger mode: {trigger_mode!r}"
        )

    return {
        "type": intent_type,
        "slot": order["slot"],
        "target_entity": order["target"],
        "requires_target_entity": True,
        "button": order.get("button"),
    }


def maybe_clear_completed_skill_order(world, actor, order):
    skill_id = order.get("skill_id")
    trigger_mode = get_skill_trigger_mode(skill_id)

    if trigger_mode == "press" and order.get("fired_once", False):
        clear_action_order(world, actor)
        return

    if (
        trigger_mode == "held_repeat"
        and order.get("fired_once", False)
        and not order_button_is_held(world, actor, order)
    ):
        clear_action_order(world, actor)


def order_button_is_held(world, actor, order):
    button = order.get("button")
    if button is None:
        return False

    pointer_actions = world.pointer_action_state.get(actor, {})
    return button in pointer_actions


def append_approach_entity_intent(world, intents, actor, target):
    target_cpos = world.transform[target].cpos
    target_tile = tile_from_cpos(target_cpos)

    intents.setdefault(actor, []).append(
        {
            "type": "move_to_tile",
            "target_tile": target_tile,
            "target_cpos": target_cpos,
            "path_policy": get_approach_path_policy(world, actor),
        }
    )


def get_approach_path_policy(world, actor):
    if actor == world.player:
        return "player_click_move"

    return "actor_move"