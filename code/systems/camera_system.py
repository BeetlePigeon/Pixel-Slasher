from support import Vec2i
from utils.camera_utils import (
    get_camera_target_cpos,
    get_camera_zoom,
    sample_camera_shake,
    update_camera_zoom,
)
from utils.tile_vec_utils import (
    interp_cpos,
    lerp_cpos,
    cpos_to_screen
)


def camera_system(world, surface, render_alpha):
    camera = world.world_camera.camera

    update_camera_zoom(camera)

    current_cpos = camera.get("current_cpos")
    prev_cpos = camera.get("prev_cpos", current_cpos)

    if current_cpos is None:
        return

    if prev_cpos is None:
        prev_cpos = current_cpos

    visual_camera_cpos = interp_cpos(
        prev_cpos,
        current_cpos,
        render_alpha,
    )

    camera_screen_x, camera_screen_y = cpos_to_screen(
        visual_camera_cpos,
        world.tile_size,
    )

    surface_center_x = surface.get_width() // 2
    surface_center_y = surface.get_height() // 2

    screen_offset = camera.get("screen_offset", Vec2i(0, 0))
    shake_offset = sample_camera_shake(camera)

    zoom_num, zoom_den = get_camera_zoom(camera)

    world.world_camera.camera_projection = {
        "camera_screen": (camera_screen_x, camera_screen_y),
        "surface_center": (surface_center_x, surface_center_y),
        "screen_offset": screen_offset,
        "zoom_num": zoom_num,
        "zoom_den": zoom_den,
    }

    world.world_camera.camera_shake_offset = shake_offset

    # Keep these for older code/fallbacks. Mouse-to-world should use
    # camera_projection after this patch.
    base_offset = (
        surface_center_x - camera_screen_x + screen_offset.x,
        surface_center_y - camera_screen_y + screen_offset.y,
    )

    world.world_camera.camera_base_offset = base_offset
    world.world_camera.camera_offset = (
        base_offset[0] + shake_offset.x,
        base_offset[1] + shake_offset.y,
    )


def camera_update_system(world):
    camera = world.world_camera.camera
    target_cpos = get_camera_target_cpos(world)

    if target_cpos is None:
        return

    if camera["current_cpos"] is not None:
        camera["prev_cpos"] = camera["current_cpos"]

    if camera["current_cpos"] is None:
        camera["current_cpos"] = target_cpos
        camera["prev_cpos"] = target_cpos
        return

    transition_mode = camera.get("transition_mode", "snap")

    if transition_mode == "snap":
        camera["current_cpos"] = target_cpos
        return

    if transition_mode == "smooth":
        start_cpos = camera.get("transition_start_cpos")

        if start_cpos is None:
            start_cpos = camera["current_cpos"]
            camera["transition_start_cpos"] = start_cpos

        duration = max(1, camera.get("transition_duration", 20))
        ticks = camera.get("transition_ticks", 0) + 1

        if ticks >= duration:
            camera["current_cpos"] = target_cpos
            camera["transition_mode"] = "snap"
            camera["transition_ticks"] = 0
            camera["transition_duration"] = 0
            camera["transition_start_cpos"] = None
            return

        camera["transition_ticks"] = ticks
        camera["current_cpos"] = lerp_cpos(
            start_cpos,
            target_cpos,
            ticks,
            duration,
        )


def camera_shake_system(world):
    camera = world.world_camera.camera

    if camera["shake_ticks"] <= 0:
        camera["shake_ticks"] = 0
        camera["shake_duration"] = 0
        camera["shake_strength"] = 0
        return

    camera["shake_ticks"] -= 1

    if camera["shake_ticks"] <= 0:
        camera["shake_ticks"] = 0
        camera["shake_duration"] = 0
        camera["shake_strength"] = 0