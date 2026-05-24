from support import Vec2i
from tile_vec_utils import tile_center, tile_from_cpos, sign



def teleport_entity_to_tile(world, entity, target_tile):
    transform = world.transform[entity]

    old_tile = tile_from_cpos(transform.cpos)
    target_cpos = tile_center(target_tile)

    # Face in the direction of the actual teleport displacement from
    # the actor's current cpos-derived tile, not stale committed tile.
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
        motion_state.pop("controller_source", None)

        # Prevent movement_arbiter_system from starting a new voluntary
        # movement later in this same tick using stale move_intent.
        motion_state["suppress_move_start_tick"] = world.tick

    # Clear pending voluntary movement requests.
    world.move_intent.pop(entity, None)

    if hasattr(world, "buffered_move_intent"):
        world.buffered_move_intent.pop(entity, None)

    if hasattr(world, "move_target"):
        world.move_target.pop(entity, None)

    transform.tile = target_tile
    transform.cpos = target_cpos

    # Prevent render interpolation from drawing teleport as a slide.
    transform.prev_cpos = target_cpos

    return True