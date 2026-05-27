from utils.tile_vec_utils import tile_from_cpos
from utils.contact_filtering_utils import filter_contact_candidates


def mark_dynamic_occupancy_dirty(world):
    world.dynamic_occupancy_dirty = True


def space_occupier_enabled(world, eid):
    space_occupier = world.space_occupier.get(eid)

    if space_occupier is None:
        return False

    return space_occupier.get("enabled", True)


def space_occupier_blocks_movement(world, eid):
    space_occupier = world.space_occupier.get(eid)

    if space_occupier is None:
        return False

    if not space_occupier.get("enabled", True):
        return False

    return space_occupier.get("blocks_movement", False)


def get_entity_occupied_tiles(world, eid):
    if eid not in world.transform:
        return ()

    space_occupier = world.space_occupier.get(eid)

    if space_occupier is None:
        return ()

    if not space_occupier.get("enabled", True):
        return ()

    shape = space_occupier.get("shape", "single_tile")

    if shape != "single_tile":
        raise ValueError(
            f"Unsupported space occupier shape for entity {eid}: "
            f"{shape!r}"
        )

    transform = world.transform[eid]

    # For v1, a space occupier claims its committed logical tile.
    # Movement destination is handled separately through reservations.
    return (
        transform.tile,
    )


def get_entity_reserved_tiles(world, eid):
    if eid not in world.space_occupier:
        return ()

    if not space_occupier_blocks_movement(world, eid):
        return ()

    motion_state = world.motion_state.get(eid)

    if motion_state is None:
        return ()

    controller = motion_state.get("controller")

    if controller is None:
        return ()

    # GridMoveController and SettleToGridController expose .end.
    if hasattr(controller, "end"):
        return (
            tile_from_cpos(controller.end),
        )

    # PathFollowController exposes nodes/current_index.
    if hasattr(controller, "nodes") and hasattr(controller, "current_index"):
        if controller.current_index < len(controller.nodes):
            return (
                tile_from_cpos(controller.nodes[controller.current_index]),
            )

    return ()


def rebuild_dynamic_occupancy(world):
    dynamic_occupancy = {}
    dynamic_blocking_occupancy = {}
    dynamic_reservations = {}

    entities = (
            set(world.space_occupier)
            & set(world.transform)
    )

    for eid in sorted(entities):
        if not space_occupier_enabled(world, eid):
            continue

        occupied_tiles = get_entity_occupied_tiles(world, eid)

        for tile in occupied_tiles:
            dynamic_occupancy.setdefault(
                tile,
                set(),
            ).add(eid)

            if space_occupier_blocks_movement(world, eid):
                dynamic_blocking_occupancy.setdefault(
                    tile,
                    set(),
                ).add(eid)

        reserved_tiles = get_entity_reserved_tiles(world, eid)

        for tile in reserved_tiles:
            dynamic_reservations.setdefault(
                tile,
                set(),
            ).add(eid)

    world.dynamic_occupancy = dynamic_occupancy
    world.dynamic_blocking_occupancy = dynamic_blocking_occupancy
    world.dynamic_reservations = dynamic_reservations
    world.dynamic_occupancy_dirty = False


def ensure_dynamic_occupancy_current(world):
    if world.dynamic_occupancy_dirty:
        rebuild_dynamic_occupancy(world)


def get_entities_occupying_tile(world, tile):
    ensure_dynamic_occupancy_current(world)

    return tuple(
        sorted(
            world.dynamic_occupancy.get(
                tile,
                (),
            )
        )
    )


def get_movement_blockers_on_tile(world, tile, mover_entity=None):
    ensure_dynamic_occupancy_current(world)

    blockers = set(
        world.dynamic_blocking_occupancy.get(
            tile,
            (),
        )
    )

    blockers.update(
        world.dynamic_reservations.get(
            tile,
            (),
        )
    )

    if mover_entity is None:
        return tuple(sorted(blockers))

    return filter_contact_candidates(
        world,
        mover_entity,
        blockers,
    )


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