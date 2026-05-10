from support import screen_to_cpos, tile_from_cpos


def internal_screen_to_world_cpos(world, screen_pos):
    offset_x, offset_y = world.camera_base_offset

    world_screen_pos = (
        screen_pos[0] - offset_x,
        screen_pos[1] - offset_y,
    )

    return screen_to_cpos(
        world_screen_pos,
        world.tile_size,
    )

def internal_screen_to_world_tile(world, screen_pos):
    return tile_from_cpos(
        internal_screen_to_world_cpos(world, screen_pos)
    )

def request_camera_snap_if_following(world, entity):
    camera = world.camera

    if camera.get("mode") == "follow" and camera.get("target") == entity:
        camera["snap_next_update"] = True

def snap_camera_to_entity_now(world, entity):
    camera = world.camera

    if camera.get("mode") != "follow":
        return

    if camera.get("target") != entity:
        return

    transform = world.transform.get(entity)

    if transform is None:
        return

    target_cpos = transform.cpos

    camera["current_cpos"] = target_cpos
    camera["prev_cpos"] = target_cpos
    camera["transition_mode"] = "snap"
    camera["transition_ticks"] = 0
    camera["transition_duration"] = 0
    camera["transition_start_cpos"] = None
    camera["snap_next_update"] = False