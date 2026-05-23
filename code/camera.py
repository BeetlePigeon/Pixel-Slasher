from support import Vec2i, screen_to_cpos, tile_from_cpos


class Camera:
    def __init__(self, world):
        self.world = world

        self.camera_base_offset = (0, 0)
        self.camera_offset = (0, 0)
        self.camera_projection = None
        self.camera_shake_offset = Vec2i(0, 0)
        self.camera = {
            "mode": "follow",
            "target": None,
            "fixed_cpos": None,
            "screen_offset": Vec2i(0, 0),
            "current_cpos": None,
            "prev_cpos": None,
            "transition_mode": "snap",
            "transition_ticks": 0,
            "transition_duration": 0,
            "default_transition_duration": 24,
            "transition_start_cpos": None,
            "snap_next_update": False,
            "shake_ticks": 0,
            "shake_duration": 0,
            "shake_strength": 0,
            "shake_max_strength": 20,
            "zoom_levels": [
                (1, 2),
                (3, 4),
                (1, 1),
                (5, 4),
                (3, 2),
                (2, 1),
            ],
            "zoom_index": 2,

            # Target zoom selected by gameplay/settings/UI.
            "zoom_num": 1,
            "zoom_den": 1,
            "zoom_target_num": 1,
            "zoom_target_den": 1,

            # Current visual zoom, fixed-point.
            # 1024 = 1.0x
            "zoom_current_fp": 1024,
            "zoom_target_fp": 1024,

            # Official camera behavior.
            "zoom_smooth": False,
            "zoom_step_fp": 64,
        }





def internal_screen_to_world_cpos(world, screen_pos):
    projection = world.world_camera.camera_projection

    if projection is None:
        offset_x, offset_y = world.world_camera.camera_base_offset

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
    camera = world.world_camera.camera

    if camera.get("mode") == "follow" and camera.get("target") == entity:
        camera["snap_next_update"] = True


def snap_camera_to_entity_now(world, entity):
    camera = world.world_camera.camera

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