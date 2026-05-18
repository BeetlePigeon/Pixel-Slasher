import pygame
from skills import SKILL_DEFS
from settings import MOVE_BUFFER_TICKS, PATH_POLICIES
from action_ops import (
    MOVEMENT_CANCELING_ACTION_TAGS,
    tags_block_voluntary_movement,
    start_action_state,
)
from path_utils import (
    find_static_tile_path_to_target,
    smooth_static_tile_path,
    path_tiles_to_cpos_nodes,
)
from support import (
    TILE_UNITS,
    Vec2i,
    sign,
    tile_center,
    tile_from_cpos,
    interp_cpos,
    iso_to_screen,
    cpos_to_screen,
    scale_vec,
    clamp_vec_axis,
    lerp_cpos,
    GridMoveController,
    SettleToGridController,
    PathFollowController,
)


def emit_event(world, event_type, **data):
    world.events.append({
        "type": event_type,
        **data,
    })


def snapshot_system(world):
    world.snapshot["cpos"].clear()
    world.snapshot["tile"].clear()

    for entity in sorted(world.transform):
        transform = world.transform[entity]
        transform.prev_cpos = transform.cpos

        world.snapshot["cpos"][entity] = transform.cpos
        world.snapshot["tile"][entity] = transform.tile


def entity_can_start_voluntary_movement(world, entity):
    active_action_tags = get_active_action_tags(world, entity)

    return not tags_block_voluntary_movement(active_action_tags)


def execute_action_event(world, entity, action_state, event):
    handler = event.get("handler")

    if handler is None:
        return

    intent = event.get("intent", {})
    skill_def = event.get("skill_def")

    handler(
        world,
        entity,
        intent,
        skill_def,
    )


def action_state_system(world):
    expired_entities = []

    for entity, action_state in list(world.action_state.items()):
        action_state["age"] += 1

        events = action_state.get("events", [])

        for event in events:
            if event.get("fired", False):
                continue

            tick = event["tick"]

            if action_state["age"] < tick:
                continue

            execute_action_event(
                world,
                entity,
                action_state,
                event,
            )

            event["fired"] = True

        duration = action_state.get("duration")

        if duration is not None:
            if action_state["age"] >= duration:
                expired_entities.append(entity)

    for entity in expired_entities:
        world.action_state.pop(entity, None)


def buffer_move_intent(world, entity, direction: Vec2i):
    world.buffered_move_intent[entity] = {
        "type": "direction",
        "direction": direction,
        "expires_tick": world.tick + MOVE_BUFFER_TICKS,
    }


def clear_buffered_move_intent(world, entity):
    world.buffered_move_intent.pop(entity, None)


def get_buffered_move_direction(world, entity):
    buffered = world.buffered_move_intent.get(entity)

    if buffered is None:
        return None

    if world.tick > buffered["expires_tick"]:
        clear_buffered_move_intent(world, entity)
        return None

    if buffered["type"] != "direction":
        return None

    return buffered["direction"]


def intent_system(world, intents):
    world.move_intent.clear()

    for entity, entity_intents in intents.items():
        found_move_intent = False

        for intent in entity_intents:
            if intent["type"] == "move_to_tile":
                set_move_target(
                    world,
                    entity,
                    intent["target_tile"],
                    intent.get("target_cpos"),
                )
                continue

            if intent["type"] != "move":
                continue

            if found_move_intent:
                continue

            dx, dy = intent["direction"]

            if dx == 0 and dy == 0:
                continue

            direction = Vec2i(dx, dy)
            world.move_intent[entity] = direction

            # Manual directional movement cancels click-to-move target.
            clear_move_target(world, entity)

            motion_state = world.motion_state.get(entity)

            if motion_state is not None:
                if motion_state.get("controller") is not None:
                    buffer_move_intent(world, entity, direction)

            if entity in world.facing:
                world.facing[entity] = direction

            found_move_intent = True


def movement_start_suppressed_this_tick(world, entity):
    motion_state = world.motion_state.get(entity)

    if motion_state is None:
        return False

    return motion_state.get("suppress_move_start_tick") == world.tick


def movement_arbiter_system(world):
    entities = (
        (
            set(world.move_intent)
            | set(world.buffered_move_intent)
            | set(world.move_target)
        )
        & set(world.transform)
        & set(world.motion_state)
        & set(world.locomotion)
    )

    for entity in sorted(entities):
        transform = world.transform[entity]
        motion_state = world.motion_state[entity]
        locomotion = world.locomotion[entity]

        if not entity_can_start_voluntary_movement(world, entity):
            cancel_voluntary_movement(world, entity)
            continue

        controller = motion_state["controller"]

        if isinstance(controller, PathFollowController):
            if refresh_path_follow_controller_if_needed(
                    world,
                    entity,
                    controller,
            ):
                continue

            continue

        slide_vector = None
        slide_context = "grid"

        if movement_start_suppressed_this_tick(world, entity):
            continue

        if motion_state["controller"] is not None:
            continue

        using_buffered_intent = False
        using_move_target = False

        if entity in world.move_intent:
            desired_direction = world.move_intent[entity]

        elif entity in world.move_target:
            target = world.move_target[entity]

            if start_path_follow_controller(
                    world,
                    entity,
                    target,
            ):
                continue

            continue

        else:
            desired_direction = get_buffered_move_direction(world, entity)
            using_buffered_intent = True

            if desired_direction is None:
                continue

        if not locomotion["can_move_8way"]:
            if desired_direction.x != 0 and desired_direction.y != 0:
                if using_buffered_intent:
                    clear_buffered_move_intent(world, entity)

                if using_move_target:
                    clear_move_target(world, entity)

                continue

        resolved_direction = resolve_grid_move_direction(
            world,
            entity,
            desired_direction,
            slide_vector,
            slide_context
        )

        if resolved_direction is None:
            if using_buffered_intent:
                clear_buffered_move_intent(world, entity)

            if using_move_target:
                clear_move_target(world, entity)

            continue

        current_tile = transform.tile
        target_tile = Vec2i(
            current_tile.x + resolved_direction.x,
            current_tile.y + resolved_direction.y,
        )

        start = tile_center(current_tile)
        end = tile_center(target_tile)

        motion_state["controller"] = GridMoveController(
            start=start,
            end=end,
            progress=0,
            duration=locomotion["step_duration"],
        )

        if using_buffered_intent:
            motion_state["controller_source"] = "buffered_move"
        else:
            motion_state["controller_source"] = "move_intent"

        if entity in world.facing:
            world.facing[entity] = resolved_direction

        if using_buffered_intent:
            clear_buffered_move_intent(world, entity)


def sample_wind_delta(world, emitter):
    mode = emitter.get("mode", "constant")

    if mode == "constant":
        return emitter["delta"]

    if mode == "cycle":
        cycle = emitter["cycle"]
        ticks_per_step = emitter["ticks_per_step"]
        index = (world.tick // ticks_per_step) % len(cycle)
        return cycle[index]

    return emitter["delta"]


def sample_magnet_delta(world, emitter_entity, emitter, target_entity):
    emitter_cpos = world.snapshot["cpos"].get(emitter_entity)
    target_cpos = world.snapshot["cpos"].get(target_entity)

    if emitter_cpos is None or target_cpos is None:
        return Vec2i(0, 0)

    dx = emitter_cpos.x - target_cpos.x
    dy = emitter_cpos.y - target_cpos.y

    # Simple square radius check for now.
    radius = emitter["radius"]
    if abs(dx) > radius or abs(dy) > radius:
        return Vec2i(0, 0)

    strength = emitter["strength"]

    return Vec2i(
        sign(dx) * strength,
        sign(dy) * strength,
    )


def motion_accepts_influences(motion_state) -> bool:
    if motion_state is None:
        return True

    influence_mode = motion_state.get("influence_mode", "normal")

    if influence_mode == "ignore_all":
        return False

    return True


def influence_system(world):
    world.influence_delta.clear()

    receivers = (
        set(world.transform)
        & set(world.influence_receiver)
    )

    for entity in sorted(receivers):
        motion_state = world.motion_state.get(entity)

        if not motion_accepts_influences(motion_state):
            world.influence_delta[entity] = Vec2i(0, 0)
            continue

        receiver = world.influence_receiver[entity]
        accepted = receiver["accepts"]

        total = Vec2i(0, 0)

        for emitter_entity in sorted(world.influence_emitter):
            emitter = world.influence_emitter[emitter_entity]
            influence_type = emitter["type"]

            if influence_type not in accepted:
                continue

            delta = Vec2i(0, 0)

            if influence_type == "wind":
                delta = sample_wind_delta(world, emitter)

            elif influence_type == "magnet":
                delta = sample_magnet_delta(world, emitter_entity, emitter, entity)

            scale_num, scale_den = receiver.get("scales", {}).get(
                influence_type,
                (1, 1),
            )

            delta = scale_vec(delta, scale_num, scale_den)
            total = total + delta

        max_delta = receiver.get("max_delta")

        if max_delta is not None:
            total = clamp_vec_axis(total, max_delta)

        world.influence_delta[entity] = total


def clear_motion_controller(motion_state):
    motion_state["controller"] = None
    motion_state["influence_mode"] = "normal"
    motion_state.pop("controller_source", None)


def cancel_active_path_follow_if_needed(world, entity):
    motion_state = world.motion_state.get(entity)

    if motion_state is None:
        return

    controller = motion_state.get("controller")

    if not isinstance(controller, PathFollowController):
        return

    if motion_state.get("controller_source") != "move_target":
        return

    transform = world.transform.get(entity)

    clear_motion_controller(motion_state)

    if transform is not None:
        start_settle_to_grid_if_needed(
            world,
            entity,
            transform,
            motion_state,
        )


def cancel_voluntary_movement(world, entity):
    world.move_intent.pop(entity, None)
    clear_buffered_move_intent(world, entity)
    clear_move_target(world, entity)
    cancel_active_path_follow_if_needed(world, entity)


def is_at_cpos(a: Vec2i, b: Vec2i) -> bool:
    return a.x == b.x and a.y == b.y


def axis_cross_position(start: Vec2i, delta: Vec2i, axis_distance: int, axis_abs_delta: int) -> Vec2i:
    return Vec2i(
        start.x + delta.x * axis_distance // axis_abs_delta,
        start.y + delta.y * axis_distance // axis_abs_delta,
    )


def safe_before_x_cross(boundary_cpos: Vec2i, step_x: int) -> Vec2i:
    return Vec2i(
        boundary_cpos.x - step_x,
        boundary_cpos.y,
    )


def safe_before_y_cross(boundary_cpos: Vec2i, step_y: int) -> Vec2i:
    return Vec2i(
        boundary_cpos.x,
        boundary_cpos.y - step_y,
    )


def safe_before_corner_cross(boundary_cpos: Vec2i, step_x: int, step_y: int) -> Vec2i:
    return Vec2i(
        boundary_cpos.x - step_x,
        boundary_cpos.y - step_y,
    )


def get_active_controller(world, entity):
    motion_state = world.motion_state.get(entity)

    if motion_state is None:
        return None

    return motion_state.get("controller")


def get_active_action_tags(world, entity):
    action_state = world.action_state.get(entity)

    if action_state is None:
        return set()

    tags = action_state.get("tags")

    if tags is not None:
        return set(tags)

    action_type = action_state.get("type")

    if action_type is None:
        return set()

    return {action_type}


def skill_allowed_by_action_state(world, entity, skill_def):
    active_action_tags = get_active_action_tags(world, entity)

    if not active_action_tags:
        return True

    blocked_tags = skill_def.get("blocked_by_action_tags", set())

    return active_action_tags.isdisjoint(blocked_tags)


def get_movement_slide_ratio(world, entity, slide_context="default"):
    controller = get_active_controller(world, entity)

    if controller is not None:
        controller_ratio = getattr(controller, "slide_min_tangent_ratio", None)

        if controller_ratio is not None:
            return controller_ratio

    policy = world.movement_collision.get(entity, {})

    if slide_context == "grid":
        return policy.get(
            "grid_slide_min_tangent_ratio",
            policy.get("slide_min_tangent_ratio", (1, 2)),
        )

    if slide_context == "mouse":
        return policy.get(
            "mouse_slide_min_tangent_ratio",
            policy.get("slide_min_tangent_ratio", (1, 2)),
        )

    return policy.get("slide_min_tangent_ratio", (1, 2))


def entity_allows_grid_slide(world, entity):
    policy = world.movement_collision.get(entity, {})
    return policy.get("static_tiles") == "slide"


def resolve_grid_move_direction(
    world,
    entity,
    desired_direction: Vec2i,
    slide_vector=None,
    slide_context="grid",
):
    transform = world.transform[entity]
    current_tile = transform.tile

    desired_tile = current_tile + desired_direction

    if slide_vector is None:
        slide_vector = desired_direction

    # If desired movement is open, take it directly.
    if not is_tile_blocked(world, desired_tile):
        return desired_direction

    # Only entities with slide policy may use this fallback.
    if not entity_allows_grid_slide(world, entity):
        return None

    # Cardinal movement into a wall has no tangent component.
    # It should block.
    if desired_direction.x == 0 or desired_direction.y == 0:
        return None

    ratio = get_movement_slide_ratio(
        world,
        entity,
        slide_context=slide_context,
    )

    candidates = []

    # Try x-only slide.
    x_direction = Vec2i(desired_direction.x, 0)
    x_tile = current_tile + x_direction

    if not is_tile_blocked(world, x_tile):
        tangent = slide_vector.x
        normal = slide_vector.y

        if passes_slide_threshold(tangent, normal, ratio):
            candidates.append((
                abs(tangent),
                0,  # deterministic priority: x before y on tie
                x_direction,
            ))

    # Try y-only slide.
    y_direction = Vec2i(0, desired_direction.y)
    y_tile = current_tile + y_direction

    if not is_tile_blocked(world, y_tile):
        tangent = slide_vector.y
        normal = slide_vector.x

        if passes_slide_threshold(tangent, normal, ratio):
            candidates.append((
                abs(tangent),
                1,  # y after x on tie
                y_direction,
            ))

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            -item[0],  # preserve strongest tangent component
            item[1],   # deterministic tie-break
        )
    )

    return candidates[0][2]


def passes_slide_threshold(tangent: int, normal: int, ratio) -> bool:
    num, den = ratio

    tangent_abs = abs(tangent)
    normal_abs = abs(normal)

    if tangent_abs == 0:
        return False

    return tangent_abs * den >= normal_abs * num


def is_tile_blocked(world, tile: Vec2i) -> bool:
    # Out of bounds is blocked.
    if tile.y < 0 or tile.y >= len(world.tilemap):
        return True

    if tile.x < 0 or tile.x >= len(world.tilemap[tile.y]):
        return True

    # Static collision from tilemap.
    return (tile.x, tile.y) in world.static_collision_tiles


def resolve_static_tile_movement(world, entity, start_cpos: Vec2i, delta: Vec2i):
    collision_result, resolved_cpos = trace_static_tile_path(
        world,
        entity,
        start_cpos,
        delta,
    )

    if collision_result == "slide":
        return resolve_slide_static_tile_movement(
            world,
            entity,
            start_cpos,
            delta,
        )

    return collision_result, resolved_cpos


def resolve_slide_static_tile_movement(world, entity, start_cpos: Vec2i, delta: Vec2i):
    ratio = get_movement_slide_ratio(world, entity)

    options = []

    # Try x-only movement.
    if delta.x != 0:
        x_delta = Vec2i(delta.x, 0)
        x_result, x_cpos = trace_static_tile_path(
            world,
            entity,
            start_cpos,
            x_delta,
        )

        if x_result == "allow":
            tangent = delta.x
            normal = delta.y

            if passes_slide_threshold(tangent, normal, ratio):
                options.append(("x", abs(tangent), x_cpos))

    # Try y-only movement.
    if delta.y != 0:
        y_delta = Vec2i(0, delta.y)
        y_result, y_cpos = trace_static_tile_path(
            world,
            entity,
            start_cpos,
            y_delta,
        )

        if y_result == "allow":
            tangent = delta.y
            normal = delta.x

            if passes_slide_threshold(tangent, normal, ratio):
                options.append(("y", abs(tangent), y_cpos))

    if not options:
        return "block", start_cpos

    # Pick the stronger valid slide component.
    # Tie-breaker is deterministic because "x" sorts before "y".
    options.sort(key=lambda item: (-item[1], item[0]))

    _, _, chosen_cpos = options[0]
    return "allow", chosen_cpos


def trace_static_tile_path(world, entity, start_cpos: Vec2i, delta: Vec2i):
    end_cpos = start_cpos + delta

    current_tile = tile_from_cpos(start_cpos)
    target_tile = tile_from_cpos(end_cpos)

    if current_tile == target_tile:
        collision_result = handle_static_tile_collision(
            world,
            entity,
            target_tile,
        )

        if collision_result != "allow":
            return collision_result, start_cpos

        return "allow", end_cpos

    dx = delta.x
    dy = delta.y

    step_x = sign(dx)
    step_y = sign(dy)

    abs_dx = abs(dx)
    abs_dy = abs(dy)

    # Distance along x/y, in canonical units, until the first tile boundary crossing.
    if step_x > 0:
        next_x_boundary = (current_tile.x + 1) * TILE_UNITS
        next_cross_x = next_x_boundary - start_cpos.x
    elif step_x < 0:
        next_x_boundary = current_tile.x * TILE_UNITS - 1
        next_cross_x = start_cpos.x - next_x_boundary
    else:
        next_cross_x = None

    if step_y > 0:
        next_y_boundary = (current_tile.y + 1) * TILE_UNITS
        next_cross_y = next_y_boundary - start_cpos.y
    elif step_y < 0:
        next_y_boundary = current_tile.y * TILE_UNITS - 1
        next_cross_y = start_cpos.y - next_y_boundary
    else:
        next_cross_y = None

    while current_tile != target_tile:
        if next_cross_x is None:
            step_axis = "y"
        elif next_cross_y is None:
            step_axis = "x"
        else:
            # Compare:
            #     next_cross_x / abs_dx
            # vs.
            #     next_cross_y / abs_dy
            #
            # without floats.
            left = next_cross_x * abs_dy
            right = next_cross_y * abs_dx

            if left < right:
                step_axis = "x"
            elif right < left:
                step_axis = "y"
            else:
                step_axis = "corner"

        if step_axis == "x":
            boundary_cpos = axis_cross_position(
                start_cpos,
                delta,
                next_cross_x,
                abs_dx,
            )

            current_tile = Vec2i(
                current_tile.x + step_x,
                current_tile.y,
            )

            collision_result = handle_static_tile_collision(
                world,
                entity,
                current_tile,
            )

            if collision_result != "allow":
                return collision_result, safe_before_x_cross(
                    boundary_cpos,
                    step_x,
                )

            next_cross_x += TILE_UNITS

        elif step_axis == "y":
            boundary_cpos = axis_cross_position(
                start_cpos,
                delta,
                next_cross_y,
                abs_dy,
            )

            current_tile = Vec2i(
                current_tile.x,
                current_tile.y + step_y,
            )

            collision_result = handle_static_tile_collision(
                world,
                entity,
                current_tile,
            )

            if collision_result != "allow":
                return collision_result, safe_before_y_cross(
                    boundary_cpos,
                    step_y,
                )

            next_cross_y += TILE_UNITS

        else:
            # Exact corner crossing. Be conservative and check the two side-adjacent
            # tiles as well as the diagonal tile.
            boundary_cpos = axis_cross_position(
                start_cpos,
                delta,
                next_cross_x,
                abs_dx,
            )

            side_x_tile = Vec2i(
                current_tile.x + step_x,
                current_tile.y,
            )

            side_y_tile = Vec2i(
                current_tile.x,
                current_tile.y + step_y,
            )

            diagonal_tile = Vec2i(
                current_tile.x + step_x,
                current_tile.y + step_y,
            )

            safe_cpos = safe_before_corner_cross(
                boundary_cpos,
                step_x,
                step_y,
            )

            collision_result = resolve_corner_crossing_collision(
                world,
                entity,
                side_x_tile,
                side_y_tile,
                diagonal_tile,
            )

            if collision_result != "allow":
                return collision_result, safe_cpos

            current_tile = diagonal_tile

            next_cross_x += TILE_UNITS
            next_cross_y += TILE_UNITS

    return "allow", end_cpos


def set_move_target(
    world,
    entity,
    target_tile: Vec2i,
    target_cpos=None,
    path_policy="traditional_click_move",
):
    if target_cpos is None:
        target_cpos = tile_center(target_tile)

    world.move_target[entity] = {
        "type": "target_tile",
        "target_tile": target_tile,
        "target_cpos": target_cpos,
        "path_policy": path_policy,
    }


def clear_move_target(world, entity):
    world.move_target.pop(entity, None)


def start_settle_to_grid_if_needed(world, entity, transform, motion_state) -> bool:
    # Only grid-positioned actors should settle.
    if transform.position_mode != "grid":
        return False

    # Only entities with locomotion are currently considered grid actors.
    if entity not in world.locomotion:
        return False

    target_tile = tile_from_cpos(transform.cpos)
    target_cpos = tile_center(target_tile)

    transform.tile = target_tile

    if is_at_cpos(transform.cpos, target_cpos):
        return False

    motion_state["controller"] = SettleToGridController(
        start=transform.cpos,
        end=target_cpos,
        progress=0,
        duration=4,
    )

    motion_state["influence_mode"] = "normal"

    return True


def get_corner_cutting_policy(world, entity):
    policy = world.movement_collision.get(entity, {})
    return policy.get("corner_cutting", "strict")


def resolve_corner_crossing_collision(
    world,
    entity,
    side_x_tile,
    side_y_tile,
    diagonal_tile,
):
    corner_policy = get_corner_cutting_policy(world, entity)

    if corner_policy == "strict":
        for candidate_tile in (side_x_tile, side_y_tile, diagonal_tile):
            collision_result = handle_static_tile_collision(
                world,
                entity,
                candidate_tile,
            )

            if collision_result != "allow":
                return collision_result

        return "allow"

    if corner_policy == "allow_if_one_side_open":
        diagonal_result = handle_static_tile_collision(
            world,
            entity,
            diagonal_tile,
        )

        if diagonal_result != "allow":
            return diagonal_result

        side_x_result = handle_static_tile_collision(
            world,
            entity,
            side_x_tile,
        )

        side_y_result = handle_static_tile_collision(
            world,
            entity,
            side_y_tile,
        )

        if side_x_result == "allow" or side_y_result == "allow":
            return "allow"

        # Both side-adjacent tiles are blocked. Return one of the blocked
        # results so the normal collision response can handle it.
        if side_x_result != "allow":
            return side_x_result

        return side_y_result

    raise ValueError(f"Unknown corner_cutting policy: {corner_policy}")


def handle_static_tile_collision(world, entity, next_tile):
    policy = world.movement_collision.get(entity)

    if policy is None:
        return "allow"

    behavior = policy.get("static_tiles", "allow")

    if not is_tile_blocked(world, next_tile):
        return "allow"

    return behavior


def get_path_policy(world, target):
    policy_name = target.get(
        "path_policy",
        "traditional_click_move",
    )

    return PATH_POLICIES[policy_name]


def get_path_follow_speed(locomotion):
    step_duration = max(1, locomotion["step_duration"])
    return TILE_UNITS // step_duration


def build_path_follow_nodes(world, entity, target):
    transform = world.transform[entity]
    locomotion = world.locomotion[entity]

    current_tile = get_navigation_start_tile(world, entity)
    target_tile = target["target_tile"]

    if current_tile == target_tile:
        return []

    path_policy = get_path_policy(world, target)

    path_tiles = find_static_tile_path_to_target(
        world,
        entity=entity,
        start_tile=current_tile,
        target_tile=target_tile,
        can_move_8way=locomotion.get("can_move_8way", True),
        max_expansions=path_policy["max_expansions"],
        max_path_length=path_policy["max_path_length"],
        target_snap_radius=path_policy["target_snap_radius"],
    )

    if path_tiles is None:
        return None

    smoothed_tiles = smooth_static_tile_path(
        world,
        entity,
        current_tile,
        path_tiles,
    )

    return path_tiles_to_cpos_nodes(smoothed_tiles)


def start_path_follow_controller(world, entity, target):
    nodes = build_path_follow_nodes(
        world,
        entity,
        target,
    )

    if nodes is None:
        clear_move_target(world, entity)
        return False

    if not nodes:
        clear_move_target(world, entity)
        return False

    locomotion = world.locomotion[entity]
    motion_state = world.motion_state[entity]

    motion_state["controller"] = PathFollowController(
        nodes=nodes,
        current_index=0,
        speed=get_path_follow_speed(locomotion),
        created_tick=world.tick,
        target_tile=target["target_tile"],
    )

    motion_state["controller_source"] = "move_target"

    return True


def should_refresh_path_follow_controller(world, entity, controller):
    target = world.move_target.get(entity)

    if target is None:
        return False

    if target["type"] != "target_tile":
        return False

    if target["target_tile"] == controller.target_tile:
        return False

    path_policy = get_path_policy(world, target)
    refresh_ticks = path_policy.get("refresh_ticks", 15)

    return world.tick - controller.created_tick >= refresh_ticks


def refresh_path_follow_controller_if_needed(world, entity, controller):
    if not should_refresh_path_follow_controller(
        world,
        entity,
        controller,
    ):
        return False

    target = world.move_target.get(entity)

    if target is None:
        return False

    return start_path_follow_controller(
        world,
        entity,
        target,
    )


def sample_controller_delta(controller, current_cpos):
    if hasattr(controller, "sample_delta_from"):
        return controller.sample_delta_from(current_cpos)

    return controller.sample_delta()


def is_path_follow_controller(controller):
    return isinstance(controller, PathFollowController)


def get_navigation_start_tile(world, entity):
    transform = world.transform[entity]

    return tile_from_cpos(transform.cpos)


def path_follow_movement_was_modified(
    controller,
    requested_cpos,
    resolved_cpos,
):
    if not is_path_follow_controller(controller):
        return False

    return resolved_cpos != requested_cpos


def movement_system(world):
    entities = (
        set(world.transform)
        & set(world.motion_state)
    )

    for entity in sorted(entities):
        motion_state = world.motion_state[entity]
        controller = motion_state["controller"]
        transform = world.transform[entity]

        base_delta = Vec2i(0, 0)

        if controller is not None:
            base_delta = sample_controller_delta(
                controller,
                transform.cpos,
            )

        influence_delta = world.influence_delta.get(entity, Vec2i(0, 0))
        delta = base_delta + influence_delta

        start_cpos = transform.cpos

        if delta.x != 0 or delta.y != 0:
            requested_cpos = start_cpos + delta
            collision_result, resolved_cpos = resolve_static_tile_movement(
                world,
                entity,
                start_cpos,
                delta,
            )

            if collision_result == "destroy":
                emit_event(
                    world,
                    "entity_destroyed_by_static_collision",
                    entity=entity,
                    cpos=transform.cpos,
                    tile=transform.tile,
                )

                world.entities.destroy(entity)
                continue

            if collision_result == "block":
                transform.cpos = resolved_cpos

                if transform.position_mode == "free":
                    transform.tile = tile_from_cpos(transform.cpos)

                motion_state["last_delta"] = transform.cpos - start_cpos

                if controller is not None:
                    clear_motion_controller(motion_state)

                    # Path-follow should replan from its actual cpos-derived tile.
                    # Do not immediately settle, because the move_target still exists.
                    if is_path_follow_controller(controller):
                        continue

                    start_settle_to_grid_if_needed(
                        world,
                        entity,
                        transform,
                        motion_state,
                    )

                continue

            transform.cpos = resolved_cpos

            if transform.position_mode == "free":
                transform.tile = tile_from_cpos(transform.cpos)

            motion_state["last_delta"] = transform.cpos - start_cpos

            if path_follow_movement_was_modified(
                    controller,
                    requested_cpos,
                    resolved_cpos,
            ):
                clear_motion_controller(motion_state)
                continue

        if controller is not None:
            controller.advance()

            if controller.finished():
                if hasattr(controller, "end"):
                    transform.cpos = controller.end

                transform.tile = tile_from_cpos(transform.cpos)

                clear_motion_controller(motion_state)
                start_settle_to_grid_if_needed(world, entity, transform, motion_state)



def skill_trigger_matches_intent(skill_def, intent):
    trigger_mode = skill_def["trigger_mode"]
    intent_type = intent["type"]

    if trigger_mode == "press":
        return intent_type == "skill_pressed"

    if trigger_mode == "held_repeat":
        return intent_type == "skill_held"

    return False


def entity_has_component(world, entity, component_name):
    component_map = getattr(world, component_name)
    return entity in component_map


def get_active_motion_tag(world, entity):
    motion_state = world.motion_state.get(entity)

    if motion_state is None:
        return None

    controller = motion_state.get("controller")

    if controller is None:
        return None

    return getattr(controller, "motion_tag", None)


def skill_allowed_by_motion_state(world, entity, skill_def):
    active_motion_tag = get_active_motion_tag(world, entity)

    if active_motion_tag is None:
        return True

    blocked_tags = skill_def["blocked_by_motion_tags"]

    return active_motion_tag not in blocked_tags


def entity_meets_skill_requirements(world, entity, skill_def):
    required_components = skill_def.get("required_components", set())

    for component_name in required_components:
        if not entity_has_component(world, entity, component_name):
            return False

    return True


def build_resolved_skill(world, caster, skill_def):
    resolved = dict(skill_def)

    if "params" in skill_def:
        resolved["params"] = dict(skill_def["params"])

    return resolved


def skill_intent_resolution_system(world, intents):
    world.resolved_skill_intents.clear()

    for entity, entity_intents in intents.items():
        for intent in entity_intents:
            if intent["type"] not in {
                "skill_pressed",
                "skill_held",
                "skill_released",
            }:
                continue

            slot = intent["slot"]
            skill_id = world.skills.get((entity, slot))

            if not skill_id:
                continue

            skill_def = SKILL_DEFS.get(skill_id)

            if skill_def is None:
                continue

            if not skill_trigger_matches_intent(skill_def, intent):
                continue

            cooldown_key = (entity, slot)
            ready_tick = world.skill_cooldown.get(cooldown_key, 0)

            if world.tick < ready_tick:
                continue

            if not entity_meets_skill_requirements(world, entity, skill_def):
                continue

            if not skill_allowed_by_motion_state(world, entity, skill_def):
                continue

            if not skill_allowed_by_action_state(world, entity, skill_def):
                continue

            resolved_skill = build_resolved_skill(world, entity, skill_def)
            handler = resolved_skill["handler"]

            world.resolved_skill_intents.append({
                "caster": entity,
                "slot": slot,
                "skill_id": skill_id,
                "skill_def": resolved_skill,
                "intent": intent,
                "handler": handler,
            })


def skill_execution_system(world):
    for resolved in sorted(
            world.resolved_skill_intents,
            key=lambda r: (r["caster"], str(r["slot"])),
    ):
        caster = resolved["caster"]
        slot = resolved["slot"]
        skill_def = resolved["skill_def"]
        intent = resolved["intent"]
        handler = resolved["handler"]

        executed = handler(world, caster, intent, skill_def)

        if executed:
            cooldown_ticks = skill_def.get("cooldown_ticks", 0)
            world.skill_cooldown[(caster, slot)] = world.tick + cooldown_ticks


def lifetime_system(world):
    for entity in sorted(list(world.lifetime)):
        lifetime = world.lifetime[entity]

        lifetime["remaining_ticks"] -= 1

        if lifetime["remaining_ticks"] <= 0:
            world.entities.destroy(entity)


def event_system(world):
    for event in world.events:
        event_type = event["type"]

        if event_type == "entity_destroyed_by_static_collision":
            start_camera_shake(
                world,
                duration_ticks=8,
                strength=2,
            )

    world.events.clear()


def sample_camera_shake(camera):
    ticks_left = camera["shake_ticks"]

    if ticks_left <= 0:
        return Vec2i(0, 0)

    duration = max(1, camera["shake_duration"])
    strength = camera["shake_strength"]

    # Fade out over time.
    current_strength = strength * ticks_left // duration

    # Deterministic small pattern. No randomness.
    pattern = [
        Vec2i(1, 0),
        Vec2i(-1, 0),
        Vec2i(0, 1),
        Vec2i(0, -1),
        Vec2i(1, 1),
        Vec2i(-1, -1),
        Vec2i(1, -1),
        Vec2i(-1, 1),
    ]

    index = ticks_left % len(pattern)
    direction = pattern[index]

    return Vec2i(
        direction.x * current_strength,
        direction.y * current_strength,
    )


def get_camera_target_cpos(world):
    camera = world.camera
    mode = camera["mode"]

    if mode == "follow":
        target = camera["target"]

        if target in world.transform:
            return world.transform[target].cpos

        return None

    if mode == "fixed":
        return camera["fixed_cpos"]

    return None


def set_camera_follow(world, target_entity, transition_mode="snap", transition_duration=None):
    camera = world.camera

    camera["mode"] = "follow"
    camera["target"] = target_entity
    camera["transition_mode"] = transition_mode

    if transition_mode == "smooth":
        if transition_duration is None:
            transition_duration = camera.get("default_transition_duration", 24)

        camera["transition_ticks"] = 0
        camera["transition_duration"] = transition_duration
        camera["transition_start_cpos"] = camera["current_cpos"]


def set_camera_fixed(world, fixed_cpos, transition_mode="snap", transition_duration=20):
    camera = world.camera

    camera["mode"] = "fixed"
    camera["fixed_cpos"] = fixed_cpos
    camera["transition_mode"] = transition_mode

    if transition_mode == "smooth":
        camera["transition_ticks"] = 0
        camera["transition_duration"] = transition_duration
        camera["transition_start_cpos"] = camera["current_cpos"]


def start_camera_shake(world, duration_ticks: int, strength: int):
    camera = world.camera

    camera["shake_ticks"] = duration_ticks
    camera["shake_duration"] = duration_ticks
    camera["shake_strength"] = strength


def camera_shake_system(world):
    camera = world.camera

    if camera["shake_ticks"] > 0:
        camera["shake_ticks"] -= 1

        if camera["shake_ticks"] <= 0:
            camera["shake_duration"] = 0
            camera["shake_strength"] = 0


def camera_update_system(world):
    camera = world.camera
    target_cpos = get_camera_target_cpos(world)

    if target_cpos is None:
        return

    if camera["current_cpos"] is not None:
        camera["prev_cpos"] = camera["current_cpos"]

    if camera["current_cpos"] is None:
        camera["current_cpos"] = target_cpos
        camera["prev_cpos"] = target_cpos
        return

    transition_mode = camera.get("transition_mode", "snap")

    if transition_mode == "snap":
        camera["current_cpos"] = target_cpos
        return

    if transition_mode == "smooth":
        start_cpos = camera.get("transition_start_cpos")

        if start_cpos is None:
            start_cpos = camera["current_cpos"]
            camera["transition_start_cpos"] = start_cpos

        duration = max(1, camera.get("transition_duration", 20))
        ticks = camera.get("transition_ticks", 0) + 1

        if ticks >= duration:
            camera["current_cpos"] = target_cpos
            camera["transition_mode"] = "snap"
            camera["transition_ticks"] = 0
            camera["transition_duration"] = 0
            camera["transition_start_cpos"] = None
            return

        camera["transition_ticks"] = ticks
        camera["current_cpos"] = lerp_cpos(
            start_cpos,
            target_cpos,
            ticks,
            duration,
        )


def camera_system(world, surface, render_alpha):
    camera = world.camera

    current_cpos = camera.get("current_cpos")
    prev_cpos = camera.get("prev_cpos", current_cpos)

    if current_cpos is None:
        return

    if prev_cpos is None:
        prev_cpos = current_cpos

    visual_camera_cpos = interp_cpos(
        prev_cpos,
        current_cpos,
        render_alpha,
    )

    target_screen_x, target_screen_y = cpos_to_screen(
        visual_camera_cpos,
        world.tile_size,
    )

    surface_center_x = surface.get_width() // 2
    surface_center_y = surface.get_height() // 2

    screen_offset = camera.get("screen_offset", Vec2i(0, 0))
    shake_offset = sample_camera_shake(camera)

    base_offset = (
        surface_center_x - target_screen_x + screen_offset.x,
        surface_center_y - target_screen_y + screen_offset.y,
    )

    world.camera_base_offset = base_offset

    world.camera_offset = (
        base_offset[0] + shake_offset.x,
        base_offset[1] + shake_offset.y,
    )


def render_tiles(world, surface, render_alpha=0.0):
    offset_x, offset_y = world.camera_offset

    for y, row in enumerate(world.tilemap):
        for x, tile in enumerate(row):
            screen_x, screen_y = iso_to_screen(x, y, world.tile_size)

            surface.blit(
                world.tile_images[tile],
                (screen_x + offset_x, screen_y + offset_y)
            )
            if (x, y) in world.static_collision_tiles:
                pygame.draw.circle(
                    surface,
                    "red",
                    (
                        screen_x + offset_x + world.tile_size // 2,
                        screen_y + offset_y + world.tile_size // 4,
                    ),
                    3,
                )


def get_sprite_offset(image, anchor):
    if anchor == "center":
        return Vec2i(-image.get_width() // 2, -image.get_height() // 2)
    if anchor == "bottom_center":
        return Vec2i(-image.get_width() // 2, -image.get_height())

    raise ValueError(f"Unknown anchor: {anchor}")


def facing_to_screen_delta(facing: Vec2i, tile_size: int, arrow_length: int) -> tuple[int, int]:
    start_cpos = Vec2i(0, 0)
    end_cpos = Vec2i(
        facing.x * TILE_UNITS,
        facing.y * TILE_UNITS,
    )

    start_x, start_y = cpos_to_screen(start_cpos, tile_size)
    end_x, end_y = cpos_to_screen(end_cpos, tile_size)

    dx = end_x - start_x
    dy = end_y - start_y

    max_abs = max(abs(dx), abs(dy))

    if max_abs == 0:
        return 0, 0

    return (
        dx * arrow_length // max_abs,
        dy * arrow_length // max_abs,
    )


def sprite_system(world, surface, render_alpha):
    draw_list = []
    debug_draw_list = []
    offset_x, offset_y = world.camera_offset

    for entity in world.sprite:
        if entity not in world.transform:
            continue

        transform = world.transform[entity]
        pos = interp_cpos(
            transform.prev_cpos,
            transform.cpos,
            render_alpha,
        )

        sprite = world.sprite[entity]

        screen_x, screen_y = cpos_to_screen(pos, world.tile_size)

        sprite_offset = get_sprite_offset(sprite["image"], sprite["anchor"])

        draw_list.append((
            screen_y + sprite.get("z", 0),
            sprite["image"],
            (
                screen_x + offset_x + sprite_offset.x,
                screen_y + offset_y + sprite_offset.y,
            ),
        ))

        debug_draw_list.append((entity, screen_x, screen_y))

    draw_list.sort(key=lambda x: x[0])

    for _, image, pos in draw_list:
        surface.blit(image, pos)

    # Debug overlay after sprites, so it stays visible.
    for entity, screen_x, screen_y in debug_draw_list:
        transform = world.transform[entity]
        committed_tile = transform.tile
        current_tile = tile_from_cpos(transform.cpos)
        committed_tile_center_cpos = tile_center(transform.tile)
        current_tile_center_cpos = tile_center(current_tile)
        committed_tile_screen_x, committed_tile_screen_y = cpos_to_screen(
            committed_tile_center_cpos,
            world.tile_size,
        )
        current_tile_screen_x, current_tile_screen_y = cpos_to_screen(
            current_tile_center_cpos,
            world.tile_size,
        )
        pygame.draw.circle(
            surface,
            "blue",
            (
                committed_tile_screen_x + offset_x,
                committed_tile_screen_y + offset_y,
            ),
            4,
        )
        pygame.draw.circle(
            surface,
            "black",
            (
                current_tile_screen_x + offset_x,
                current_tile_screen_y + offset_y,
            ),
            4,
        )
        pygame.draw.circle(
            surface,
            "red",
            (
                screen_x + offset_x,
                screen_y + offset_y,
            ),
            4,
        )

        if entity in world.facing:
            facing = world.facing[entity]

            arrow_dx, arrow_dy = facing_to_screen_delta(
                facing,
                world.tile_size,
                arrow_length=32,
            )

            pygame.draw.line(
                surface,
                "black",
                (
                    screen_x + offset_x,
                    screen_y + offset_y,
                ),
                (
                    screen_x + offset_x + arrow_dx,
                    screen_y + offset_y + arrow_dy,
                ),
                2,
            )