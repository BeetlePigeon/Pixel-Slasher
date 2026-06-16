from support import Vec2i
from utils.placement_utils import is_tile_valid_for_entity_placement
from utils.camera_utils import internal_screen_to_world_cpos
from utils.soft_targeting_utils import (
    acquire_soft_target,
    soft_target_is_valid,
)
from skill_use_validator import skill_use_is_valid
from utils.targeting_policy_utils import get_soft_targeting_profile
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
    chebyshev_tile_distance,
    tile_center,
)


def action_order_system(world, intents):
    for actor in sorted(list(world.action_order)):
        if not action_order_actor_is_valid(world, actor):
            clear_action_order(world, actor)
            continue

        order = world.action_order[actor]

        if not action_order_target_is_valid(world, order):
            mark_action_input_invalidated(world, actor, order)
            clear_action_order(world, actor)
            continue

        process_action_order(world, intents, actor, order)


def process_action_order(world, intents, actor, order):
    order_type = order["type"]

    if order_type == "move_to_position":
        process_move_to_position_order(
            world,
            intents,
            actor,
            order,
        )
        return

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

    if order_type == "move_with_soft_skill_use":
        process_move_with_soft_skill_use_order(
            world,
            intents,
            actor,
            order,
        )
        return

    if order_type == "attack_in_place":
        process_use_skill_in_place_order(
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


def process_move_to_position_order(world, intents, actor, order):
    if order.get("track_mouse_while_held", False):
        if order_input_is_held(world, actor, order):
            target_cpos = get_order_mouse_target_cpos(
                world,
                actor,
                order,
            )
            if target_cpos is not None:
                order["target_cpos"] = target_cpos
                order["target_tile"] = tile_from_cpos(target_cpos)

    target_tile = order.get("target_tile")
    target_cpos = order.get("target_cpos")

    if target_tile is None or target_cpos is None:
        clear_action_order(world, actor)
        return

    actor_tile = tile_from_cpos(
        world.transform[actor].cpos,
    )

    is_tracking_held_mouse = (
            order.get("track_mouse_while_held", False)
            and order_input_is_held(world, actor, order)
    )

    if actor_tile == target_tile:
        if is_tracking_held_mouse:
            intents.setdefault(actor, []).append(
                {
                    "type": "stop_moving",
                }
            )
            return

        clear_action_order(world, actor)
        return

    intents.setdefault(actor, []).append(
        {
            "type": "move_to_tile",
            "target_tile": target_tile,
            "target_cpos": target_cpos,
            "path_policy": order.get("path_policy", get_approach_path_policy(world, actor)),
            "owner_order_id": order["order_id"],
        }
    )


def process_use_skill_in_place_order(
    world,
    intents,
    actor,
    order,
):
    if not order_input_is_held(world, actor, order):
        clear_action_order(world, actor)
        return

    skill_id = order.get("skill_id")
    slot = order.get("slot")

    if skill_id is None or slot is None:
        clear_action_order(world, actor)
        return

    soft_policy = get_soft_targeting_profile(
        skill_id,
        context_id=order.get("input_context"),
    )

    target = resolve_order_soft_target(
        world,
        actor,
        order,
        soft_policy,
    )

    if target is not None:
        append_soft_target_skill_intents(
            world,
            intents,
            actor,
            order,
            target,
        )
        return

    order.pop("soft_target", None)
    append_use_skill_in_place_intent(
        world,
        intents,
        actor,
        order,
    )


def append_use_skill_in_place_intent(
    world,
    intents,
    actor,
    order,
):
    if not skill_trigger_policy_allows_skill_intent(world, actor, order):
        maybe_clear_completed_skill_order(world, actor, order)
        return

    intent = build_use_skill_in_place_intent(
        world,
        actor,
        order,
    )

    validation = validate_order_skill_use(
        world,
        actor,
        order,
        intent,
    )

    if not validation.is_valid:
        return

    intents.setdefault(actor, []).append(
        {
            "type": "stop_moving",
        }
    )

    if (
        skill_requires_centered_start(validation.skill_def)
        and actor_needs_recenter_for_action(world, actor)
    ):
        append_recenter_for_action_intent(
            world,
            intents,
            actor,
            order,
        )
        return

    intents.setdefault(actor, []).append(intent)

    order["fired_once"] = True
    maybe_clear_completed_skill_order(world, actor, order)


def build_use_skill_in_place_intent(world, actor, order):
    trigger_mode = get_skill_trigger_mode(
        order.get("skill_id"),
    )

    if trigger_mode == "press":
        intent_type = "skill_pressed"
    elif trigger_mode == "held_repeat":
        intent_type = "skill_held"
    else:
        raise ValueError(
            f"Unsupported use-skill-in-place trigger mode: {trigger_mode!r}"
        )

    return {
        "type": intent_type,
        "slot": order["slot"],
        "mouse_pos": get_order_mouse_pos(
            world,
            actor,
            order,
        ),
        "target_source": "use_skill_in_place",
        "button": order.get("button"),
    }


def get_order_mouse_pos(world, actor, order):
    aim_state = world.aim_state.get(actor, {})

    return aim_state.get(
        "mouse_pos",
        order.get("press_mouse_pos"),
    )


def get_actor_current_tile_and_center(world, actor):
    actor_tile = tile_from_cpos(
        world.transform[actor].cpos,
    )

    return actor_tile, tile_center(actor_tile)


def actor_is_centered_for_action(world, actor):
    _, actor_center_cpos = get_actor_current_tile_and_center(
        world,
        actor,
    )

    return world.transform[actor].cpos == actor_center_cpos


def append_recenter_for_action_intent(
    world,
    intents,
    actor,
    order,
):
    actor_tile, actor_center_cpos = get_actor_current_tile_and_center(
        world,
        actor,
    )

    intents.setdefault(actor, []).append(
        {
            "type": "recenter_for_action",
            "target_tile": actor_tile,
            "target_cpos": actor_center_cpos,
            "owner_order_id": order["order_id"],
        }
    )


def actor_needs_recenter_for_action(world, actor):
    return not actor_is_centered_for_action(
        world,
        actor,
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
            interact_range_tiles,
            order["order_id"],
        )
        return

    if actor_needs_recenter_for_action(
        world,
        actor,
    ):
        append_recenter_for_action_intent(
            world,
            intents,
            actor,
            order,
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

    if not skill_trigger_policy_allows_skill_intent(world, actor, order):
        maybe_clear_completed_skill_order(world, actor, order)
        return

    intent = build_order_skill_intent(
        world,
        actor,
        order,
    )

    validation = validate_order_skill_use(
        world,
        actor,
        order,
        intent,
    )

    if not validation.is_valid:
        return

    use_range_tiles = get_skill_use_range_tiles(skill_id)

    if use_range_tiles is not None:
        if not entities_are_within_tile_range(
            world,
            actor,
            target,
            use_range_tiles,
        ):
            if not order.get("allow_approach", True):
                return

            append_approach_entity_intent(
                world,
                intents,
                actor,
                target,
                use_range_tiles,
                order["order_id"],
            )
            return

    if (
        skill_requires_centered_start(validation.skill_def)
        and actor_needs_recenter_for_action(
            world,
            actor,
        )
    ):
        append_recenter_for_action_intent(
            world,
            intents,
            actor,
            order,
        )
        return

    intents.setdefault(actor, []).append(intent)

    order["fired_once"] = True
    maybe_clear_completed_skill_order(world, actor, order)


def process_move_with_soft_skill_use_order(world, intents, actor, order):
    if not order_input_is_held(world, actor, order):
        clear_action_order(world, actor)
        return

    skill_id = order.get("skill_id")
    slot = order.get("slot")

    if skill_id is None or slot is None:
        clear_action_order(world, actor)
        return

    soft_policy = get_soft_targeting_profile(
        skill_id,
        context_id=order.get("input_context"),
    )

    target = resolve_order_soft_target(
        world,
        actor,
        order,
        soft_policy,
    )

    if target is not None:
        append_soft_target_skill_intents(
            world,
            intents,
            actor,
            order,
            target,
        )
        return

    order.pop("soft_target", None)
    append_order_mouse_move_intent(
        world,
        intents,
        actor,
        order,
    )


def resolve_order_soft_target(world, actor, order, soft_policy):
    current_target = order.get("soft_target")

    reference_direction = get_soft_target_reference_direction(
        world,
        actor,
        order,
        soft_policy,
    )
    origin_cpos = get_soft_target_origin_cpos(
        world,
        actor,
        order,
        soft_policy,
    )

    if soft_target_is_valid(
        world,
        actor,
        current_target,
        soft_policy,
        reference_direction=reference_direction,
        origin_cpos=origin_cpos,
    ):
        return current_target

    target = acquire_soft_target(
        world,
        actor,
        soft_policy,
        reference_direction=reference_direction,
        origin_cpos=origin_cpos,
    )

    if target is not None:
        order["soft_target"] = target

    return target


def get_soft_target_origin_cpos(
    world,
    actor,
    order,
    soft_policy,
):
    origin = soft_policy["origin"]

    if origin == "actor":
        return None

    if origin == "cursor":
        return get_order_mouse_target_cpos(
            world,
            actor,
            order,
        )

    raise NotImplementedError(
        f"Soft target origin not implemented: {origin!r}"
    )


def get_soft_target_reference_direction(
    world,
    actor,
    order,
    soft_policy,
):
    direction_source = soft_policy.get(
        "reference_direction",
        "facing",
    )

    if direction_source == "none":
        return None

    if direction_source == "facing":
        return world.facing.get(actor)

    if direction_source == "mouse":
        target_cpos = get_order_mouse_target_cpos(
            world,
            actor,
            order,
        )
        if target_cpos is None:
            return world.facing.get(actor)

        actor_cpos = world.transform[actor].cpos
        delta = target_cpos - actor_cpos

        if delta.x == 0 and delta.y == 0:
            return world.facing.get(actor)

        return delta

    raise NotImplementedError(
        f"Soft target reference direction not implemented: {direction_source!r}"
    )


def append_soft_target_skill_intents(
    world,
    intents,
    actor,
    order,
    target,
):
    if not skill_trigger_policy_allows_skill_intent(world, actor, order):
        maybe_clear_completed_skill_order(world, actor, order)
        return

    intent = build_soft_target_skill_intent(
        world,
        actor,
        order,
        target,
    )

    validation = validate_order_skill_use(
        world,
        actor,
        order,
        intent,
    )

    if not validation.is_valid:
        return

    intents.setdefault(actor, []).append(
        {
            "type": "stop_moving",
        }
    )

    if (
        skill_requires_centered_start(validation.skill_def)
        and actor_needs_recenter_for_action(
            world,
            actor,
        )
    ):
        append_recenter_for_action_intent(
            world,
            intents,
            actor,
            order,
        )
        return

    intents.setdefault(actor, []).append(intent)

    order["fired_once"] = True
    maybe_clear_completed_skill_order(world, actor, order)


def build_soft_target_skill_intent(
    world,
    actor,
    order,
    target,
):
    trigger_mode = get_skill_trigger_mode(
        order.get("skill_id"),
    )

    if trigger_mode == "press":
        intent_type = "skill_pressed"
    elif trigger_mode == "held_repeat":
        intent_type = "skill_held"
    else:
        raise ValueError(
            f"Unsupported soft-target skill trigger mode: {trigger_mode!r}"
        )

    return {
        "type": intent_type,
        "slot": order["slot"],
        "target_entity": target,
        "target_source": "soft",
        "requires_target_entity": True,
        "button": order.get("button"),
    }


def append_order_mouse_move_intent(
    world,
    intents,
    actor,
    order,
):
    target_cpos = get_order_mouse_target_cpos(
        world,
        actor,
        order,
    )

    if target_cpos is None:
        return

    target_tile = tile_from_cpos(target_cpos)

    intents.setdefault(actor, []).append(
        {
            "type": "move_to_tile",
            "target_tile": target_tile,
            "target_cpos": target_cpos,
            "mouse_pos": order.get("press_mouse_pos"),
            "path_policy": get_approach_path_policy(world, actor),
        }
    )


def get_order_mouse_target_cpos(world, actor, order):
    aim_state = world.aim_state.get(actor, {})
    mouse_pos = aim_state.get(
        "mouse_pos",
        order.get("press_mouse_pos"),
    )

    if mouse_pos is None:
        return None

    return internal_screen_to_world_cpos(
        world,
        mouse_pos,
    )


def skill_trigger_policy_allows_skill_intent(world, actor, order):
    skill_id = order.get("skill_id")
    trigger_mode = get_skill_trigger_mode(skill_id)
    fired_once = order.get("fired_once", False)

    if trigger_mode == "press":
        return not fired_once

    if trigger_mode == "held_repeat":
        return (
            order_input_is_held(world, actor, order)
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
        and not order_input_is_held(world, actor, order)
    ):
        clear_action_order(world, actor)


def order_input_is_held(world, actor, order):
    input_kind = order.get("input_kind", "mouse")

    if input_kind == "mouse":
        button = order.get("button")
        if button is None:
            return False

        pointer_actions = world.pointer_action_state.get(actor, {})
        return button in pointer_actions

    if input_kind == "keyboard":
        key = order.get("key")
        if key is None:
            return False

        keyboard_actions = world.keyboard_action_state.get(actor, {})
        return key in keyboard_actions

    raise NotImplementedError(
        f"Action order input kind not implemented: {input_kind!r}"
    )


def append_approach_entity_intent(
    world,
    intents,
    actor,
    target,
    desired_range_tiles,
    owner_order_id,
):

    approach_tile = find_entity_approach_tile(
        world,
        actor,
        target,
        desired_range_tiles,
    )

    if approach_tile is None:
        approach_tile = find_entity_best_effort_approach_tile(
            world,
            actor,
            target,
        )

    if approach_tile is None:
        return

    target_cpos = tile_center(approach_tile)

    intents.setdefault(actor, []).append(
        {
            "type": "move_to_tile",
            "target_tile": approach_tile,
            "target_cpos": target_cpos,
            "path_policy": get_approach_path_policy(world, actor),
            "owner_order_id": owner_order_id,
        }
    )


def find_entity_approach_tile(
    world,
    actor,
    target,
    desired_range_tiles,
):
    actor_tile = tile_from_cpos(
        world.transform[actor].cpos,
    )
    target_tile = tile_from_cpos(
        world.transform[target].cpos,
    )

    if chebyshev_tile_distance(
        actor_tile,
        target_tile,
    ) <= desired_range_tiles:
        return actor_tile

    candidates = []

    for candidate_tile in iter_tiles_within_range(
        target_tile,
        desired_range_tiles,
    ):
        if (
            desired_range_tiles > 0
            and candidate_tile == target_tile
        ):
            continue

        if not is_tile_valid_for_entity_placement(
            world,
            candidate_tile,
            entity=actor,
            include_dynamic=True,
        ):
            continue

        candidates.append(
            (
                chebyshev_tile_distance(
                    actor_tile,
                    candidate_tile,
                ),
                chebyshev_tile_distance(
                    candidate_tile,
                    target_tile,
                ),
                candidate_tile.y,
                candidate_tile.x,
                candidate_tile,
            )
        )

    if not candidates:
        return None

    candidates.sort()
    return candidates[0][-1]


def find_entity_best_effort_approach_tile(
    world,
    actor,
    target,
):
    actor_tile = tile_from_cpos(
        world.transform[actor].cpos,
    )
    target_tile = tile_from_cpos(
        world.transform[target].cpos,
    )

    direct_tile = find_direct_progress_tile_toward_target(
        world,
        actor,
        actor_tile,
        target_tile,
    )
    if direct_tile is not None:
        return direct_tile

    return find_neighbor_progress_tile_toward_target(
        world,
        actor,
        actor_tile,
        target_tile,
    )


def find_direct_progress_tile_toward_target(
    world,
    actor,
    actor_tile,
    target_tile,
):
    step = Vec2i(
        sign_int(target_tile.x - actor_tile.x),
        sign_int(target_tile.y - actor_tile.y),
    )

    if step.x == 0 and step.y == 0:
        return None

    current_tile = actor_tile
    best_tile = None
    visited = set()

    while True:
        next_tile = current_tile + step
        key = (next_tile.x, next_tile.y)

        if key in visited:
            break

        visited.add(key)

        if next_tile == target_tile:
            break

        if not is_tile_valid_for_entity_placement(
            world,
            next_tile,
            entity=actor,
            include_dynamic=True,
        ):
            break

        best_tile = next_tile
        current_tile = next_tile

    return best_tile


def find_neighbor_progress_tile_toward_target(
    world,
    actor,
    actor_tile,
    target_tile,
):
    current_distance = chebyshev_tile_distance(
        actor_tile,
        target_tile,
    )

    candidates = []

    for direction in iter_best_effort_directions_toward_target(
        actor,
        actor_tile,
        target_tile,
    ):
        candidate_tile = actor_tile + direction

        if not is_tile_valid_for_entity_placement(
            world,
            candidate_tile,
            entity=actor,
            include_dynamic=True,
        ):
            continue

        candidate_distance = chebyshev_tile_distance(
            candidate_tile,
            target_tile,
        )

        if candidate_distance >= current_distance:
            continue

        candidates.append(
            (
                candidate_distance,
                candidate_tile.y,
                candidate_tile.x,
                candidate_tile,
            )
        )

    if not candidates:
        return None

    candidates.sort()
    return candidates[0][-1]


def iter_best_effort_directions_toward_target(
    actor,
    actor_tile,
    target_tile,
):
    dx = sign_int(target_tile.x - actor_tile.x)
    dy = sign_int(target_tile.y - actor_tile.y)

    primary = Vec2i(dx, dy)

    directions = []
    seen = set()

    def add_direction(direction):
        if direction.x == 0 and direction.y == 0:
            return

        key = (direction.x, direction.y)
        if key in seen:
            return

        seen.add(key)
        directions.append(direction)

    add_direction(primary)

    if dx != 0:
        add_direction(Vec2i(dx, 0))

    if dy != 0:
        add_direction(Vec2i(0, dy))

    # Try deterministic side-ish alternatives after direct progress.
    if dx != 0 and dy != 0:
        if actor % 2 == 0:
            add_direction(Vec2i(dx, -dy))
            add_direction(Vec2i(-dx, dy))
        else:
            add_direction(Vec2i(-dx, dy))
            add_direction(Vec2i(dx, -dy))

    return directions


def sign_int(value):
    if value < 0:
        return -1

    if value > 0:
        return 1

    return 0


def iter_tiles_within_range(center_tile, range_tiles):
    for dy in range(-range_tiles, range_tiles + 1):
        for dx in range(-range_tiles, range_tiles + 1):
            candidate_tile = center_tile + Vec2i(dx, dy)

            if chebyshev_tile_distance(
                candidate_tile,
                center_tile,
            ) > range_tiles:
                continue

            yield candidate_tile


def get_approach_path_policy(world, actor):
    if actor == world.player:
        return "player_click_move"

    return "actor_move"


def mark_action_input_invalidated(world, actor, order):
    input_kind = order.get("input_kind", "mouse")

    if input_kind == "mouse":
        button = order.get("button")
        if button is None:
            return

        pointer_actions = world.pointer_action_state.get(actor, {})
        action_state = pointer_actions.get(button)

        if action_state is None:
            return

        if not action_state.get("consumes_button_until_release", False):
            return

        action_state["hard_target_invalidated"] = True
        return

    if input_kind == "keyboard":
        key = order.get("key")
        if key is None:
            return

        keyboard_actions = world.keyboard_action_state.get(actor, {})
        action_state = keyboard_actions.get(key)

        if action_state is None:
            return

        if not action_state.get("consumes_key_until_release", False):
            return

        action_state["hard_target_invalidated"] = True
        return

    raise NotImplementedError(
        f"Action order input kind not implemented: {input_kind!r}"
    )


def validate_order_skill_use(world, actor, order, intent):
    validation = skill_use_is_valid(
        world,
        actor,
        intent["slot"],
        intent,
    )

    if validation.is_valid:
        return validation

    maybe_clear_invalid_skill_order(world, actor, order)
    return validation


def maybe_clear_invalid_skill_order(world, actor, order):
    trigger_mode = get_skill_trigger_mode(order.get("skill_id"))

    if trigger_mode == "press":
        order["fired_once"] = True
        maybe_clear_completed_skill_order(world, actor, order)


def skill_requires_centered_start(skill_def):
    return skill_def.get("requires_centered_start", True)