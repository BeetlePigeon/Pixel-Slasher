from policies import DESTACK_POLICIES
from support import Vec2i
from utils.perf_profiler import profiled
from systems.movement_system import (
    clear_failed_path_queries_for_entity,
    clear_motion_controller,
    clear_move_target,
)
from utils.occupancy_utils import (
    get_entity_occupied_tiles,
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


def get_entity_occupied_tiles_for_destacking(world, entity):
    if not entity_can_participate_in_destacking(world, entity):
        return ()

    return get_entity_occupied_tiles(
        world,
        entity,
    )


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


def get_destack_occupants_on_tile(world, tile):
    occupants = []

    for entity in sorted(world.space_occupier):
        if not entity_can_participate_in_destacking(world, entity):
            continue

        occupied_tiles = get_entity_occupied_tiles_for_destacking(
            world,
            entity,
        )

        if tile in occupied_tiles:
            occupants.append(entity)

    return occupants


def get_stacked_occupant_groups(world):
    tile_to_entities = {}

    for entity in sorted(world.space_occupier):
        if not entity_can_participate_in_destacking(world, entity):
            continue

        for tile in get_entity_occupied_tiles_for_destacking(world, entity):
            tile_to_entities.setdefault(
                tile,
                [],
            ).append(entity)

    groups = []

    for tile, entities in tile_to_entities.items():
        if len(entities) < 2:
            continue

        groups.append((
            tile,
            sorted(entities),
        ))

    groups.sort(
        key=lambda item: (
            item[0].y,
            item[0].x,
        ),
    )

    return groups


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


def resolve_stacked_occupants(world, origin_tile, entities, policy):
    current_entities = get_destack_occupants_on_tile(
        world,
        origin_tile,
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
        # Another move earlier in this pass may already have changed the
        # stack, so re-check before resolving this entity.
        current_entities = get_destack_occupants_on_tile(
            world,
            origin_tile,
        )

        if mover not in current_entities:
            continue

        if len(current_entities) < 2:
            break

        destination_tile = find_valid_destack_placement(
            world,
            mover,
            origin_tile,
            policy,
        )

        if destination_tile is None:
            if policy.get("debug_print", False):
                print(
                    "[destack] failed to move entity "
                    f"{mover} from stacked tile {origin_tile}"
                )
            continue

        if policy.get("debug_print", False):
            print(
                "[destack] moved entity "
                f"{mover} from tile {origin_tile} "
                f"to tile {destination_tile}"
            )

        snap_entity_to_destack_placement(
            world,
            mover,
            destination_tile,
        )

        moved_any = True

    return moved_any