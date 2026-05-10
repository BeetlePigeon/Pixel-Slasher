from support import tile_center, Vec2i, sign


def teleport_entity_to_tile(world, entity, target_tile):
    transform = world.transform[entity]

    old_tile = transform.tile
    target_cpos = tile_center(target_tile)

    # Face in the direction of the actual teleport displacement.
    facing_direction = Vec2i(
        sign(target_tile.x - old_tile.x),
        sign(target_tile.y - old_tile.y),
    )

    if entity in world.facing:
        if facing_direction.x != 0 or facing_direction.y != 0:
            world.facing[entity] = facing_direction

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