from math import isqrt
from policies import PATH_POLICIES, DIRECTIONAL_MOVEMENT_MODE, SETTLE_LOCKED_TAG
from constants import MOVE_BUFFER_TICKS, TILE_UNITS
from .action_state_system import get_active_action_tags, tags_block_voluntary_movement
from .event_system import emit_event
from support import Vec2i
from dataclasses import dataclass
from typing import Optional
from utils.placement_utils import is_static_movement_placement_blocked
from utils.perf_profiler import profiled, record_counter_for_world
from utils.flow_field_utils import (
    get_or_build_flow_field,
    get_flow_field_side_pressure_counts,
    get_flow_field_step_candidates,
    get_flow_field_step_candidates_from_tile,
)
from utils.occupancy_utils import (
    rebuild_dynamic_occupancy,
    refresh_entity_dynamic_occupancy,
    is_tile_blocked_for_movement,
    get_dynamic_movement_blockers_for_placement,
    get_dynamic_movement_blocker_sources_for_placement,
    get_movement_body_tiles_for_origin_tile,
)
from motion_controllers import (
    BLOCK_RESPONSE_ABORT,
    BLOCK_RESPONSE_AGE,
    BLOCK_RESPONSE_RETRY,
    GridMoveController,
    SettleToGridController,
    PathFollowController,
    DirectionalMoveController,
    FlowChaseDirectController,
)
from utils.tile_vec_utils import (
    sign,
    tile_center,
    tile_from_cpos,
    normalize_vector_to_dir_scale,
    scale_normalized_dir,
    chebyshev_tile_distance,
)
from utils.path_utils import (
    find_static_tile_path_to_target,
    smooth_static_tile_path,
    path_tiles_to_cpos_nodes,
    build_local_dynamic_blocker_context,
)


CORNER_CROSSING_TOLERANCE_CPOS = 32
PATH_FOLLOW_STALL_LOCAL = "local_stalled"
PATH_FOLLOW_STALL_PATH_PROGRESS_TIMEOUT = "path_progress_timed_out"
PATH_FOLLOW_STALL_LIFETIME = "lifetime_expired"
PATH_BUILD_DEFERRED = object()

FLOW_CHASE_LOCAL_STEERING_ENABLED = True
FLOW_CHASE_LOCAL_STEERING_SIDE_PERSIST_TICKS = 12
FLOW_CHASE_LOCAL_STEERING_MAX_EXTRA_DISTANCE_CPOS = TILE_UNITS * 2
FLOW_CHASE_LOCAL_STEERING_TINY_MOVE_DIAGNOSTIC_CPOS = TILE_UNITS // 8
FLOW_CHASE_LOCAL_STEERING_MIN_RESOLVED_NUMERATOR = 3
FLOW_CHASE_LOCAL_STEERING_MIN_RESOLVED_DENOMINATOR = 4
FLOW_CHASE_LOCAL_STEERING_SHARP_TURN_DOT_MAX = 0
FLOW_CHASE_LOCAL_STEERING_PURE_SIDE_MIN_NO_PROGRESS_TICKS = 9999

FLOW_CHASE_PROACTIVE_STEERING_ENABLED = True
FLOW_CHASE_PROACTIVE_NEIGHBOR_RADIUS_CPOS = TILE_UNITS * 2
FLOW_CHASE_PROACTIVE_DYNAMIC_COLLISION_PENALTY = TILE_UNITS * 19
FLOW_CHASE_PROACTIVE_STATIC_COLLISION_PENALTY = TILE_UNITS * 42
FLOW_CHASE_PROACTIVE_PARTIAL_MOVE_PENALTY = TILE_UNITS * 4
FLOW_CHASE_PROACTIVE_CLEARANCE_WEIGHT = 4
FLOW_CHASE_PROACTIVE_SIDE_CONTINUITY_BONUS = TILE_UNITS // 3
FLOW_CHASE_PROACTIVE_SIDE_SWITCH_PENALTY = TILE_UNITS * 3
FLOW_CHASE_PROACTIVE_DIRECT_BIAS = TILE_UNITS // 8
FLOW_CHASE_PROACTIVE_HOLD_ON_ALL_COLLIDING = True
FLOW_CHASE_PROACTIVE_ALLOW_STATIC_SLIDE = False

# Temporary
FLOW_CHASE_MANUAL_STEERING_TEST_ENABLED = False
FLOW_CHASE_MANUAL_STEERING_TEST_ENTITY = None
FLOW_CHASE_MANUAL_STEERING_TEST_SIDE = 1
FLOW_CHASE_MANUAL_STEERING_TEST_SIDE_CPOS = TILE_UNITS
FLOW_CHASE_MANUAL_STEERING_TEST_FORWARD_CPOS = TILE_UNITS * 2


@dataclass(frozen=True)
class MovementCollisionResult:
    collision_result: str
    blocker_collision_type: Optional[str] = None
    blocked_tile: Optional[Vec2i] = None
    blocker_entity: Optional[int] = None

    @property
    def allows_movement(self):
        return self.collision_result == "allow"

    @property
    def blocks_movement(self):
        return self.collision_result == "block"

    @property
    def slides_movement(self):
        return self.collision_result == "slide"

    @property
    def destroys_entity(self):
        return self.collision_result == "destroy"


MOVEMENT_COLLISION_ALLOW = MovementCollisionResult("allow")


def make_movement_collision_result(
    collision_result,
    blocker_collision_type=None,
    blocked_tile=None,
    blocker_entity=None,
):
    if collision_result == "allow":
        return MOVEMENT_COLLISION_ALLOW

    return MovementCollisionResult(
        collision_result=collision_result,
        blocker_collision_type=blocker_collision_type,
        blocked_tile=blocked_tile,
        blocker_entity=blocker_entity,
    )

def movement_collision_allows(collision_result):
    return collision_result.allows_movement


def movement_collision_blocks(collision_result):
    return collision_result.blocks_movement


def movement_collision_slides(collision_result):
    return collision_result.slides_movement


def movement_collision_destroys(collision_result):
    return collision_result.destroys_entity


def emit_movement_collision_event(
    world,
    event_type,
    entity,
    cpos,
    tile,
    collision_result,
    controller,
    influence_active,
):
    emit_event(
        world,
        event_type,
        entity=entity,
        cpos=cpos,
        tile=tile,
        blocker_collision_type=collision_result.blocker_collision_type,
        blocked_tile=collision_result.blocked_tile,
        blocker_entity=collision_result.blocker_entity,
        had_controller=controller is not None,
        influence_active=influence_active,
    )


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
            (
                DirectionalMoveController,
                FlowChaseDirectController,
            ),
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

        if clear_stale_order_owned_move_target(world, entity):
            refresh_moved_entity_occupancy(
                world,
                entity,
            )
            continue

        if not entity_can_start_voluntary_movement(world, entity):
            cancel_voluntary_movement(world, entity)
            continue

        controller = motion_state["controller"]

        if isinstance(controller, FlowChaseDirectController):
            if entity in world.move_intent:
                cancel_move_target_for_directional_input(world, entity)
                clear_motion_controller(motion_state)
                refresh_moved_entity_occupancy(
                    world,
                    entity,
                )
                continue

            update_flow_chase_direct_controller(
                world,
                entity,
                controller,
            )
            continue

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
                    refresh_moved_entity_occupancy(
                        world,
                        entity,
                    )

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

                refresh_moved_entity_occupancy(
                    world,
                    entity,
                )

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
                refresh_moved_entity_occupancy(
                    world,
                    entity,
                )
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


def refresh_moved_entity_occupancy(world, entity):
    refresh_entity_dynamic_occupancy(
        world,
        entity,
    )


def make_path_query_key(
    entity,
    start_tile,
    target_tile,
    path_policy_name,
    dynamic_blocker_key,
    path_policy,
):
    key_scope = path_policy.get(
        "failed_query_key_scope",
        "exact",
    )

    if key_scope == "exact":
        return (
            entity,
            "exact",
            start_tile.x,
            start_tile.y,
            target_tile.x,
            target_tile.y,
            path_policy_name,
            dynamic_blocker_key,
        )

    if key_scope == "target_only":
        return (
            entity,
            "target_only",
            target_tile.x,
            target_tile.y,
            path_policy_name,
        )

    raise ValueError(
        f"Unknown failed_query_key_scope: {key_scope!r}"
    )


def path_query_key_needs_dynamic_blocker_context(path_policy):
    return (
        path_policy.get(
            "failed_query_key_scope",
            "exact",
        )
        == "exact"
    )


def get_path_dynamic_blocker_key(dynamic_blocker_context):
    if dynamic_blocker_context is None:
        return None

    return dynamic_blocker_context.cache_key()


def get_active_controller(world, entity):
    motion_state = world.motion_state.get(entity)

    if motion_state is None:
        return None

    return motion_state.get("controller")


def path_query_failed_recently(world, query_key):
    retry_tick = world.failed_path_queries.get(query_key)

    if retry_tick is None:
        record_counter_for_world(
            world,
            "path.failed_cache.miss",
        )
        return False

    if world.tick < retry_tick:
        record_counter_for_world(
            world,
            "path.failed_cache.hit",
        )
        return True

    world.failed_path_queries.pop(query_key, None)
    record_counter_for_world(
        world,
        "path.failed_cache.expired",
    )
    return False


def remember_failed_path_query(world, query_key, retry_ticks):
    world.failed_path_queries[query_key] = world.tick + retry_ticks
    record_counter_for_world(
        world,
        "path.failed_cache.remember",
    )


def clear_failed_path_query(world, query_key):
    world.failed_path_queries.pop(query_key, None)


def clear_failed_path_queries_for_entity(world, entity):
    for query_key in list(world.failed_path_queries):
        if query_key[0] == entity:
            world.failed_path_queries.pop(query_key, None)


def get_path_policy_name(target):
    return target.get("path_policy")


def get_path_policy(world, target):
    return PATH_POLICIES[get_path_policy_name(target)]


def get_path_build_budget_key(path_policy_name, path_policy):
    return path_policy.get(
        "path_build_budget_key",
        path_policy_name,
    )


def get_path_build_budget_state(world, budget_key):
    state = world.path_build_budget_state.setdefault(
        budget_key,
        {
            "tick": world.tick,
            "used": 0,
        },
    )

    if state["tick"] != world.tick:
        state["tick"] = world.tick
        state["used"] = 0

    return state


def path_build_budget_allows(
    world,
    path_policy_name,
    path_policy,
):
    max_builds = path_policy.get("max_path_builds_per_tick")

    if max_builds is None:
        return True

    budget_key = get_path_build_budget_key(
        path_policy_name,
        path_policy,
    )
    state = get_path_build_budget_state(
        world,
        budget_key,
    )

    if state["used"] >= max_builds:
        record_counter_for_world(
            world,
            "path.build_budget.exhausted",
        )
        record_counter_for_world(
            world,
            f"path.build_budget.exhausted.{budget_key}",
        )
        return False

    state["used"] += 1

    record_counter_for_world(
        world,
        "path.build_budget.consumed",
    )
    record_counter_for_world(
        world,
        f"path.build_budget.consumed.{budget_key}",
    )

    return True


def build_path_dynamic_blocker_context(
    world,
    entity,
    start_tile,
    path_policy,
):
    if not path_policy["path_local_dynamic_blockers_enabled"]:
        return None

    return build_local_dynamic_blocker_context(
        world,
        entity,
        start_tile,
        radius_tiles=path_policy[
            "path_local_dynamic_blocker_radius_tiles"
        ],
        max_entities=path_policy[
            "path_local_dynamic_blocker_max_entities"
        ],
        include_moving=path_policy[
            "path_local_dynamic_blocker_include_moving"
        ],
        include_reservations=path_policy[
            "path_local_dynamic_blocker_include_reservations"
        ],
    )


def get_path_build_cooldown_ticks(world, target):
    path_policy = get_path_policy(
        world,
        target,
    )

    return path_policy["path_build_cooldown_ticks"]


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


def dot_vec(a: Vec2i, b: Vec2i) -> int:
    return a.x * b.x + a.y * b.y


def cpos_distance(a: Vec2i, b: Vec2i) -> int:
    return isqrt(cpos_distance_sq(a, b))


def scale_vec_ratio(vec: Vec2i, numerator: int, denominator: int) -> Vec2i:
    if denominator == 0:
        raise ValueError("Cannot scale vector with denominator 0.")

    return Vec2i(
        vec.x * numerator // denominator,
        vec.y * numerator // denominator,
    )


def clamp_vec_length_to_reference(vec: Vec2i, reference: Vec2i) -> Vec2i:
    reference_len_sq = cpos_distance_sq(
        Vec2i(0, 0),
        reference,
    )

    vec_len_sq = cpos_distance_sq(
        Vec2i(0, 0),
        vec,
    )

    if vec_len_sq == 0:
        return Vec2i(0, 0)

    if vec_len_sq <= reference_len_sq:
        return vec

    reference_len = isqrt(reference_len_sq)
    vec_len = isqrt(vec_len_sq)

    if vec_len == 0:
        return Vec2i(0, 0)

    return Vec2i(
        vec.x * reference_len // vec_len,
        vec.y * reference_len // vec_len,
    )


def append_unique_nonzero_delta(candidates, seen, delta):
    if not vec_is_nonzero(delta):
        return

    key = (delta.x, delta.y)

    if key in seen:
        return

    seen.add(key)
    candidates.append(delta)


def get_path_follow_node_distance(controller, cpos):
    current_node = get_path_follow_current_node(controller)

    if current_node is None:
        return None

    return cpos_distance(cpos, current_node)


def make_local_avoidance_score(
    controller,
    path_policy,
    start_cpos,
    resolved_cpos,
    candidate_index,
):
    before_distance = get_path_follow_node_distance(
        controller,
        start_cpos,
    )
    after_distance = get_path_follow_node_distance(
        controller,
        resolved_cpos,
    )

    if before_distance is None or after_distance is None:
        return (candidate_index,)

    prefer_progress = path_policy[
        "local_avoidance_prefer_progress"
    ]

    made_progress = after_distance < before_distance

    if prefer_progress:
        return (
            0 if made_progress else 1,
            after_distance,
            candidate_index,
        )

    return (
        candidate_index,
        after_distance,
    )


def find_best_flow_chase_local_steering_option(
    world,
    entity,
    controller,
    start_cpos,
    candidate_deltas,
    allowed_side,
    allowed_labels=None,
):
    options = []

    for index, (side, label, candidate_delta) in enumerate(candidate_deltas):
        if allowed_side is not None and side != allowed_side:
            continue

        if allowed_labels is not None and label not in allowed_labels:
            continue

        previous_collision_context = push_movement_collision_debug_context(
            world,
            "flow_chase.local_steering_candidate",
        )
        try:
            candidate_result, candidate_cpos = resolve_static_tile_movement(
                world,
                entity,
                start_cpos,
                candidate_delta,
            )
        finally:
            pop_movement_collision_debug_context(
                world,
                previous_collision_context,
            )

        if not movement_collision_allows(candidate_result):
            record_counter_for_world(
                world,
                f"flow_chase.local_steering.candidate_blocked.{label}",
            )
            continue

        if not flow_chase_local_steering_resolved_enough(
                start_cpos,
                candidate_cpos,
                candidate_delta,
        ):
            record_counter_for_world(
                world,
                f"flow_chase.local_steering.candidate_rejected_partial.{label}",
            )
            continue

        if not flow_chase_local_steering_candidate_is_acceptable(
            controller,
            start_cpos,
            candidate_cpos,
        ):
            record_counter_for_world(
                world,
                f"flow_chase.local_steering.candidate_rejected.{label}",
            )
            continue

        score = make_flow_chase_local_steering_score(
            controller,
            start_cpos,
            candidate_cpos,
            side,
            candidate_delta,
            index,
        )

        options.append(
            (
                score,
                side,
                label,
                candidate_result,
                candidate_cpos,
                candidate_delta,
            )
        )

    if not options:
        return None

    options.sort(key=lambda item: item[0])
    return options[0]


def find_best_flow_chase_local_steering_option_for_side_tiers(
    world,
    entity,
    controller,
    start_cpos,
    candidate_deltas,
    allowed_side,
):
    forward_option = find_best_flow_chase_local_steering_option(
        world,
        entity,
        controller,
        start_cpos,
        candidate_deltas,
        allowed_side,
        allowed_labels={
            "forward_half_side",
            "forward_full_side",
        },
    )

    if forward_option is not None:
        return forward_option

    if not flow_chase_local_steering_pure_side_allowed(controller):
        record_counter_for_world(
            world,
            "flow_chase.local_steering.pure_side_suppressed_not_stuck",
        )
        return None

    record_counter_for_world(
        world,
        "flow_chase.local_steering.pure_side_fallback_considered",
    )

    return find_best_flow_chase_local_steering_option(
        world,
        entity,
        controller,
        start_cpos,
        candidate_deltas,
        allowed_side,
        allowed_labels={
            "pure_side",
        },
    )


def try_resolve_flow_chase_local_steering(
    world,
    entity,
    controller,
    start_cpos,
    delta,
    original_collision_result,
):
    record_counter_for_world(
        world,
        "flow_chase.local_steering.entry",
    )

    if not FLOW_CHASE_LOCAL_STEERING_ENABLED:
        record_counter_for_world(
            world,
            "flow_chase.local_steering.skip.disabled",
        )
        return None

    if not isinstance(controller, FlowChaseDirectController):
        record_counter_for_world(
            world,
            "flow_chase.local_steering.skip.not_flow_chase",
        )
        return None

    if controller.steering_points:
        record_counter_for_world(
            world,
            "flow_chase.local_steering.skip.has_steering_points",
        )
        return None

    if original_collision_result.blocker_collision_type != "dynamic":
        record_counter_for_world(
            world,
            "flow_chase.local_steering.skip.not_dynamic",
        )
        record_counter_for_world(
            world,
            f"flow_chase.local_steering.skip.collision.{original_collision_result.collision_result}",
        )

        if original_collision_result.blocker_collision_type is None:
            record_counter_for_world(
                world,
                "flow_chase.local_steering.skip.blocker_type.none",
            )
        else:
            record_counter_for_world(
                world,
                f"flow_chase.local_steering.skip.blocker_type.{original_collision_result.blocker_collision_type}",
            )

        return None

    candidate_deltas = iter_flow_chase_local_steering_candidate_deltas(
        entity,
        controller,
        delta,
    )

    chosen_option = None

    if controller.local_steering_side in {-1, 1}:
        chosen_option = find_best_flow_chase_local_steering_option_for_side_tiers(
            world,
            entity,
            controller,
            start_cpos,
            candidate_deltas,
            controller.local_steering_side,
        )

        if chosen_option is None:
            chosen_option = find_best_flow_chase_local_steering_option_for_side_tiers(
                world,
                entity,
                controller,
                start_cpos,
                candidate_deltas,
                -controller.local_steering_side,
            )

            if chosen_option is not None:
                record_counter_for_world(
                    world,
                    "flow_chase.local_steering.side_switch",
                )
    else:
        chosen_option = find_best_flow_chase_local_steering_option_for_side_tiers(
            world,
            entity,
            controller,
            start_cpos,
            candidate_deltas,
            None,
        )

    if chosen_option is None:
        controller.local_steering_no_progress_ticks += 1

        record_counter_for_world(
            world,
            "flow_chase.local_steering.failed",
        )
        record_counter_for_world(
            world,
            "flow_chase.local_steering.progress_state.failed_no_progress_tick",
        )

        return None

    (
        _score,
        side,
        label,
        candidate_result,
        candidate_cpos,
        candidate_delta,
    ) = chosen_option

    controller.local_steering_side = side
    controller.local_steering_last_tick = world.tick
    controller.local_steering_last_delta = candidate_delta

    update_flow_chase_local_steering_progress_state(
        world,
        controller,
        start_cpos,
        candidate_cpos,
    )

    record_flow_chase_local_steering_motion_diagnostics(
        world,
        controller,
        start_cpos,
        candidate_cpos,
        candidate_delta,
    )

    if entity in world.facing:
        world.facing[entity] = Vec2i(
            sign(candidate_delta.x),
            sign(candidate_delta.y),
        )

    record_counter_for_world(
        world,
        "flow_chase.local_steering.resolved",
    )
    record_counter_for_world(
        world,
        f"flow_chase.local_steering.resolved.{label}",
    )

    if side < 0:
        record_counter_for_world(
            world,
            "flow_chase.local_steering.side.left",
        )
    else:
        record_counter_for_world(
            world,
            "flow_chase.local_steering.side.right",
        )

    return candidate_result, candidate_cpos


def try_resolve_path_follow_local_avoidance(
    world,
    entity,
    controller,
    start_cpos,
    delta,
    original_collision_result,
):
    if not is_path_follow_controller(controller):
        return None

    if original_collision_result.blocker_collision_type != "dynamic":
        return None

    target = world.move_target.get(entity)

    if target is None:
        return None

    path_policy = get_path_policy(world, target)

    if not path_policy["local_avoidance_enabled"]:
        return None

    options = []

    candidate_deltas = iter_local_avoidance_candidate_deltas(
        entity,
        delta,
        path_policy,
    )

    for index, candidate_delta in enumerate(candidate_deltas):
        candidate_result, candidate_cpos = resolve_static_tile_movement(
            world,
            entity,
            start_cpos,
            candidate_delta,
        )

        if not movement_collision_allows(candidate_result):
            continue

        if not local_avoidance_candidate_is_acceptable(
            controller,
            path_policy,
            start_cpos,
            candidate_cpos,
        ):
            continue

        score = make_local_avoidance_score(
            controller,
            path_policy,
            start_cpos,
            candidate_cpos,
            index,
        )

        options.append(
            (
                score,
                candidate_result,
                candidate_cpos,
            )
        )

    if not options:
        return None

    options.sort(key=lambda item: item[0])

    _, collision_result, resolved_cpos = options[0]

    return collision_result, resolved_cpos


def local_avoidance_candidate_is_acceptable(
    controller,
    path_policy,
    start_cpos,
    resolved_cpos,
):
    if resolved_cpos == start_cpos:
        return False

    before_distance = get_path_follow_node_distance(
        controller,
        start_cpos,
    )
    after_distance = get_path_follow_node_distance(
        controller,
        resolved_cpos,
    )

    if before_distance is None or after_distance is None:
        return True

    max_extra_distance = path_policy[
        "local_avoidance_max_extra_node_distance_cpos"
    ]

    if after_distance > before_distance + max_extra_distance:
        return False

    if path_policy["local_avoidance_require_progress"]:
        min_progress = path_policy[
            "local_avoidance_min_progress_cpos"
        ]

        if after_distance > before_distance - min_progress:
            return False

    return True


def get_flow_chase_local_steering_sides(entity, controller):
    if controller.local_steering_side in {-1, 1}:
        return (
            controller.local_steering_side,
            -controller.local_steering_side,
        )

    if entity % 2 == 0:
        return (1, -1)

    return (-1, 1)


def make_flow_chase_side_delta(delta, side):
    return Vec2i(
        -delta.y * side,
        delta.x * side,
    )


def append_flow_chase_local_steering_candidate(
    candidates,
    seen,
    side,
    label,
    delta,
):
    if not vec_is_nonzero(delta):
        return

    key = (delta.x, delta.y)

    if key in seen:
        return

    seen.add(key)
    candidates.append(
        (
            side,
            label,
            delta,
        )
    )


def iter_flow_chase_local_steering_candidate_deltas(
    entity,
    controller,
    delta,
):
    candidates = []
    seen = set()

    for side in get_flow_chase_local_steering_sides(
        entity,
        controller,
    ):
        side_delta = make_flow_chase_side_delta(
            delta,
            side,
        )

        half_side_delta = scale_vec_ratio(
            side_delta,
            1,
            2,
        )
        forward_half_side_delta = clamp_vec_length_to_reference(
            delta + half_side_delta,
            delta,
        )
        append_flow_chase_local_steering_candidate(
            candidates,
            seen,
            side,
            "forward_half_side",
            forward_half_side_delta,
        )

        forward_full_side_delta = clamp_vec_length_to_reference(
            delta + side_delta,
            delta,
        )
        append_flow_chase_local_steering_candidate(
            candidates,
            seen,
            side,
            "forward_full_side",
            forward_full_side_delta,
        )

        append_flow_chase_local_steering_candidate(
            candidates,
            seen,
            side,
            "pure_side",
            side_delta,
        )

    return candidates


def flow_chase_local_steering_candidate_is_acceptable(
    controller,
    start_cpos,
    resolved_cpos,
):
    if resolved_cpos == start_cpos:
        return False

    before_distance = cpos_distance(
        start_cpos,
        controller.base_target_cpos,
    )
    after_distance = cpos_distance(
        resolved_cpos,
        controller.base_target_cpos,
    )

    return (
        after_distance
        <= before_distance + FLOW_CHASE_LOCAL_STEERING_MAX_EXTRA_DISTANCE_CPOS
    )


def make_flow_chase_local_steering_score(
    controller,
    start_cpos,
    resolved_cpos,
    side,
    candidate_delta,
    candidate_index,
):
    before_distance = cpos_distance(
        start_cpos,
        controller.base_target_cpos,
    )
    after_distance = cpos_distance(
        resolved_cpos,
        controller.base_target_cpos,
    )

    made_progress_penalty = 0 if after_distance < before_distance else 1

    heading_penalty = 0

    if vec_is_nonzero(controller.local_steering_last_delta):
        heading_penalty = -dot_vec(
            candidate_delta,
            controller.local_steering_last_delta,
        )

    return (
        made_progress_penalty,
        heading_penalty,
        after_distance,
        candidate_index,
    )


def record_flow_chase_local_steering_motion_diagnostics(
    world,
    controller,
    start_cpos,
    candidate_cpos,
    candidate_delta,
):
    movement_distance = cpos_distance(
        start_cpos,
        candidate_cpos,
    )

    if movement_distance <= FLOW_CHASE_LOCAL_STEERING_TINY_MOVE_DIAGNOSTIC_CPOS:
        record_counter_for_world(
            world,
            "flow_chase.local_steering.tiny_movement",
        )

    before_distance = cpos_distance(
        start_cpos,
        controller.base_target_cpos,
    )
    after_distance = cpos_distance(
        candidate_cpos,
        controller.base_target_cpos,
    )

    if after_distance < before_distance:
        record_counter_for_world(
            world,
            "flow_chase.local_steering.progress",
        )
    else:
        record_counter_for_world(
            world,
            "flow_chase.local_steering.no_progress",
        )

    if not vec_is_nonzero(controller.local_steering_last_delta):
        return

    heading_dot = dot_vec(
        candidate_delta,
        controller.local_steering_last_delta,
    )

    if heading_dot < 0:
        record_counter_for_world(
            world,
            "flow_chase.local_steering.heading_flip",
        )
    elif heading_dot <= FLOW_CHASE_LOCAL_STEERING_SHARP_TURN_DOT_MAX:
        record_counter_for_world(
            world,
            "flow_chase.local_steering.heading_sharp_turn",
        )


def vec_length_cpos(delta: Vec2i) -> int:
    return cpos_distance(
        Vec2i(0, 0),
        delta,
    )


def flow_chase_local_steering_resolved_enough(
    start_cpos,
    resolved_cpos,
    candidate_delta,
):
    requested_distance = vec_length_cpos(
        candidate_delta,
    )

    if requested_distance == 0:
        return False

    resolved_distance = cpos_distance(
        start_cpos,
        resolved_cpos,
    )

    return (
        resolved_distance * FLOW_CHASE_LOCAL_STEERING_MIN_RESOLVED_DENOMINATOR
        >= requested_distance * FLOW_CHASE_LOCAL_STEERING_MIN_RESOLVED_NUMERATOR
    )


def iter_local_avoidance_candidate_deltas(entity, delta: Vec2i, path_policy):
    candidates = []
    seen = set()

    abs_x = abs(delta.x)
    abs_y = abs(delta.y)

    x_only = Vec2i(delta.x, 0)
    y_only = Vec2i(0, delta.y)

    if abs_x > abs_y:
        axis_candidates = (x_only, y_only)
    elif abs_y > abs_x:
        axis_candidates = (y_only, x_only)
    else:
        # Deterministic variation for exact diagonals.
        if entity % 2 == 0:
            axis_candidates = (x_only, y_only)
        else:
            axis_candidates = (y_only, x_only)

    perpendicular_scale_num = path_policy[
        "local_avoidance_perpendicular_scale_num"
    ]
    perpendicular_scale_den = path_policy[
        "local_avoidance_perpendicular_scale_den"
    ]

    left_perp = scale_vec_ratio(
        Vec2i(-delta.y, delta.x),
        perpendicular_scale_num,
        perpendicular_scale_den,
    )
    right_perp = scale_vec_ratio(
        Vec2i(delta.y, -delta.x),
        perpendicular_scale_num,
        perpendicular_scale_den,
    )

    if entity % 2 == 0:
        perpendicular_candidates = (left_perp, right_perp)
    else:
        perpendicular_candidates = (right_perp, left_perp)

    forward_side_scale_num = path_policy[
        "local_avoidance_forward_side_scale_num"
    ]
    forward_side_scale_den = path_policy[
        "local_avoidance_forward_side_scale_den"
    ]

    forward_side_candidates = []

    for perpendicular_delta in perpendicular_candidates:
        scaled_perpendicular_delta = scale_vec_ratio(
            perpendicular_delta,
            forward_side_scale_num,
            forward_side_scale_den,
        )

        forward_side_delta = clamp_vec_length_to_reference(
            delta + scaled_perpendicular_delta,
            delta,
        )

        append_unique_nonzero_delta(
            forward_side_candidates,
            set(),
            forward_side_delta,
        )

    # Prefer moves that still have forward intent.
    for candidate_delta in forward_side_candidates:
        append_unique_nonzero_delta(
            candidates,
            seen,
            candidate_delta,
        )

    # Then try axis-only candidates.
    for candidate_delta in axis_candidates:
        append_unique_nonzero_delta(
            candidates,
            seen,
            candidate_delta,
        )

    # Finally try pure side movement.
    for candidate_delta in perpendicular_candidates:
        append_unique_nonzero_delta(
            candidates,
            seen,
            candidate_delta,
        )

    return candidates



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
        # Existing stale-path signal. Keep this unchanged for now.
        "last_progress_tick": world.tick,
        "last_index": controller.current_index,
        "last_distance_sq": distance_sq,

        # Explicit node-progress signal.
        "last_node_progress_tick": world.tick,
        "best_node_distance_sq": distance_sq,

        # Local escape signal.
        "anchor_cpos": Vec2i(
            transform.cpos.x,
            transform.cpos.y,
        ),
        "last_escape_tick": world.tick,

        # Detection outputs. These are diagnostic for this patch.
        "ticks_since_escape": 0,
        "ticks_since_node_progress": 0,
        "local_stalled": False,
        "path_progress_timed_out": False,
        "stall_reason": None,
    }


def update_path_follow_stall_detection(world, progress, path_policy):
    ticks_since_escape = world.tick - progress["last_escape_tick"]
    ticks_since_node_progress = (
        world.tick - progress["last_node_progress_tick"]
    )

    progress["ticks_since_escape"] = ticks_since_escape
    progress["ticks_since_node_progress"] = ticks_since_node_progress

    progress["local_stalled"] = (
        ticks_since_escape >= path_policy["stall_ticks_before_repath"]
    )

    progress["path_progress_timed_out"] = (
        ticks_since_node_progress
        >= path_policy["path_progress_timeout_ticks"]
    )


def update_path_follow_progress(world, entity, controller):
    motion_state = world.motion_state[entity]
    transform = world.transform[entity]

    target = world.move_target.get(entity)

    if target is None:
        return

    path_policy = get_path_policy(world, target)

    progress_min_cpos = path_policy["progress_min_cpos"]
    progress_min_sq = progress_min_cpos * progress_min_cpos

    stall_escape_cpos = path_policy["stall_escape_cpos"]
    stall_escape_sq = stall_escape_cpos * stall_escape_cpos

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

        progress["last_node_progress_tick"] = world.tick
        progress["best_node_distance_sq"] = 0

        progress["anchor_cpos"] = Vec2i(
            transform.cpos.x,
            transform.cpos.y,
        )
        progress["last_escape_tick"] = world.tick

        update_path_follow_stall_detection(
            world,
            progress,
            path_policy,
        )
        return

    distance_sq = cpos_distance_sq(
        transform.cpos,
        current_node,
    )

    index_advanced = controller.current_index > progress["last_index"]

    distance_decreased = (
        distance_sq + progress_min_sq
        < progress["best_node_distance_sq"]
    )

    if index_advanced or distance_decreased:
        # Keep the existing stale-path signal behavior intact.
        progress["last_progress_tick"] = world.tick
        progress["last_index"] = controller.current_index
        progress["last_distance_sq"] = distance_sq

        # Update explicit node-progress signal.
        progress["last_node_progress_tick"] = world.tick
        progress["best_node_distance_sq"] = distance_sq

        # A real path-node progress event also becomes the new local anchor.
        progress["anchor_cpos"] = Vec2i(
            transform.cpos.x,
            transform.cpos.y,
        )
        progress["last_escape_tick"] = world.tick

    else:
        anchor_cpos = progress["anchor_cpos"]

        escaped_anchor = (
            cpos_distance_sq(
                transform.cpos,
                anchor_cpos,
            )
            >= stall_escape_sq
        )

        if escaped_anchor:
            progress["anchor_cpos"] = Vec2i(
                transform.cpos.x,
                transform.cpos.y,
            )
            progress["last_escape_tick"] = world.tick

    update_path_follow_stall_detection(
        world,
        progress,
        path_policy,
    )


def abandon_move_target(world, entity):
    motion_state = world.motion_state.get(entity)

    clear_move_target(world, entity)

    if motion_state is None:
        return

    clear_motion_controller(motion_state)

    request_settle_when_allowed(world, entity)
    start_requested_settle_if_allowed(world, entity)


def clear_move_target_after_path_finish_if_needed(world, entity):
    target = world.move_target.get(entity)

    if target is None:
        return

    if target["type"] == "flow_field_to_entity":
        record_counter_for_world(
            world,
            "flow_field.finish.keep_target",
        )
        return

    path_policy = get_path_policy(world, target)

    if path_policy["clear_target_on_path_finish"]:
        clear_move_target(world, entity)


def abort_path_follow_controller(world, entity, motion_state):
    target = world.move_target.get(entity)

    if target is not None:
        path_policy = get_path_policy(world, target)

        if path_policy["clear_target_on_path_abort"]:
            clear_move_target(world, entity)

    clear_motion_controller(motion_state)

    request_settle_when_allowed(world, entity)
    start_requested_settle_if_allowed(world, entity)


def path_follow_exceeded_lifetime(world, target, path_policy):
    created_tick = target.get(
        "created_tick",
        world.tick,
    )

    max_follow_ticks = path_policy["max_follow_ticks"]

    if max_follow_ticks is None:
        return False

    return world.tick - created_tick >= max_follow_ticks


def get_path_follow_stall_reason(world, entity, target, path_policy):
    progress = world.motion_state[entity].get("path_follow_progress")

    if path_follow_exceeded_lifetime(
        world,
        target,
        path_policy,
    ):
        if progress is not None:
            progress["stall_reason"] = PATH_FOLLOW_STALL_LIFETIME

        return PATH_FOLLOW_STALL_LIFETIME

    if progress is None:
        return None

    # Keep these values current even if movement was blocked and
    # update_path_follow_progress(...) did not run this tick.
    update_path_follow_stall_detection(
        world,
        progress,
        path_policy,
    )

    if progress["local_stalled"]:
        progress["stall_reason"] = PATH_FOLLOW_STALL_LOCAL
        return PATH_FOLLOW_STALL_LOCAL

    if progress["path_progress_timed_out"]:
        progress["stall_reason"] = PATH_FOLLOW_STALL_PATH_PROGRESS_TIMEOUT
        return PATH_FOLLOW_STALL_PATH_PROGRESS_TIMEOUT

    progress["stall_reason"] = None
    return None


def recover_stale_path_follow_if_needed(world, entity, controller):
    target = world.move_target.get(entity)

    if target is None:
        return False

    if target["type"] != "target_tile":
        return False

    path_policy = get_path_policy(world, target)

    stall_reason = get_path_follow_stall_reason(
        world,
        entity,
        target,
        path_policy,
    )

    if stall_reason is None:
        return False

    if stall_reason == PATH_FOLLOW_STALL_LIFETIME:
        abandon_move_target(world, entity)
        return True

    max_repath_attempts = path_policy["max_repath_attempts"]

    if target.get("repath_attempts", 0) >= max_repath_attempts:
        abandon_move_target(world, entity)
        return True

    if world.tick < target.get("next_repath_tick", world.tick):
        return False

    if not entity_can_attempt_path_build(
        world,
        entity,
        target,
    ):
        return False

    target["repath_attempts"] = target.get("repath_attempts", 0) + 1

    target["next_repath_tick"] = (
        world.tick + path_policy["repath_cooldown_ticks"]
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

    return not movement_collision_allows(handle_movement_tile_collision(
        world,
        mover_entity,
        tile,
    ))


def resolve_static_tile_movement(world, entity, start_cpos: Vec2i, delta: Vec2i):
    collision_result, resolved_cpos = trace_static_tile_path(
        world,
        entity,
        start_cpos,
        delta,
    )

    if movement_collision_slides(collision_result):
        return resolve_slide_static_tile_movement(
            world,
            entity,
            start_cpos,
            delta,
            collision_result,
        )

    return collision_result, resolved_cpos


def resolve_flow_chase_direct_movement(
    world,
    entity,
    controller,
    start_cpos: Vec2i,
    delta: Vec2i,
):
    collision_result, resolved_cpos = trace_static_tile_path(
        world,
        entity,
        start_cpos,
        delta,
    )

    if not (
            movement_collision_slides(collision_result)
            and collision_result.blocker_collision_type == "dynamic"
    ):
        controller.local_steering_no_progress_ticks = 0

    if (
            movement_collision_slides(collision_result)
            and collision_result.blocker_collision_type == "dynamic"
    ):
        record_counter_for_world(
            world,
            "flow_chase.local_steering.dynamic_slide_seen",
        )
        record_counter_for_world(
            world,
            "flow_chase.local_steering.dynamic_retry_attempt",
        )

        local_steering_result = try_resolve_flow_chase_local_steering(
            world,
            entity,
            controller,
            start_cpos,
            delta,
            collision_result,
        )

        if local_steering_result is not None:
            record_counter_for_world(
                world,
                "flow_chase.local_steering.dynamic_retry_resolved",
            )
            return local_steering_result

        record_counter_for_world(
            world,
            "flow_chase.local_steering.dynamic_retry_failed",
        )
        record_counter_for_world(
            world,
            "flow_chase.local_steering.dynamic_retry_failed_no_generic_slide",
        )

        return collision_result, resolved_cpos

    if movement_collision_slides(collision_result):
        return resolve_slide_static_tile_movement(
            world,
            entity,
            start_cpos,
            delta,
            collision_result,
        )

    return collision_result, resolved_cpos


def resolve_slide_static_tile_movement(world, entity, start_cpos: Vec2i, delta: Vec2i, slide_source_result=None):
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

        if movement_collision_allows(x_result):
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

        if movement_collision_allows(y_result):
            tangent = delta.y
            normal = delta.x

            if passes_slide_threshold(tangent, normal, ratio):
                options.append(("y", abs(tangent), y_cpos))

    if not options:
        return (
            make_movement_collision_result(
                "block",
                blocker_collision_type=getattr(slide_source_result, "blocker_collision_type", None),
                blocked_tile=getattr(slide_source_result, "blocked_tile", None)
            ),
            start_cpos,
        )

    # Pick the stronger valid slide component.
    # Tie-breaker is deterministic because "x" sorts before "y".
    options.sort(key=lambda item: (-item[1], item[0]))

    _, _, chosen_cpos = options[0]
    return MOVEMENT_COLLISION_ALLOW, chosen_cpos


def trace_static_tile_path(world, entity, start_cpos: Vec2i, delta: Vec2i):
    end_cpos = start_cpos + delta

    current_tile = tile_from_cpos(start_cpos)
    target_tile = tile_from_cpos(end_cpos)

    if current_tile == target_tile:
        return MOVEMENT_COLLISION_ALLOW, end_cpos

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

            if not movement_collision_allows(collision_result):
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

            if not movement_collision_allows(collision_result):
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

            if not movement_collision_allows(collision_result):
                return collision_result, safe_cpos

            current_tile = diagonal_tile

            next_cross_x += TILE_UNITS
            next_cross_y += TILE_UNITS

    return MOVEMENT_COLLISION_ALLOW, end_cpos


def set_move_target(
    world,
    entity,
    target_tile: Vec2i,
    target_cpos=None,
    path_policy="actor_move",
    owner_order_id=None,
):
    if target_cpos is None:
        target_cpos = tile_center(target_tile)

    existing_target = world.move_target.get(entity)
    owner_changed = (
            existing_target is not None
            and existing_target.get("owner_order_id") != owner_order_id
    )
    if existing_target is None or owner_changed:
        created_tick = world.tick
        repath_attempts = 0
        next_repath_tick = world.tick
    else:
        created_tick = existing_target.get("created_tick", world.tick)
        repath_attempts = existing_target.get("repath_attempts", 0)
        next_repath_tick = existing_target.get("next_repath_tick", world.tick)

    world.move_target[entity] = {
        "type": "target_tile",
        "target_tile": target_tile,
        "target_cpos": target_cpos,
        "path_policy": path_policy,
        "owner_order_id": owner_order_id,
        "created_tick": created_tick,
        "repath_attempts": repath_attempts,
        "next_repath_tick": next_repath_tick,
    }


def set_flow_field_move_target(
    world,
    entity,
    target_entity,
    desired_range_tiles,
    max_radius_tiles,
    path_policy,
    flow_policy,
    lookahead_nodes,
    owner_order_id=None,
):
    existing_target = world.move_target.get(entity)

    owner_changed = (
        existing_target is not None
        and existing_target.get("owner_order_id") != owner_order_id
    )

    if existing_target is None:
        target_changed = True

    elif existing_target.get("type") != "flow_field_to_entity":
        target_changed = True

    else:
        target_changed = (
            existing_target["target_entity"] != target_entity
            or existing_target["desired_range_tiles"] != desired_range_tiles
            or existing_target["max_radius_tiles"] != max_radius_tiles
            or existing_target["path_policy"] != path_policy
            or existing_target["flow_policy"] != flow_policy
            or existing_target["lookahead_nodes"] != lookahead_nodes
        )

    if existing_target is None or owner_changed or target_changed:
        created_tick = world.tick
        repath_attempts = 0
        next_repath_tick = world.tick

    else:
        created_tick = existing_target.get("created_tick", world.tick)
        repath_attempts = existing_target.get("repath_attempts", 0)
        next_repath_tick = existing_target.get("next_repath_tick", world.tick)

    world.move_target[entity] = {
        "type": "flow_field_to_entity",
        "target_entity": target_entity,
        "desired_range_tiles": desired_range_tiles,
        "max_radius_tiles": max_radius_tiles,
        "path_policy": path_policy,
        "flow_policy": flow_policy,
        "owner_order_id": owner_order_id,
        "created_tick": created_tick,
        "repath_attempts": repath_attempts,
        "next_repath_tick": next_repath_tick,
        "lookahead_nodes": lookahead_nodes,
    }


def clear_move_target(world, entity):
    world.move_target.pop(entity, None)
    clear_path_build_state(world, entity)


def cancel_move_target_for_directional_input(world, entity):
    clear_move_target(world, entity)
    clear_failed_path_queries_for_entity(world, entity)


def move_target_owner_is_current(world, entity):
    target = world.move_target.get(entity)
    if target is None:
        return True

    owner_order_id = target.get("owner_order_id")

    # Legacy/direct movement target with no owner is allowed for now.
    # After migration, these should disappear.
    if owner_order_id is None:
        return True

    order = world.action_order.get(entity)
    if order is None:
        return False

    return order.get("order_id") == owner_order_id


def clear_stale_order_owned_move_target(world, entity):
    if move_target_owner_is_current(world, entity):
        return False

    clear_move_target(world, entity)

    motion_state = world.motion_state.get(entity)
    if motion_state is not None:
        controller = motion_state.get("controller")
        if (
            isinstance(controller, PathFollowController)
            and motion_state.get("controller_source") == "move_target"
        ):
            clear_motion_controller(motion_state)
            request_settle_when_allowed(world, entity)
            start_requested_settle_if_allowed(world, entity)

    return True


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

            if not movement_collision_allows(collision_result):
                return collision_result

        return MOVEMENT_COLLISION_ALLOW

    if corner_policy == "allow_if_one_side_open":
        diagonal_result = handle_movement_tile_collision(
            world,
            entity,
            diagonal_tile,
        )

        if not movement_collision_allows(diagonal_result):
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

        if movement_collision_allows(side_x_result) or movement_collision_allows(side_y_result):
            return MOVEMENT_COLLISION_ALLOW

        # Both side-adjacent tiles are blocked. Return one of the blocked
        # results so the normal collision response can handle it.
        if not movement_collision_allows(side_x_result):
            return side_x_result

        return side_y_result

    raise ValueError(f"Unknown corner_cutting policy: {corner_policy}")


def handle_static_tile_collision(world, entity, next_tile):
    policy = world.movement_collision[entity]
    behavior = policy["static_tiles"]

    if behavior == "allow":
        return MOVEMENT_COLLISION_ALLOW

    if is_static_movement_placement_blocked(
        world,
        entity,
        next_tile,
    ):
        return make_movement_collision_result(behavior, blocker_collision_type="static", blocked_tile=next_tile)

    return MOVEMENT_COLLISION_ALLOW


def get_movement_collision_debug_context(world):
    return getattr(
        world,
        "_movement_collision_debug_context",
        "unknown",
    )


def push_movement_collision_debug_context(world, context):
    previous_context = get_movement_collision_debug_context(world)
    world._movement_collision_debug_context = context
    return previous_context


def pop_movement_collision_debug_context(world, previous_context):
    world._movement_collision_debug_context = previous_context


def record_dynamic_movement_block_counter(world, entity):
    record_counter_for_world(
        world,
        "movement.dynamic_block",
    )
    record_counter_for_world(
        world,
        f"movement.dynamic_block.context.{get_movement_collision_debug_context(world)}",
    )

    target = world.move_target.get(entity)
    if target is not None:
        record_counter_for_world(
            world,
            f"movement.dynamic_block.target.{target['type']}",
        )

    motion_state = world.motion_state.get(entity)
    if motion_state is None:
        record_counter_for_world(
            world,
            "movement.dynamic_block.controller.none",
        )
        return

    controller = motion_state.get("controller")
    if controller is None:
        record_counter_for_world(
            world,
            "movement.dynamic_block.controller.none",
        )
        return

    if isinstance(controller, PathFollowController):
        record_counter_for_world(
            world,
            "movement.dynamic_block.controller.path_follow",
        )
        return

    if isinstance(controller, FlowChaseDirectController):
        record_counter_for_world(
            world,
            "movement.dynamic_block.controller.flow_chase_direct",
        )
        return

    if isinstance(controller, DirectionalMoveController):
        record_counter_for_world(
            world,
            "movement.dynamic_block.controller.directional",
        )
        return

    if isinstance(controller, GridMoveController):
        record_counter_for_world(
            world,
            "movement.dynamic_block.controller.grid_move",
        )
        return

    if isinstance(controller, SettleToGridController):
        record_counter_for_world(
            world,
            "movement.dynamic_block.controller.settle",
        )
        return

    record_counter_for_world(
        world,
        "movement.dynamic_block.controller.other",
    )


def record_dynamic_movement_block_source_counters(world, blocker_sources):
    current_body_on_center = bool(
        blocker_sources.get("current_body_on_center")
    )
    current_center_on_body = bool(
        blocker_sources.get("current_center_on_body")
    )
    reserved_body_on_center = bool(
        blocker_sources.get("reserved_body_on_center")
    )
    reserved_center_on_body = bool(
        blocker_sources.get("reserved_center_on_body")
    )

    has_current = current_body_on_center or current_center_on_body
    has_reserved = reserved_body_on_center or reserved_center_on_body

    if not has_current and not has_reserved:
        record_counter_for_world(
            world,
            "movement.dynamic_block.source.unknown",
        )
        return

    if has_current:
        record_counter_for_world(
            world,
            "movement.dynamic_block.source.current",
        )

    if has_reserved:
        record_counter_for_world(
            world,
            "movement.dynamic_block.source.reserved",
        )

    if has_current and has_reserved:
        record_counter_for_world(
            world,
            "movement.dynamic_block.source.current_and_reserved",
        )
    elif has_current:
        record_counter_for_world(
            world,
            "movement.dynamic_block.source.current_only",
        )
    else:
        record_counter_for_world(
            world,
            "movement.dynamic_block.source.reserved_only",
        )

    if current_body_on_center:
        record_counter_for_world(
            world,
            "movement.dynamic_block.source.current_body_on_center",
        )

    if current_center_on_body:
        record_counter_for_world(
            world,
            "movement.dynamic_block.source.current_center_on_body",
        )

    if reserved_body_on_center:
        record_counter_for_world(
            world,
            "movement.dynamic_block.source.reserved_body_on_center",
        )

    if reserved_center_on_body:
        record_counter_for_world(
            world,
            "movement.dynamic_block.source.reserved_center_on_body",
        )


def get_dynamic_blocker_controller_label(world, blocker_entity):
    motion_state = world.motion_state.get(blocker_entity)

    if motion_state is None:
        return "no_motion_state"

    controller = motion_state.get("controller")

    if controller is None:
        return "none"

    if isinstance(controller, PathFollowController):
        return "path_follow"

    if isinstance(controller, FlowChaseDirectController):
        return "flow_chase_direct"

    if isinstance(controller, DirectionalMoveController):
        return "directional"

    if isinstance(controller, GridMoveController):
        return "grid_move"

    if isinstance(controller, SettleToGridController):
        return "settle"

    return "other"


def record_dynamic_movement_blocker_state_counters(world, blocker_sources):
    all_blockers = set()

    current_blockers = set()
    reserved_blockers = set()

    for source_name, source_blockers in blocker_sources.items():
        all_blockers.update(source_blockers)

        if source_name.startswith("current_"):
            current_blockers.update(source_blockers)

        if source_name.startswith("reserved_"):
            reserved_blockers.update(source_blockers)

    for blocker_entity in all_blockers:
        controller_label = get_dynamic_blocker_controller_label(
            world,
            blocker_entity,
        )
        record_counter_for_world(
            world,
            f"movement.dynamic_block.blocker_controller.{controller_label}",
        )

    for blocker_entity in current_blockers:
        controller_label = get_dynamic_blocker_controller_label(
            world,
            blocker_entity,
        )
        record_counter_for_world(
            world,
            f"movement.dynamic_block.current_blocker_controller.{controller_label}",
        )

    for blocker_entity in reserved_blockers:
        controller_label = get_dynamic_blocker_controller_label(
            world,
            blocker_entity,
        )
        record_counter_for_world(
            world,
            f"movement.dynamic_block.reserved_blocker_controller.{controller_label}",
        )


def handle_dynamic_movement_collision(world, entity, next_tile):
    policy = world.movement_collision[entity]
    behavior = policy["dynamic_blockers"]

    if behavior == "allow":
        return MOVEMENT_COLLISION_ALLOW

    proposed_body_tiles = get_movement_body_tiles_for_origin_tile(
        world,
        entity,
        next_tile,
    )

    blockers = get_dynamic_movement_blockers_for_placement(
        world,
        mover_entity=entity,
        proposed_center_tile=next_tile,
        proposed_body_tiles=proposed_body_tiles,
        include_reservations=True,
    )

    if blockers:
        blocker_sources = get_dynamic_movement_blocker_sources_for_placement(
            world,
            mover_entity=entity,
            proposed_center_tile=next_tile,
            proposed_body_tiles=proposed_body_tiles,
            include_reservations=True,
        )

        record_dynamic_movement_block_counter(
            world,
            entity,
        )
        record_dynamic_movement_block_source_counters(
            world,
            blocker_sources,
        )
        record_dynamic_movement_blocker_state_counters(
            world,
            blocker_sources,
        )

        return make_movement_collision_result(
            behavior,
            blocker_collision_type="dynamic",
            blocked_tile=next_tile,
            blocker_entity=blockers[0],
        )

    return MOVEMENT_COLLISION_ALLOW


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

    if not movement_collision_allows(static_result):
        return static_result

    dynamic_result = handle_dynamic_movement_collision(
        world,
        entity,
        next_tile,
    )

    if not movement_collision_allows(dynamic_result):
        return dynamic_result

    return MOVEMENT_COLLISION_ALLOW


def get_locomotion_speed_cpos_per_tick(locomotion):
    speed = locomotion["speed_cpos_per_tick"]

    if speed <= 0:
        raise ValueError(
            f"speed_cpos_per_tick must be positive, got {speed!r}"
        )

    return speed


def get_grid_move_duration_from_speed(locomotion):
    speed = get_locomotion_speed_cpos_per_tick(locomotion)

    return max(
        1,
        (TILE_UNITS + speed - 1) // speed,
    )


def get_greedy_fallback_direction(current_tile, target_tile):
    return Vec2i(
        sign(target_tile.x - current_tile.x),
        sign(target_tile.y - current_tile.y),
    )


def build_direct_fallback_nodes(world, entity, target, path_policy):
    if not path_policy["direct_fallback_on_fail"]:
        return None

    current_tile = get_navigation_start_tile(world, entity)
    target_tile = target["target_tile"]

    if current_tile == target_tile:
        return None

    max_steps = path_policy["direct_fallback_max_tiles"]
    min_steps = path_policy["direct_fallback_min_tiles"]

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

        if not movement_collision_allows(collision_result):
            break

        fallback_tiles.append(next_tile)
        visited_tiles.add(next_tile)
        current_tile = next_tile

    if len(fallback_tiles) < min_steps:
        return None

    return path_tiles_to_cpos_nodes(fallback_tiles)


@profiled("path.build")
def build_path_follow_nodes(world, entity, target):
    locomotion = world.locomotion[entity]

    current_tile = get_navigation_start_tile(world, entity)
    target_tile = target["target_tile"]

    if current_tile == target_tile:
        return []

    path_policy_name = get_path_policy_name(target)
    path_policy = get_path_policy(world, target)

    dynamic_blocker_context = None
    dynamic_blocker_key = None

    if path_query_key_needs_dynamic_blocker_context(path_policy):
        dynamic_blocker_context = build_path_dynamic_blocker_context(
            world,
            entity,
            current_tile,
            path_policy,
        )
        dynamic_blocker_key = get_path_dynamic_blocker_key(
            dynamic_blocker_context,
        )

    query_key = make_path_query_key(
        entity,
        current_tile,
        target_tile,
        path_policy_name,
        dynamic_blocker_key,
        path_policy,
    )

    if path_query_failed_recently(world, query_key):
        record_counter_for_world(
            world,
            "path.build.skipped_failed_cache",
        )
        return build_direct_fallback_nodes(
            world,
            entity,
            target,
            path_policy,
        )

    if not path_build_budget_allows(
        world,
        path_policy_name,
        path_policy,
    ):
        record_counter_for_world(
            world,
            "path.build.deferred_budget",
        )
        return PATH_BUILD_DEFERRED

    if not path_query_key_needs_dynamic_blocker_context(path_policy):
        dynamic_blocker_context = build_path_dynamic_blocker_context(
            world,
            entity,
            current_tile,
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
        dynamic_blocker_context=dynamic_blocker_context,
        max_candidate_goals=path_policy["target_snap_candidate_limit"],
    )

    if path_tiles is None:
        remember_failed_path_query(
            world,
            query_key,
            path_policy["failed_retry_ticks"],
        )
        return build_direct_fallback_nodes(
            world,
            entity,
            target,
            path_policy,
        )

    clear_failed_path_query(world, query_key)

    smooth_max = path_policy["smooth_max_path_length"]

    if smooth_max is not None and len(path_tiles) > smooth_max:
        smoothed_tiles = path_tiles

    else:
        smoothed_tiles = smooth_static_tile_path(
            world,
            entity,
            current_tile,
            path_tiles,
            dynamic_blocker_context=dynamic_blocker_context,
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
        speed=get_locomotion_speed_cpos_per_tick(locomotion),
        created_tick=world.tick,
        target_tile=target_tile,
    )

    if using_buffered_intent:
        motion_state["controller_source"] = "buffered_move"
    else:
        motion_state["controller_source"] = "move_intent"

    if entity in world.facing:
        world.facing[entity] = resolved_direction

    refresh_moved_entity_occupancy(
        world,
        entity,
    )
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
        duration=get_grid_move_duration_from_speed(locomotion),
    )

    if using_buffered_intent:
        motion_state["controller_source"] = "buffered_move"
    else:
        motion_state["controller_source"] = "move_intent"

    if entity in world.facing:
        world.facing[entity] = resolved_direction

    refresh_moved_entity_occupancy(
        world,
        entity,
    )
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

    motion_state["controller"] = DirectionalMoveController(
        aim_vector=aim_vector,
        raw_direction=desired_direction,
        speed=get_locomotion_speed_cpos_per_tick(locomotion),
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

    controller.aim_vector = aim_vector
    controller.raw_direction = desired_direction
    controller.speed = get_locomotion_speed_cpos_per_tick(locomotion)

    if entity in world.facing:
        world.facing[entity] = desired_direction

    return True


def stop_directional_continuous_controller(world, entity):
    motion_state = world.motion_state[entity]

    clear_motion_controller(motion_state)

    refresh_moved_entity_occupancy(
        world,
        entity,
    )

    request_settle_when_allowed(world, entity)
    start_requested_settle_if_allowed(world, entity)


def get_flow_chase_target_entity(world, target):
    target_entity = target["target_entity"]

    if target_entity not in world.transform:
        return None

    return target_entity


def get_flow_chase_target_cpos(world, target):
    target_entity = get_flow_chase_target_entity(
        world,
        target,
    )

    if target_entity is None:
        return None

    target_tile = tile_from_cpos(
        world.transform[target_entity].cpos,
    )

    return tile_center(
        target_tile,
    )


def flow_chase_entity_in_desired_range(world, entity, target):
    target_cpos = get_flow_chase_target_cpos(
        world,
        target,
    )

    if target_cpos is None:
        return False

    current_tile = tile_from_cpos(
        world.transform[entity].cpos,
    )
    target_tile = tile_from_cpos(
        target_cpos,
    )

    return (
        chebyshev_tile_distance(
            current_tile,
            target_tile,
        )
        <= target["desired_range_tiles"]
    )


def get_flow_chase_raw_vector(world, entity, target):
    target_cpos = get_flow_chase_target_cpos(
        world,
        target,
    )

    if target_cpos is None:
        return None

    return target_cpos - world.transform[entity].cpos


def discard_reached_flow_chase_steering_points(world, entity, controller):
    transform = world.transform[entity]

    while (
        controller.steering_points
        and is_at_cpos(transform.cpos, controller.steering_points[0])
    ):
        controller.steering_points.pop(0)
        record_counter_for_world(
            world,
            "flow_chase.steering.point_reached",
        )


def get_flow_chase_active_target_cpos(controller):
    if controller.steering_points:
        return controller.steering_points[0]

    return controller.base_target_cpos


def flow_chase_manual_steering_test_applies_to_entity(entity):
    return (
        FLOW_CHASE_MANUAL_STEERING_TEST_ENTITY is None
        or entity == FLOW_CHASE_MANUAL_STEERING_TEST_ENTITY
    )


def build_manual_flow_chase_steering_points(world, entity, base_target_cpos):
    start_cpos = world.transform[entity].cpos
    raw_forward = base_target_cpos - start_cpos
    forward_dir = normalize_vector_to_dir_scale(raw_forward)

    if forward_dir is None:
        return []

    raw_side = Vec2i(
        -raw_forward.y * FLOW_CHASE_MANUAL_STEERING_TEST_SIDE,
        raw_forward.x * FLOW_CHASE_MANUAL_STEERING_TEST_SIDE,
    )
    side_dir = normalize_vector_to_dir_scale(raw_side)

    if side_dir is None:
        return []

    side_step = scale_normalized_dir(
        side_dir,
        FLOW_CHASE_MANUAL_STEERING_TEST_SIDE_CPOS,
    )
    forward_step = scale_normalized_dir(
        forward_dir,
        FLOW_CHASE_MANUAL_STEERING_TEST_FORWARD_CPOS,
    )

    return [
        start_cpos + side_step,
        start_cpos + side_step + forward_step,
    ]


def maybe_install_manual_flow_chase_steering_test(
    world,
    entity,
    controller,
    base_target_cpos,
):
    if not FLOW_CHASE_MANUAL_STEERING_TEST_ENABLED:
        return

    if not flow_chase_manual_steering_test_applies_to_entity(entity):
        return

    if getattr(controller, "manual_steering_test_installed", False):
        return

    if controller.steering_points:
        return

    steering_points = build_manual_flow_chase_steering_points(
        world,
        entity,
        base_target_cpos,
    )

    if not steering_points:
        return

    controller.steering_points = steering_points
    controller.manual_steering_test_installed = True

    record_counter_for_world(
        world,
        "flow_chase.manual_steering_test.installed",
    )
    record_counter_for_world(
        world,
        f"flow_chase.manual_steering_test.points.{len(steering_points)}",
    )


def clear_stale_flow_chase_local_steering_side(world, controller):
    if controller.local_steering_side == 0:
        return

    if (
        world.tick - controller.local_steering_last_tick
        <= FLOW_CHASE_LOCAL_STEERING_SIDE_PERSIST_TICKS
    ):
        return

    controller.local_steering_side = 0
    controller.local_steering_last_tick = -1
    controller.local_steering_last_delta = Vec2i(0, 0)
    controller.local_steering_no_progress_ticks = 0


def flow_chase_local_steering_makes_progress(
    controller,
    start_cpos,
    candidate_cpos,
):
    before_distance = cpos_distance(
        start_cpos,
        controller.base_target_cpos,
    )
    after_distance = cpos_distance(
        candidate_cpos,
        controller.base_target_cpos,
    )

    return after_distance < before_distance


def flow_chase_local_steering_pure_side_allowed(controller):
    return (
        controller.local_steering_no_progress_ticks
        >= FLOW_CHASE_LOCAL_STEERING_PURE_SIDE_MIN_NO_PROGRESS_TICKS
    )


def update_flow_chase_local_steering_progress_state(
    world,
    controller,
    start_cpos,
    candidate_cpos,
):
    if flow_chase_local_steering_makes_progress(
        controller,
        start_cpos,
        candidate_cpos,
    ):
        controller.local_steering_no_progress_ticks = 0
        record_counter_for_world(
            world,
            "flow_chase.local_steering.progress_state.reset",
        )
        return

    controller.local_steering_no_progress_ticks += 1
    record_counter_for_world(
        world,
        "flow_chase.local_steering.progress_state.no_progress_tick",
    )


def update_flow_chase_direct_controller_values(
    world,
    entity,
    controller,
    base_target_cpos,
):
    controller.base_target_cpos = base_target_cpos

    clear_stale_flow_chase_local_steering_side(
        world,
        controller,
    )

    discard_reached_flow_chase_steering_points(
        world,
        entity,
        controller,
    )

    active_target_cpos = get_flow_chase_active_target_cpos(
        controller,
    )

    raw_vector = active_target_cpos - world.transform[entity].cpos
    aim_vector = normalize_vector_to_dir_scale(raw_vector)

    if aim_vector is None:
        return False

    controller.aim_vector = aim_vector
    controller.raw_vector = raw_vector
    controller.speed = get_locomotion_speed_cpos_per_tick(
        world.locomotion[entity],
    )

    if entity in world.facing:
        world.facing[entity] = Vec2i(
            sign(raw_vector.x),
            sign(raw_vector.y),
        )

    return True


def start_flow_chase_direct_controller(world, entity, target):
    target_entity = get_flow_chase_target_entity(
        world,
        target,
    )

    if target_entity is None:
        clear_move_target(world, entity)
        return False

    if flow_chase_entity_in_desired_range(
        world,
        entity,
        target,
    ):
        record_counter_for_world(
            world,
            "flow_chase.direct.in_desired_range",
        )
        return False

    if not world.locomotion[entity].get("can_move_8way", True):
        return False

    base_target_cpos = get_flow_chase_target_cpos(
        world,
        target,
    )

    if base_target_cpos is None:
        clear_move_target(world, entity)
        return False

    raw_vector = base_target_cpos - world.transform[entity].cpos
    aim_vector = normalize_vector_to_dir_scale(raw_vector)

    if aim_vector is None:
        return False

    controller = FlowChaseDirectController(
        target_entity=target_entity,
        desired_range_tiles=target["desired_range_tiles"],
        base_target_cpos=base_target_cpos,
        aim_vector=aim_vector,
        raw_vector=raw_vector,
        speed=get_locomotion_speed_cpos_per_tick(
            world.locomotion[entity],
        ),
    )

    motion_state = world.motion_state[entity]
    motion_state["controller"] = controller
    motion_state["controller_source"] = "flow_chase_direct"

    if entity in world.facing:
        world.facing[entity] = Vec2i(
            sign(raw_vector.x),
            sign(raw_vector.y),
        )

    refresh_moved_entity_occupancy(
        world,
        entity,
    )

    record_counter_for_world(
        world,
        "flow_chase.direct.start",
    )

    return True


def stop_flow_chase_direct_controller(world, entity):
    motion_state = world.motion_state[entity]
    clear_motion_controller(motion_state)
    refresh_moved_entity_occupancy(
        world,
        entity,
    )

    record_counter_for_world(
        world,
        "flow_chase.direct.stop",
    )


def update_flow_chase_direct_controller(world, entity, controller):
    target = world.move_target.get(entity)

    if target is None or target["type"] != "flow_field_to_entity":
        stop_flow_chase_direct_controller(
            world,
            entity,
        )
        return

    target_entity = get_flow_chase_target_entity(
        world,
        target,
    )

    if target_entity is None:
        clear_move_target(world, entity)
        stop_flow_chase_direct_controller(
            world,
            entity,
        )
        return

    if flow_chase_entity_in_desired_range(
        world,
        entity,
        target,
    ):
        stop_flow_chase_direct_controller(
            world,
            entity,
        )
        record_counter_for_world(
            world,
            "flow_chase.direct.stop_in_desired_range",
        )
        return

    base_target_cpos = get_flow_chase_target_cpos(
        world,
        target,
    )

    if base_target_cpos is None:
        clear_move_target(world, entity)
        stop_flow_chase_direct_controller(
            world,
            entity,
        )
        return

    updated = update_flow_chase_direct_controller_values(
        world,
        entity,
        controller,
        base_target_cpos,
    )

    if not updated:
        stop_flow_chase_direct_controller(
            world,
            entity,
        )
        return

    refresh_moved_entity_occupancy(
        world,
        entity,
    )

    record_counter_for_world(
        world,
        "flow_chase.direct.update",
    )


def install_path_follow_controller(world, entity, target, nodes):
    locomotion = world.locomotion[entity]
    motion_state = world.motion_state[entity]
    path_policy = get_path_policy(world, target)

    motion_state["controller"] = PathFollowController(
        nodes=nodes,
        current_index=0,
        speed=get_locomotion_speed_cpos_per_tick(locomotion),
        created_tick=world.tick,
        target_tile=target["target_tile"],
        block_response=path_policy["dynamic_block_response"],
    )

    motion_state["controller_source"] = "move_target"

    initialize_path_follow_progress(
        world,
        entity,
        motion_state["controller"],
    )

    refresh_moved_entity_occupancy(
        world,
        entity,
    )
    return True


def build_flow_field_lookahead_nodes(
    world,
    entity,
    flow_field,
    start_tile,
    first_direction,
    max_nodes,
    side_pressure_counts,
    side_pressure_weight,
):
    max_nodes = max(
        1,
        max_nodes,
    )

    nodes = []
    current_tile = start_tile
    direction = first_direction
    final_tile = start_tile

    for _ in range(max_nodes):
        next_tile = current_tile + direction

        if next_tile not in flow_field["distances"]:
            break

        nodes.append(
            tile_center(next_tile),
        )

        final_tile = next_tile
        current_tile = next_tile

        candidate_directions = get_flow_field_step_candidates_from_tile(
            world,
            entity,
            flow_field,
            current_tile,
            include_sideways=False,
            side_pressure_counts=side_pressure_counts,
            side_pressure_weight=side_pressure_weight,
        )

        if not candidate_directions:
            break

        direction = candidate_directions[0]

    return nodes, final_tile


def start_flow_field_controller(world, entity, target):
    record_counter_for_world(
        world,
        "flow_field.start.attempt",
    )

    target_entity = target["target_entity"]

    if target_entity not in world.transform:
        clear_move_target(world, entity)
        return False

    locomotion = world.locomotion[entity]
    current_tile = get_navigation_start_tile(
        world,
        entity,
    )

    flow_policy = target["flow_policy"]
    flow_field = get_or_build_flow_field(
        world,
        mover_entity=entity,
        target_entity=target_entity,
        desired_range_tiles=target["desired_range_tiles"],
        max_radius_tiles=target["max_radius_tiles"],
        can_move_8way=locomotion["can_move_8way"],
        rebuild_interval_ticks=flow_policy["rebuild_interval_ticks"],
        rebuild_distance_tiles=flow_policy["rebuild_distance_tiles"],
    )

    if flow_field is None:
        record_counter_for_world(
            world,
            "flow_field.start.no_field",
        )
        return False

    current_distance = flow_field["distances"].get(current_tile)

    target_tile = flow_field["target_tile"]

    side_pressure_counts = {}
    side_pressure_weight = 0

    if target_tile is not None:
        distance_to_target = max(
            abs(current_tile.x - target_tile.x),
            abs(current_tile.y - target_tile.y),
        )

        if distance_to_target <= flow_policy["engagement_pressure_radius_tiles"]:
            side_pressure_counts = get_flow_field_side_pressure_counts(
                world,
                entity,
                target_entity,
                target_tile,
                flow_policy["engagement_pressure_radius_tiles"],
            )
            side_pressure_weight = flow_policy[
                "engagement_side_pressure_weight"
            ]

            record_counter_for_world(
                world,
                "flow_field.pressure.active",
            )

    candidate_directions = get_flow_field_step_candidates(
        world,
        entity,
        flow_field,
        include_sideways=False,
        side_pressure_counts=side_pressure_counts,
        side_pressure_weight=side_pressure_weight,
    )

    if not candidate_directions:
        candidate_directions = get_flow_field_step_candidates(
            world,
            entity,
            flow_field,
            include_sideways=True,
            side_pressure_counts=side_pressure_counts,
            side_pressure_weight=side_pressure_weight,
        )

        if candidate_directions:
            record_counter_for_world(
                world,
                "flow_field.start.sideways_fallback",
            )

    if not candidate_directions:
        record_counter_for_world(
            world,
            "flow_field.start.no_direction",
        )
        return False

    for desired_direction in candidate_directions:
        record_counter_for_world(
            world,
            "flow_field.start.candidate_considered",
        )

        previous_collision_context = push_movement_collision_debug_context(
            world,
            "flow_field.start_candidate",
        )
        try:
            resolved_direction = resolve_grid_move_direction_from_tile(
                world,
                entity,
                current_tile,
                desired_direction,
                slide_vector=desired_direction,
                slide_context="grid",
            )
        finally:
            pop_movement_collision_debug_context(
                world,
                previous_collision_context,
            )

        if resolved_direction is None:
            record_counter_for_world(
                world,
                "flow_field.start.candidate_blocked",
            )
            record_counter_for_world(
                world,
                "flow_field.start.candidate_unresolved",
            )
            continue

        if resolved_direction == desired_direction:
            record_counter_for_world(
                world,
                "flow_field.start.candidate_direct_resolved",
            )
        else:
            record_counter_for_world(
                world,
                "flow_field.start.candidate_slide_resolved",
            )

        next_tile = current_tile + resolved_direction
        next_distance = flow_field["distances"].get(next_tile)

        if next_distance is None:
            record_counter_for_world(
                world,
                "flow_field.start.candidate_off_field",
            )
            continue

        if current_distance is not None:
            if next_distance > current_distance:
                record_counter_for_world(
                    world,
                    "flow_field.start.candidate_uphill",
                )
                continue

            if next_distance == current_distance:
                record_counter_for_world(
                    world,
                    "flow_field.start.sideways_step",
                )

        lookahead_nodes = target["lookahead_nodes"]

        nodes, final_tile = build_flow_field_lookahead_nodes(
            world,
            entity,
            flow_field,
            current_tile,
            resolved_direction,
            lookahead_nodes,
            side_pressure_counts,
            side_pressure_weight,
        )

        record_counter_for_world(
            world,
            "flow_field.start.lookahead_nodes",
            len(nodes),
        )

        if not nodes:
            record_counter_for_world(
                world,
                "flow_field.start.no_lookahead_nodes",
            )
            continue

        motion_state = world.motion_state[entity]

        motion_state["controller"] = PathFollowController(
            nodes=nodes,
            current_index=0,
            speed=get_locomotion_speed_cpos_per_tick(locomotion),
            created_tick=world.tick,
            target_tile=final_tile,
            block_response=BLOCK_RESPONSE_ABORT,
        )
        motion_state["controller_source"] = "move_target"

        if entity in world.facing:
            world.facing[entity] = resolved_direction

        initialize_path_follow_progress(
            world,
            entity,
            motion_state["controller"],
        )

        refresh_moved_entity_occupancy(
            world,
            entity,
        )

        if resolved_direction == desired_direction:
            record_counter_for_world(
                world,
                "flow_field.start.success",
            )

        else:
            record_counter_for_world(
                world,
                "flow_field.start.slide_success",
            )

        return True

    record_counter_for_world(
        world,
        "flow_field.start.blocked",
    )

    return False


def start_path_follow_controller(world, entity, target):
    if target["type"] == "flow_field_to_entity":
        if start_flow_chase_direct_controller(
            world,
            entity,
            target,
        ):
            return True

        return start_flow_field_controller(
            world,
            entity,
            target,
        )

    path_policy = get_path_policy(world, target)
    nodes = build_path_follow_nodes(
        world,
        entity,
        target,
    )

    if nodes is PATH_BUILD_DEFERRED:
        return False

    if nodes is None:
        if path_policy["clear_target_on_path_fail"]:
            clear_move_target(world, entity)

        return False

    if not nodes:
        if path_policy["clear_target_on_path_finish"]:
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

    if hasattr(controller, "_pending_steering_points"):
        delattr(controller, "_pending_steering_points")


def path_follow_target_changed(controller, target):
    return target["target_tile"] != controller.target_tile


def should_refresh_path_follow_controller(world, entity, controller):
    target = world.move_target.get(entity)

    if target is None:
        return False

    if target["type"] != "target_tile":
        return False

    path_policy = get_path_policy(world, target)
    target_changed = path_follow_target_changed(controller, target)

    if target_changed:
        if not path_policy["retarget_active_path_on_target_change"]:
            return False
    else:
        if not path_policy["active_path_refresh_enabled"]:
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

    # Refresh is non-destructive.
    # If the current world state cannot
    # produce a usable replacement path, keep following the existing
    # controller and let the normal movement pipeline continue.
    if nodes is PATH_BUILD_DEFERRED:
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

        if not movement_collision_allows(collision_result):
            return collision_result, start_cpos, steps

        return MOVEMENT_COLLISION_ALLOW, end_cpos, steps

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

            return make_movement_collision_result("block"), start_cpos, steps

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

            if not movement_collision_allows(collision_result):
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

            if not movement_collision_allows(collision_result):
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

            if not movement_collision_allows(collision_result):
                return collision_result, safe_cpos, steps

            current_tile = diagonal_tile
            next_cross_x += TILE_UNITS
            next_cross_y += TILE_UNITS

    return MOVEMENT_COLLISION_ALLOW, end_cpos, steps


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
            f"{placement_result.collision_result:<10} "
            f"{center_trace_result.collision_result:<12} "
            f"{current_trace_result.collision_result:<13}"
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


def finish_controller_after_block_if_needed(world, entity, controller):
    if controller is None:
        return False

    if not controller.finished():
        return False

    motion_state = world.motion_state[entity]
    transform = world.transform[entity]

    if hasattr(controller, "end"):
        transform.cpos = controller.end

    transform.tile = tile_from_cpos(transform.cpos)

    clear_motion_controller(motion_state)

    request_settle_when_allowed(world, entity)
    start_requested_settle_if_allowed(world, entity)

    return True


def get_controller_block_response(controller):
    return getattr(controller, "block_response")


def controller_ages_on_block(controller):
    return get_controller_block_response(controller) == BLOCK_RESPONSE_AGE


def controller_aborts_on_block(controller):
    return get_controller_block_response(controller) == BLOCK_RESPONSE_ABORT


def controller_retries_on_block(controller):
    return get_controller_block_response(controller) == BLOCK_RESPONSE_RETRY


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


def flow_chase_movement_was_modified(
    controller,
    requested_cpos,
    resolved_cpos,
):
    if not isinstance(controller, FlowChaseDirectController):
        return False

    return resolved_cpos != requested_cpos


def flow_chase_vec_distance_sq(a: Vec2i, b: Vec2i) -> int:
    dx = a.x - b.x
    dy = a.y - b.y
    return dx * dx + dy * dy


def flow_chase_vec_distance(a: Vec2i, b: Vec2i) -> int:
    return isqrt(flow_chase_vec_distance_sq(a, b))


def flow_chase_scale_vec_ratio(vec: Vec2i, numerator: int, denominator: int) -> Vec2i:
    return Vec2i(
        vec.x * numerator // denominator,
        vec.y * numerator // denominator,
    )


def flow_chase_dot_vec(a: Vec2i, b: Vec2i) -> int:
    return a.x * b.x + a.y * b.y


def flow_chase_candidate_delta_from_raw(raw_delta: Vec2i, speed: int) -> Vec2i:
    aim_vector = normalize_vector_to_dir_scale(raw_delta)

    if aim_vector is None:
        return Vec2i(0, 0)

    return scale_normalized_dir(
        aim_vector,
        speed,
    )


def build_flow_chase_proactive_candidates(base_delta: Vec2i, speed: int):
    if not vec_is_nonzero(base_delta):
        return []

    left_side_delta = Vec2i(
        -base_delta.y,
        base_delta.x,
    )
    right_side_delta = Vec2i(
        base_delta.y,
        -base_delta.x,
    )

    return [
        (
            "direct",
            0,
            base_delta,
        ),
        (
            "forward_left_small",
            -1,
            flow_chase_candidate_delta_from_raw(
                base_delta + flow_chase_scale_vec_ratio(left_side_delta, 1, 4),
                speed,
            ),
        ),
        (
            "forward_right_small",
            1,
            flow_chase_candidate_delta_from_raw(
                base_delta + flow_chase_scale_vec_ratio(right_side_delta, 1, 4),
                speed,
            ),
        ),
        (
            "forward_left_wide",
            -1,
            flow_chase_candidate_delta_from_raw(
                base_delta + flow_chase_scale_vec_ratio(left_side_delta, 1, 2),
                speed,
            ),
        ),
        (
            "forward_right_wide",
            1,
            flow_chase_candidate_delta_from_raw(
                base_delta + flow_chase_scale_vec_ratio(right_side_delta, 1, 2),
                speed,
            ),
        ),
        (
            "forward_left_very_wide",
            -1,
            flow_chase_candidate_delta_from_raw(
                base_delta + flow_chase_scale_vec_ratio(left_side_delta, 3, 4),
                speed,
            ),
        ),
        (
            "forward_right_very_wide",
            1,
            flow_chase_candidate_delta_from_raw(
                base_delta + flow_chase_scale_vec_ratio(right_side_delta, 3, 4),
                speed,
            ),
        ),
        (
            "side_left_forward",
            -1,
            flow_chase_candidate_delta_from_raw(
                left_side_delta + flow_chase_scale_vec_ratio(base_delta, 1, 4),
                speed,
            ),
        ),
        (
            "side_right_forward",
            1,
            flow_chase_candidate_delta_from_raw(
                right_side_delta + flow_chase_scale_vec_ratio(base_delta, 1, 4),
                speed,
            ),
        ),
    ]


def get_flow_chase_same_target_neighbor_cposes(
    world,
    entity,
    controller,
):
    current_cpos = world.transform[entity].cpos
    radius_sq = (
        FLOW_CHASE_PROACTIVE_NEIGHBOR_RADIUS_CPOS
        * FLOW_CHASE_PROACTIVE_NEIGHBOR_RADIUS_CPOS
    )

    neighbors = []

    for other_entity, other_transform in world.transform.items():
        if other_entity == entity:
            continue

        other_motion_state = world.motion_state.get(other_entity)

        if other_motion_state is None:
            continue

        other_controller = other_motion_state.get("controller")

        if not isinstance(other_controller, FlowChaseDirectController):
            continue

        if other_controller.target_entity != controller.target_entity:
            continue

        distance_sq = flow_chase_vec_distance_sq(
            current_cpos,
            other_transform.cpos,
        )

        if distance_sq > radius_sq:
            continue

        neighbors.append(
            (
                distance_sq,
                other_entity,
                other_transform.cpos,
            )
        )

    neighbors.sort(
        key=lambda item: (
            item[0],
            item[1],
        )
    )

    return [
        neighbor_cpos
        for _distance_sq, _other_entity, neighbor_cpos in neighbors
    ]


def score_flow_chase_neighbor_clearance(
    candidate_cpos: Vec2i,
    neighbor_cposes,
):
    score = 0

    for neighbor_cpos in neighbor_cposes:
        distance = flow_chase_vec_distance(
            candidate_cpos,
            neighbor_cpos,
        )

        if distance >= FLOW_CHASE_PROACTIVE_NEIGHBOR_RADIUS_CPOS:
            continue

        score -= (
            FLOW_CHASE_PROACTIVE_NEIGHBOR_RADIUS_CPOS - distance
        ) * FLOW_CHASE_PROACTIVE_CLEARANCE_WEIGHT

    return score


def is_flow_chase_proactive_candidate_clean(candidate):
    collision_result = candidate["collision_result"]

    if movement_collision_destroys(collision_result):
        return False

    if movement_collision_blocks(collision_result):
        return False

    if movement_collision_slides(collision_result):
        if collision_result.blocker_collision_type == "dynamic":
            return False

        return FLOW_CHASE_PROACTIVE_ALLOW_STATIC_SLIDE

    if not candidate["resolved_enough"]:
        return False

    if candidate["resolved_cpos"] == candidate["start_cpos"]:
        return False

    return True


def score_flow_chase_proactive_candidate(
    world,
    entity,
    controller,
    start_cpos: Vec2i,
    base_delta: Vec2i,
    label,
    side,
    candidate_delta: Vec2i,
    neighbor_cposes,
):
    if not vec_is_nonzero(candidate_delta):
        return None

    previous_collision_context = push_movement_collision_debug_context(
        world,
        "flow_chase.proactive_candidate",
    )
    try:
        collision_result, resolved_cpos = trace_static_tile_path(
            world,
            entity,
            start_cpos,
            candidate_delta,
        )
    finally:
        pop_movement_collision_debug_context(
            world,
            previous_collision_context,
        )

    if movement_collision_destroys(collision_result):
        record_counter_for_world(
            world,
            f"flow_chase.proactive_candidate.destroyed.{label}",
        )
        return None

    before_distance = flow_chase_vec_distance(
        start_cpos,
        controller.base_target_cpos,
    )
    after_distance = flow_chase_vec_distance(
        resolved_cpos,
        controller.base_target_cpos,
    )

    progress = before_distance - after_distance

    requested_distance = flow_chase_vec_distance(
        start_cpos,
        start_cpos + candidate_delta,
    )
    resolved_distance = flow_chase_vec_distance(
        start_cpos,
        resolved_cpos,
    )

    resolved_enough = flow_chase_local_steering_resolved_enough(
        start_cpos,
        resolved_cpos,
        candidate_delta,
    )

    score = progress

    if label == "direct":
        score += FLOW_CHASE_PROACTIVE_DIRECT_BIAS

    score += score_flow_chase_neighbor_clearance(
        resolved_cpos,
        neighbor_cposes,
    )

    previous_side = getattr(
        controller,
        "local_steering_side",
        0,
    )

    if side != 0 and previous_side != 0:
        if side == previous_side:
            score += FLOW_CHASE_PROACTIVE_SIDE_CONTINUITY_BONUS
        else:
            score -= FLOW_CHASE_PROACTIVE_SIDE_SWITCH_PENALTY

    if movement_collision_slides(collision_result):
        if collision_result.blocker_collision_type == "dynamic":
            score -= FLOW_CHASE_PROACTIVE_DYNAMIC_COLLISION_PENALTY
            record_counter_for_world(
                world,
                f"flow_chase.proactive_candidate.dynamic_collision.{label}",
            )
        else:
            score -= FLOW_CHASE_PROACTIVE_STATIC_COLLISION_PENALTY
            record_counter_for_world(
                world,
                f"flow_chase.proactive_candidate.static_collision.{label}",
            )

    if movement_collision_blocks(collision_result):
        score -= FLOW_CHASE_PROACTIVE_STATIC_COLLISION_PENALTY
        record_counter_for_world(
            world,
            f"flow_chase.proactive_candidate.blocked.{label}",
        )

    if resolved_distance < requested_distance:
        score -= (
            requested_distance - resolved_distance
        ) * FLOW_CHASE_PROACTIVE_PARTIAL_MOVE_PENALTY // max(
            1,
            TILE_UNITS,
        )

        record_counter_for_world(
            world,
            f"flow_chase.proactive_candidate.partial.{label}",
        )

    if not resolved_enough:
        record_counter_for_world(
            world,
            f"flow_chase.proactive_candidate.rejected_partial.{label}",
        )

    if after_distance < before_distance:
        record_counter_for_world(
            world,
            f"flow_chase.proactive_candidate.progress.{label}",
        )
    else:
        record_counter_for_world(
            world,
            f"flow_chase.proactive_candidate.no_progress.{label}",
        )

    return {
        "score": score,
        "label": label,
        "side": side,
        "delta": candidate_delta,
        "collision_result": collision_result,
        "resolved_cpos": resolved_cpos,
        "start_cpos": start_cpos,
        "resolved_enough": resolved_enough,
    }


def choose_flow_chase_proactive_delta(
    world,
    entity,
    controller,
    start_cpos: Vec2i,
    base_delta: Vec2i,
):
    if not FLOW_CHASE_PROACTIVE_STEERING_ENABLED:
        return base_delta

    if not isinstance(controller, FlowChaseDirectController):
        return base_delta

    if not vec_is_nonzero(base_delta):
        return base_delta

    record_counter_for_world(
        world,
        "flow_chase.proactive.entry",
    )

    speed = getattr(
        controller,
        "speed",
        flow_chase_vec_distance(
            start_cpos,
            start_cpos + base_delta,
        ),
    )

    neighbor_cposes = get_flow_chase_same_target_neighbor_cposes(
        world,
        entity,
        controller,
    )

    if neighbor_cposes:
        record_counter_for_world(
            world,
            "flow_chase.proactive.neighbors",
            len(neighbor_cposes),
        )

    candidates = build_flow_chase_proactive_candidates(
        base_delta,
        speed,
    )

    scored_candidates = []

    for label, side, candidate_delta in candidates:
        record_counter_for_world(
            world,
            f"flow_chase.proactive_candidate.considered.{label}",
        )

        scored_candidate = score_flow_chase_proactive_candidate(
            world,
            entity,
            controller,
            start_cpos,
            base_delta,
            label,
            side,
            candidate_delta,
            neighbor_cposes,
        )

        if scored_candidate is None:
            continue

        scored_candidates.append(scored_candidate)

    if not scored_candidates:
        record_counter_for_world(
            world,
            "flow_chase.proactive.no_candidate",
        )
        return base_delta

    clean_candidates = [
        candidate
        for candidate in scored_candidates
        if is_flow_chase_proactive_candidate_clean(candidate)
    ]

    if clean_candidates:
        record_counter_for_world(
            world,
            "flow_chase.proactive.clean_candidate",
        )
        candidates_to_sort = clean_candidates
    else:
        record_counter_for_world(
            world,
            "flow_chase.proactive.no_clean_candidate",
        )

        if FLOW_CHASE_PROACTIVE_HOLD_ON_ALL_COLLIDING:
            record_counter_for_world(
                world,
                "flow_chase.proactive.selected.hold",
            )
            return Vec2i(0, 0)

        candidates_to_sort = scored_candidates

    candidates_to_sort.sort(
        key=lambda candidate: (
            -candidate["score"],
            candidate["label"],
        )
    )

    chosen = candidates_to_sort[0]

    record_counter_for_world(
        world,
        "flow_chase.proactive.selected",
    )
    record_counter_for_world(
        world,
        f"flow_chase.proactive.selected.{chosen['label']}",
    )

    if chosen["label"] != "direct":
        record_counter_for_world(
            world,
            "flow_chase.proactive.selected_non_direct",
        )

    if chosen["side"] != 0:
        controller.local_steering_side = chosen["side"]
        controller.local_steering_last_tick = world.tick
        controller.local_steering_last_delta = chosen["delta"]

    return chosen["delta"]


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

        start_cpos = transform.cpos

        if isinstance(controller, FlowChaseDirectController):
            base_delta = choose_flow_chase_proactive_delta(
                world,
                entity,
                controller,
                start_cpos,
                base_delta,
            )

        influence_delta = world.influence_delta.get(entity, Vec2i(0, 0))
        influence_active = vec_is_nonzero(influence_delta)
        delta = base_delta + influence_delta

        if vec_is_nonzero(delta):
            requested_cpos = start_cpos + delta

            previous_collision_context = push_movement_collision_debug_context(
                world,
                "movement_system.main_resolve",
            )
            try:
                if isinstance(controller, FlowChaseDirectController):
                    collision_result, resolved_cpos = resolve_flow_chase_direct_movement(
                        world,
                        entity,
                        controller,
                        start_cpos,
                        delta,
                    )
                else:
                    collision_result, resolved_cpos = resolve_static_tile_movement(
                        world,
                        entity,
                        start_cpos,
                        delta,
                    )
            finally:
                pop_movement_collision_debug_context(
                    world,
                    previous_collision_context,
                )

            if not isinstance(controller, FlowChaseDirectController):
                local_avoidance_result = try_resolve_path_follow_local_avoidance(
                    world,
                    entity,
                    controller,
                    start_cpos,
                    delta,
                    collision_result,
                )
                if local_avoidance_result is not None:
                    collision_result, resolved_cpos = local_avoidance_result

            if movement_collision_destroys(collision_result):
                collision_cpos = resolved_cpos
                collision_tile = tile_from_cpos(collision_cpos)
                emit_movement_collision_event(
                    world,
                    "entity_destroyed_by_movement_collision",
                    entity,
                    collision_cpos,
                    collision_tile,
                    collision_result,
                    controller,
                    influence_active,
                )
                world.entities.destroy(entity)
                continue

            if movement_collision_blocks(collision_result):
                transform.cpos = resolved_cpos

                if transform.position_mode == "free" or influence_active:
                    transform.tile = tile_from_cpos(transform.cpos)

                mark_settle_after_influence_if_needed(
                    transform,
                    motion_state,
                    influence_active,
                )

                motion_state["last_delta"] = transform.cpos - start_cpos

                emit_movement_collision_event(
                    world,
                    "entity_movement_blocked",
                    entity,
                    transform.cpos,
                    transform.tile,
                    collision_result,
                    controller,
                    influence_active,
                )

                if controller is None:
                    refresh_moved_entity_occupancy(
                        world,
                        entity,
                    )
                    continue

                if controller_ages_on_block(controller):
                    controller.advance()

                    if finish_controller_after_block_if_needed(
                            world,
                            entity,
                            controller,
                    ):
                        refresh_moved_entity_occupancy(
                            world,
                            entity,
                        )

                        continue

                    refresh_moved_entity_occupancy(
                        world,
                        entity,
                    )

                    continue

                if controller_aborts_on_block(controller):
                    if is_path_follow_controller(controller):
                        abort_path_follow_controller(
                            world,
                            entity,
                            motion_state,
                        )
                    else:
                        clear_motion_controller(motion_state)
                        request_settle_when_allowed(world, entity)
                        start_requested_settle_if_allowed(world, entity)

                    refresh_moved_entity_occupancy(
                        world,
                        entity,
                    )
                    continue

                if controller_retries_on_block(controller):
                    refresh_moved_entity_occupancy(
                        world,
                        entity,
                    )

                    continue

                raise ValueError(
                    f"Unhandled controller block_response "
                    f"{get_controller_block_response(controller)!r} "
                    f"for controller {controller!r}"
                )

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

            if (
                    path_follow_movement_was_modified(
                        controller,
                        requested_cpos,
                        resolved_cpos,
                    )
                    or flow_chase_movement_was_modified(
                controller,
                requested_cpos,
                resolved_cpos,
            )
            ):
                discard_pending_controller_advance(controller)
                refresh_moved_entity_occupancy(
                    world,
                    entity,
                )
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

                if is_path_follow_controller(controller):
                    clear_move_target_after_path_finish_if_needed(
                        world,
                        entity,
                    )

                clear_motion_controller(motion_state)

                request_settle_when_allowed(world, entity)
                start_requested_settle_if_allowed(world, entity)

        refresh_moved_entity_occupancy(
            world,
            entity,
        )


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