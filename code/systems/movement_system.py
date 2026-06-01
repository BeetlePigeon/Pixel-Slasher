from policies import PATH_POLICIES, DIRECTIONAL_MOVEMENT_MODE, SETTLE_LOCKED_TAG
from constants import MOVE_BUFFER_TICKS, TILE_UNITS
from .action_state_system import get_active_action_tags, tags_block_voluntary_movement
from .event_system import emit_event
from support import Vec2i
from utils.placement_utils import (
    is_dynamic_movement_placement_blocked,
    is_static_movement_placement_blocked,
)
from utils.perf_profiler import profiled
from utils.occupancy_utils import (
    rebuild_dynamic_occupancy,
    mark_dynamic_occupancy_dirty,
    is_tile_static_blocked,
    is_tile_blocked_for_movement,
    get_movement_blockers_on_tile,
    get_obstacle_footprint_tiles_for_origin_tile,
)
from motion_controllers import (
    GridMoveController,
    SettleToGridController,
    PathFollowController,
    DirectionalMoveController,
)
from utils.tile_vec_utils import (
    sign,
    tile_center,
    tile_from_cpos,
    normalize_vector_to_dir_scale,
)
from utils.path_utils import (
    find_static_tile_path_to_target,
    smooth_static_tile_path,
    path_tiles_to_cpos_nodes,
)


CORNER_CROSSING_TOLERANCE_CPOS = 32


def vec_is_nonzero(vec: Vec2i) -> bool:
    return vec.x != 0 or vec.y != 0


def is_at_cpos(a: Vec2i, b: Vec2i) -> bool:
    return a.x == b.x and a.y == b.y


def axis_cross_position(start: Vec2i, delta: Vec2i, axis_distance: int, axis_abs_delta: int) -> Vec2i:
    return Vec2i(
        start.x + delta.x * axis_distance // axis_abs_delta,
        start.y + delta.y * axis_distance // axis_abs_delta,
    )


def corner_boundary_cpos(current_tile: Vec2i, step_x: int, step_y: int) -> Vec2i:
    if step_x > 0:
        boundary_x = (current_tile.x + 1) * TILE_UNITS
    else:
        boundary_x = current_tile.x * TILE_UNITS

    if step_y > 0:
        boundary_y = (current_tile.y + 1) * TILE_UNITS
    else:
        boundary_y = current_tile.y * TILE_UNITS

    return Vec2i(boundary_x, boundary_y)


def near_corner_crossing(
    next_cross_x: int,
    next_cross_y: int,
    abs_dx: int,
    abs_dy: int,
) -> bool:
    # left/right are the existing integer cross-multiply comparison.
    left = next_cross_x * abs_dy
    right = next_cross_y * abs_dx

    # Scale tolerance into the same cross-multiplied space.
    tolerance = CORNER_CROSSING_TOLERANCE_CPOS * max(abs_dx, abs_dy)

    return abs(left - right) <= tolerance


def safe_before_boundary_coord(boundary_coord: int, step: int) -> int:
    if step > 0:
        return boundary_coord - 1

    if step < 0:
        return boundary_coord

    return boundary_coord


def safe_before_x_cross(boundary_cpos: Vec2i, step_x: int) -> Vec2i:
    return Vec2i(
        safe_before_boundary_coord(boundary_cpos.x, step_x),
        boundary_cpos.y,
    )


def safe_before_y_cross(boundary_cpos: Vec2i, step_y: int) -> Vec2i:
    return Vec2i(
        boundary_cpos.x,
        safe_before_boundary_coord(boundary_cpos.y, step_y),
    )


def safe_before_corner_cross(boundary_cpos: Vec2i, step_x: int, step_y: int) -> Vec2i:
    return Vec2i(
        safe_before_boundary_coord(boundary_cpos.x, step_x),
        safe_before_boundary_coord(boundary_cpos.y, step_y),
    )


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


def movement_start_suppressed_this_tick(world, entity):
    motion_state = world.motion_state.get(entity)

    if motion_state is None:
        return False

    return motion_state.get("suppress_move_start_tick") == world.tick


def entity_can_start_voluntary_movement(world, entity):
    active_action_tags = get_active_action_tags(world, entity)

    return not tags_block_voluntary_movement(active_action_tags)


@profiled("movement_arbiter")
def movement_arbiter_system(world):
    rebuild_dynamic_occupancy(world)

    active_directional_entities = {
        entity
        for entity, motion_state in world.motion_state.items()
        if isinstance(
            motion_state.get("controller"),
            DirectionalMoveController,
        )
    }

    entities = (
        (
            set(world.move_intent)
            | set(world.buffered_move_intent)
            | set(world.move_target)
            | active_directional_entities
        )
        & set(world.transform)
        & set(world.motion_state)
        & set(world.locomotion)
    )

    for entity in sorted(entities):
        motion_state = world.motion_state[entity]

        if not entity_can_start_voluntary_movement(world, entity):
            cancel_voluntary_movement(world, entity)
            continue

        controller = motion_state["controller"]

        if isinstance(controller, DirectionalMoveController):
            if entity in world.move_intent:
                cancel_move_target_for_directional_input(world, entity)

                updated = update_directional_continuous_controller(
                    world,
                    entity,
                    controller,
                    world.move_intent[entity],
                )
                if not updated:
                    stop_directional_continuous_controller(
                        world,
                        entity,
                    )
                else:
                    mark_dynamic_occupancy_dirty(world)
                    rebuild_dynamic_occupancy(world)

                continue

            # No directional input this tick: stop continuous movement
            # and let the grid actor settle.
            stop_directional_continuous_controller(
                world,
                entity,
            )
            continue

        if isinstance(controller, PathFollowController):
            # Manual directional movement should cancel active click path.
            if (
                    entity in world.move_intent
                    and motion_state.get("controller_source") == "move_target"
            ):
                cancel_move_target_for_directional_input(world, entity)

                clear_motion_controller(motion_state)

                mark_dynamic_occupancy_dirty(world)
                rebuild_dynamic_occupancy(world)

                request_settle_when_allowed(world, entity)
                start_requested_settle_if_allowed(world, entity)
            else:
                if recover_stale_path_follow_if_needed(
                        world,
                        entity,
                        controller,
                ):
                    continue

                if refresh_path_follow_controller_if_needed(
                        world,
                        entity,
                        controller,
                ):
                    continue

            continue

        if movement_start_suppressed_this_tick(world, entity):
            continue

        if motion_state["controller"] is not None:
            continue

        if entity in world.move_intent:
            cancel_move_target_for_directional_input(world, entity)

            desired_direction = world.move_intent[entity]

            if DIRECTIONAL_MOVEMENT_MODE == "continuous":
                start_directional_continuous_controller(
                    world,
                    entity,
                    desired_direction,
                )
                mark_dynamic_occupancy_dirty(world)
                rebuild_dynamic_occupancy(world)
                continue

            started = start_directional_movement_controller(
                world,
                entity,
                desired_direction,
                using_buffered_intent=False,
            )
            if not started:
                continue

            continue

        if entity in world.move_target:
            target = world.move_target[entity]

            if start_path_follow_controller(
                world,
                entity,
                target,
            ):
                continue

            continue

        # Buffered directional movement is useful for tile/node stepping,
        # but should not drive continuous movement after input release.
        if DIRECTIONAL_MOVEMENT_MODE == "continuous":
            clear_buffered_move_intent(world, entity)
            continue

        desired_direction = get_buffered_move_direction(world, entity)

        if desired_direction is None:
            continue

        started = start_directional_movement_controller(
            world,
            entity,
            desired_direction,
            using_buffered_intent=True,
        )

        if not started:
            clear_buffered_move_intent(world, entity)
            continue

        clear_buffered_move_intent(world, entity)


def clear_motion_controller(motion_state):
    motion_state["controller"] = None
    motion_state["influence_mode"] = "normal"
    motion_state.pop("controller_source", None)
    motion_state.pop("path_follow_progress", None)


def make_path_query_key(entity, start_tile, target_tile, path_policy_name):
    return (
        entity,
        start_tile.x,
        start_tile.y,
        target_tile.x,
        target_tile.y,
        path_policy_name,
    )


def get_active_controller(world, entity):
    motion_state = world.motion_state.get(entity)

    if motion_state is None:
        return None

    return motion_state.get("controller")


def path_query_failed_recently(world, query_key):
    retry_tick = world.failed_path_queries.get(query_key)

    if retry_tick is None:
        return False

    if world.tick < retry_tick:
        return True

    world.failed_path_queries.pop(query_key, None)
    return False


def remember_failed_path_query(world, query_key, retry_ticks):
    world.failed_path_queries[query_key] = world.tick + retry_ticks


def clear_failed_path_query(world, query_key):
    world.failed_path_queries.pop(query_key, None)


def clear_failed_path_queries_for_entity(world, entity):
    for query_key in list(world.failed_path_queries):
        if query_key[0] == entity:
            world.failed_path_queries.pop(query_key, None)


def get_path_policy_name(target):
    return target.get(
        "path_policy",
        "actor_move",
    )


def get_path_policy(world, target):
    return PATH_POLICIES[
        get_path_policy_name(target)
    ]


def get_path_build_cooldown_ticks(world, target):
    path_policy = get_path_policy(
        world,
        target,
    )

    return path_policy.get(
        "path_build_cooldown_ticks",
        10,
    )


def get_entity_path_build_state(world, entity):
    return world.path_build_state.setdefault(
        entity,
        {
            "next_allowed_tick": 0,
            "last_attempt_tick": None,
        },
    )


def entity_can_attempt_path_build(world, entity, target):
    path_build_state = get_entity_path_build_state(
        world,
        entity,
    )

    return (
        world.tick
        >= path_build_state.get("next_allowed_tick", 0)
    )


def mark_path_build_attempted(world, entity, target):
    cooldown_ticks = get_path_build_cooldown_ticks(
        world,
        target,
    )

    path_build_state = get_entity_path_build_state(
        world,
        entity,
    )

    path_build_state["last_attempt_tick"] = world.tick
    path_build_state["next_allowed_tick"] = (
        world.tick
        + cooldown_ticks
    )


def clear_path_build_state(world, entity):
    world.path_build_state.pop(entity, None)


def cpos_distance_sq(a: Vec2i, b: Vec2i) -> int:
    dx = a.x - b.x
    dy = a.y - b.y

    return dx * dx + dy * dy


def get_path_follow_current_node(controller):
    if controller.current_index >= len(controller.nodes):
        return None

    return controller.nodes[controller.current_index]


def initialize_path_follow_progress(world, entity, controller):
    motion_state = world.motion_state[entity]
    transform = world.transform[entity]

    current_node = get_path_follow_current_node(controller)

    if current_node is None:
        distance_sq = 0
    else:
        distance_sq = cpos_distance_sq(
            transform.cpos,
            current_node,
        )

    motion_state["path_follow_progress"] = {
        "last_progress_tick": world.tick,
        "last_index": controller.current_index,
        "last_distance_sq": distance_sq,
    }


def update_path_follow_progress(world, entity, controller):
    motion_state = world.motion_state[entity]
    transform = world.transform[entity]
    target = world.move_target.get(entity)

    if target is None:
        return

    path_policy = get_path_policy(world, target)

    progress_min_cpos = path_policy.get(
        "progress_min_cpos",
        128,
    )

    progress_min_sq = progress_min_cpos * progress_min_cpos

    progress = motion_state.get("path_follow_progress")

    if progress is None:
        initialize_path_follow_progress(
            world,
            entity,
            controller,
        )
        return

    current_node = get_path_follow_current_node(controller)

    if current_node is None:
        progress["last_progress_tick"] = world.tick
        progress["last_index"] = controller.current_index
        progress["last_distance_sq"] = 0
        return

    distance_sq = cpos_distance_sq(
        transform.cpos,
        current_node,
    )

    index_advanced = controller.current_index > progress["last_index"]

    distance_decreased = (
        distance_sq + progress_min_sq
        < progress["last_distance_sq"]
    )

    if index_advanced or distance_decreased:
        progress["last_progress_tick"] = world.tick
        progress["last_index"] = controller.current_index
        progress["last_distance_sq"] = distance_sq


def abandon_move_target(world, entity):
    motion_state = world.motion_state.get(entity)

    clear_move_target(world, entity)

    if motion_state is None:
        return

    clear_motion_controller(motion_state)

    request_settle_when_allowed(world, entity)
    start_requested_settle_if_allowed(world, entity)


def path_follow_exceeded_lifetime(world, target, path_policy):
    created_tick = target.get(
        "created_tick",
        world.tick,
    )

    max_follow_ticks = path_policy.get("max_follow_ticks")

    if max_follow_ticks is None:
        return False

    return world.tick - created_tick >= max_follow_ticks


def path_follow_is_stalled(world, entity, path_policy):
    progress = world.motion_state[entity].get("path_follow_progress")

    if progress is None:
        return False

    stall_ticks = path_policy.get(
        "stall_ticks_before_repath",
        10,
    )

    return (
        world.tick - progress["last_progress_tick"]
        >= stall_ticks
    )


def recover_stale_path_follow_if_needed(world, entity, controller):
    target = world.move_target.get(entity)

    if target is None:
        return False

    if target["type"] != "target_tile":
        return False

    path_policy = get_path_policy(world, target)

    if path_follow_exceeded_lifetime(
        world,
        target,
        path_policy,
    ):
        abandon_move_target(world, entity)
        return True

    if not path_follow_is_stalled(
        world,
        entity,
        path_policy,
    ):
        return False

    if world.tick < target.get("next_repath_tick", world.tick):
        return False

    if not entity_can_attempt_path_build(
            world,
            entity,
            target,
    ):
        return False

    max_repath_attempts = path_policy.get(
        "max_repath_attempts",
        4,
    )

    if target.get("repath_attempts", 0) >= max_repath_attempts:
        abandon_move_target(world, entity)
        return True

    target["repath_attempts"] = target.get("repath_attempts", 0) + 1
    target["next_repath_tick"] = (
        world.tick
        + path_policy.get("repath_cooldown_ticks", 12)
    )

    mark_path_build_attempted(
        world,
        entity,
        target,
    )

    motion_state = world.motion_state[entity]

    clear_motion_controller(motion_state)

    request_settle_when_allowed(world, entity)
    start_requested_settle_if_allowed(world, entity)

    return True


def cancel_active_voluntary_motion_if_needed(world, entity):
    motion_state = world.motion_state.get(entity)

    if motion_state is None:
        return

    controller = motion_state.get("controller")

    if controller is None:
        return

    controller_source = motion_state.get("controller_source")

    if (
        isinstance(controller, PathFollowController)
        and controller_source == "move_target"
    ):
        transform = world.transform.get(entity)

        clear_motion_controller(motion_state)

        if transform is not None:
            request_settle_when_allowed(world, entity)
            start_requested_settle_if_allowed(world, entity)

        return

    if (
        isinstance(controller, DirectionalMoveController)
        and controller_source in {"move_intent", "buffered_move"}
    ):
        transform = world.transform.get(entity)

        clear_motion_controller(motion_state)

        if transform is not None:
            request_settle_when_allowed(world, entity)
            start_requested_settle_if_allowed(world, entity)

        return


def cancel_voluntary_movement(world, entity):
    world.move_intent.pop(entity, None)
    clear_buffered_move_intent(world, entity)
    clear_move_target(world, entity)
    cancel_active_voluntary_motion_if_needed(world, entity)


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


def resolve_grid_move_direction_from_tile(
    world,
    entity,
    current_tile: Vec2i,
    desired_direction: Vec2i,
    slide_vector=None,
    slide_context="grid",
):
    desired_tile = current_tile + desired_direction

    if slide_vector is None:
        slide_vector = desired_direction

    # If desired movement is open, take it directly.
    if not is_tile_blocked(
            world,
            desired_tile,
            mover_entity=entity,
    ):
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

    if not is_tile_blocked(
            world,
            x_tile,
            mover_entity=entity,
    ):
        tangent = slide_vector.x
        normal = slide_vector.y

        if passes_slide_threshold(tangent, normal, ratio):
            candidates.append((
                abs(tangent),
                0,
                x_direction,
            ))

    # Try y-only slide.
    y_direction = Vec2i(0, desired_direction.y)
    y_tile = current_tile + y_direction

    if not is_tile_blocked(
            world,
            y_tile,
            mover_entity=entity,
    ):
        tangent = slide_vector.y
        normal = slide_vector.x

        if passes_slide_threshold(tangent, normal, ratio):
            candidates.append((
                abs(tangent),
                1,
                y_direction,
            ))

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            -item[0],
            item[1],
        )
    )

    return candidates[0][2]


def resolve_grid_move_direction(
    world,
    entity,
    desired_direction: Vec2i,
    slide_vector=None,
    slide_context="grid",
):
    transform = world.transform[entity]

    return resolve_grid_move_direction_from_tile(
        world,
        entity,
        transform.tile,
        desired_direction,
        slide_vector=slide_vector,
        slide_context=slide_context,
    )


def passes_slide_threshold(tangent: int, normal: int, ratio) -> bool:
    num, den = ratio

    tangent_abs = abs(tangent)
    normal_abs = abs(normal)

    if tangent_abs == 0:
        return False

    return tangent_abs * den >= normal_abs * num


def is_tile_blocked(world, tile: Vec2i, mover_entity=None) -> bool:
    if mover_entity is None:
        return is_tile_blocked_for_movement(
            world,
            tile,
            mover_entity=None,
        )

    return handle_movement_tile_collision(
        world,
        mover_entity,
        tile,
    ) != "allow"


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
        collision_result = handle_movement_tile_collision(
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
        next_x_boundary = current_tile.x * TILE_UNITS
        next_cross_x = start_cpos.x - next_x_boundary
    else:
        next_cross_x = None

    if step_y > 0:
        next_y_boundary = (current_tile.y + 1) * TILE_UNITS
        next_cross_y = next_y_boundary - start_cpos.y
    elif step_y < 0:
        next_y_boundary = current_tile.y * TILE_UNITS
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

            if near_corner_crossing(
                    next_cross_x,
                    next_cross_y,
                    abs_dx,
                    abs_dy,
            ):
                step_axis = "corner"
            elif left < right:
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

            collision_result = handle_movement_tile_collision(
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

            collision_result = handle_movement_tile_collision(
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
            # Exact or near corner crossing.
            boundary_cpos = corner_boundary_cpos(
                current_tile,
                step_x,
                step_y,
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
    path_policy="actor_move",
):
    if target_cpos is None:
        target_cpos = tile_center(target_tile)

    existing_target = world.move_target.get(entity)

    if existing_target is None:
        created_tick = world.tick
        repath_attempts = 0
        next_repath_tick = world.tick
    else:
        created_tick = existing_target.get(
            "created_tick",
            world.tick,
        )

        repath_attempts = existing_target.get(
            "repath_attempts",
            0,
        )

        next_repath_tick = existing_target.get(
            "next_repath_tick",
            world.tick,
        )

    world.move_target[entity] = {
        "type": "target_tile",
        "target_tile": target_tile,
        "target_cpos": target_cpos,
        "path_policy": path_policy,
        "created_tick": created_tick,
        "repath_attempts": repath_attempts,
        "next_repath_tick": next_repath_tick,
    }


def clear_move_target(world, entity):
    world.move_target.pop(entity, None)
    clear_path_build_state(world, entity)


def cancel_move_target_for_directional_input(world, entity):
    clear_move_target(world, entity)
    clear_failed_path_queries_for_entity(world, entity)


def mark_settle_after_influence_if_needed(
    transform,
    motion_state,
    influence_active,
):
    if not influence_active:
        return

    if transform.position_mode != "grid":
        return

    motion_state["settle_after_influence"] = True


def settle_after_influence_if_needed(world, entity, transform, motion_state):
    if not motion_state.get("settle_after_influence", False):
        return False

    if motion_state.get("controller") is not None:
        return False

    motion_state.pop("settle_after_influence", None)

    request_settle_when_allowed(world, entity)

    return start_requested_settle_if_allowed(
        world,
        entity,
    )


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
        motion_state.pop("settle_when_allowed", None)
        return False

    if not entity_can_auto_settle(world, entity):
        motion_state["settle_when_allowed"] = True
        return False

    motion_state["controller"] = SettleToGridController(
        start=transform.cpos,
        end=target_cpos,
        progress=0,
        duration=3,
    )

    motion_state["influence_mode"] = "normal"
    motion_state["controller_source"] = "settle"

    return True


def entity_can_auto_settle(world, entity):
    active_tags = get_active_action_tags(world, entity)

    return SETTLE_LOCKED_TAG not in active_tags


def request_settle_when_allowed(world, entity):
    transform = world.transform.get(entity)
    motion_state = world.motion_state.get(entity)

    if transform is None or motion_state is None:
        return False

    if transform.position_mode != "grid":
        return False

    if entity not in world.locomotion:
        return False

    target_tile = tile_from_cpos(transform.cpos)
    target_cpos = tile_center(target_tile)

    transform.tile = target_tile

    if is_at_cpos(transform.cpos, target_cpos):
        motion_state.pop("settle_when_allowed", None)
        return False

    motion_state["settle_when_allowed"] = True
    return True


def start_requested_settle_if_allowed(world, entity):
    transform = world.transform.get(entity)
    motion_state = world.motion_state.get(entity)

    if transform is None or motion_state is None:
        return False

    if not motion_state.get("settle_when_allowed", False):
        return False

    if motion_state.get("controller") is not None:
        return False

    if not entity_can_auto_settle(world, entity):
        return False

    started = start_settle_to_grid_if_needed(
        world,
        entity,
        transform,
        motion_state,
    )

    if started:
        motion_state.pop("settle_when_allowed", None)

    return started


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

    if corner_policy == "allow":
        diagonal_result = handle_movement_tile_collision(
            world,
            entity,
            diagonal_tile,
        )

        return diagonal_result

    if corner_policy == "strict":
        for candidate_tile in (side_x_tile, side_y_tile, diagonal_tile):
            collision_result = handle_movement_tile_collision(
                world,
                entity,
                candidate_tile,
            )

            if collision_result != "allow":
                return collision_result

        return "allow"

    if corner_policy == "allow_if_one_side_open":
        diagonal_result = handle_movement_tile_collision(
            world,
            entity,
            diagonal_tile,
        )

        if diagonal_result != "allow":
            return diagonal_result

        side_x_result = handle_movement_tile_collision(
            world,
            entity,
            side_x_tile,
        )

        side_y_result = handle_movement_tile_collision(
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

    if behavior == "allow":
        return "allow"

    if is_static_movement_placement_blocked(
        world,
        entity,
        next_tile,
    ):
        return behavior

    return "allow"


def handle_dynamic_movement_collision(world, entity, next_tile):
    policy = world.movement_collision.get(entity)

    if policy is None:
        return "allow"

    behavior = policy.get(
        "dynamic_blockers",
        "allow",
    )

    if behavior == "allow":
        return "allow"

    if is_dynamic_movement_placement_blocked(
        world,
        entity,
        next_tile,
    ):
        return behavior

    return "allow"


def handle_movement_tile_collision(world, entity, next_tile):
    # next_tile is the proposed logical-center tile.
    #
    # Movement footprints are center + wings:
    # - static collision is controlled by STATIC_WING_COLLISION_POLICY
    # - dynamic collision blocks center/body overlap
    # - dynamic wing/wing overlap is allowed

    static_result = handle_static_tile_collision(
        world,
        entity,
        next_tile,
    )

    if static_result != "allow":
        return static_result

    dynamic_result = handle_dynamic_movement_collision(
        world,
        entity,
        next_tile,
    )

    if dynamic_result != "allow":
        return dynamic_result

    return "allow"


def get_path_policy(world, target):
    policy_name = target.get(
        "path_policy",
        "traditional_click_move",
    )

    return PATH_POLICIES[policy_name]


def get_path_follow_speed(locomotion):
    step_duration = max(1, locomotion["step_duration"])
    return TILE_UNITS // step_duration


def get_greedy_fallback_direction(current_tile, target_tile):
    return Vec2i(
        sign(target_tile.x - current_tile.x),
        sign(target_tile.y - current_tile.y),
    )


def build_direct_fallback_nodes(world, entity, target, path_policy):
    if not path_policy.get("direct_fallback_on_fail", False):
        return None

    current_tile = get_navigation_start_tile(world, entity)
    target_tile = target["target_tile"]

    if current_tile == target_tile:
        return None

    max_steps = path_policy.get(
        "direct_fallback_max_tiles",
        path_policy.get("max_path_length", 30),
    )

    min_steps = path_policy.get("direct_fallback_min_tiles", 1)

    fallback_tiles = []
    visited_tiles = {current_tile}

    for _ in range(max_steps):
        desired_direction = get_greedy_fallback_direction(
            current_tile,
            target_tile,
        )

        if desired_direction.x == 0 and desired_direction.y == 0:
            break

        # Use the full target vector as the slide preference.
        # This makes a failed diagonal target choose the stronger useful tangent
        # instead of aiming into the wall face.
        slide_vector = Vec2i(
            target_tile.x - current_tile.x,
            target_tile.y - current_tile.y,
        )

        resolved_direction = resolve_grid_move_direction(
            world,
            entity,
            desired_direction,
            slide_vector=slide_vector,
            slide_context="mouse",
        )

        if resolved_direction is None:
            break

        next_tile = current_tile + resolved_direction

        if next_tile in visited_tiles:
            break

        # Validate the actual center-to-center segment that PathFollowController
        # will attempt. This prevents fallback nodes that immediately snag on DDA.
        start_cpos = tile_center(current_tile)
        end_cpos = tile_center(next_tile)
        delta = end_cpos - start_cpos

        collision_result, _ = trace_static_tile_path(
            world,
            entity,
            start_cpos,
            delta,
        )

        if collision_result != "allow":
            break

        fallback_tiles.append(next_tile)
        visited_tiles.add(next_tile)
        current_tile = next_tile

    if len(fallback_tiles) < min_steps:
        return None

    return path_tiles_to_cpos_nodes(fallback_tiles)


@profiled("path.build")
def build_path_follow_nodes(world, entity, target):
    transform = world.transform[entity]
    locomotion = world.locomotion[entity]

    current_tile = get_navigation_start_tile(world, entity)
    target_tile = target["target_tile"]

    if current_tile == target_tile:
        return []

    path_policy_name = get_path_policy_name(target)
    path_policy = get_path_policy(world, target)

    query_key = make_path_query_key(
        entity,
        current_tile,
        target_tile,
        path_policy_name,
    )

    if path_query_failed_recently(world, query_key):
        return build_direct_fallback_nodes(
            world,
            entity,
            target,
            path_policy,
        )

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
        remember_failed_path_query(
            world,
            query_key,
            path_policy.get("failed_retry_ticks", 30),
        )

        return build_direct_fallback_nodes(
            world,
            entity,
            target,
            path_policy,
        )

    clear_failed_path_query(world, query_key)

    smooth_max = path_policy.get("smooth_max_path_length", 20)

    if smooth_max is not None and len(path_tiles) > smooth_max:
        smoothed_tiles = path_tiles
    else:
        smoothed_tiles = smooth_static_tile_path(
            world,
            entity,
            current_tile,
            path_tiles,
        )

    return path_tiles_to_cpos_nodes(smoothed_tiles)


def start_directional_node_follow_controller(
    world,
    entity,
    desired_direction,
    using_buffered_intent=False,
):
    transform = world.transform[entity]
    locomotion = world.locomotion[entity]
    motion_state = world.motion_state[entity]

    if not locomotion["can_move_8way"]:
        if desired_direction.x != 0 and desired_direction.y != 0:
            return False

    current_tile = tile_from_cpos(transform.cpos)

    resolved_direction = resolve_grid_move_direction_from_tile(
        world,
        entity,
        current_tile,
        desired_direction,
        slide_vector=desired_direction,
        slide_context="grid",
    )

    if resolved_direction is None:
        return False

    target_tile = current_tile + resolved_direction
    target_cpos = tile_center(target_tile)

    motion_state["controller"] = PathFollowController(
        nodes=[target_cpos],
        current_index=0,
        speed=get_path_follow_speed(locomotion),
        created_tick=world.tick,
        target_tile=target_tile,
    )

    if using_buffered_intent:
        motion_state["controller_source"] = "buffered_move"
    else:
        motion_state["controller_source"] = "move_intent"

    if entity in world.facing:
        world.facing[entity] = resolved_direction

    rebuild_dynamic_occupancy(world)

    return True


def start_directional_grid_move_controller(
    world,
    entity,
    desired_direction,
    using_buffered_intent=False,
):
    transform = world.transform[entity]
    locomotion = world.locomotion[entity]
    motion_state = world.motion_state[entity]

    if not locomotion["can_move_8way"]:
        if desired_direction.x != 0 and desired_direction.y != 0:
            return False

    resolved_direction = resolve_grid_move_direction(
        world,
        entity,
        desired_direction,
        slide_vector=None,
        slide_context="grid",
    )

    if resolved_direction is None:
        return False

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

    rebuild_dynamic_occupancy(world)

    return True


def start_directional_movement_controller(
    world,
    entity,
    desired_direction,
    using_buffered_intent=False,
):
    if DIRECTIONAL_MOVEMENT_MODE == "node_follow":
        return start_directional_node_follow_controller(
            world,
            entity,
            desired_direction,
            using_buffered_intent=using_buffered_intent,
        )

    if DIRECTIONAL_MOVEMENT_MODE == "grid_move":
        return start_directional_grid_move_controller(
            world,
            entity,
            desired_direction,
            using_buffered_intent=using_buffered_intent,
        )

    raise ValueError(
        f"Unknown DIRECTIONAL_MOVEMENT_MODE: {DIRECTIONAL_MOVEMENT_MODE}"
    )


def is_directional_move_controller(controller):
    return isinstance(controller, DirectionalMoveController)


def start_directional_continuous_controller(
    world,
    entity,
    desired_direction,
):
    transform = world.transform[entity]
    locomotion = world.locomotion[entity]
    motion_state = world.motion_state[entity]

    if not locomotion["can_move_8way"]:
        if desired_direction.x != 0 and desired_direction.y != 0:
            return False

    aim_vector = normalize_vector_to_dir_scale(desired_direction)

    if aim_vector is None:
        return False

    if entity == getattr(world, "player", None):
        print(
            "[move_actual_start] "
            f"tick={world.tick} "
            f"entity={entity} "
            f"cpos={format_debug_vec(transform.cpos)} "
            f"tile={format_debug_tile(tile_from_cpos(transform.cpos))} "
            f"desired_direction={format_debug_vec(desired_direction)} "
            f"aim_vector={format_debug_vec(aim_vector)}"
        )

    motion_state["controller"] = DirectionalMoveController(
        aim_vector=aim_vector,
        raw_direction=desired_direction,
        speed=get_path_follow_speed(locomotion),
    )

    motion_state["controller_source"] = "move_intent"

    if entity in world.facing:
        world.facing[entity] = desired_direction

    return True


def update_directional_continuous_controller(
    world,
    entity,
    controller,
    desired_direction,
):
    locomotion = world.locomotion[entity]

    if not locomotion["can_move_8way"]:
        if desired_direction.x != 0 and desired_direction.y != 0:
            return False

    aim_vector = normalize_vector_to_dir_scale(desired_direction)

    if aim_vector is None:
        return False

    if entity == getattr(world, "player", None):
        transform = world.transform[entity]

        print(
            "[move_actual_update] "
            f"tick={world.tick} "
            f"entity={entity} "
            f"cpos={format_debug_vec(transform.cpos)} "
            f"tile={format_debug_tile(tile_from_cpos(transform.cpos))} "
            f"desired_direction={format_debug_vec(desired_direction)} "
            f"old_raw_direction={format_debug_vec(getattr(controller, 'raw_direction', None))} "
            f"old_aim_vector={format_debug_vec(getattr(controller, 'aim_vector', None))} "
            f"new_aim_vector={format_debug_vec(aim_vector)}"
        )

    controller.aim_vector = aim_vector
    controller.raw_direction = desired_direction
    controller.speed = get_path_follow_speed(locomotion)

    if entity in world.facing:
        world.facing[entity] = desired_direction

    return True


def stop_directional_continuous_controller(world, entity):
    motion_state = world.motion_state[entity]

    clear_motion_controller(motion_state)

    mark_dynamic_occupancy_dirty(world)
    rebuild_dynamic_occupancy(world)

    request_settle_when_allowed(world, entity)
    start_requested_settle_if_allowed(world, entity)


def install_path_follow_controller(world, entity, target, nodes):
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

    initialize_path_follow_progress(
        world,
        entity,
        motion_state["controller"],
    )

    rebuild_dynamic_occupancy(world)

    return True


def start_path_follow_controller(world, entity, target):
    if not entity_can_attempt_path_build(
        world,
        entity,
        target,
    ):
        return False

    mark_path_build_attempted(
        world,
        entity,
        target,
    )

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

    return install_path_follow_controller(
        world,
        entity,
        target,
        nodes,
    )


def discard_pending_controller_advance(controller):
    if hasattr(controller, "_pending_index"):
        delattr(controller, "_pending_index")


def should_refresh_path_follow_controller(world, entity, controller):
    target = world.move_target.get(entity)

    if target is None:
        return False

    if target["type"] != "target_tile":
        return False

    return entity_can_attempt_path_build(
        world,
        entity,
        target,
    )


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

    mark_path_build_attempted(
        world,
        entity,
        target,
    )

    nodes = build_path_follow_nodes(
        world,
        entity,
        target,
    )

    # Refresh is non-destructive. If the current world state cannot
    # produce a usable replacement path, keep following the existing
    # controller and let the normal movement pipeline continue.
    if nodes is None:
        return False

    if not nodes:
        return False

    return install_path_follow_controller(
        world,
        entity,
        target,
        nodes,
    )


def sample_controller_delta(controller, current_cpos):
    if hasattr(controller, "sample_delta_from"):
        return controller.sample_delta_from(current_cpos)

    return controller.sample_delta()


MOVEMENT_DIAGNOSTIC_DIRECTIONS = (
    ("N", Vec2i(0, -1)),
    ("NE", Vec2i(1, -1)),
    ("E", Vec2i(1, 0)),
    ("SE", Vec2i(1, 1)),
    ("S", Vec2i(0, 1)),
    ("SW", Vec2i(-1, 1)),
    ("W", Vec2i(-1, 0)),
    ("NW", Vec2i(-1, -1)),
)


def format_debug_vec(value):
    if value is None:
        return "None"

    return f"({value.x},{value.y})"


def format_debug_tile(value):
    return format_debug_vec(value)


def diagnose_trace_static_tile_path(world, entity, start_cpos: Vec2i, delta: Vec2i):
    steps = []

    def add_step(step):
        steps.append(step)

    end_cpos = start_cpos + delta
    current_tile = tile_from_cpos(start_cpos)
    target_tile = tile_from_cpos(end_cpos)

    add_step({
        "type": "start",
        "start_cpos": start_cpos,
        "end_cpos": end_cpos,
        "start_tile": current_tile,
        "target_tile": target_tile,
        "delta": delta,
    })

    if current_tile == target_tile:
        collision_result = handle_movement_tile_collision(
            world,
            entity,
            target_tile,
        )

        add_step({
            "type": "same_tile",
            "tile": target_tile,
            "result": collision_result,
        })

        if collision_result != "allow":
            return collision_result, start_cpos, steps

        return "allow", end_cpos, steps

    dx = delta.x
    dy = delta.y

    step_x = sign(dx)
    step_y = sign(dy)

    abs_dx = abs(dx)
    abs_dy = abs(dy)

    if step_x > 0:
        next_x_boundary = (current_tile.x + 1) * TILE_UNITS
        next_cross_x = next_x_boundary - start_cpos.x
    elif step_x < 0:
        next_x_boundary = current_tile.x * TILE_UNITS
        next_cross_x = start_cpos.x - next_x_boundary
    else:
        next_x_boundary = None
        next_cross_x = None

    if step_y > 0:
        next_y_boundary = (current_tile.y + 1) * TILE_UNITS
        next_cross_y = next_y_boundary - start_cpos.y
    elif step_y < 0:
        next_y_boundary = current_tile.y * TILE_UNITS
        next_cross_y = start_cpos.y - next_y_boundary
    else:
        next_y_boundary = None
        next_cross_y = None

    safety_counter = 0

    while current_tile != target_tile:
        safety_counter += 1

        if safety_counter > 32:
            add_step({
                "type": "safety_break",
                "current_tile": current_tile,
                "target_tile": target_tile,
            })

            return "block", start_cpos, steps

        if next_cross_x is None:
            step_axis = "y"
        elif next_cross_y is None:
            step_axis = "x"
        else:
            left = next_cross_x * abs_dy
            right = next_cross_y * abs_dx

            if left < right:
                step_axis = "x"
            elif right < left:
                step_axis = "y"
            else:
                step_axis = "corner"

        from_tile = current_tile

        if step_axis == "x":
            boundary_cpos = axis_cross_position(
                start_cpos,
                delta,
                next_cross_x,
                abs_dx,
            )

            candidate_tile = Vec2i(
                current_tile.x + step_x,
                current_tile.y,
            )

            collision_result = handle_movement_tile_collision(
                world,
                entity,
                candidate_tile,
            )

            safe_cpos = safe_before_x_cross(
                boundary_cpos,
                step_x,
            )

            add_step({
                "type": "x",
                "from_tile": from_tile,
                "candidate_tile": candidate_tile,
                "boundary_cpos": boundary_cpos,
                "safe_cpos": safe_cpos,
                "result": collision_result,
            })

            if collision_result != "allow":
                return collision_result, safe_cpos, steps

            current_tile = candidate_tile
            next_cross_x += TILE_UNITS

        elif step_axis == "y":
            boundary_cpos = axis_cross_position(
                start_cpos,
                delta,
                next_cross_y,
                abs_dy,
            )

            candidate_tile = Vec2i(
                current_tile.x,
                current_tile.y + step_y,
            )

            collision_result = handle_movement_tile_collision(
                world,
                entity,
                candidate_tile,
            )

            safe_cpos = safe_before_y_cross(
                boundary_cpos,
                step_y,
            )

            add_step({
                "type": "y",
                "from_tile": from_tile,
                "candidate_tile": candidate_tile,
                "boundary_cpos": boundary_cpos,
                "safe_cpos": safe_cpos,
                "result": collision_result,
            })

            if collision_result != "allow":
                return collision_result, safe_cpos, steps

            current_tile = candidate_tile
            next_cross_y += TILE_UNITS

        else:
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

            side_x_result = handle_movement_tile_collision(
                world,
                entity,
                side_x_tile,
            )

            side_y_result = handle_movement_tile_collision(
                world,
                entity,
                side_y_tile,
            )

            diagonal_result = handle_movement_tile_collision(
                world,
                entity,
                diagonal_tile,
            )

            collision_result = resolve_corner_crossing_collision(
                world,
                entity,
                side_x_tile,
                side_y_tile,
                diagonal_tile,
            )

            safe_cpos = safe_before_corner_cross(
                boundary_cpos,
                step_x,
                step_y,
            )

            add_step({
                "type": "corner",
                "from_tile": from_tile,
                "side_x_tile": side_x_tile,
                "side_x_result": side_x_result,
                "side_y_tile": side_y_tile,
                "side_y_result": side_y_result,
                "diagonal_tile": diagonal_tile,
                "diagonal_result": diagonal_result,
                "boundary_cpos": boundary_cpos,
                "safe_cpos": safe_cpos,
                "result": collision_result,
            })

            if collision_result != "allow":
                return collision_result, safe_cpos, steps

            current_tile = diagonal_tile
            next_cross_x += TILE_UNITS
            next_cross_y += TILE_UNITS

    return "allow", end_cpos, steps


def print_movement_trace_steps(label, result, resolved_cpos, steps):
    print(
        f"  trace {label}: "
        f"result={result} "
        f"resolved={format_debug_vec(resolved_cpos)}"
    )

    for index, step in enumerate(steps):
        step_type = step["type"]

        if step_type == "start":
            print(
                f"    [{index}] start "
                f"cpos={format_debug_vec(step['start_cpos'])} "
                f"tile={format_debug_tile(step['start_tile'])} "
                f"end={format_debug_vec(step['end_cpos'])} "
                f"target_tile={format_debug_tile(step['target_tile'])} "
                f"delta={format_debug_vec(step['delta'])}"
            )

        elif step_type == "same_tile":
            print(
                f"    [{index}] same_tile "
                f"tile={format_debug_tile(step['tile'])} "
                f"result={step['result']}"
            )

        elif step_type in {"x", "y"}:
            print(
                f"    [{index}] axis={step_type} "
                f"from={format_debug_tile(step['from_tile'])} "
                f"candidate={format_debug_tile(step['candidate_tile'])} "
                f"boundary={format_debug_vec(step['boundary_cpos'])} "
                f"safe={format_debug_vec(step['safe_cpos'])} "
                f"result={step['result']}"
            )

        elif step_type == "corner":
            print(
                f"    [{index}] corner "
                f"from={format_debug_tile(step['from_tile'])} "
                f"side_x={format_debug_tile(step['side_x_tile'])}:{step['side_x_result']} "
                f"side_y={format_debug_tile(step['side_y_tile'])}:{step['side_y_result']} "
                f"diag={format_debug_tile(step['diagonal_tile'])}:{step['diagonal_result']} "
                f"boundary={format_debug_vec(step['boundary_cpos'])} "
                f"safe={format_debug_vec(step['safe_cpos'])} "
                f"result={step['result']}"
            )

        else:
            print(f"    [{index}] {step}")


def get_entity_movement_footprint_debug_name(world, entity):
    space_occupier = world.space_occupier.get(entity, {})

    return space_occupier.get(
        "movement_footprint",
        space_occupier.get(
            "obstacle_footprint",
            "single_tile",
        ),
    )


def print_entity_movement_diagnostics(world, entity):
    if entity is None:
        print("[move_diag] no entity")
        return

    if entity not in world.transform:
        print(f"[move_diag] entity {entity} has no transform")
        return

    rebuild_dynamic_occupancy(world)

    transform = world.transform[entity]
    motion_state = world.motion_state.get(entity, {})
    controller = motion_state.get("controller")

    current_tile = tile_from_cpos(transform.cpos)
    current_center = tile_center(current_tile)
    center_offset = transform.cpos - current_center

    movement_policy = world.movement_collision.get(entity, {})
    footprint_name = get_entity_movement_footprint_debug_name(
        world,
        entity,
    )

    print("")
    print("=" * 96)
    print(
        "[move_diag] "
        f"tick={world.tick} "
        f"entity={entity} "
        f"footprint={footprint_name} "
        f"corner={movement_policy.get('corner_cutting', 'strict')}"
    )
    print(
        "  cpos="
        f"{format_debug_vec(transform.cpos)} "
        "tile="
        f"{format_debug_tile(current_tile)} "
        "tile_center="
        f"{format_debug_vec(current_center)} "
        "offset_from_center="
        f"{format_debug_vec(center_offset)}"
    )

    if controller is None:
        print("  controller=None")
    else:
        print(
            "  controller="
            f"{controller.__class__.__name__} "
            f"motion_tag={getattr(controller, 'motion_tag', None)} "
            f"raw_direction={format_debug_vec(getattr(controller, 'raw_direction', None))} "
            f"aim_vector={format_debug_vec(getattr(controller, 'aim_vector', None))} "
            f"speed={getattr(controller, 'speed', None)}"
        )

    print("")
    print("  Neighbor placement/trace summary")
    print("  dir target     placement  center_trace  current_trace")

    mismatch_labels = []

    for label, direction in MOVEMENT_DIAGNOSTIC_DIRECTIONS:
        target_tile = current_tile + direction
        target_cpos = tile_center(target_tile)

        placement_result = handle_movement_tile_collision(
            world,
            entity,
            target_tile,
        )

        center_delta = target_cpos - current_center

        center_trace_result, center_resolved, center_steps = (
            diagnose_trace_static_tile_path(
                world,
                entity,
                current_center,
                center_delta,
            )
        )

        current_delta = target_cpos - transform.cpos

        current_trace_result, current_resolved, current_steps = (
            diagnose_trace_static_tile_path(
                world,
                entity,
                transform.cpos,
                current_delta,
            )
        )

        print(
            "  "
            f"{label:<2} "
            f"{format_debug_tile(target_tile):<10} "
            f"{placement_result:<10} "
            f"{center_trace_result:<12} "
            f"{current_trace_result:<13}"
        )

        if (
            label in {"NE", "SE", "SW", "NW"}
            or placement_result != current_trace_result
            or center_trace_result != current_trace_result
        ):
            mismatch_labels.append((
                label,
                placement_result,
                center_trace_result,
                center_resolved,
                center_steps,
                current_trace_result,
                current_resolved,
                current_steps,
            ))

    print("")
    print("  Detailed traces for mismatches and diagonals")

    for (
        label,
        placement_result,
        center_trace_result,
        center_resolved,
        center_steps,
        current_trace_result,
        current_resolved,
        current_steps,
    ) in mismatch_labels:
        print(
            f"  {label}: placement={placement_result} "
            f"center_trace={center_trace_result} "
            f"current_trace={current_trace_result}"
        )

        print_movement_trace_steps(
            f"{label} center-to-center",
            center_trace_result,
            center_resolved,
            center_steps,
        )

        print_movement_trace_steps(
            f"{label} current-to-target-center",
            current_trace_result,
            current_resolved,
            current_steps,
        )

    if controller is not None:
        actual_delta = sample_controller_delta(
            controller,
            transform.cpos,
        )

        actual_result, actual_resolved, actual_steps = (
            diagnose_trace_static_tile_path(
                world,
                entity,
                transform.cpos,
                actual_delta,
            )
        )

        print("")
        print(
            "  Actual controller delta: "
            f"delta={format_debug_vec(actual_delta)} "
            f"result={actual_result} "
            f"resolved={format_debug_vec(actual_resolved)}"
        )

        print_movement_trace_steps(
            "actual controller",
            actual_result,
            actual_resolved,
            actual_steps,
        )

    print("=" * 96)
    print("")


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


@profiled("movement_system")
def movement_system(world):
    rebuild_dynamic_occupancy(world)

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
        influence_active = vec_is_nonzero(influence_delta)

        delta = base_delta + influence_delta
        start_cpos = transform.cpos

        if vec_is_nonzero(delta):
            requested_cpos = start_cpos + delta

            if entity == getattr(world, "player", None):
                from_tile = tile_from_cpos(start_cpos)
                to_tile = tile_from_cpos(requested_cpos)

                print(
                    "[move_actual_trace_request] "
                    f"tick={world.tick} "
                    f"entity={entity} "
                    f"controller={controller.__class__.__name__ if controller is not None else None} "
                    f"source={motion_state.get('controller_source')} "
                    f"start_cpos={format_debug_vec(start_cpos)} "
                    f"requested_cpos={format_debug_vec(requested_cpos)} "
                    f"delta={format_debug_vec(delta)} "
                    f"base_delta={format_debug_vec(base_delta)} "
                    f"influence_delta={format_debug_vec(influence_delta)} "
                    f"from_tile={format_debug_tile(from_tile)} "
                    f"to_tile={format_debug_tile(to_tile)} "
                    f"tile_delta=({to_tile.x - from_tile.x},{to_tile.y - from_tile.y})"
                )

            collision_result, resolved_cpos = resolve_static_tile_movement(
                world,
                entity,
                start_cpos,
                delta,
            )

            if entity == getattr(world, "player", None):
                resolved_tile = tile_from_cpos(resolved_cpos)

                print(
                    "[move_actual_trace_result] "
                    f"tick={world.tick} "
                    f"entity={entity} "
                    f"controller={controller.__class__.__name__ if controller is not None else None} "
                    f"source={motion_state.get('controller_source')} "
                    f"collision_result={collision_result} "
                    f"start_cpos={format_debug_vec(start_cpos)} "
                    f"requested_cpos={format_debug_vec(requested_cpos)} "
                    f"resolved_cpos={format_debug_vec(resolved_cpos)} "
                    f"delta={format_debug_vec(delta)} "
                    f"actual_delta=({resolved_cpos.x - start_cpos.x},{resolved_cpos.y - start_cpos.y}) "
                    f"from_tile={format_debug_tile(tile_from_cpos(start_cpos))} "
                    f"requested_tile={format_debug_tile(tile_from_cpos(requested_cpos))} "
                    f"resolved_tile={format_debug_tile(resolved_tile)}"
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

                if transform.position_mode == "free" or influence_active:
                    transform.tile = tile_from_cpos(transform.cpos)

                mark_settle_after_influence_if_needed(
                    transform,
                    motion_state,
                    influence_active,
                )

                motion_state["last_delta"] = transform.cpos - start_cpos

                mark_dynamic_occupancy_dirty(world)
                rebuild_dynamic_occupancy(world)

                if controller is not None:
                    # Directional movement is allowed to keep trying while input is held.
                    if is_path_follow_controller(controller):
                        continue

                    request_settle_when_allowed(world, entity)
                    start_requested_settle_if_allowed(world, entity)

                continue

            transform.cpos = resolved_cpos

            if isinstance(controller, PathFollowController):
                update_path_follow_progress(
                    world,
                    entity,
                    controller,
                )

            if transform.position_mode == "free" or influence_active:
                transform.tile = tile_from_cpos(transform.cpos)

            mark_settle_after_influence_if_needed(
                transform,
                motion_state,
                influence_active,
            )

            motion_state["last_delta"] = transform.cpos - start_cpos

            if path_follow_movement_was_modified(
                    controller,
                    requested_cpos,
                    resolved_cpos,
            ):
                discard_pending_controller_advance(controller)

                mark_dynamic_occupancy_dirty(world)
                rebuild_dynamic_occupancy(world)

                continue

        else:
            motion_state["last_delta"] = Vec2i(0, 0)

            if controller is None:
                settle_after_influence_if_needed(
                    world,
                    entity,
                    transform,
                    motion_state,
                )

                start_requested_settle_if_allowed(
                    world,
                    entity,
                )

        if controller is not None:
            controller.advance()

            if isinstance(controller, PathFollowController):
                update_path_follow_progress(
                    world,
                    entity,
                    controller,
                )

            if controller.finished():
                if hasattr(controller, "end"):
                    transform.cpos = controller.end

                transform.tile = tile_from_cpos(transform.cpos)

                clear_motion_controller(motion_state)

                request_settle_when_allowed(world, entity)
                start_requested_settle_if_allowed(world, entity)

        mark_dynamic_occupancy_dirty(world)
        rebuild_dynamic_occupancy(world)


def cancel_motion_by_tags_for_status(world, entity, motion_tags):
    if not motion_tags:
        return False

    motion_state = world.motion_state.get(entity)

    if motion_state is None:
        return False

    controller = motion_state.get("controller")

    if controller is None:
        return False

    motion_tag = get_motion_controller_tag(controller)

    if motion_tag not in motion_tags:
        return False

    clear_motion_controller(motion_state)
    motion_state["last_delta"] = Vec2i(0, 0)

    request_settle_when_allowed(world, entity)
    start_requested_settle_if_allowed(world, entity)

    return True


def get_active_motion_tag(world, entity):
    motion_state = world.motion_state.get(entity)

    if motion_state is None:
        return None

    controller = motion_state.get("controller")

    if controller is None:
        return None

    return getattr(controller, "motion_tag", None)


def get_motion_controller_tag(controller):
    if controller is None:
        return None

    return getattr(controller, "motion_tag", None)