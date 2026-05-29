from constants import TILE_UNITS
from data.tables_movement_footprints import get_movement_footprint_offsets
from support import Vec2i
from utils.perf_profiler import profiled
from utils.contact_filtering_utils import filter_contact_candidates
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
        return "single_tile"

    return space_occupier.get("movement_footprint")


def get_entity_movement_footprint_offsets(world, eid):
    footprint_name = get_entity_movement_footprint_name(world, eid)

    return get_movement_footprint_offsets(footprint_name)


def get_movement_footprint_tiles_for_origin_tile(world, eid, origin_tile):
    return tuple(
        origin_tile + offset
        for offset in get_entity_movement_footprint_offsets(world, eid)
    )


def get_entity_occupied_tiles(world, eid):
    if eid not in world.transform:
        return ()

    if not space_occupier_blocks_movement(world, eid):
        return ()

    transform = world.transform[eid]
    origin_tile = tile_from_cpos(transform.cpos)

    return get_movement_footprint_tiles_for_origin_tile(
        world,
        eid,
        origin_tile,
    )


def get_first_tile_entered_from_cpos(start_cpos, target_cpos):
    current_tile = tile_from_cpos(start_cpos)

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


def get_entity_reserved_tiles(world, eid):
    if not space_occupier_blocks_movement(world, eid):
        return ()

    transform = world.transform.get(eid)

    if transform is None:
        return ()

    motion_state = world.motion_state.get(eid)

    if motion_state is None:
        return ()

    controller = motion_state.get("controller")

    if controller is None:
        return ()

    current_tile = tile_from_cpos(transform.cpos)

    next_tile = get_controller_immediate_next_tile(
        transform.cpos,
        controller,
    )

    if next_tile is None:
        return ()

    if next_tile == current_tile:
        return ()

    if abs(next_tile.x - current_tile.x) > 1:
        return ()

    if abs(next_tile.y - current_tile.y) > 1:
        return ()

    return get_movement_footprint_tiles_for_origin_tile(
        world,
        eid,
        next_tile,
    )


@profiled("occupancy.rebuild")
def rebuild_dynamic_occupancy(world):
    dynamic_occupancy = {}
    dynamic_blocking_occupancy = {}
    dynamic_reservations = {}

    entities = (
        set(world.space_occupier)
        & set(world.transform)
    )

    for eid in sorted(entities):
        if not space_occupier_blocks_movement(world, eid):
            continue

        occupied_tiles = get_entity_occupied_tiles(world, eid)

        for tile in occupied_tiles:
            dynamic_occupancy.setdefault(
                tile,
                set(),
            ).add(eid)

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