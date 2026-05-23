import pygame
from support import (
    Vec2i,
    interp_cpos,
    lerp_cpos,
    cpos_to_screen
)


def sample_camera_shake(camera):
    ticks_left = camera["shake_ticks"]

    if ticks_left <= 0:
        return Vec2i(0, 0)

    duration = max(1, camera["shake_duration"])
    strength = camera["shake_strength"]

    # Fade out over time.
    current_strength = strength * ticks_left // duration

    # Deterministic small pattern. No randomness.
    pattern = [
        Vec2i(1, 0),
        Vec2i(-1, 0),
        Vec2i(0, 1),
        Vec2i(0, -1),
        Vec2i(1, 1),
        Vec2i(-1, -1),
        Vec2i(1, -1),
        Vec2i(-1, 1),
    ]

    index = ticks_left % len(pattern)
    direction = pattern[index]

    return Vec2i(
        direction.x * current_strength,
        direction.y * current_strength,
    )


def get_camera_target_cpos(world):
    camera = world.world_camera.camera
    mode = camera["mode"]

    if mode == "follow":
        target = camera["target"]

        if target in world.transform:
            return world.transform[target].cpos

        return None

    if mode == "fixed":
        return camera["fixed_cpos"]

    return None


def set_camera_follow(world, target_entity, transition_mode="snap", transition_duration=None):
    camera = world.world_camera.camera

    camera["mode"] = "follow"
    camera["target"] = target_entity
    camera["transition_mode"] = transition_mode

    if transition_mode == "smooth":
        if transition_duration is None:
            transition_duration = camera.get("default_transition_duration", 24)

        camera["transition_ticks"] = 0
        camera["transition_duration"] = transition_duration
        camera["transition_start_cpos"] = camera["current_cpos"]


def set_camera_fixed(world, fixed_cpos, transition_mode="snap", transition_duration=20):
    camera = world.world_camera.camera

    camera["mode"] = "fixed"
    camera["fixed_cpos"] = fixed_cpos
    camera["transition_mode"] = transition_mode

    if transition_mode == "smooth":
        camera["transition_ticks"] = 0
        camera["transition_duration"] = transition_duration
        camera["transition_start_cpos"] = camera["current_cpos"]


def start_camera_shake(world, duration_ticks: int, strength: int):
    camera = world.world_camera.camera

    max_strength = camera.get("shake_max_strength")

    camera["shake_strength"] = min(
        max_strength,
        camera.get("shake_strength") + strength,
    )

    camera["shake_ticks"] = max(
        camera.get("shake_ticks"),
        duration_ticks,
    )

    camera["shake_duration"] = max(
        camera.get("shake_duration"),
        duration_ticks,
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


def get_camera_zoom(camera):
    return (
        camera.get("zoom_current_fp", ZOOM_FP_SCALE),
        ZOOM_FP_SCALE,
    )


def scale_length_by_camera_zoom(world, value):
    zoom_num, zoom_den = get_camera_zoom(world.world_camera.camera)

    return max(1, value * zoom_num // zoom_den)


def scale_vec_by_camera_zoom(world, vec):
    zoom_num, zoom_den = get_camera_zoom(world.world_camera.camera)

    return Vec2i(
        vec.x * zoom_num // zoom_den,
        vec.y * zoom_num // zoom_den,
    )


def scale_surface_by_camera_zoom(world, surface):
    zoom_num, zoom_den = get_camera_zoom(world.world_camera.camera)

    if zoom_num == zoom_den:
        return surface

    width = max(1, surface.get_width() * zoom_num // zoom_den)
    height = max(1, surface.get_height() * zoom_num // zoom_den)

    return pygame.transform.scale(
        surface,
        (width, height),
    )


ZOOM_FP_SCALE = 1024


def zoom_fraction_to_fp(zoom_num, zoom_den):
    zoom_den = max(1, zoom_den)

    return max(
        1,
        zoom_num * ZOOM_FP_SCALE // zoom_den,
    )


def step_int_toward(current, target, step):
    if current < target:
        return min(target, current + step)

    if current > target:
        return max(target, current - step)

    return current


def update_camera_zoom(camera):
    target_fp = camera.get(
        "zoom_target_fp",
        zoom_fraction_to_fp(
            camera.get("zoom_num", 1),
            camera.get("zoom_den", 1),
        ),
    )

    if not camera.get("zoom_smooth", True):
        camera["zoom_current_fp"] = target_fp
        return

    current_fp = camera.get("zoom_current_fp", target_fp)
    step_fp = camera.get("zoom_step_fp", 64)

    camera["zoom_current_fp"] = step_int_toward(
        current_fp,
        target_fp,
        step_fp,
    )


def project_screen_point(world, base_screen_x, base_screen_y, include_shake=True):
    projection = world.world_camera.camera_projection

    if projection is None:
        offset_x, offset_y = world.world_camera.camera_offset

        return (
            base_screen_x + offset_x,
            base_screen_y + offset_y,
        )

    zoom_num = projection["zoom_num"]
    zoom_den = projection["zoom_den"]

    center_x, center_y = projection["surface_center"]
    camera_screen_x, camera_screen_y = projection["camera_screen"]
    screen_offset = projection["screen_offset"]

    shake_offset = Vec2i(0, 0)

    if include_shake:
        shake_offset = world.world_camera.camera_shake_offset

    return (
        center_x
        + (base_screen_x - camera_screen_x) * zoom_num // zoom_den
        + screen_offset.x
        + shake_offset.x,

        center_y
        + (base_screen_y - camera_screen_y) * zoom_num // zoom_den
        + screen_offset.y
        + shake_offset.y,
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