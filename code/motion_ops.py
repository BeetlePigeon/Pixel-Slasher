from support import tile_center


def teleport_entity_to_tile(world, entity, target_tile):
    transform = world.transform[entity]
    target_cpos = tile_center(target_tile)

    motion_state = world.motion_state.get(entity)

    if motion_state is not None:
        motion_state["controller"] = None
        motion_state["influence_mode"] = "normal"
        motion_state["last_delta"] = target_cpos - transform.cpos

    transform.tile = target_tile
    transform.cpos = target_cpos

    # Prevent render interpolation from drawing teleport as a slide.
    transform.prev_cpos = target_cpos

    return True