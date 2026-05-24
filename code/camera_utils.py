import pygame
from support import Vec2i
from constants import ZOOM_FP_SCALE
from tile_vec_utils import screen_to_cpos, tile_from_cpos


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