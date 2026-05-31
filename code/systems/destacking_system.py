from policies import DESTACK_POLICIES
from support import Vec2i
from utils.perf_profiler import profiled
from systems.movement_system import (
    clear_failed_path_queries_for_entity,
    clear_motion_controller,
    clear_move_target,
)
from utils.occupancy_utils import (
    get_dynamic_movement_blockers_for_placement,
    get_entity_movement_body_tiles,
    get_entity_movement_center_tile,
    mark_dynamic_occupancy_dirty,
    rebuild_dynamic_occupancy,
    space_occupier_blocks_movement,
)
from utils.placement_utils import (
    is_tile_valid_for_entity_placement,
    iter_tile_ring,
)
from utils.tile_vec_utils import tile_center


@profiled("destacking_system")
def destacking_system(world, policy_name="default"):
    policy = get_destack_policy(policy_name)

    rebuild_dynamic_occupancy(world)

    for _ in range(policy["max_passes"]):
        groups = get_stacked_occupant_groups(world)

        if not groups:
            return

        moved_any = False

        for origin_tile, entities in groups:
            if resolve_stacked_occupants(
                world,
                origin_tile,
                entities,
                policy,
            ):
                moved_any = True

        if not moved_any:
            return


def get_destack_policy(policy_name="default"):
    return DESTACK_POLICIES[policy_name]


def entity_can_participate_in_destacking(world, entity):
    if entity not in world.transform:
        return False

    if not space_occupier_blocks_movement(world, entity):
        return False

    return True


def get_destack_stay_priority(world, entity, policy):
    if entity == getattr(world, "player", None):
        return policy["player_stay_priority"]

    return policy["default_stay_priority"]


def choose_destack_anchor(world, entities, policy):
    return sorted(
        entities,
        key=lambda entity: (
            -get_destack_stay_priority(world, entity, policy),
            entity,
        ),
    )[0]


def get_destack_movers(world, entities, anchor, policy):
    return sorted(
        (
            entity
            for entity in entities
            if entity != anchor
        ),
        key=lambda entity: (
            get_destack_stay_priority(world, entity, policy),
            entity,
        ),
    )




def destack_placement_is_valid(world, entity, tile):
    return is_tile_valid_for_entity_placement(
        world,
        tile,
        entity=entity,
        include_dynamic=True,
    )


def find_valid_destack_placement(world, entity, origin_tile, policy):
    max_search_radius = policy["max_search_radius"]

    for radius in range(1, max_search_radius + 1):
        candidates = sorted(
            iter_tile_ring(origin_tile, radius),
            key=lambda tile: (
                tile.y,
                tile.x,
            ),
        )

        for candidate_tile in candidates:
            if destack_placement_is_valid(
                world,
                entity,
                candidate_tile,
            ):
                return candidate_tile

    return None


def clear_entity_movement_after_destack(world, entity):
    motion_state = world.motion_state.get(entity)

    if motion_state is not None:
        clear_motion_controller(motion_state)
        motion_state["last_delta"] = Vec2i(0, 0)

    clear_move_target(world, entity)
    clear_failed_path_queries_for_entity(world, entity)

    world.move_intent.pop(entity, None)
    world.buffered_move_intent.pop(entity, None)


def snap_entity_to_destack_placement(world, entity, destination_tile):
    transform = world.transform[entity]
    destination_cpos = tile_center(destination_tile)

    transform.cpos = destination_cpos
    transform.prev_cpos = destination_cpos
    transform.tile = destination_tile

    clear_entity_movement_after_destack(world, entity)

    mark_dynamic_occupancy_dirty(world)
    rebuild_dynamic_occupancy(world)


def get_destack_conflicts_for_entity(world, entity):
    if not entity_can_participate_in_destacking(
        world,
        entity,
    ):
        return ()

    center_tile = get_entity_movement_center_tile(
        world,
        entity,
    )

    if center_tile is None:
        return ()

    body_tiles = get_entity_movement_body_tiles(
        world,
        entity,
    )

    return get_dynamic_movement_blockers_for_placement(
        world,
        mover_entity=entity,
        proposed_center_tile=center_tile,
        proposed_body_tiles=body_tiles,
        include_reservations=False,
    )


def get_destack_origin_tile(world, entities):
    for entity in sorted(entities):
        center_tile = get_entity_movement_center_tile(
            world,
            entity,
        )

        if center_tile is not None:
            return center_tile

    return None


def get_stacked_occupant_groups(world):
    groups = []
    seen_groups = set()

    for entity in sorted(world.space_occupier):
        if not entity_can_participate_in_destacking(
            world,
            entity,
        ):
            continue

        conflicts = get_destack_conflicts_for_entity(
            world,
            entity,
        )

        if not conflicts:
            continue

        group = tuple(
            sorted(
                set(conflicts)
                | {entity}
            )
        )

        if group in seen_groups:
            continue

        seen_groups.add(group)

        origin_tile = get_destack_origin_tile(
            world,
            group,
        )

        if origin_tile is None:
            continue

        groups.append((
            origin_tile,
            list(group),
        ))

    groups.sort(
        key=lambda item: (
            item[0].y,
            item[0].x,
            tuple(item[1]),
        ),
    )

    return groups


def resolve_stacked_occupants(world, origin_tile, entities, policy):
    current_entities = set()

    for entity in entities:
        conflicts = get_destack_conflicts_for_entity(
            world,
            entity,
        )

        if conflicts:
            current_entities.add(entity)
            current_entities.update(conflicts)

    current_entities = sorted(
        entity
        for entity in current_entities
        if entity_can_participate_in_destacking(world, entity)
    )

    if len(current_entities) < 2:
        return False

    anchor = choose_destack_anchor(
        world,
        current_entities,
        policy,
    )

    movers = get_destack_movers(
        world,
        current_entities,
        anchor,
        policy,
    )

    moved_any = False

    for mover in movers:
        conflicts = get_destack_conflicts_for_entity(
            world,
            mover,
        )

        if not conflicts:
            continue

        mover_origin_tile = get_entity_movement_center_tile(
            world,
            mover,
        )

        if mover_origin_tile is None:
            continue

        destination_tile = find_valid_destack_placement(
            world,
            mover,
            mover_origin_tile,
            policy,
        )

        if destination_tile is None:
            if policy.get("debug_print", False):
                print(
                    "[destack] failed to move entity "
                    f"{mover} from conflict near {mover_origin_tile}"
                )

            continue

        if policy.get("debug_print", False):
            print(
                "[destack] moved entity "
                f"{mover} from tile {mover_origin_tile} "
                f"to tile {destination_tile}"
            )

        snap_entity_to_destack_placement(
            world,
            mover,
            destination_tile,
        )

        moved_any = True

    return moved_any