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
from utils.action_order_utils import (
    entities_are_within_tile_range,
    get_entity_skill_range_tiles,
)
from utils.occupancy_utils import (
    clear_dynamic_movement_reservations,
    add_entity_movement_reservations_for_origin_path,
    rebuild_dynamic_occupancy,
    mark_dynamic_occupancy_dirty,
    is_tile_blocked_for_movement,
    get_dynamic_movement_blockers_for_placement,
    get_movement_body_tiles_for_origin_tile,
)
from motion_controllers import (
    BLOCK_RESPONSE_ABORT,
    BLOCK_RESPONSE_AGE,
    BLOCK_RESPONSE_RETRY,
    GridMoveController,
    SettleToGridController,
    PathFollowController,
    ChaseEntityController,
    DirectionalMoveController,
)
from utils.tile_vec_utils import (
    sign,
    tile_center,
    tile_from_cpos,
    chebyshev_tile_distance,
    normalize_vector_to_dir_scale,
)
from utils.path_utils import (
    find_static_tile_path_to_target,
    smooth_static_tile_path,
    path_tiles_to_cpos_nodes,
    build_local_dynamic_blocker_context,
)


ORDER_OWNED_CONTROLLER_SOURCES = {
    "move_target",
    "recenter_for_action",
    "chase_entity",
}

CORNER_CROSSING_TOLERANCE_CPOS = 32

DEBUG_PATH_RUNTIME_EDGE_CHECK = False
DEBUG_PATH_RUNTIME_EDGE_PLAYER_ONLY = True

PATH_FOLLOW_STALL_LOCAL = "local_stalled"
PATH_FOLLOW_STALL_PATH_PROGRESS_TIMEOUT = "path_progress_timed_out"
PATH_FOLLOW_STALL_LIFETIME = "lifetime_expired"

CHASE_DIRECT_LOOKAHEAD_TILES = 6
CHASE_REPLAN_INTERVAL_TICKS = 30
CHASE_WAYPOINT_MAX_AGE_TICKS = 12
CHASE_LOCAL_PROBE_MIN_TILES = 1
CHASE_LOCAL_PROBE_MAX_TILES = 1
CHASE_STATIC_SIDE_PREFERENCE_TICKS = 60
CHASE_DYNAMIC_RETRY_TICKS = 30
CHASE_TARGET_TELEPORT_TILES = 4
CHASE_RECENT_BLOCKED_TILE_AVOID_TICKS = 3

CHASE_LOCAL_AVOIDANCE_DEFAULT = "default"
CHASE_LOCAL_AVOIDANCE_STATIC = "static"
CHASE_LOCAL_AVOIDANCE_MOVING_DYNAMIC = "moving_dynamic"
CHASE_LOCAL_AVOIDANCE_STALLED_DYNAMIC = "stalled_dynamic"
CHASE_LOCAL_AVOIDANCE_ENGAGED_DYNAMIC = "engaged_dynamic"

CHASE_RING_WALL_FOLLOW_CLOCKWISE = 1
CHASE_RING_WALL_FOLLOW_COUNTERCLOCKWISE = -1

CHASE_RING_WALL_BUCKETS_CLOCKWISE = (
    Vec2i(0, -1),   # N
    Vec2i(1, -1),   # NE
    Vec2i(1, 0),    # E
    Vec2i(1, 1),    # SE
    Vec2i(0, 1),    # S
    Vec2i(-1, 1),   # SW
    Vec2i(-1, 0),   # W
    Vec2i(-1, -1),  # NW
)

CHASE_BLOCKAGE_UNKNOWN = "unknown"
CHASE_BLOCKAGE_STATIC = "static"
CHASE_BLOCKAGE_MOVING_DYNAMIC = "moving_dynamic"
CHASE_BLOCKAGE_STALLED_DYNAMIC = "stalled_dynamic"
CHASE_BLOCKAGE_ENGAGED_DYNAMIC = "engaged_dynamic"

CHASE_STATIC_AVOIDANCE_EPISODE_TICKS = 12
CHASE_STALLED_DYNAMIC_AVOIDANCE_EPISODE_TICKS = 10
CHASE_ENGAGED_DYNAMIC_AVOIDANCE_EPISODE_TICKS = 16

CHASE_STALLED_BLOCKER_TICKS = 6  ## Threshold ticks to recognize this dynamic blocker is not just passing through, it's stuck
CHASE_STALLED_DYNAMIC_ESCAPE_FAILED_ATTEMPTS = 1
CHASE_STALLED_DYNAMIC_MAX_WORSEN_TILES = 2


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


@dataclass(frozen=True)
class MovementAdmissionPolicy:
    claims_movement_space: bool
    reserves_movement_space: bool
    allows_finish_current_tile: bool


@dataclass(frozen=True)
class MovementProposal:
    entity: int
    controller: object
    start_cpos: Vec2i
    base_delta: Vec2i
    influence_delta: Vec2i
    final_delta: Vec2i
    influence_active: bool
    admission_policy: MovementAdmissionPolicy


@dataclass(frozen=True)
class MovementApproval:
    entity: int
    approved: bool
    delta: Vec2i
    resolution_kind: str
    collision_result: MovementCollisionResult = MOVEMENT_COLLISION_ALLOW
    requested_collision_result: MovementCollisionResult = MOVEMENT_COLLISION_ALLOW
    placement_path: tuple = ()
    requested_cpos: Optional[Vec2i] = None
    resolved_cpos: Optional[Vec2i] = None


@dataclass(frozen=True)
class MovementPathCheckResult:
    collision_result: MovementCollisionResult
    placement_path: tuple = ()


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


def movement_collision_can_attempt_slide(collision_result):
    return movement_collision_slides(collision_result)


def movement_collision_destroys(collision_result):
    return collision_result.destroys_entity


def get_collision_counter_name(collision_result):
    if collision_result.blocker_collision_type is not None:
        return collision_result.blocker_collision_type

    return collision_result.collision_result


def record_collision_result_counter(world, prefix, collision_result):
    record_counter_for_world(
        world,
        f"{prefix}.{collision_result.collision_result}",
    )

    collision_name = get_collision_counter_name(collision_result)
    if collision_name is not None:
        record_counter_for_world(
            world,
            f"{prefix}.{collision_name}",
        )


def classify_chase_blockage(world, entity, controller, collision_result):
    if not isinstance(controller, ChaseEntityController):
        return CHASE_BLOCKAGE_UNKNOWN

    if collision_result.blocker_collision_type == "static":
        return CHASE_BLOCKAGE_STATIC

    if collision_result.blocker_collision_type != "dynamic":
        return CHASE_BLOCKAGE_UNKNOWN

    blocker_entity = collision_result.blocker_entity
    if blocker_entity is None:
        return CHASE_BLOCKAGE_MOVING_DYNAMIC

    if blocker_is_engaged_with_chase_target(
        world,
        blocker_entity,
        controller,
    ):
        return CHASE_BLOCKAGE_ENGAGED_DYNAMIC

    if blocker_is_stalled_dynamic_obstacle(
        world,
        blocker_entity,
    ):
        return CHASE_BLOCKAGE_STALLED_DYNAMIC

    return CHASE_BLOCKAGE_MOVING_DYNAMIC


def blocker_is_engaged_with_chase_target(
    world,
    blocker_entity,
    controller,
):
    target_entity = controller.target_entity
    if target_entity not in world.transform:
        return False

    if blocker_entity not in world.transform:
        return False

    if not entities_are_within_tile_range(
        world,
        blocker_entity,
        target_entity,
        controller.desired_range_tiles,
    ):
        return False

    return blocker_is_targeting_entity(
        world,
        blocker_entity,
        target_entity,
    )


def blocker_is_targeting_entity(world, blocker_entity, target_entity):
    order = world.action_order.get(blocker_entity)
    if order is not None and order.get("target") == target_entity:
        return True

    ai_agent = world.ai_agent.get(blocker_entity)
    if ai_agent is not None and ai_agent.get("target_entity") == target_entity:
        return True

    return False


def blocker_is_stalled_dynamic_obstacle(world, blocker_entity):
    motion_state = world.motion_state.get(blocker_entity)
    if motion_state is None:
        return False

    if blocker_moved_last_tick(motion_state):
        return False

    if blocker_has_active_movement_goal(world, blocker_entity, motion_state):
        return True

    return False


def blocker_moved_last_tick(motion_state):
    last_delta = motion_state.get("last_delta")
    if last_delta is None:
        return False

    return last_delta.x != 0 or last_delta.y != 0


def blocker_has_active_movement_goal(world, blocker_entity, motion_state):
    if motion_state.get("controller") is not None:
        return True

    if blocker_entity in world.move_target:
        return True

    if blocker_entity in world.move_intent:
        return True

    if blocker_entity in world.buffered_move_intent:
        return True

    order = world.action_order.get(blocker_entity)
    if order is not None:
        return True

    return False


def record_chase_direct_block_feedback(
    world,
    entity,
    controller,
    collision_result,
):
    if not isinstance(controller, ChaseEntityController):
        return

    if collision_result is None:
        return

    if not movement_collision_blocks(collision_result):
        return

    if (
        controller.last_blocked_tick == world.tick
        and controller.last_blocker_entity == collision_result.blocker_entity
        and controller.last_blocked_tile == collision_result.blocked_tile
        and controller.last_blocker_collision_type
        == collision_result.blocker_collision_type
    ):
        return

    record_counter_for_world(
        world,
        "chase.direct_block_feedback.recorded",
    )

    if collision_result.blocker_collision_type is not None:
        record_counter_for_world(
            world,
            f"chase.direct_block_feedback."
            f"{collision_result.blocker_collision_type}",
        )

    record_chase_controller_block(
        world,
        entity,
        controller,
        collision_result,
    )

    record_counter_for_world(
        world,
        f"chase.direct_block_feedback.classified."
        f"{controller.last_chase_blockage_type}",
    )


def record_chase_controller_block(world, entity, controller, collision_result):
    if not isinstance(controller, ChaseEntityController):
        return

    blockage_type = classify_chase_blockage(
        world,
        entity,
        controller,
        collision_result,
    )

    controller.last_blocked_tick = world.tick
    controller.last_blocker_collision_type = collision_result.blocker_collision_type
    controller.last_blocked_tile = collision_result.blocked_tile
    controller.last_blocker_entity = collision_result.blocker_entity
    controller.last_chase_blockage_type = blockage_type

    record_counter_for_world(
        world,
        f"chase.blockage.{blockage_type}",
    )

    if collision_result.blocker_collision_type == "dynamic":
        controller.dynamic_retry_after_tick = (
            world.tick + CHASE_DYNAMIC_RETRY_TICKS
        )

    if collision_result.blocker_collision_type == "static":
        if controller.side_preference == 0:
            controller.side_preference = 1 if entity % 2 == 0 else -1

        controller.side_preference_until_tick = (
            world.tick + CHASE_STATIC_SIDE_PREFERENCE_TICKS
        )

    start_or_update_chase_avoidance_episode(
        world,
        entity,
        controller,
        blockage_type,
    )

    start_chase_ring_wall_follow_if_needed(
        world,
        entity,
        controller,
        blockage_type,
    )


def record_movement_approval_counters(world, approval):
    record_counter_for_world(
        world,
        "movement.proposal.total",
    )

    if movement_collision_allows(approval.collision_result):
        record_counter_for_world(
            world,
            f"movement.proposal.approved.{approval.resolution_kind}",
        )

        if approval.placement_path:
            record_counter_for_world(
                world,
                "movement.proposal.approved.with_path",
            )
            record_counter_for_world(
                world,
                "movement.proposal.path_len",
                len(approval.placement_path),
            )
            record_counter_for_world(
                world,
                f"movement.proposal.path_len.{approval.resolution_kind}",
                len(approval.placement_path),
            )

        return

    record_counter_for_world(
        world,
        f"movement.proposal.rejected.{approval.resolution_kind}",
    )
    record_collision_result_counter(
        world,
        "movement.proposal.rejected",
        approval.collision_result,
    )

    if approval.placement_path:
        record_counter_for_world(
            world,
            "movement.proposal.rejected.path_len",
            len(approval.placement_path),
        )


def record_direct_rejection_counters(world, collision_result):
    record_counter_for_world(
        world,
        "movement.proposal.direct_rejected",
    )
    record_collision_result_counter(
        world,
        "movement.proposal.direct_rejected",
        collision_result,
    )


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

    active_chase_entities = {
        entity
        for entity, motion_state in world.motion_state.items()
        if isinstance(
            motion_state.get("controller"),
            ChaseEntityController,
        )
    }

    entities = (
        (
            set(world.move_intent)
            | set(world.buffered_move_intent)
            | set(world.move_target)
            | active_directional_entities
            | active_chase_entities
        )
        & set(world.transform)
        & set(world.motion_state)
        & set(world.locomotion)
    )

    for entity in sorted(entities):
        motion_state = world.motion_state[entity]

        if clear_stale_order_owned_movement(world, entity):
            mark_dynamic_occupancy_dirty(world)
            rebuild_dynamic_occupancy(world)
            continue

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

        if isinstance(controller, ChaseEntityController):
            if entity in world.move_intent:
                cancel_move_target_for_directional_input(world, entity)
                clear_motion_controller(motion_state)
                mark_dynamic_occupancy_dirty(world)
                rebuild_dynamic_occupancy(world)
                request_settle_when_allowed(world, entity)
                start_requested_settle_if_allowed(world, entity)
                continue

            if refresh_chase_entity_controller_if_needed(
                    world,
                    entity,
                    controller,
            ):
                mark_dynamic_occupancy_dirty(world)
                rebuild_dynamic_occupancy(world)

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

            if target["type"] == "chase_entity":
                start_chase_entity_controller(
                    world,
                    entity,
                    target,
                )
                continue

            if target["type"] == "target_tile":
                if start_path_follow_controller(
                        world,
                        entity,
                        target,
                ):
                    continue
                continue

            raise ValueError(f"Unknown move_target type: {target['type']!r}")

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


@profiled("movement_proposal_system")
def movement_proposal_system(world):
    world.clear_movement_planning_runtime()

    rebuild_dynamic_occupancy(world)
    clear_dynamic_movement_reservations(world)

    entities = (
        set(world.transform)
        & set(world.motion_state)
    )

    for entity in sorted(entities):
        proposal = build_movement_proposal(
            world,
            entity,
        )

        world.movement_proposal[entity] = proposal

        approval = build_movement_admission_approval(
            world,
            proposal,
        )

        world.movement_approval[entity] = approval

        record_debug_enemy_movement_info(
            world,
            proposal,
            approval,
        )
        
        if proposal.admission_policy.claims_movement_space:
            record_counter_for_world(
                world,
                "movement.proposal.policy.claims_space",
            )
        else:
            record_counter_for_world(
                world,
                "movement.proposal.policy.non_space_claiming",
            )

        record_movement_approval_counters(
            world,
            approval,
        )

        if (
            proposal.admission_policy.reserves_movement_space
            and approval.approved
            and movement_collision_allows(approval.collision_result)
            and approval.placement_path
        ):
            add_entity_movement_reservations_for_origin_path(
                world,
                entity,
                approval.placement_path,
            )
            record_counter_for_world(
                world,
                "movement.proposal.reserved_path",
            )
            record_counter_for_world(
                world,
                "movement.proposal.reserved_path_len",
                len(approval.placement_path),
            )


@profiled("movement_apply_system")
def movement_apply_system(world):
    rebuild_dynamic_occupancy(world)

    entities = (
        set(world.transform)
        & set(world.motion_state)
    )

    for entity in sorted(entities):
        motion_state = world.motion_state[entity]
        controller = motion_state["controller"]
        transform = world.transform[entity]

        proposal = world.movement_proposal.get(entity)
        approval = world.movement_approval.get(entity)

        if proposal is None or approval is None:
            motion_state["last_delta"] = Vec2i(0, 0)
            continue

        influence_active = proposal.influence_active

        if not approval.approved:
            motion_state["last_delta"] = Vec2i(0, 0)
            continue

        start_cpos = proposal.start_cpos
        delta = approval.delta

        requested_cpos = approval.requested_cpos
        if requested_cpos is None:
            requested_cpos = start_cpos + proposal.final_delta

        resolved_cpos = approval.resolved_cpos
        if resolved_cpos is None:
            resolved_cpos = start_cpos + delta

        collision_result = approval.collision_result
        movement_was_requested = vec_is_nonzero(proposal.final_delta)

        if movement_was_requested:

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

                record_chase_controller_block(
                    world,
                    entity,
                    controller,
                    collision_result,
                )

                if controller is None:
                    mark_dynamic_occupancy_dirty(world)
                    rebuild_dynamic_occupancy(world)
                    continue

                if controller_ages_on_block(controller):
                    controller.advance()

                    if finish_controller_after_block_if_needed(
                            world,
                            entity,
                            controller,
                    ):
                        mark_dynamic_occupancy_dirty(world)
                        rebuild_dynamic_occupancy(world)

                        continue

                    mark_dynamic_occupancy_dirty(world)
                    rebuild_dynamic_occupancy(world)

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

                    mark_dynamic_occupancy_dirty(world)
                    rebuild_dynamic_occupancy(world)
                    continue

                if controller_retries_on_block(controller):
                    mark_dynamic_occupancy_dirty(world)
                    rebuild_dynamic_occupancy(world)

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

            if isinstance(controller, ChaseEntityController):
                if world.tick >= controller.side_preference_until_tick:
                    controller.side_preference = 0

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

                if is_path_follow_controller(controller):
                    clear_move_target_after_path_finish_if_needed(
                        world,
                        entity,
                    )

                clear_motion_controller(motion_state)

                request_settle_when_allowed(world, entity)
                start_requested_settle_if_allowed(world, entity)

        mark_dynamic_occupancy_dirty(world)
        rebuild_dynamic_occupancy(world)


def clear_motion_controller(motion_state):
    motion_state["controller"] = None
    motion_state["influence_mode"] = "normal"
    motion_state.pop("controller_source", None)
    motion_state.pop("controller_owner_order_id", None)
    motion_state.pop("recenter_for_action_target_tile", None)
    motion_state.pop("path_follow_progress", None)


def vec_is_nonzero(vec: Vec2i) -> bool:
    return vec.x != 0 or vec.y != 0


def is_at_cpos(a: Vec2i, b: Vec2i) -> bool:
    return a.x == b.x and a.y == b.y


def same_tile_delta_stays_on_pre_center_half(
    start_cpos: Vec2i,
    delta: Vec2i,
) -> bool:
    if not vec_is_nonzero(delta):
        return True

    current_tile = tile_from_cpos(start_cpos)
    current_center = tile_center(current_tile)
    end_cpos = start_cpos + delta

    start_offset = start_cpos - current_center
    end_offset = end_cpos - current_center

    start_projection = start_offset.x * delta.x + start_offset.y * delta.y
    end_projection = end_offset.x * delta.x + end_offset.y * delta.y

    return start_projection <= 0 and end_projection <= 0


def same_tile_delta_lands_on_blocked_side_for_axis(
    start_cpos: Vec2i,
    delta: Vec2i,
    axis: str,
) -> bool:
    if not vec_is_nonzero(delta):
        return False

    current_tile = tile_from_cpos(start_cpos)
    current_center = tile_center(current_tile)
    end_cpos = start_cpos + delta

    if axis == "x":
        step = sign(delta.x)
        if step == 0:
            return False

        return (end_cpos.x - current_center.x) * step > 0

    if axis == "y":
        step = sign(delta.y)
        if step == 0:
            return False

        return (end_cpos.y - current_center.y) * step > 0

    raise ValueError(f"Unknown movement axis {axis!r}")


def diagonal_approach_can_ignore_side_axis_guards(
    world,
    entity,
    current_tile: Vec2i,
    delta: Vec2i,
) -> bool:
    if delta.x == 0 or delta.y == 0:
        return False

    step_x = sign(delta.x)
    step_y = sign(delta.y)

    if step_x == 0 or step_y == 0:
        return False

    movement_collision = world.movement_collision.get(entity)

    if movement_collision is None:
        return False

    corner_policy = movement_collision.get("corner_cutting")

    if corner_policy is None:
        return False

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

    diagonal_path = []
    diagonal_collision = check_axis_movement_placement(
        world,
        entity,
        diagonal_path,
        diagonal_tile,
    )

    if not movement_collision_allows(diagonal_collision):
        return False

    if corner_policy == "allow":
        return True

    side_x_path = []
    side_x_collision = check_axis_movement_placement(
        world,
        entity,
        side_x_path,
        side_x_tile,
    )

    side_x_allowed = movement_collision_allows(side_x_collision)

    side_y_path = []
    side_y_collision = check_axis_movement_placement(
        world,
        entity,
        side_y_path,
        side_y_tile,
    )

    side_y_allowed = movement_collision_allows(side_y_collision)

    if corner_policy == "strict":
        return side_x_allowed and side_y_allowed

    if corner_policy == "allow_if_one_side_open":
        return side_x_allowed or side_y_allowed

    raise ValueError(
        f"Unknown corner_cutting policy: {corner_policy!r}"
    )


def check_same_tile_blocked_axis_components(
    world,
    entity,
    current_tile: Vec2i,
    start_cpos: Vec2i,
    delta: Vec2i,
    step_axis: str,
):
    axis_order = []

    if step_axis == "x":
        axis_order = ["x", "y"]
    elif step_axis == "y":
        axis_order = ["y", "x"]
    else:
        axis_order = ["x", "y"]

    if diagonal_approach_can_ignore_side_axis_guards(
        world,
        entity,
        current_tile,
        delta,
    ):
        return None

    for axis in axis_order:
        if axis == "x":
            if delta.x == 0:
                continue

            if not same_tile_delta_lands_on_blocked_side_for_axis(
                start_cpos,
                delta,
                "x",
            ):
                continue

            placement_path = []

            tile = Vec2i(
                current_tile.x + sign(delta.x),
                current_tile.y,
            )

            collision_result = check_axis_movement_placement(
                world,
                entity,
                placement_path,
                tile,
            )

            if not movement_collision_allows(collision_result):
                return MovementPathCheckResult(
                    collision_result=collision_result,
                    placement_path=tuple(placement_path),
                )

            continue

        if axis == "y":
            if delta.y == 0:
                continue

            if not same_tile_delta_lands_on_blocked_side_for_axis(
                start_cpos,
                delta,
                "y",
            ):
                continue

            placement_path = []

            tile = Vec2i(
                current_tile.x,
                current_tile.y + sign(delta.y),
            )

            collision_result = check_axis_movement_placement(
                world,
                entity,
                placement_path,
                tile,
            )

            if not movement_collision_allows(collision_result):
                return MovementPathCheckResult(
                    collision_result=collision_result,
                    placement_path=tuple(placement_path),
                )

            continue

    return None


def check_blocked_axis_components_for_segment(
    world,
    entity,
    current_tile: Vec2i,
    segment_start_cpos: Vec2i,
    segment_end_cpos: Vec2i,
    step_axis: str,
):
    segment_delta = segment_end_cpos - segment_start_cpos

    if not vec_is_nonzero(segment_delta):
        return None

    result = check_same_tile_blocked_axis_components(
        world,
        entity,
        current_tile,
        segment_start_cpos,
        segment_delta,
        step_axis,
    )

    return result


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


def make_path_query_key(
    entity,
    start_tile,
    target_tile,
    path_policy_name,
    dynamic_blocker_key,
):
    return (
        entity,
        start_tile.x,
        start_tile.y,
        target_tile.x,
        target_tile.y,
        path_policy_name,
        dynamic_blocker_key,
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
    return target.get("path_policy")


def get_path_policy(world, target):
    return PATH_POLICIES[get_path_policy_name(target)]


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


def cpos_distance(a: Vec2i, b: Vec2i) -> int:
    return isqrt(cpos_distance_sq(a, b))


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


def cpos_vector_length(vec: Vec2i) -> int:
    return cpos_distance(Vec2i(0, 0), vec)


def get_remaining_movement_budget(reference_delta: Vec2i, spent_delta: Vec2i) -> int:
    remaining = (
        cpos_vector_length(reference_delta)
        - cpos_vector_length(spent_delta)
    )
    if remaining <= 0:
        return 0
    return remaining


def build_axis_delta_from_budget(axis: str, direction_sign: int, budget: int) -> Vec2i:
    if budget <= 0 or direction_sign == 0:
        return Vec2i(0, 0)

    if axis == "x":
        return Vec2i(direction_sign * budget, 0)

    if axis == "y":
        return Vec2i(0, direction_sign * budget)

    raise ValueError(f"Unknown movement axis {axis!r}")


def get_path_follow_node_distance(controller, cpos):
    current_node = get_path_follow_current_node(controller)

    if current_node is None:
        return None

    return cpos_distance(cpos, current_node)


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


def set_chase_entity_target(
    world,
    entity,
    target_entity,
    desired_range_tiles,
    owner_order_id=None,
):
    existing_target = world.move_target.get(entity)
    owner_changed = (
        existing_target is not None
        and existing_target.get("owner_order_id") != owner_order_id
    )

    if existing_target is None or owner_changed:
        created_tick = world.tick
    else:
        created_tick = existing_target.get("created_tick", world.tick)

    world.move_target[entity] = {
        "type": "chase_entity",
        "target_entity": target_entity,
        "desired_range_tiles": desired_range_tiles,
        "owner_order_id": owner_order_id,
        "created_tick": created_tick,
    }

    clear_path_build_state(world, entity)


def clear_move_target(world, entity):
    old_target = world.move_target.pop(entity, None)
    clear_path_build_state(world, entity)


def cancel_move_target_for_directional_input(world, entity):
    clear_move_target(world, entity)
    clear_failed_path_queries_for_entity(world, entity)


def order_owner_is_current(world, entity, owner_order_id):
    if owner_order_id is None:
        return True

    order = world.action_order.get(entity)
    if order is None:
        return False

    return order.get("order_id") == owner_order_id


def move_target_owner_is_current(world, entity):
    target = world.move_target.get(entity)

    if target is None:
        return True

    return order_owner_is_current(
        world,
        entity,
        target.get("owner_order_id"),
    )


def active_order_owned_controller_is_current(world, entity):
    motion_state = world.motion_state.get(entity)

    if motion_state is None:
        return True

    controller = motion_state.get("controller")

    if controller is None:
        return True

    controller_source = motion_state.get("controller_source")

    if controller_source not in ORDER_OWNED_CONTROLLER_SOURCES:
        return True

    return order_owner_is_current(
        world,
        entity,
        motion_state.get("controller_owner_order_id"),
    )


def clear_stale_order_owned_movement(world, entity):
    cleared = False

    if not move_target_owner_is_current(world, entity):
        clear_move_target(world, entity)
        cleared = True

    if not active_order_owned_controller_is_current(world, entity):
        motion_state = world.motion_state.get(entity)

        if motion_state is not None:
            clear_motion_controller(motion_state)
            request_settle_when_allowed(world, entity)
            start_requested_settle_if_allowed(world, entity)
            cleared = True

    return cleared


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


def handle_dynamic_movement_collision(world, entity, next_tile):
    policy = world.movement_collision[entity]
    behavior = policy["dynamic_blockers"]

    if behavior == "allow":
        return MOVEMENT_COLLISION_ALLOW

    blockers = get_dynamic_movement_blockers_for_placement(
        world,
        mover_entity=entity,
        proposed_center_tile=next_tile,
        proposed_body_tiles=get_movement_body_tiles_for_origin_tile(
            world,
            entity,
            next_tile,
        ),
        include_reservations=True,
    )

    if blockers:
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
    transform = world.transform[entity]
    locomotion = world.locomotion[entity]

    current_tile = get_navigation_start_tile(world, entity)
    target_tile = target["target_tile"]

    if current_tile == target_tile:
        return []

    path_policy_name = get_path_policy_name(target)
    path_policy = get_path_policy(world, target)

    dynamic_blocker_context = build_path_dynamic_blocker_context(
        world,
        entity,
        current_tile,
        path_policy,
    )

    edge_is_allowed = make_path_runtime_clean_edge_filter(
        world,
        entity,
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
        dynamic_blocker_context=dynamic_blocker_context,
        edge_is_allowed=edge_is_allowed,
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

    debug_path_runtime_edges_for_tile_path(
        world,
        entity,
        "raw",
        current_tile,
        path_tiles,
    )

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
            edge_is_allowed=edge_is_allowed,
        )

    debug_path_runtime_edges_for_tile_path(
        world,
        entity,
        "smoothed",
        current_tile,
        smoothed_tiles,
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
        duration=get_grid_move_duration_from_speed(locomotion),
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

    mark_dynamic_occupancy_dirty(world)
    rebuild_dynamic_occupancy(world)

    request_settle_when_allowed(world, entity)
    start_requested_settle_if_allowed(world, entity)


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
    motion_state["controller_owner_order_id"] = target.get("owner_order_id")

    initialize_path_follow_progress(
        world,
        entity,
        motion_state["controller"],
    )

    rebuild_dynamic_occupancy(world)

    return True


def start_path_follow_controller(world, entity, target):
    path_policy = get_path_policy(world, target)

    nodes = build_path_follow_nodes(
        world,
        entity,
        target,
    )

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


def start_chase_entity_controller(world, entity, target):
    waypoints, target_tile, goal_tile = build_chase_waypoints(
        world,
        entity,
        target,
        force_replan=True,
    )

    if not waypoints:
        return False

    locomotion = world.locomotion[entity]
    motion_state = world.motion_state[entity]

    controller = ChaseEntityController(
        target_entity=target["target_entity"],
        desired_range_tiles=target["desired_range_tiles"],
        waypoints=waypoints,
        current_index=0,
        speed=get_locomotion_speed_cpos_per_tick(locomotion),
        created_tick=target.get("created_tick", world.tick),
        cached_target_tile=target_tile,
        cached_goal_tile=goal_tile,
        last_replan_tick=world.tick,
        waypoint_created_tick=world.tick,
    )

    motion_state["controller"] = controller
    motion_state["controller_source"] = "chase_entity"
    motion_state["controller_owner_order_id"] = target.get("owner_order_id")

    if entity in world.facing and goal_tile is not None:
        actor_tile = tile_from_cpos(world.transform[entity].cpos)
        world.facing[entity] = Vec2i(
            sign(goal_tile.x - actor_tile.x),
            sign(goal_tile.y - actor_tile.y),
        )

    rebuild_dynamic_occupancy(world)
    return True


def refresh_chase_entity_controller_if_needed(world, entity, controller):
    target = world.move_target.get(entity)
    if target is None or target.get("type") != "chase_entity":
        clear_motion_controller(world.motion_state[entity])
        request_settle_when_allowed(world, entity)
        start_requested_settle_if_allowed(world, entity)
        return True

    if chase_target_is_missing(world, controller):
        clear_move_target(world, entity)
        clear_motion_controller(world.motion_state[entity])
        request_settle_when_allowed(world, entity)
        start_requested_settle_if_allowed(world, entity)
        return True

    if entities_are_within_tile_range(
        world,
        entity,
        controller.target_entity,
        controller.desired_range_tiles,
    ):
        clear_motion_controller(world.motion_state[entity])
        request_settle_when_allowed(world, entity)
        start_requested_settle_if_allowed(world, entity)
        return True

    if not chase_controller_needs_replan(world, entity, controller):
        return False

    waypoints, target_tile, goal_tile = build_chase_waypoints(
        world,
        entity,
        target,
        force_replan=False,
        controller=controller,
    )

    if not waypoints:
        controller.waypoints = []
        controller.current_index = 0
        controller.last_replan_tick = world.tick
        controller.waypoint_created_tick = world.tick
        discard_pending_controller_advance(controller)
        return True

    locomotion = world.locomotion[entity]
    controller.waypoints = waypoints
    controller.current_index = 0
    controller.speed = get_locomotion_speed_cpos_per_tick(locomotion)
    controller.cached_target_tile = target_tile
    controller.cached_goal_tile = goal_tile
    controller.last_replan_tick = world.tick
    controller.waypoint_created_tick = world.tick
    discard_pending_controller_advance(controller)

    if entity in world.facing and goal_tile is not None:
        actor_tile = tile_from_cpos(world.transform[entity].cpos)
        world.facing[entity] = Vec2i(
            sign(goal_tile.x - actor_tile.x),
            sign(goal_tile.y - actor_tile.y),
        )

    return True


def chase_target_is_missing(world, controller):
    return controller.target_entity not in world.transform


def chase_controller_needs_replan(world, entity, controller):
    if controller.finished():
        return True

    if not controller.waypoints:
        return True

    if chase_ring_wall_follow_is_active(world, controller):
        return True

    if (
            controller.last_blocker_collision_type == "dynamic"
            and world.tick < controller.dynamic_retry_after_tick
    ):
        return False

    if world.tick - controller.waypoint_created_tick >= CHASE_WAYPOINT_MAX_AGE_TICKS:
        return True

    if controller.last_blocked_tick >= controller.last_replan_tick:
        return True

    if world.tick - controller.last_replan_tick < CHASE_REPLAN_INTERVAL_TICKS:
        return False

    actor_tile = tile_from_cpos(world.transform[entity].cpos)
    target_tile = tile_from_cpos(world.transform[controller.target_entity].cpos)

    if target_tile_changed_sharply(
        controller.cached_target_tile,
        target_tile,
    ):
        return True

    goal_tile = choose_chase_goal_tile(
        world,
        entity,
        controller.target_entity,
    )
    if goal_tile is None:
        return False

    waypoint = get_chase_current_waypoint(controller)
    if waypoint is None:
        return True

    waypoint_tile = tile_from_cpos(waypoint)
    return not chase_waypoint_still_improves_goal(
        actor_tile,
        waypoint_tile,
        goal_tile,
    )


def chase_waypoint_still_improves_goal(actor_tile, waypoint_tile, goal_tile):
    actor_distance = chebyshev_tile_distance(actor_tile, goal_tile)
    waypoint_distance = chebyshev_tile_distance(waypoint_tile, goal_tile)
    return waypoint_distance < actor_distance


def blockage_type_can_start_ring_wall_follow(blockage_type):
    return blockage_type in {
        CHASE_BLOCKAGE_STALLED_DYNAMIC,
        CHASE_BLOCKAGE_ENGAGED_DYNAMIC,
    }


def start_chase_ring_wall_follow_if_needed(
    world,
    entity,
    controller,
    blockage_type,
):
    if not isinstance(controller, ChaseEntityController):
        return

    if not blockage_type_can_start_ring_wall_follow(blockage_type):
        return

    target_entity = controller.target_entity
    if target_entity not in world.transform:
        return

    target_tile = tile_from_cpos(world.transform[target_entity].cpos)

    if (
        controller.ring_wall_follow_active
        and controller.ring_wall_follow_target_entity == target_entity
        and controller.ring_wall_follow_target_tile == target_tile
    ):
        return

    controller.ring_wall_follow_active = True
    controller.ring_wall_follow_target_entity = target_entity
    controller.ring_wall_follow_target_tile = target_tile
    controller.ring_wall_follow_last_tile = None

    if controller.avoidance_episode_side_preference != 0:
        controller.ring_wall_follow_side = (
            controller.avoidance_episode_side_preference
        )
    elif controller.side_preference != 0:
        controller.ring_wall_follow_side = controller.side_preference
    else:
        controller.ring_wall_follow_side = (
            CHASE_RING_WALL_FOLLOW_CLOCKWISE
            if entity % 2 == 0
            else CHASE_RING_WALL_FOLLOW_COUNTERCLOCKWISE
        )

    record_counter_for_world(
        world,
        "chase.ring_wall_follow.started",
    )
    record_counter_for_world(
        world,
        f"chase.ring_wall_follow.{blockage_type}.started",
    )


def clear_chase_ring_wall_follow(controller):
    controller.ring_wall_follow_active = False
    controller.ring_wall_follow_target_entity = None
    controller.ring_wall_follow_target_tile = None
    controller.ring_wall_follow_side = 0
    controller.ring_wall_follow_last_tile = None


def chase_ring_wall_follow_is_active(world, controller):
    if not isinstance(controller, ChaseEntityController):
        return False

    if not controller.ring_wall_follow_active:
        return False

    target_entity = controller.ring_wall_follow_target_entity
    if target_entity is None or target_entity not in world.transform:
        clear_chase_ring_wall_follow(controller)
        record_counter_for_world(
            world,
            "chase.ring_wall_follow.cleared.target_missing",
        )
        return False

    target_tile = tile_from_cpos(world.transform[target_entity].cpos)

    if target_tile != controller.ring_wall_follow_target_tile:
        clear_chase_ring_wall_follow(controller)
        record_counter_for_world(
            world,
            "chase.ring_wall_follow.cleared.target_tile_changed",
        )
        return False

    return True


def iter_8_neighbor_tiles(tile):
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue

            yield Vec2i(tile.x + dx, tile.y + dy)


def direction_bucket(delta):
    return Vec2i(
        sign(delta.x),
        sign(delta.y),
    )


def ring_wall_bucket_index(tile, target_tile):
    bucket = direction_bucket(tile - target_tile)

    if bucket in CHASE_RING_WALL_BUCKETS_CLOCKWISE:
        return CHASE_RING_WALL_BUCKETS_CLOCKWISE.index(bucket)

    return 0


def ring_wall_progress_distance(
    actor_tile,
    target_tile,
    candidate_tile,
    side,
):
    current_index = ring_wall_bucket_index(actor_tile, target_tile)
    candidate_index = ring_wall_bucket_index(candidate_tile, target_tile)
    count = len(CHASE_RING_WALL_BUCKETS_CLOCKWISE)

    if side == CHASE_RING_WALL_FOLLOW_CLOCKWISE:
        return (candidate_index - current_index) % count

    return (current_index - candidate_index) % count


def build_ring_wall_body_tiles(
    world,
    entity,
    target_entity,
    desired_range_tiles,
):
    wall_tiles = set()

    target_tile = tile_from_cpos(world.transform[target_entity].cpos)

    wall_tiles.update(
        get_movement_body_tiles_for_origin_tile(
            world,
            target_entity,
            target_tile,
        )
    )

    for other_entity in sorted(world.transform):
        if other_entity == entity:
            continue

        if other_entity == target_entity:
            continue

        if not blocker_is_targeting_entity(
            world,
            other_entity,
            target_entity,
        ):
            continue

        if not entities_are_within_tile_range(
            world,
            other_entity,
            target_entity,
            desired_range_tiles,
        ):
            continue

        motion_state = world.motion_state.get(other_entity)
        if motion_state is not None and blocker_moved_last_tick(motion_state):
            continue

        other_tile = tile_from_cpos(world.transform[other_entity].cpos)

        wall_tiles.update(
            get_movement_body_tiles_for_origin_tile(
                world,
                other_entity,
                other_tile,
            )
        )

    return wall_tiles


def ring_wall_follow_tile_is_legal(
    world,
    entity,
    actor_cpos,
    tile,
):
    return chase_candidate_tile_is_reachable(
        world,
        entity,
        actor_cpos,
        tile,
    )


def ring_wall_follow_tile_touches_wall(tile, wall_body_tiles):
    for neighbor_tile in iter_8_neighbor_tiles(tile):
        if neighbor_tile in wall_body_tiles:
            return True

    return False


def choose_next_ring_wall_follow_tile(
    world,
    entity,
    controller,
):
    if not chase_ring_wall_follow_is_active(world, controller):
        return None

    target_entity = controller.ring_wall_follow_target_entity
    if target_entity not in world.transform:
        clear_chase_ring_wall_follow(controller)
        return None

    actor_cpos = world.transform[entity].cpos
    actor_tile = tile_from_cpos(actor_cpos)
    target_tile = controller.ring_wall_follow_target_tile

    wall_body_tiles = build_ring_wall_body_tiles(
        world,
        entity,
        target_entity,
        controller.desired_range_tiles,
    )

    candidates = []

    for candidate_tile in iter_8_neighbor_tiles(actor_tile):
        if not ring_wall_follow_tile_is_legal(
            world,
            entity,
            actor_cpos,
            candidate_tile,
        ):
            continue

        if not ring_wall_follow_tile_touches_wall(
            candidate_tile,
            wall_body_tiles,
        ):
            continue

        progress = ring_wall_progress_distance(
            actor_tile,
            target_tile,
            candidate_tile,
            controller.ring_wall_follow_side,
        )

        if progress == 0:
            progress = len(CHASE_RING_WALL_BUCKETS_CLOCKWISE)

        backtrack = (
            controller.ring_wall_follow_last_tile is not None
            and candidate_tile == controller.ring_wall_follow_last_tile
        )

        actor_distance = chebyshev_tile_distance(
            actor_tile,
            target_tile,
        )
        candidate_distance = chebyshev_tile_distance(
            candidate_tile,
            target_tile,
        )

        candidates.append(
            (
                1 if backtrack else 0,
                progress,
                abs(candidate_distance - actor_distance),
                candidate_distance,
                candidate_tile.x,
                candidate_tile.y,
                candidate_tile,
            )
        )

    if not candidates:
        record_counter_for_world(
            world,
            "chase.ring_wall_follow.no_candidate",
        )
        return None

    candidates.sort()

    chosen_tile = candidates[0][-1]

    controller.ring_wall_follow_last_tile = actor_tile

    record_counter_for_world(
        world,
        "chase.ring_wall_follow.next_tile",
    )

    return chosen_tile


def stationary_bypass_tile_is_inside_blocker_body(
    world,
    blocker_entity,
    blocker_tile,
    tile,
):
    blocker_body_tiles = get_movement_body_tiles_for_origin_tile(
        world,
        blocker_entity,
        blocker_tile,
    )

    return tile in blocker_body_tiles


def build_chase_waypoints(
    world,
    entity,
    target,
    force_replan,
    controller=None,
):
    target_entity = target["target_entity"]
    desired_range_tiles = target["desired_range_tiles"]

    if target_entity not in world.transform:
        return [], None, None

    if entities_are_within_tile_range(
        world,
        entity,
        target_entity,
        desired_range_tiles,
    ):
        return [], None, None

    target_tile = tile_from_cpos(world.transform[target_entity].cpos)
    goal_tile = choose_chase_goal_tile(
        world,
        entity,
        target_entity,
    )

    if goal_tile is None:
        return [], target_tile, None

    if chase_ring_wall_follow_is_active(world, controller):
        ring_tile = choose_next_ring_wall_follow_tile(
            world,
            entity,
            controller,
        )

        if ring_tile is not None:
            record_counter_for_world(
                world,
                "chase.build_waypoints.using_ring_wall_follow",
            )
            return [tile_center(ring_tile)], target_tile, goal_tile

    direct_tile, direct_block_collision = choose_direct_chase_waypoint_attempt(
        world,
        entity,
        goal_tile,
        desired_range_tiles,
    )
    if direct_tile is not None:
        return [tile_center(direct_tile)], target_tile, goal_tile

    if direct_block_collision is not None:
        record_chase_direct_block_feedback(
            world,
            entity,
            controller,
            direct_block_collision,
        )

        ring_tile = choose_next_ring_wall_follow_tile(
            world,
            entity,
            controller,
        )

        if ring_tile is not None:
            record_counter_for_world(
                world,
                "chase.build_waypoints.using_ring_wall_follow_after_direct_block",
            )
            return [tile_center(ring_tile)], target_tile, goal_tile

    local_tile = choose_local_chase_waypoint_tile(
        world,
        entity,
        goal_tile,
        desired_range_tiles,
        controller=controller,
    )

    if local_tile is not None:
        return [tile_center(local_tile)], target_tile, goal_tile

    return [], target_tile, goal_tile


WALL_HUG_DIRECTION_BUCKETS = (
    Vec2i(1, 0),
    Vec2i(1, 1),
    Vec2i(0, 1),
    Vec2i(-1, 1),
    Vec2i(-1, 0),
    Vec2i(-1, -1),
    Vec2i(0, -1),
    Vec2i(1, -1),
)


def ordered_wall_hug_direction_buckets(
    blocker_center_tile,
    actor_tile,
    side_preference,
):
    actor_bucket = wall_hug_direction_bucket(
        actor_tile - blocker_center_tile,
    )

    if actor_bucket in WALL_HUG_DIRECTION_BUCKETS:
        start_index = WALL_HUG_DIRECTION_BUCKETS.index(actor_bucket)
    else:
        start_index = 0

    step = 1 if side_preference >= 0 else -1

    ordered = []
    count = len(WALL_HUG_DIRECTION_BUCKETS)

    # Start one bucket to the side, not directly where the actor already is.
    for offset in range(1, count + 1):
        ordered.append(
            WALL_HUG_DIRECTION_BUCKETS[
                (start_index + step * offset) % count
            ]
        )

    return ordered


def wall_hug_direction_bucket(delta):
    return Vec2i(
        sign(delta.x),
        sign(delta.y),
    )


def iter_8_neighbor_tiles(tile):
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            yield Vec2i(tile.x + dx, tile.y + dy)


def stationary_wall_hug_candidate_is_plausible(
    world,
    entity,
    actor_cpos,
    candidate_tile,
    blocker_body_tiles,
):
    if candidate_tile in blocker_body_tiles:
        return False

    if stationary_bypass_tile_is_inside_blocker_body(
        world,
        entity,
        candidate_tile,
        blocker_body_tiles,
    ):
        return False

    return chase_candidate_tile_is_reachable(
        world,
        entity,
        actor_cpos,
        candidate_tile,
    )


def chase_tile_tiebreak_for_entity(entity, tile):
    if entity % 2 == 0:
        return tile.y, tile.x

    return -tile.y, -tile.x


def chase_recent_blocked_tile_is_active(world, controller):
    if controller is None:
        return False

    if controller.last_blocked_tile is None:
        return False

    if controller.last_blocked_tick < 0:
        return False

    return (
        world.tick - controller.last_blocked_tick
        <= CHASE_RECENT_BLOCKED_TILE_AVOID_TICKS
    )


def chase_candidate_is_recently_blocked_tile(
    world,
    controller,
    candidate_tile,
):
    if not chase_recent_blocked_tile_is_active(world, controller):
        return False

    return candidate_tile == controller.last_blocked_tile


def stalled_dynamic_escape_probe_is_unlocked(world, controller):
    if controller is None:
        return False

    if not chase_avoidance_episode_is_active(world, controller):
        return False

    if (
        controller.avoidance_episode_type
        != CHASE_LOCAL_AVOIDANCE_STALLED_DYNAMIC
    ):
        return False

    return (
        controller.avoidance_episode_failed_attempts
        >= CHASE_STALLED_DYNAMIC_ESCAPE_FAILED_ATTEMPTS
    )


def get_chase_local_avoidance_mode(world, controller):
    if controller is None:
        return CHASE_LOCAL_AVOIDANCE_DEFAULT

    clear_expired_chase_avoidance_episode(world, controller)

    if chase_avoidance_episode_is_active(world, controller):
        return controller.avoidance_episode_type

    if controller.last_chase_blockage_type == CHASE_BLOCKAGE_STATIC:
        if (
            controller.side_preference != 0
            and world.tick < controller.side_preference_until_tick
        ):
            return CHASE_LOCAL_AVOIDANCE_STATIC

        return CHASE_LOCAL_AVOIDANCE_DEFAULT

    if controller.last_chase_blockage_type == CHASE_BLOCKAGE_ENGAGED_DYNAMIC:
        if chase_recent_blocked_tile_is_active(world, controller):
            return CHASE_LOCAL_AVOIDANCE_ENGAGED_DYNAMIC

        return CHASE_LOCAL_AVOIDANCE_DEFAULT

    if controller.last_chase_blockage_type == CHASE_BLOCKAGE_STALLED_DYNAMIC:
        if chase_recent_blocked_tile_is_active(world, controller):
            return CHASE_LOCAL_AVOIDANCE_STALLED_DYNAMIC

        return CHASE_LOCAL_AVOIDANCE_DEFAULT

    if controller.last_chase_blockage_type == CHASE_BLOCKAGE_MOVING_DYNAMIC:
        if (
            controller.last_blocker_collision_type == "dynamic"
            and controller.last_blocked_tick >= 0
            and world.tick < controller.dynamic_retry_after_tick
        ):
            return CHASE_LOCAL_AVOIDANCE_MOVING_DYNAMIC

        return CHASE_LOCAL_AVOIDANCE_DEFAULT

    return CHASE_LOCAL_AVOIDANCE_DEFAULT


def chase_avoidance_episode_is_active(world, controller):
    if controller is None:
        return False

    if controller.avoidance_episode_type is None:
        return False

    return world.tick < controller.avoidance_episode_until_tick


def get_chase_blockage_episode_type(blockage_type):
    if blockage_type == CHASE_BLOCKAGE_STATIC:
        return CHASE_LOCAL_AVOIDANCE_STATIC

    if blockage_type == CHASE_BLOCKAGE_STALLED_DYNAMIC:
        return CHASE_LOCAL_AVOIDANCE_STALLED_DYNAMIC

    if blockage_type == CHASE_BLOCKAGE_ENGAGED_DYNAMIC:
        return CHASE_LOCAL_AVOIDANCE_ENGAGED_DYNAMIC

    return None


def get_chase_avoidance_episode_duration_ticks(episode_type):
    if episode_type == CHASE_LOCAL_AVOIDANCE_STATIC:
        return CHASE_STATIC_AVOIDANCE_EPISODE_TICKS

    if episode_type == CHASE_LOCAL_AVOIDANCE_STALLED_DYNAMIC:
        return CHASE_STALLED_DYNAMIC_AVOIDANCE_EPISODE_TICKS

    if episode_type == CHASE_LOCAL_AVOIDANCE_ENGAGED_DYNAMIC:
        return CHASE_ENGAGED_DYNAMIC_AVOIDANCE_EPISODE_TICKS

    return 0


def get_default_chase_side_preference(entity):
    return 1 if entity % 2 == 0 else -1


def get_chase_episode_side_preference(entity, controller):
    if controller is not None and controller.avoidance_episode_side_preference != 0:
        return controller.avoidance_episode_side_preference

    if controller is not None and controller.side_preference != 0:
        return controller.side_preference

    return get_default_chase_side_preference(entity)


def start_or_update_chase_avoidance_episode(
    world,
    entity,
    controller,
    blockage_type,
):
    episode_type = get_chase_blockage_episode_type(blockage_type)
    if episode_type is None:
        return

    duration_ticks = get_chase_avoidance_episode_duration_ticks(
        episode_type,
    )
    if duration_ticks <= 0:
        return

    same_episode = (
        controller.avoidance_episode_type == episode_type
        and chase_avoidance_episode_is_active(world, controller)
    )

    if same_episode:
        controller.avoidance_episode_failed_attempts += 1
    else:
        controller.avoidance_episode_failed_attempts = 0

    controller.avoidance_episode_type = episode_type
    controller.avoidance_episode_started_tick = world.tick
    controller.avoidance_episode_until_tick = world.tick + duration_ticks
    controller.avoidance_episode_side_preference = (
        get_chase_episode_side_preference(entity, controller)
    )
    controller.avoidance_episode_blocked_tile = controller.last_blocked_tile
    controller.avoidance_episode_blocker_entity = controller.last_blocker_entity

    record_counter_for_world(
        world,
        f"chase.avoidance_episode.{episode_type}",
    )


def clear_expired_chase_avoidance_episode(world, controller):
    if controller is None:
        return

    if controller.avoidance_episode_type is None:
        return

    if world.tick < controller.avoidance_episode_until_tick:
        return

    controller.avoidance_episode_type = None
    controller.avoidance_episode_started_tick = -1
    controller.avoidance_episode_until_tick = -1
    controller.avoidance_episode_side_preference = 0
    controller.avoidance_episode_failed_attempts = 0
    controller.avoidance_episode_blocked_tile = None
    controller.avoidance_episode_blocker_entity = None


def get_chase_local_side_preference(world, entity, controller):
    fallback_side = get_default_chase_side_preference(entity)

    if controller is None:
        return fallback_side, False

    clear_expired_chase_avoidance_episode(world, controller)

    if (
        chase_avoidance_episode_is_active(world, controller)
        and controller.avoidance_episode_side_preference != 0
    ):
        return controller.avoidance_episode_side_preference, True

    if (
        controller.side_preference != 0
        and world.tick < controller.side_preference_until_tick
    ):
        return controller.side_preference, True

    return fallback_side, False


def choose_chase_goal_tile(world, entity, target_entity):
    actor_tile = tile_from_cpos(world.transform[entity].cpos)
    target_tiles = get_entity_skill_range_tiles(
        world,
        target_entity,
    )

    if not target_tiles:
        return None

    candidates = []
    for target_tile in target_tiles:
        tie_y, tie_x = chase_tile_tiebreak_for_entity(
            entity,
            target_tile,
        )

        candidates.append(
            (
                chebyshev_tile_distance(actor_tile, target_tile),
                tie_y,
                tie_x,
                target_tile,
            )
        )

    candidates.sort()
    return candidates[0][-1]


def choose_chase_direct_failure_collision(current, candidate):
    if candidate is None:
        return current

    if not movement_collision_blocks(candidate):
        return current

    if current is None:
        return candidate

    if (
        current.blocker_collision_type != "dynamic"
        and candidate.blocker_collision_type == "dynamic"
    ):
        return candidate

    if current.blocker_entity is None and candidate.blocker_entity is not None:
        return candidate

    return current


def choose_direct_chase_waypoint_attempt(
    world,
    entity,
    goal_tile,
    desired_range_tiles,
):
    actor_cpos = world.transform[entity].cpos
    actor_tile = tile_from_cpos(actor_cpos)
    actor_distance = chebyshev_tile_distance(actor_tile, goal_tile)

    blocking_collision_result = None

    for candidate_tile in iter_direct_chase_tiles(
        actor_tile,
        goal_tile,
        CHASE_DIRECT_LOOKAHEAD_TILES,
    ):
        candidate_distance = chebyshev_tile_distance(
            candidate_tile,
            goal_tile,
        )

        if candidate_distance > actor_distance:
            continue

        reachable, collision_result = check_chase_candidate_tile_reachability(
            world,
            entity,
            actor_cpos,
            candidate_tile,
        )

        if not reachable:
            blocking_collision_result = choose_chase_direct_failure_collision(
                blocking_collision_result,
                collision_result,
            )
            continue

        if candidate_distance <= desired_range_tiles:
            return candidate_tile, None

        return candidate_tile, None

    return None, blocking_collision_result


def choose_direct_chase_waypoint_tile(
    world,
    entity,
    goal_tile,
    desired_range_tiles,
):
    direct_tile, _ = choose_direct_chase_waypoint_attempt(
        world,
        entity,
        goal_tile,
        desired_range_tiles,
    )
    return direct_tile


def choose_local_chase_waypoint_tile(
    world,
    entity,
    goal_tile,
    desired_range_tiles,
    controller=None,
):
    mode = get_chase_local_avoidance_mode(world, controller)

    if mode == CHASE_LOCAL_AVOIDANCE_STATIC:
        return choose_static_chase_avoidance_tile(
            world,
            entity,
            goal_tile,
            desired_range_tiles,
            controller=controller,
        )

    if mode == CHASE_LOCAL_AVOIDANCE_MOVING_DYNAMIC:
        return choose_moving_dynamic_chase_avoidance_tile(
            world,
            entity,
            goal_tile,
            desired_range_tiles,
            controller=controller,
        )

    if mode == CHASE_LOCAL_AVOIDANCE_STALLED_DYNAMIC:
        return choose_stalled_dynamic_chase_avoidance_tile(
            world,
            entity,
            goal_tile,
            desired_range_tiles,
            controller=controller,
        )

    if mode == CHASE_LOCAL_AVOIDANCE_ENGAGED_DYNAMIC:
        return choose_engaged_dynamic_chase_avoidance_tile(
            world,
            entity,
            goal_tile,
            desired_range_tiles,
            controller=controller,
        )

    return choose_default_chase_avoidance_tile(
        world,
        entity,
        goal_tile,
        desired_range_tiles,
        controller=controller,
    )


def choose_chase_avoidance_probe_tile_from_directions(
    world,
    entity,
    goal_tile,
    directions,
    controller=None,
    mode=CHASE_LOCAL_AVOIDANCE_DEFAULT,
    allow_worse_distance_tiles=0,
    counter_prefix=None,
):
    actor_cpos = world.transform[entity].cpos
    actor_tile = tile_from_cpos(actor_cpos)
    current_distance = chebyshev_tile_distance(actor_tile, goal_tile)

    min_probe_tiles = max(1, CHASE_LOCAL_PROBE_MIN_TILES)
    max_probe_tiles = max(min_probe_tiles, CHASE_LOCAL_PROBE_MAX_TILES)

    candidates = []

    for direction_order, direction in enumerate(directions):
        candidate = choose_best_chase_probe_tile_for_direction(
            world,
            entity,
            actor_cpos,
            actor_tile,
            goal_tile,
            direction,
            min_probe_tiles=min_probe_tiles,
            max_probe_tiles=max_probe_tiles,
            allow_worse_distance_tiles=allow_worse_distance_tiles,
            current_distance=current_distance,
            controller=controller,
        )

        if candidate is None:
            continue

        candidate_tile, probe_length, candidate_distance = candidate
        candidate_is_worse = candidate_distance > current_distance

        candidates.append(
            (
                candidate_distance,
                direction_order,
                -probe_length,
                candidate_tile.y,
                candidate_tile.x,
                candidate_is_worse,
                candidate_tile,
                probe_length,
            )
        )

    if not candidates:
        return None

    candidates.sort()

    chosen = candidates[0]
    chosen_is_worse = chosen[-3]
    chosen_tile = chosen[-2]
    chosen_length = chosen[-1]

    record_counter_for_world(
        world,
        "chase.local_probe.length",
        chosen_length,
    )
    record_counter_for_world(
        world,
        f"chase.local_probe.{mode}.length",
        chosen_length,
    )

    if chosen_length > 1:
        record_counter_for_world(
            world,
            "chase.local_probe.extended",
        )
        record_counter_for_world(
            world,
            f"chase.local_probe.{mode}.extended",
        )

    if chosen_is_worse and counter_prefix is not None:
        record_counter_for_world(
            world,
            f"{counter_prefix}.worse_candidate",
        )

    return chosen_tile


def choose_best_chase_probe_tile_for_direction(
    world,
    entity,
    actor_cpos,
    actor_tile,
    goal_tile,
    direction,
    min_probe_tiles,
    max_probe_tiles,
    allow_worse_distance_tiles,
    current_distance,
    controller=None,
):
    if direction.x == 0 and direction.y == 0:
        return None

    for probe_length in range(max_probe_tiles, min_probe_tiles - 1, -1):
        candidate_tile = actor_tile + Vec2i(
            direction.x * probe_length,
            direction.y * probe_length,
        )

        candidate_distance = chebyshev_tile_distance(
            candidate_tile,
            goal_tile,
        )

        if candidate_distance > current_distance + allow_worse_distance_tiles:
            continue

        if chase_candidate_is_recently_blocked_tile(
            world,
            controller,
            candidate_tile,
        ):
            continue

        if not chase_candidate_tile_is_reachable(
            world,
            entity,
            actor_cpos,
            candidate_tile,
        ):
            continue

        return candidate_tile, probe_length, candidate_distance

    return None


def choose_chase_avoidance_probe_tile_for_mode(
    world,
    entity,
    goal_tile,
    desired_range_tiles,
    controller=None,
    mode=CHASE_LOCAL_AVOIDANCE_DEFAULT,
    counter_prefix=None,
):
    actor_tile = tile_from_cpos(world.transform[entity].cpos)

    side_preference, _ = get_chase_local_side_preference(
        world,
        entity,
        controller,
    )

    allow_worse_distance_tiles = 0
    if (
        mode == CHASE_LOCAL_AVOIDANCE_STALLED_DYNAMIC
        and stalled_dynamic_escape_probe_is_unlocked(world, controller)
    ):
        allow_worse_distance_tiles = CHASE_STALLED_DYNAMIC_MAX_WORSEN_TILES

    directions = make_ordered_chase_direction_list(
        entity,
        actor_tile,
        goal_tile,
        side_preference=side_preference,
        order_mode=mode,
    )

    return choose_chase_avoidance_probe_tile_from_directions(
        world,
        entity,
        goal_tile,
        directions,
        controller=controller,
        mode=mode,
        allow_worse_distance_tiles=allow_worse_distance_tiles,
        counter_prefix=counter_prefix,
    )


def choose_default_chase_avoidance_tile(
    world,
    entity,
    goal_tile,
    desired_range_tiles,
    controller=None,
):
    return choose_chase_avoidance_probe_tile_for_mode(
        world,
        entity,
        goal_tile,
        desired_range_tiles,
        controller=controller,
        mode=CHASE_LOCAL_AVOIDANCE_DEFAULT,
    )


def choose_static_chase_avoidance_tile(
    world,
    entity,
    goal_tile,
    desired_range_tiles,
    controller=None,
):
    return choose_chase_avoidance_probe_tile_for_mode(
        world,
        entity,
        goal_tile,
        desired_range_tiles,
        controller=controller,
        mode=CHASE_LOCAL_AVOIDANCE_STATIC,
        counter_prefix="chase.avoidance.static",
    )


def choose_moving_dynamic_chase_avoidance_tile(
    world,
    entity,
    goal_tile,
    desired_range_tiles,
    controller=None,
):
    return choose_chase_avoidance_probe_tile_for_mode(
        world,
        entity,
        goal_tile,
        desired_range_tiles,
        controller=controller,
        mode=CHASE_LOCAL_AVOIDANCE_MOVING_DYNAMIC,
        counter_prefix="chase.avoidance.moving_dynamic",
    )


def choose_engaged_dynamic_chase_avoidance_tile(
    world,
    entity,
    goal_tile,
    desired_range_tiles,
    controller=None,
):
    return choose_chase_avoidance_probe_tile_for_mode(
        world,
        entity,
        goal_tile,
        desired_range_tiles,
        controller=controller,
        mode=CHASE_LOCAL_AVOIDANCE_ENGAGED_DYNAMIC,
        counter_prefix="chase.avoidance.engaged_dynamic",
    )


def choose_stalled_dynamic_chase_avoidance_tile(
    world,
    entity,
    goal_tile,
    desired_range_tiles,
    controller=None,
):
    return choose_chase_avoidance_probe_tile_for_mode(
        world,
        entity,
        goal_tile,
        desired_range_tiles,
        controller=controller,
        mode=CHASE_LOCAL_AVOIDANCE_STALLED_DYNAMIC,
        counter_prefix="chase.avoidance.stalled_dynamic",
    )


def chase_candidate_tile_is_reachable(
    world,
    entity,
    actor_cpos,
    candidate_tile,
):
    reachable, _ = check_chase_candidate_tile_reachability(
        world,
        entity,
        actor_cpos,
        candidate_tile,
    )
    return reachable


def check_chase_candidate_tile_reachability(
    world,
    entity,
    actor_cpos,
    candidate_tile,
):
    candidate_cpos = tile_center(candidate_tile)
    delta = candidate_cpos - actor_cpos

    static_collision_result, resolved_cpos = trace_static_tile_path(
        world,
        entity,
        actor_cpos,
        delta,
    )

    if not movement_collision_allows(static_collision_result):
        return False, static_collision_result

    if resolved_cpos != candidate_cpos:
        return (
            False,
            make_movement_collision_result(
                "block",
                blocker_collision_type="static",
                blocked_tile=tile_from_cpos(resolved_cpos),
            ),
        )

    dynamic_collision_result = handle_dynamic_movement_collision(
        world,
        entity,
        candidate_tile,
    )

    if not movement_collision_allows(dynamic_collision_result):
        return False, dynamic_collision_result

    return True, MOVEMENT_COLLISION_ALLOW


def iter_direct_chase_tiles(start_tile, goal_tile, max_tiles):
    dx = goal_tile.x - start_tile.x
    dy = goal_tile.y - start_tile.y

    steps = max(abs(dx), abs(dy))
    if steps == 0:
        return

    steps = min(steps, max_tiles)

    previous = start_tile
    for step_index in range(1, steps + 1):
        x = start_tile.x + signed_round_div(dx * step_index, steps)
        y = start_tile.y + signed_round_div(dy * step_index, steps)
        tile = Vec2i(x, y)

        if tile == previous:
            continue

        previous = tile
        yield tile


def signed_round_div(numerator, denominator):
    if numerator < 0:
        return -((-numerator + denominator // 2) // denominator)
    return (numerator + denominator // 2) // denominator


def make_ordered_chase_direction_list(
    entity,
    actor_tile,
    goal_tile,
    side_preference=None,
    order_mode=CHASE_LOCAL_AVOIDANCE_DEFAULT,
):
    dx = sign(goal_tile.x - actor_tile.x)
    dy = sign(goal_tile.y - actor_tile.y)

    if side_preference is None or side_preference == 0:
        side_preference = 1 if entity % 2 == 0 else -1

    directions = []
    seen = set()

    def add(direction):
        if direction.x == 0 and direction.y == 0:
            return

        key = (direction.x, direction.y)
        if key in seen:
            return

        seen.add(key)
        directions.append(direction)

    def ordered_side_pair(first, second):
        if side_preference > 0:
            return first, second

        return second, first

    side_directions = []

    if dx != 0 and dy != 0:
        side_directions = ordered_side_pair(
            Vec2i(dx, -dy),
            Vec2i(-dx, dy),
        )
    elif dx != 0:
        side_directions = ordered_side_pair(
            Vec2i(dx, 1),
            Vec2i(dx, -1),
        )
    elif dy != 0:
        side_directions = ordered_side_pair(
            Vec2i(1, dy),
            Vec2i(-1, dy),
        )

    axis_directions = (
        Vec2i(dx, 0),
        Vec2i(0, dy),
    )

    direct_direction = Vec2i(dx, dy)

    perpendicular_directions = []

    if dx != 0 and dy != 0:
        perpendicular_directions = ordered_side_pair(
            Vec2i(-dx, dy),
            Vec2i(dx, -dy),
        )
    elif dx != 0:
        perpendicular_directions = ordered_side_pair(
            Vec2i(0, 1),
            Vec2i(0, -1),
        )
    elif dy != 0:
        perpendicular_directions = ordered_side_pair(
            Vec2i(1, 0),
            Vec2i(-1, 0),
        )

    backward_angle_directions = []

    if dx != 0 and dy != 0:
        backward_angle_directions = ordered_side_pair(
            Vec2i(-dx, 0),
            Vec2i(0, -dy),
        )
    elif dx != 0:
        backward_angle_directions = ordered_side_pair(
            Vec2i(-dx, 1),
            Vec2i(-dx, -1),
        )
    elif dy != 0:
        backward_angle_directions = ordered_side_pair(
            Vec2i(1, -dy),
            Vec2i(-1, -dy),
        )

    if order_mode == CHASE_LOCAL_AVOIDANCE_STATIC:
        # Static obstacles are stable. If direct is blocked, commit to a
        # remembered side before trying axis-only shuffling.
        add(direct_direction)

        for direction in side_directions:
            add(direction)

        for direction in axis_directions:
            add(direction)

        return directions

    if order_mode == CHASE_LOCAL_AVOIDANCE_MOVING_DYNAMIC:
        # Moving dynamic blockers may vacate soon. Try direct/axis progress
        # first, then cheap side probes. Do not overcommit.
        add(direct_direction)

        for direction in axis_directions:
            add(direction)

        for direction in side_directions:
            add(direction)

        return directions

    if order_mode == CHASE_LOCAL_AVOIDANCE_STALLED_DYNAMIC:
        # Stalled dynamic blockers are not walls, but they are not vacating.
        # Try side movement before axis shuffling, then allow sharper escape
        # probes. The shared chooser still rejects candidates that worsen
        # distance to the goal.
        add(direct_direction)

        for direction in side_directions:
            add(direction)

        for direction in perpendicular_directions:
            add(direction)

        for direction in axis_directions:
            add(direction)

        for direction in backward_angle_directions:
            add(direction)

        return directions

    if order_mode == CHASE_LOCAL_AVOIDANCE_ENGAGED_DYNAMIC:
        # Engaged blockers are usually occupying a valid front-line slot.
        # Do not solve ring chasing here yet; for now prefer side movement
        # over pushing straight into the occupied slot again.
        add(direct_direction)

        for direction in side_directions:
            add(direction)

        for direction in axis_directions:
            add(direction)

        return directions

    # Default fallback: old behavior, parity split but no static commitment.
    add(direct_direction)

    for direction in axis_directions:
        add(direction)

    for direction in side_directions:
        add(direction)

    return directions


def target_tile_changed_sharply(old_tile, new_tile):
    if old_tile is None:
        return False

    return (
        chebyshev_tile_distance(old_tile, new_tile)
        >= CHASE_TARGET_TELEPORT_TILES
    )


def get_chase_current_waypoint(controller):
    if controller.current_index >= len(controller.waypoints):
        return None
    return controller.waypoints[controller.current_index]


def discard_pending_controller_advance(controller):
    if hasattr(controller, "_pending_index"):
        delattr(controller, "_pending_index")


def same_order_path_follow_controller_active(
    world,
    entity,
    owner_order_id,
):
    motion_state = world.motion_state.get(entity)
    if motion_state is None:
        return False

    controller = motion_state.get("controller")
    if not isinstance(controller, PathFollowController):
        return False

    if motion_state.get("controller_source") != "move_target":
        return False

    return motion_state.get("controller_owner_order_id") == owner_order_id


def recenter_for_action_controller_active(
    world,
    entity,
    target_tile,
    owner_order_id,
):
    motion_state = world.motion_state.get(entity)
    if motion_state is None:
        return False

    controller = motion_state.get("controller")
    if controller is None:
        return False

    if motion_state.get("controller_source") != "recenter_for_action":
        return False

    if motion_state.get("controller_owner_order_id") != owner_order_id:
        return False

    return motion_state.get("recenter_for_action_target_tile") == target_tile


def mark_recenter_for_action_controller(
    motion_state,
    target_tile,
    owner_order_id,
):
    motion_state["controller_source"] = "recenter_for_action"
    motion_state["controller_owner_order_id"] = owner_order_id
    motion_state["recenter_for_action_target_tile"] = target_tile
    motion_state.pop("path_follow_progress", None)


def retarget_path_follow_controller_for_action_recenter(
    world,
    entity,
    controller,
    target_tile,
    target_cpos,
    owner_order_id,
):
    locomotion = world.locomotion[entity]
    motion_state = world.motion_state[entity]

    controller.nodes = [target_cpos]
    controller.current_index = 0
    controller.speed = get_locomotion_speed_cpos_per_tick(locomotion)
    controller.created_tick = world.tick
    controller.target_tile = target_tile

    discard_pending_controller_advance(controller)

    mark_recenter_for_action_controller(
        motion_state,
        target_tile,
        owner_order_id,
    )

    clear_move_target(world, entity)
    clear_buffered_move_intent(world, entity)
    world.move_intent.pop(entity, None)

    mark_dynamic_occupancy_dirty(world)
    rebuild_dynamic_occupancy(world)

    return True


def start_recenter_for_action_settle_controller(
    world,
    entity,
    target_tile,
    target_cpos,
    owner_order_id,
):
    transform = world.transform.get(entity)
    motion_state = world.motion_state.get(entity)
    locomotion = world.locomotion.get(entity)

    if transform is None or motion_state is None or locomotion is None:
        return False

    if is_at_cpos(transform.cpos, target_cpos):
        return False

    motion_state["controller"] = SettleToGridController(
        start=transform.cpos,
        end=target_cpos,
        progress=0,
        duration=3,
    )
    motion_state["influence_mode"] = "normal"

    mark_recenter_for_action_controller(
        motion_state,
        target_tile,
        owner_order_id,
    )

    mark_dynamic_occupancy_dirty(world)
    rebuild_dynamic_occupancy(world)

    return True


def start_or_update_recenter_for_action(
    world,
    entity,
    target_tile,
    target_cpos,
    owner_order_id,
):
    clear_buffered_move_intent(world, entity)
    world.move_intent.pop(entity, None)

    if recenter_for_action_controller_active(
        world,
        entity,
        target_tile,
        owner_order_id,
    ):
        return True

    motion_state = world.motion_state.get(entity)
    if motion_state is None:
        return False

    controller = motion_state.get("controller")

    if same_order_path_follow_controller_active(
        world,
        entity,
        owner_order_id,
    ):
        return retarget_path_follow_controller_for_action_recenter(
            world,
            entity,
            controller,
            target_tile,
            target_cpos,
            owner_order_id,
        )

    clear_move_target(world, entity)

    if controller is not None:
        clear_motion_controller(motion_state)

    return start_recenter_for_action_settle_controller(
        world,
        entity,
        target_tile,
        target_cpos,
        owner_order_id,
    )


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


def entity_claims_movement_space(world, entity):
    space_occupier = world.space_occupier.get(entity)
    if space_occupier is None:
        return False

    return space_occupier.get("blocks_movement", False)


def get_movement_admission_policy(world, entity):
    claims_movement_space = entity_claims_movement_space(
        world,
        entity,
    )

    return MovementAdmissionPolicy(
        claims_movement_space=claims_movement_space,
        reserves_movement_space=claims_movement_space,
        allows_finish_current_tile=claims_movement_space,
    )


def should_debug_path_runtime_edges(world, entity) -> bool:
    if not DEBUG_PATH_RUNTIME_EDGE_CHECK:
        return False

    if not DEBUG_PATH_RUNTIME_EDGE_PLAYER_ONLY:
        return True

    return entity == getattr(world, "player", None)


def build_path_runtime_edge_probe_proposal(
    world,
    entity,
    start_cpos: Vec2i,
    end_cpos: Vec2i,
):
    delta = end_cpos - start_cpos

    return MovementProposal(
        entity=entity,
        controller=None,
        start_cpos=start_cpos,
        base_delta=delta,
        influence_delta=Vec2i(0, 0),
        final_delta=delta,
        influence_active=False,
        admission_policy=get_movement_admission_policy(
            world,
            entity,
        ),
    )


def path_runtime_edge_is_clean(proposal, approval) -> bool:
    requested_cpos = approval.requested_cpos

    if requested_cpos is None:
        requested_cpos = proposal.start_cpos + proposal.final_delta

    resolved_cpos = approval.resolved_cpos

    if resolved_cpos is None:
        resolved_cpos = proposal.start_cpos + approval.delta

    expected_cpos = proposal.start_cpos + proposal.final_delta

    return (
        approval.approved
        and approval.delta == proposal.final_delta
        and requested_cpos == expected_cpos
        and resolved_cpos == expected_cpos
        and movement_collision_allows(approval.collision_result)
        and movement_collision_allows(approval.requested_collision_result)
    )


def build_movement_proposal(world, entity):
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
    final_delta = base_delta + influence_delta

    return MovementProposal(
        entity=entity,
        controller=controller,
        start_cpos=transform.cpos,
        base_delta=base_delta,
        influence_delta=influence_delta,
        final_delta=final_delta,
        influence_active=vec_is_nonzero(influence_delta),
        admission_policy=get_movement_admission_policy(
            world,
            entity,
        ),
    )


def append_unique_movement_placement(path, tile):
    if tile not in path:
        path.append(tile)


def get_next_movement_crossing_axis(
    next_cross_x,
    next_cross_y,
    abs_dx: int,
    abs_dy: int,
):
    if next_cross_x is None:
        return "y"

    if next_cross_y is None:
        return "x"

    if near_corner_crossing(
        next_cross_x,
        next_cross_y,
        abs_dx,
        abs_dy,
    ):
        return "corner"

    left = next_cross_x * abs_dy
    right = next_cross_y * abs_dx

    if left < right:
        return "x"

    if right < left:
        return "y"

    return "corner"


def check_axis_movement_placement(world, entity, placement_path, tile):
    collision_result = handle_movement_tile_collision(
        world,
        entity,
        tile,
    )

    if not movement_collision_allows(collision_result):
        return collision_result

    append_unique_movement_placement(
        placement_path,
        tile,
    )

    return MOVEMENT_COLLISION_ALLOW


def check_corner_movement_placement(
    world,
    entity,
    placement_path,
    current_tile: Vec2i,
    step_x: int,
    step_y: int,
):
    record_counter_for_world(
        world,
        "movement.proposal.corner_crossing",
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

    collision_result = resolve_corner_crossing_collision(
        world,
        entity,
        side_x_tile,
        side_y_tile,
        diagonal_tile,
    )

    if movement_collision_allows(collision_result):
        record_counter_for_world(
            world,
            "movement.proposal.corner_crossing.allow",
        )
    else:
        record_collision_result_counter(
            world,
            "movement.proposal.corner_crossing.blocked",
            collision_result,
        )

    if not movement_collision_allows(collision_result):
        return collision_result, current_tile

    # The diagonal tile is the actual next logical center placement.
    # The side tiles are corner-clearance tests, not necessarily claimed
    # origin placements.
    append_unique_movement_placement(
        placement_path,
        diagonal_tile,
    )

    return MOVEMENT_COLLISION_ALLOW, diagonal_tile


def check_same_tile_extrapolated_movement_path(
    world,
    entity,
    current_tile: Vec2i,
    start_cpos: Vec2i,
    delta: Vec2i,
    step_x: int,
    step_y: int,
    next_cross_x,
    next_cross_y,
    abs_dx: int,
    abs_dy: int,
):
    placement_path = []

    step_axis = get_next_movement_crossing_axis(
        next_cross_x,
        next_cross_y,
        abs_dx,
        abs_dy,
    )

    blocked_axis_result = check_same_tile_blocked_axis_components(
        world,
        entity,
        current_tile,
        start_cpos,
        delta,
        step_axis,
    )

    if blocked_axis_result is not None:
        return blocked_axis_result

    if step_axis == "x":
        tile = Vec2i(
            current_tile.x + step_x,
            current_tile.y,
        )
        collision_result = check_axis_movement_placement(
            world,
            entity,
            placement_path,
            tile,
        )
    elif step_axis == "y":
        tile = Vec2i(
            current_tile.x,
            current_tile.y + step_y,
        )
        collision_result = check_axis_movement_placement(
            world,
            entity,
            placement_path,
            tile,
        )
    else:
        collision_result, _ = check_corner_movement_placement(
            world,
            entity,
            placement_path,
            current_tile,
            step_x,
            step_y,
        )

    if (
        not movement_collision_allows(collision_result)
        and same_tile_delta_stays_on_pre_center_half(
            start_cpos,
            delta,
        )
    ):
        return MovementPathCheckResult(
            collision_result=MOVEMENT_COLLISION_ALLOW,
            placement_path=(),
        )

    return MovementPathCheckResult(
        collision_result=collision_result,
        placement_path=tuple(placement_path),
    )


def check_normal_movement_delta_path(
    world,
    entity,
    start_cpos: Vec2i,
    delta: Vec2i,
):
    if not vec_is_nonzero(delta):
        return MovementPathCheckResult(
            collision_result=MOVEMENT_COLLISION_ALLOW,
            placement_path=(),
        )

    target_cpos = start_cpos + delta

    current_tile = tile_from_cpos(start_cpos)
    target_tile = tile_from_cpos(target_cpos)

    step_x = sign(delta.x)
    step_y = sign(delta.y)

    abs_dx = abs(delta.x)
    abs_dy = abs(delta.y)

    if current_tile == target_tile:
        if abs_dx == 0:
            next_cross_x = None
        elif step_x > 0:
            next_cross_x = (
                (current_tile.x + 1) * TILE_UNITS
                - start_cpos.x
            )
        else:
            next_cross_x = (
                start_cpos.x
                - current_tile.x * TILE_UNITS
            )

        if abs_dy == 0:
            next_cross_y = None
        elif step_y > 0:
            next_cross_y = (
                (current_tile.y + 1) * TILE_UNITS
                - start_cpos.y
            )
        else:
            next_cross_y = (
                start_cpos.y
                - current_tile.y * TILE_UNITS
            )

        return check_same_tile_extrapolated_movement_path(
            world,
            entity,
            current_tile,
            start_cpos,
            delta,
            step_x,
            step_y,
            next_cross_x,
            next_cross_y,
            abs_dx,
            abs_dy,
        )

    placement_path = []

    if abs_dx == 0:
        next_cross_x = None
    elif step_x > 0:
        next_cross_x = (
            (current_tile.x + 1) * TILE_UNITS
            - start_cpos.x
        )
    else:
        next_cross_x = (
            start_cpos.x
            - current_tile.x * TILE_UNITS
        )

    if abs_dy == 0:
        next_cross_y = None
    elif step_y > 0:
        next_cross_y = (
            (current_tile.y + 1) * TILE_UNITS
            - start_cpos.y
        )
    else:
        next_cross_y = (
            start_cpos.y
            - current_tile.y * TILE_UNITS
        )

    segment_start_cpos = start_cpos

    while current_tile != target_tile:
        step_axis = get_next_movement_crossing_axis(
            next_cross_x,
            next_cross_y,
            abs_dx,
            abs_dy,
        )

        if step_axis == "x":
            boundary_cpos = axis_cross_position(
                start_cpos,
                delta,
                next_cross_x,
                abs_dx,
            )
            segment_end_cpos = safe_before_x_cross(
                boundary_cpos,
                step_x,
            )

            blocked_axis_result = check_blocked_axis_components_for_segment(
                world,
                entity,
                current_tile,
                segment_start_cpos,
                segment_end_cpos,
                step_axis,
            )

            if blocked_axis_result is not None:
                return blocked_axis_result

            next_tile = Vec2i(
                current_tile.x + step_x,
                current_tile.y,
            )

            collision_result = check_axis_movement_placement(
                world,
                entity,
                placement_path,
                next_tile,
            )

            if not movement_collision_allows(collision_result):
                return MovementPathCheckResult(
                    collision_result=collision_result,
                    placement_path=tuple(placement_path),
                )

            current_tile = next_tile
            if step_x > 0:
                segment_start_cpos = boundary_cpos
            else:
                segment_start_cpos = Vec2i(
                    boundary_cpos.x - 1,
                    boundary_cpos.y,
                )
            next_cross_x += TILE_UNITS
            continue

        if step_axis == "y":
            boundary_cpos = axis_cross_position(
                start_cpos,
                delta,
                next_cross_y,
                abs_dy,
            )
            segment_end_cpos = safe_before_y_cross(
                boundary_cpos,
                step_y,
            )

            blocked_axis_result = check_blocked_axis_components_for_segment(
                world,
                entity,
                current_tile,
                segment_start_cpos,
                segment_end_cpos,
                step_axis,
            )

            if blocked_axis_result is not None:
                return blocked_axis_result

            next_tile = Vec2i(
                current_tile.x,
                current_tile.y + step_y,
            )

            collision_result = check_axis_movement_placement(
                world,
                entity,
                placement_path,
                next_tile,
            )

            if not movement_collision_allows(collision_result):
                return MovementPathCheckResult(
                    collision_result=collision_result,
                    placement_path=tuple(placement_path),
                )

            current_tile = next_tile
            if step_y > 0:
                segment_start_cpos = boundary_cpos
            else:
                segment_start_cpos = Vec2i(
                    boundary_cpos.x,
                    boundary_cpos.y - 1,
                )
            next_cross_y += TILE_UNITS
            continue

        boundary_cpos = corner_boundary_cpos(
            current_tile,
            step_x,
            step_y,
        )
        segment_end_cpos = safe_before_corner_cross(
            boundary_cpos,
            step_x,
            step_y,
        )

        blocked_axis_result = check_blocked_axis_components_for_segment(
            world,
            entity,
            current_tile,
            segment_start_cpos,
            segment_end_cpos,
            step_axis,
        )

        if blocked_axis_result is not None:
            return blocked_axis_result

        collision_result, next_tile = check_corner_movement_placement(
            world,
            entity,
            placement_path,
            current_tile,
            step_x,
            step_y,
        )

        if not movement_collision_allows(collision_result):
            return MovementPathCheckResult(
                collision_result=collision_result,
                placement_path=tuple(placement_path),
            )

        current_tile = next_tile
        segment_start_cpos = Vec2i(
            boundary_cpos.x if step_x > 0 else boundary_cpos.x - 1,
            boundary_cpos.y if step_y > 0 else boundary_cpos.y - 1,
        )
        next_cross_x += TILE_UNITS
        next_cross_y += TILE_UNITS

    final_segment_result = check_blocked_axis_components_for_segment(
        world,
        entity,
        current_tile,
        segment_start_cpos,
        target_cpos,
        "corner",
    )

    if final_segment_result is not None:
        return final_segment_result

    return MovementPathCheckResult(
        collision_result=MOVEMENT_COLLISION_ALLOW,
        placement_path=tuple(placement_path),
    )


def make_allowed_movement_approval(
    proposal: MovementProposal,
    delta: Vec2i,
    resolution_kind: str,
    placement_path=(),
    requested_collision_result=MOVEMENT_COLLISION_ALLOW,
):
    return MovementApproval(
        entity=proposal.entity,
        approved=True,
        delta=delta,
        resolution_kind=resolution_kind,
        collision_result=MOVEMENT_COLLISION_ALLOW,
        requested_collision_result=requested_collision_result,
        placement_path=placement_path,
        requested_cpos=proposal.start_cpos + proposal.final_delta,
        resolved_cpos=proposal.start_cpos + delta,
    )


def make_blocked_movement_approval(
    proposal: MovementProposal,
    collision_result: MovementCollisionResult,
    resolution_kind: str,
    placement_path=(),
):
    return MovementApproval(
        entity=proposal.entity,
        approved=True,
        delta=Vec2i(0, 0),
        resolution_kind=resolution_kind,
        collision_result=collision_result,
        requested_collision_result=collision_result,
        placement_path=placement_path,
        requested_cpos=proposal.start_cpos + proposal.final_delta,
        resolved_cpos=proposal.start_cpos,
    )


def is_explicit_current_tile_centering(proposal: MovementProposal):
    return (
        proposal.admission_policy.allows_finish_current_tile
        and isinstance(proposal.controller, SettleToGridController)
        and not proposal.influence_active
    )


def build_explicit_centering_approval(proposal: MovementProposal):
    return make_allowed_movement_approval(
        proposal,
        proposal.final_delta,
        "explicit_centering",
        placement_path=(),
    )


def get_blocked_axis_from_collision(
    start_cpos: Vec2i,
    collision_result: MovementCollisionResult,
):
    blocked_tile = collision_result.blocked_tile
    if blocked_tile is None:
        return None

    current_tile = tile_from_cpos(start_cpos)
    dx = blocked_tile.x - current_tile.x
    dy = blocked_tile.y - current_tile.y

    if dx != 0 and dy == 0:
        return "x"

    if dy != 0 and dx == 0:
        return "y"

    return None


def get_tangent_axis_for_blocked_axis(blocked_axis: str):
    if blocked_axis == "x":
        return "y"

    if blocked_axis == "y":
        return "x"

    return None


def get_axis_component(vec: Vec2i, axis: str) -> int:
    if axis == "x":
        return vec.x

    if axis == "y":
        return vec.y

    raise ValueError(f"Unknown movement axis {axis!r}")


def build_blocked_axis_center_delta(
    start_cpos: Vec2i,
    reference_delta: Vec2i,
    blocked_axis: str,
) -> Vec2i:
    if not vec_is_nonzero(reference_delta):
        return Vec2i(0, 0)

    current_tile = tile_from_cpos(start_cpos)
    current_center = tile_center(current_tile)

    if blocked_axis == "x":
        to_center = Vec2i(
            current_center.x - start_cpos.x,
            0,
        )
    elif blocked_axis == "y":
        to_center = Vec2i(
            0,
            current_center.y - start_cpos.y,
        )
    else:
        return Vec2i(0, 0)

    if not vec_is_nonzero(to_center):
        return Vec2i(0, 0)

    return clamp_vec_length_to_reference(
        to_center,
        reference_delta,
    )


def try_build_clipped_to_center_approval(
    proposal: MovementProposal,
    rejection_result: MovementCollisionResult,
):
    if not proposal.admission_policy.allows_finish_current_tile:
        return None

    if movement_collision_destroys(rejection_result):
        return None

    blocked_axis = get_blocked_axis_from_collision(
        proposal.start_cpos,
        rejection_result,
    )

    if blocked_axis is None:
        return None

    center_delta = build_blocked_axis_center_delta(
        proposal.start_cpos,
        proposal.final_delta,
        blocked_axis,
    )

    if not vec_is_nonzero(center_delta):
        return None

    return make_allowed_movement_approval(
        proposal,
        center_delta,
        "clipped_to_blocked_axis_center",
        placement_path=(),
        requested_collision_result=rejection_result,
    )


def try_build_direct_movement_approval(proposal: MovementProposal, world):
    path_check = check_normal_movement_delta_path(
        world,
        proposal.entity,
        proposal.start_cpos,
        proposal.final_delta,
    )

    if not movement_collision_allows(path_check.collision_result):
        return None, path_check

    return (
        make_allowed_movement_approval(
            proposal,
            proposal.final_delta,
            "direct",
            placement_path=path_check.placement_path,
        ),
        path_check,
    )


def try_build_directional_center_finish_approval(
    world,
    proposal: MovementProposal,
    direct_rejection: MovementPathCheckResult,
):
    if not isinstance(proposal.controller, DirectionalMoveController):
        return None

    if not proposal.admission_policy.allows_finish_current_tile:
        return None

    current_tile = tile_from_cpos(proposal.start_cpos)
    current_center = tile_center(current_tile)

    center_delta = current_center - proposal.start_cpos

    if not vec_is_nonzero(center_delta):
        return None

    center_delta = clamp_vec_length_to_reference(
        center_delta,
        proposal.final_delta,
    )

    if not vec_is_nonzero(center_delta):
        return None

    center_check = check_normal_movement_delta_path(
        world,
        proposal.entity,
        proposal.start_cpos,
        center_delta,
    )

    if not movement_collision_allows(center_check.collision_result):
        return None

    return MovementApproval(
        entity=proposal.entity,
        approved=True,
        delta=center_delta,
        resolution_kind="blocked_directional_center_finish",
        collision_result=MOVEMENT_COLLISION_ALLOW,
        requested_collision_result=direct_rejection.collision_result,
        placement_path=tuple(center_check.placement_path),
        requested_cpos=proposal.start_cpos + proposal.final_delta,
        resolved_cpos=proposal.start_cpos + center_delta,
    )


def try_build_path_follow_current_node_finish_approval(
    world,
    proposal: MovementProposal,
    direct_rejection: MovementPathCheckResult,
):
    controller = proposal.controller

    if not isinstance(controller, PathFollowController):
        return None

    current_node = get_path_follow_current_node(controller)

    if current_node is None:
        return None

    node_delta = current_node - proposal.start_cpos

    if not vec_is_nonzero(node_delta):
        return None

    node_distance = cpos_vector_length(node_delta)
    request_budget = cpos_vector_length(proposal.final_delta)

    if node_distance > request_budget:
        return None

    node_check = check_normal_movement_delta_path(
        world,
        proposal.entity,
        proposal.start_cpos,
        node_delta,
    )

    if not movement_collision_allows(node_check.collision_result):
        return None

    controller._pending_index = controller.current_index + 1

    return MovementApproval(
        entity=proposal.entity,
        approved=True,
        delta=node_delta,
        resolution_kind="path_follow_current_node_finish",
        collision_result=MOVEMENT_COLLISION_ALLOW,
        requested_collision_result=direct_rejection.collision_result,
        placement_path=tuple(node_check.placement_path),
        requested_cpos=proposal.start_cpos + node_delta,
        resolved_cpos=proposal.start_cpos + node_delta,
    )


def try_build_slide_approval(
    world,
    proposal: MovementProposal,
    direct_rejection: MovementPathCheckResult,
):
    collision_result = direct_rejection.collision_result

    if not movement_collision_can_attempt_slide(collision_result):
        return None

    blocked_axis = get_blocked_axis_from_collision(
        proposal.start_cpos,
        collision_result,
    )
    tangent_axis = get_tangent_axis_for_blocked_axis(blocked_axis)

    if blocked_axis is None or tangent_axis is None:
        return None

    requested_delta = proposal.final_delta

    normal_component = get_axis_component(
        requested_delta,
        blocked_axis,
    )
    tangent_component = get_axis_component(
        requested_delta,
        tangent_axis,
    )

    if tangent_component == 0:
        return None

    ratio = get_movement_slide_ratio(
        world,
        proposal.entity,
    )

    if not passes_slide_threshold(
        tangent_component,
        normal_component,
        ratio,
    ):
        return None

    center_delta = build_blocked_axis_center_delta(
        proposal.start_cpos,
        requested_delta,
        blocked_axis,
    )

    slide_start_cpos = proposal.start_cpos + center_delta

    remaining_budget = get_remaining_movement_budget(
        requested_delta,
        center_delta,
    )

    if remaining_budget <= 0:
        if not vec_is_nonzero(center_delta):
            return None

        return make_allowed_movement_approval(
            proposal,
            center_delta,
            "clipped_to_blocked_axis_center",
            placement_path=(),
            requested_collision_result=collision_result,
        )

    slide_delta = build_axis_delta_from_budget(
        tangent_axis,
        sign(tangent_component),
        remaining_budget,
    )

    if not vec_is_nonzero(slide_delta):
        if not vec_is_nonzero(center_delta):
            return None

        return make_allowed_movement_approval(
            proposal,
            center_delta,
            "clipped_to_blocked_axis_center",
            placement_path=(),
            requested_collision_result=collision_result,
        )

    slide_check = check_normal_movement_delta_path(
        world,
        proposal.entity,
        slide_start_cpos,
        slide_delta,
    )

    if not movement_collision_allows(slide_check.collision_result):
        if not vec_is_nonzero(center_delta):
            return None

        return make_allowed_movement_approval(
            proposal,
            center_delta,
            "clipped_to_blocked_axis_center",
            placement_path=(),
            requested_collision_result=collision_result,
        )

    resolved_delta = center_delta + slide_delta

    resolution_kind = "slide"
    if vec_is_nonzero(center_delta):
        resolution_kind = "blocked_axis_center_then_slide"

    return make_allowed_movement_approval(
        proposal,
        resolved_delta,
        resolution_kind,
        placement_path=slide_check.placement_path,
        requested_collision_result=collision_result,
    )


def build_movement_admission_approval(world, proposal: MovementProposal):
    if not vec_is_nonzero(proposal.final_delta):
        return make_allowed_movement_approval(
            proposal,
            Vec2i(0, 0),
            "zero",
            placement_path=(),
        )

    if is_explicit_current_tile_centering(proposal):
        return build_explicit_centering_approval(proposal)

    direct_approval, direct_rejection = try_build_direct_movement_approval(
        proposal,
        world,
    )

    if direct_approval is not None:
        return direct_approval

    record_direct_rejection_counters(
        world,
        direct_rejection.collision_result,
    )

    path_node_finish_approval = try_build_path_follow_current_node_finish_approval(
        world,
        proposal,
        direct_rejection,
    )

    if path_node_finish_approval is not None:
        return path_node_finish_approval

    slide_approval = try_build_slide_approval(
        world,
        proposal,
        direct_rejection,
    )

    if slide_approval is not None:
        return slide_approval
    center_finish_approval = try_build_directional_center_finish_approval(
        world,
        proposal,
        direct_rejection,
    )

    if center_finish_approval is not None:
        return center_finish_approval

    clipped_to_center_approval = try_build_clipped_to_center_approval(
        proposal,
        direct_rejection.collision_result,
    )

    if clipped_to_center_approval is not None:
        return clipped_to_center_approval

    return make_blocked_movement_approval(
        proposal,
        direct_rejection.collision_result,
        "blocked",
        placement_path=direct_rejection.placement_path,
    )


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


def get_controller_debug_name(controller):
    if controller is None:
        return "none"

    return getattr(
        controller,
        "motion_tag",
        controller.__class__.__name__,
    )


def get_path_follow_debug_info(controller):
    if not isinstance(controller, PathFollowController):
        return {
            "path_index": None,
            "path_len": None,
            "current_path_node": None,
            "next_path_nodes": (),
        }

    nodes = getattr(controller, "nodes", ())
    current_index = getattr(controller, "current_index", None)

    current_path_node = None
    next_path_nodes = ()

    if current_index is not None and 0 <= current_index < len(nodes):
        current_path_node = nodes[current_index]
        next_path_nodes = tuple(nodes[current_index:current_index + 4])

    return {
        "path_index": current_index,
        "path_len": len(nodes),
        "current_path_node": current_path_node,
        "next_path_nodes": next_path_nodes,
    }


def get_move_target_debug_info(world, entity):
    move_target = world.move_target.get(entity)
    if move_target is None:
        return {
            "move_target_tile": None,
            "move_target_cpos": None,
        }

    return {
        "move_target_tile": move_target.get("target_tile"),
        "move_target_cpos": move_target.get("target_cpos"),
    }


def build_debug_enemy_movement_info(world, proposal, approval):
    entity = proposal.entity
    agent = world.ai_agent.get(entity, {})
    motion_state = world.motion_state.get(entity, {})
    controller = proposal.controller

    path_info = get_path_follow_debug_info(controller)
    move_target_info = get_move_target_debug_info(world, entity)

    return {
        "entity": entity,
        "ai_state": agent.get("state"),
        "target_entity": agent.get("debug_target_entity", agent.get("target_entity")),
        "in_attack_range": agent.get("debug_in_attack_range"),
        "attack_position_tile": agent.get("debug_attack_position_tile"),
        "controller": get_controller_debug_name(controller),
        "controller_source": motion_state.get("controller_source"),
        "start_cpos": proposal.start_cpos,
        "direct_end_cpos": proposal.start_cpos + proposal.final_delta,
        "approved_end_cpos": approval.resolved_cpos,
        "resolution_kind": approval.resolution_kind,
        "collision_result": approval.collision_result.collision_result,
        "blocker_collision_type": approval.collision_result.blocker_collision_type,
        "blocked_tile": approval.collision_result.blocked_tile,
        "blocker_entity": approval.collision_result.blocker_entity,
        "requested_collision_result": (
            approval.requested_collision_result.collision_result
        ),
        "requested_blocker_collision_type": (
            approval.requested_collision_result.blocker_collision_type
        ),
        "requested_blocked_tile": approval.requested_collision_result.blocked_tile,
        "requested_blocker_entity": approval.requested_collision_result.blocker_entity,
        "placement_path": approval.placement_path,
        **move_target_info,
        **path_info,
    }


def record_debug_enemy_movement_info(world, proposal, approval):
    if not getattr(world.game, "debug_mode", False):
        return

    if proposal.entity not in world.ai_agent:
        return

    world.debug_enemy_movement[proposal.entity] = build_debug_enemy_movement_info(
        world,
        proposal,
        approval,
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


def make_path_runtime_clean_edge_filter(world, entity):
    cache = {}

    def edge_is_allowed(from_tile: Vec2i, to_tile: Vec2i) -> bool:
        key = (
            from_tile.x,
            from_tile.y,
            to_tile.x,
            to_tile.y,
        )

        if key in cache:
            return cache[key]

        start_cpos = tile_center(from_tile)
        end_cpos = tile_center(to_tile)

        proposal = build_path_runtime_edge_probe_proposal(
            world,
            entity,
            start_cpos,
            end_cpos,
        )

        approval = build_movement_admission_approval(
            world,
            proposal,
        )

        clean = path_runtime_edge_is_clean(
            proposal,
            approval,
        )

        cache[key] = clean
        return clean

    return edge_is_allowed


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




def debug_path_runtime_edges_for_tile_path(
    world,
    entity,
    label: str,
    start_tile: Vec2i,
    path_tiles,
):
    if not should_debug_path_runtime_edges(world, entity):
        return

    full_path = [start_tile] + list(path_tiles)

    if len(full_path) < 2:
        print(
            f"[path_edge_runtime_empty] tick={world.tick} entity={entity} "
            f"label={label} start={start_tile} path={path_tiles}"
        )
        return

    checked = 0
    bad = 0

    for index in range(len(full_path) - 1):
        from_tile = full_path[index]
        to_tile = full_path[index + 1]

        start_cpos = tile_center(from_tile)
        end_cpos = tile_center(to_tile)

        proposal = build_path_runtime_edge_probe_proposal(
            world,
            entity,
            start_cpos,
            end_cpos,
        )

        approval = build_movement_admission_approval(
            world,
            proposal,
        )

        checked += 1

        if path_runtime_edge_is_clean(proposal, approval):
            continue

        bad += 1

        requested_cpos = approval.requested_cpos

        if requested_cpos is None:
            requested_cpos = proposal.start_cpos + proposal.final_delta

        resolved_cpos = approval.resolved_cpos

        if resolved_cpos is None:
            resolved_cpos = proposal.start_cpos + approval.delta

        print(
            f"[path_edge_runtime_mismatch] tick={world.tick} entity={entity} "
            f"label={label} edge_index={index} "
            f"from_tile={from_tile} to_tile={to_tile} "
            f"start_cpos={start_cpos} end_cpos={end_cpos} "
            f"delta={proposal.final_delta} "
            f"approved={approval.approved} "
            f"approved_delta={approval.delta} "
            f"resolution={approval.resolution_kind} "
            f"collision={approval.collision_result.collision_result} "
            f"blocker_type={approval.collision_result.blocker_collision_type} "
            f"blocked_tile={approval.collision_result.blocked_tile} "
            f"requested_collision={approval.requested_collision_result.collision_result} "
            f"requested_blocker_type={approval.requested_collision_result.blocker_collision_type} "
            f"requested_blocked_tile={approval.requested_collision_result.blocked_tile} "
            f"requested_cpos={requested_cpos} "
            f"resolved_cpos={resolved_cpos} "
            f"placement_path={approval.placement_path} "
            f"full_path={full_path}"
        )

    print(
        f"[path_edge_runtime_summary] tick={world.tick} entity={entity} "
        f"label={label} start={start_tile} "
        f"edges_checked={checked} bad_edges={bad}"
    )
