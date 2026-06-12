from constants import TILE_UNITS
from data.tables_tile_footprints import get_footprint_offsets
from support import Vec2i
from utils.contact_filtering_utils import filter_contact_candidates
from utils.perf_profiler import profiled, record_counter_for_world
from utils.tile_vec_utils import sign, tile_from_cpos


def mark_dynamic_occupancy_dirty(world):
    world.dynamic_occupancy_dirty = True


def space_occupier_blocks_movement(world, eid):
    space_occupier = world.space_occupier.get(eid)

    if space_occupier is None:
        return False

    return bool(space_occupier.get("blocks_movement", True))


def get_entity_movement_footprint_name(world, eid):
    space_occupier = world.space_occupier.get(eid)
    if space_occupier is None:
        raise KeyError(
            f"Entity {eid} has no space_occupier component; "
            "movement footprint must be explicit"
        )

    if "movement_footprint" not in space_occupier:
        raise KeyError(
            f"Entity {eid} space_occupier has no movement_footprint"
        )

    return space_occupier["movement_footprint"]


def get_entity_movement_footprint_offsets(world, eid):
    return get_footprint_offsets(
        get_entity_movement_footprint_name(world, eid)
    )


def get_movement_center_tile_for_origin_tile(origin_tile):
    return origin_tile


def get_movement_body_tiles_for_origin_tile(world, eid, origin_tile):
    return tuple(
        origin_tile + offset
        for offset in get_entity_movement_footprint_offsets(world, eid)
    )


def get_movement_wing_tiles_for_origin_tile(world, eid, origin_tile):
    center_tile = get_movement_center_tile_for_origin_tile(origin_tile)

    return tuple(
        tile
        for tile in get_movement_body_tiles_for_origin_tile(
            world,
            eid,
            origin_tile,
        )
        if tile != center_tile
    )


def get_entity_movement_center_tile(world, eid):
    transform = world.transform.get(eid)

    if transform is None:
        return None

    return tile_from_cpos(transform.cpos)


def get_entity_movement_body_tiles(world, eid):
    center_tile = get_entity_movement_center_tile(world, eid)

    if center_tile is None:
        return ()

    if not space_occupier_blocks_movement(world, eid):
        return ()

    return get_movement_body_tiles_for_origin_tile(
        world,
        eid,
        center_tile,
    )


def get_entity_movement_wing_tiles(world, eid):
    center_tile = get_entity_movement_center_tile(world, eid)

    if center_tile is None:
        return ()

    if not space_occupier_blocks_movement(world, eid):
        return ()

    return get_movement_wing_tiles_for_origin_tile(
        world,
        eid,
        center_tile,
    )


# Compatibility: this now means "movement body tiles",
# not "fully hard occupied tiles".
def get_entity_occupied_tiles(world, eid):
    return get_entity_movement_body_tiles(world, eid)


def get_first_tile_entered_from_cpos(start_cpos, target_cpos):
    current_tile = tile_from_cpos(start_cpos)
    target_tile = tile_from_cpos(target_cpos)

    if target_tile == current_tile:
        return None

    dx = target_cpos.x - start_cpos.x
    dy = target_cpos.y - start_cpos.y

    step_x = sign(dx)
    step_y = sign(dy)

    abs_dx = abs(dx)
    abs_dy = abs(dy)

    if step_x == 0 and step_y == 0:
        return None

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

    if next_cross_x is None:
        return current_tile + Vec2i(0, step_y)

    if next_cross_y is None:
        return current_tile + Vec2i(step_x, 0)

    left = next_cross_x * abs_dy
    right = next_cross_y * abs_dx

    if left < right:
        return current_tile + Vec2i(step_x, 0)

    if right < left:
        return current_tile + Vec2i(0, step_y)

    return current_tile + Vec2i(step_x, step_y)


def get_controller_immediate_next_tile(current_cpos, controller):
    if hasattr(controller, "end"):
        return get_first_tile_entered_from_cpos(
            current_cpos,
            controller.end,
        )

    if hasattr(controller, "nodes") and hasattr(controller, "current_index"):
        index = controller.current_index

        while index < len(controller.nodes):
            target_cpos = controller.nodes[index]

            if target_cpos == current_cpos:
                index += 1
                continue

            return get_first_tile_entered_from_cpos(
                current_cpos,
                target_cpos,
            )

    if hasattr(controller, "raw_direction"):
        current_tile = tile_from_cpos(current_cpos)
        dx = sign(controller.raw_direction.x)
        dy = sign(controller.raw_direction.y)

        if dx == 0 and dy == 0:
            return None

        return current_tile + Vec2i(dx, dy)

    return None


def get_entity_reserved_center_tile(world, eid):
    if not space_occupier_blocks_movement(world, eid):
        return None

    transform = world.transform.get(eid)

    if transform is None:
        return None

    motion_state = world.motion_state.get(eid)

    if motion_state is None:
        return None

    controller = motion_state.get("controller")

    if controller is None:
        return None

    current_tile = tile_from_cpos(transform.cpos)

    next_tile = get_controller_immediate_next_tile(
        transform.cpos,
        controller,
    )

    if next_tile is None:
        return None

    if next_tile == current_tile:
        return None

    if abs(next_tile.x - current_tile.x) > 1:
        return None

    if abs(next_tile.y - current_tile.y) > 1:
        return None

    return next_tile


def get_entity_reserved_body_tiles(world, eid):
    reserved_center_tile = get_entity_reserved_center_tile(world, eid)

    if reserved_center_tile is None:
        return ()

    return get_movement_body_tiles_for_origin_tile(
        world,
        eid,
        reserved_center_tile,
    )


# Compatibility name.
def get_entity_reserved_tiles(world, eid):
    return get_entity_reserved_body_tiles(world, eid)


def reset_dynamic_occupancy_maps(world):
    world.dynamic_center_occupancy = {}
    world.dynamic_body_occupancy = {}
    world.dynamic_reserved_centers = {}
    world.dynamic_reserved_bodies = {}

    world.dynamic_center_tiles_by_entity = {}
    world.dynamic_body_tiles_by_entity = {}
    world.dynamic_reserved_center_tiles_by_entity = {}
    world.dynamic_reserved_body_tiles_by_entity = {}

    # Compatibility aliases.
    world.dynamic_occupancy = world.dynamic_body_occupancy
    world.dynamic_blocking_occupancy = world.dynamic_body_occupancy
    world.dynamic_reservations = world.dynamic_reserved_bodies


def add_entity_tile_to_occupancy(
    occupancy_map,
    reverse_map,
    eid,
    tile,
):
    occupancy_map.setdefault(
        tile,
        set(),
    ).add(eid)

    reverse_map.setdefault(
        eid,
        set(),
    ).add(tile)


def discard_entity_tiles_from_occupancy(
    occupancy_map,
    reverse_map,
    eid,
):
    tiles = reverse_map.pop(
        eid,
        set(),
    )

    for tile in tiles:
        entities = occupancy_map.get(tile)

        if entities is None:
            continue

        entities.discard(eid)

        if not entities:
            occupancy_map.pop(
                tile,
                None,
            )


def remove_entity_from_dynamic_occupancy(world, eid):
    discard_entity_tiles_from_occupancy(
        world.dynamic_center_occupancy,
        world.dynamic_center_tiles_by_entity,
        eid,
    )
    discard_entity_tiles_from_occupancy(
        world.dynamic_body_occupancy,
        world.dynamic_body_tiles_by_entity,
        eid,
    )
    discard_entity_tiles_from_occupancy(
        world.dynamic_reserved_centers,
        world.dynamic_reserved_center_tiles_by_entity,
        eid,
    )
    discard_entity_tiles_from_occupancy(
        world.dynamic_reserved_bodies,
        world.dynamic_reserved_body_tiles_by_entity,
        eid,
    )


def add_entity_to_dynamic_occupancy(world, eid):
    if eid not in world.space_occupier:
        return

    if eid not in world.transform:
        return

    if not space_occupier_blocks_movement(world, eid):
        return

    center_tile = get_entity_movement_center_tile(
        world,
        eid,
    )

    if center_tile is None:
        return

    add_entity_tile_to_occupancy(
        world.dynamic_center_occupancy,
        world.dynamic_center_tiles_by_entity,
        eid,
        center_tile,
    )

    for body_tile in get_entity_movement_body_tiles(
        world,
        eid,
    ):
        add_entity_tile_to_occupancy(
            world.dynamic_body_occupancy,
            world.dynamic_body_tiles_by_entity,
            eid,
            body_tile,
        )

    reserved_center_tile = get_entity_reserved_center_tile(
        world,
        eid,
    )

    if reserved_center_tile is not None:
        add_entity_tile_to_occupancy(
            world.dynamic_reserved_centers,
            world.dynamic_reserved_center_tiles_by_entity,
            eid,
            reserved_center_tile,
        )

    for reserved_body_tile in get_entity_reserved_body_tiles(
        world,
        eid,
    ):
        add_entity_tile_to_occupancy(
            world.dynamic_reserved_bodies,
            world.dynamic_reserved_body_tiles_by_entity,
            eid,
            reserved_body_tile,
        )


@profiled("occupancy.refresh_entity")
def refresh_entity_dynamic_occupancy(world, eid):
    record_counter_for_world(
        world,
        "occupancy.refresh_entity",
    )

    if world.dynamic_occupancy_dirty:
        record_counter_for_world(
            world,
            "occupancy.refresh_entity.full_rebuild_fallback",
        )
        rebuild_dynamic_occupancy(world)
        return

    remove_entity_from_dynamic_occupancy(
        world,
        eid,
    )
    add_entity_to_dynamic_occupancy(
        world,
        eid,
    )


@profiled("occupancy.rebuild")
def rebuild_dynamic_occupancy(world):
    reset_dynamic_occupancy_maps(world)

    entities = (
        set(world.space_occupier)
        & set(world.transform)
    )

    for eid in sorted(entities):
        add_entity_to_dynamic_occupancy(
            world,
            eid,
        )

    world.dynamic_occupancy_dirty = False


def ensure_dynamic_occupancy_current(world):
    if world.dynamic_occupancy_dirty:
        rebuild_dynamic_occupancy(world)


def get_entities_occupying_tile(world, tile):
    ensure_dynamic_occupancy_current(world)

    return tuple(
        sorted(
            world.dynamic_body_occupancy.get(
                tile,
                (),
            )
        )
    )


def get_relevant_dynamic_blockers(world, mover_entity, candidates):
    candidates = set(candidates)
    candidates.discard(mover_entity)

    if mover_entity is None:
        return tuple(sorted(candidates))

    return filter_contact_candidates(
        world,
        mover_entity,
        candidates,
    )


def get_movement_blockers_on_tile(world, tile, mover_entity=None):
    # Tile-level query means:
    # "Would a mover center be blocked if it entered this tile?"
    #
    # Therefore this checks occupied/reserved bodies.
    ensure_dynamic_occupancy_current(world)

    blockers = set(
        world.dynamic_body_occupancy.get(
            tile,
            (),
        )
    )

    blockers.update(
        world.dynamic_reserved_bodies.get(
            tile,
            (),
        )
    )

    return get_relevant_dynamic_blockers(
        world,
        mover_entity,
        blockers,
    )


def get_dynamic_movement_blockers_for_placement(
    world,
    mover_entity,
    proposed_center_tile,
    proposed_body_tiles,
    include_reservations=True,
):
    ensure_dynamic_occupancy_current(world)

    blockers = set()

    # Mover center may not overlap another entity's body.
    blockers.update(
        world.dynamic_body_occupancy.get(
            proposed_center_tile,
            (),
        )
    )

    if include_reservations:
        blockers.update(
            world.dynamic_reserved_bodies.get(
                proposed_center_tile,
                (),
            )
        )

    # Mover body may not overlap another entity's center.
    for body_tile in proposed_body_tiles:
        blockers.update(
            world.dynamic_center_occupancy.get(
                body_tile,
                (),
            )
        )

        if include_reservations:
            blockers.update(
                world.dynamic_reserved_centers.get(
                    body_tile,
                    (),
                )
            )

    # Wing-wing overlap is intentionally not checked.
    return get_relevant_dynamic_blockers(
        world,
        mover_entity,
        blockers,
    )


def get_dynamic_movement_blocker_sources_for_placement(
    world,
    mover_entity,
    proposed_center_tile,
    proposed_body_tiles,
    include_reservations=True,
):
    ensure_dynamic_occupancy_current(world)

    source_candidates = {
        "current_body_on_center": set(
            world.dynamic_body_occupancy.get(
                proposed_center_tile,
                (),
            )
        ),
        "current_center_on_body": set(),
    }

    if include_reservations:
        source_candidates["reserved_body_on_center"] = set(
            world.dynamic_reserved_bodies.get(
                proposed_center_tile,
                (),
            )
        )
        source_candidates["reserved_center_on_body"] = set()

    for body_tile in proposed_body_tiles:
        source_candidates["current_center_on_body"].update(
            world.dynamic_center_occupancy.get(
                body_tile,
                (),
            )
        )

        if include_reservations:
            source_candidates["reserved_center_on_body"].update(
                world.dynamic_reserved_centers.get(
                    body_tile,
                    (),
                )
            )

    source_blockers = {}

    for source_name, candidates in source_candidates.items():
        blockers = get_relevant_dynamic_blockers(
            world,
            mover_entity,
            candidates,
        )

        if blockers:
            source_blockers[source_name] = blockers

    return source_blockers


def is_tile_static_blocked(world, tile):
    if tile.y < 0 or tile.y >= len(world.tilemap):
        return True

    if tile.x < 0 or tile.x >= len(world.tilemap[tile.y]):
        return True

    return (tile.x, tile.y) in world.static_collision_tiles


def is_tile_dynamically_blocked_for_movement(
    world,
    tile,
    mover_entity=None,
):
    return bool(
        get_movement_blockers_on_tile(
            world,
            tile,
            mover_entity=mover_entity,
        )
    )


def is_tile_blocked_for_movement(
    world,
    tile,
    mover_entity=None,
    include_dynamic=True,
):
    if is_tile_static_blocked(world, tile):
        return True

    if include_dynamic and is_tile_dynamically_blocked_for_movement(
        world,
        tile,
        mover_entity=mover_entity,
    ):
        return True

    return False