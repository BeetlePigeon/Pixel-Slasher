from support import screen_to_cpos, tile_from_cpos


def internal_screen_to_world_cpos(world, screen_pos):
    projection = world.camera_projection

    if projection is None:
        offset_x, offset_y = world.camera_base_offset

        world_screen_pos = (
            screen_pos[0] - offset_x,
            screen_pos[1] - offset_y,
        )

        return screen_to_cpos(
            world_screen_pos,
            world.tile_size,
        )

    zoom_num = projection["zoom_num"]
    zoom_den = projection["zoom_den"]

    center_x, center_y = projection["surface_center"]
    camera_screen_x, camera_screen_y = projection["camera_screen"]
    screen_offset = projection["screen_offset"]

    # Do not subtract camera shake here. Mouse targeting should not jitter
    # while the camera is shaking.
    base_screen_x = (
        camera_screen_x
        + (screen_pos[0] - center_x - screen_offset.x) * zoom_den // zoom_num
    )

    base_screen_y = (
        camera_screen_y
        + (screen_pos[1] - center_y - screen_offset.y) * zoom_den // zoom_num
    )

    return screen_to_cpos(
        (base_screen_x, base_screen_y),
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