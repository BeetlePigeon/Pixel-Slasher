from skill_registry import SKILL_DEFS
from utils.tile_vec_utils import (
    chebyshev_tile_distance,
    tile_from_cpos,
)


DEFAULT_INTERACT_RANGE_TILES = 1


def clear_action_order(world, actor):
    world.action_order.pop(actor, None)


def set_action_order(world, actor, order):
    order = dict(order)

    if "order_id" not in order:
        order["order_id"] = world.next_action_order_id
        world.next_action_order_id += 1

    world.action_order[actor] = order


def action_order_actor_is_valid(world, actor):
    return (
        actor in world.transform
        and actor in world.motion_state
    )


def action_order_target_is_valid(world, order):
    target = order.get("target")
    if target is None:
        return True

    if target not in world.transform:
        return False

    selectable = world.selectable.get(target)
    if selectable is not None and not selectable.get("enabled", True):
        return False

    target_kind = order.get("target_kind")

    if target_kind == "enemy":
        if target not in world.health:
            return False

        if target not in world.hittable:
            return False

        health = world.health[target]
        if health.get("current", 1) <= 0:
            return False

    if target_kind == "interactable":
        return target in world.interactable

    return True


def get_skill_def(skill_id):
    if skill_id is None:
        return None

    return SKILL_DEFS.get(skill_id)


def get_skill_params(skill_id):
    skill_def = get_skill_def(skill_id)
    if skill_def is None:
        return {}

    return skill_def.get("params", {})


def get_skill_trigger_mode(skill_id):
    skill_def = get_skill_def(skill_id)
    if skill_def is None:
        return None

    return skill_def["trigger_mode"]


def get_skill_use_range_tiles(skill_id):
    params = get_skill_params(skill_id)
    return params.get("use_range_tiles")


def get_skill_interact_range_tiles(skill_id):
    params = get_skill_params(skill_id)
    return params.get(
        "interact_range_tiles",
        DEFAULT_INTERACT_RANGE_TILES,
    )


def entities_are_within_tile_range(world, actor, target, range_tiles):
    actor_tile = tile_from_cpos(
        world.transform[actor].cpos,
    )
    target_tile = tile_from_cpos(
        world.transform[target].cpos,
    )

    return (
        chebyshev_tile_distance(
            actor_tile,
            target_tile,
        )
        <= range_tiles
    )


def get_action_order_summary(world, actor):
    order = world.action_order.get(actor)
    if order is None:
        return "None"

    order_type = order.get("type")
    target = order.get("target")
    target_kind = order.get("target_kind")
    skill_id = order.get("skill_id")
    fired_once = order.get("fired_once", False)

    return (
        f"{order_type} "
        f"target={target} "
        f"kind={target_kind} "
        f"skill={skill_id} "
        f"fired={fired_once}"
    )