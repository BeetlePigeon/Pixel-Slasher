import pygame
from support import Vec2i
from utils.tile_vec_utils import cpos_to_screen
from utils.camera_utils import (
    project_screen_point,
    scale_length_by_camera_zoom,
    scale_vec_by_camera_zoom,
)


def resolve_hovered_selectable(world, mouse_pos):
    hits = []

    for entity in sorted(world.selectable):
        if not selectable_is_enabled(world, entity):
            continue

        rect = get_selectable_click_rect(world, entity)
        if rect is None:
            continue

        if not rect.collidepoint(mouse_pos):
            continue

        selectable = world.selectable[entity]
        priority = selectable.get("screen_priority", 0)
        base_y = get_entity_base_screen_y(world, entity)

        hits.append(
            (
                -priority,
                -base_y,
                entity,
            )
        )

    if not hits:
        return None

    hits.sort()
    return hits[0][2]


def selectable_is_enabled(world, entity):
    if entity not in world.transform:
        return False

    selectable = world.selectable.get(entity)
    if selectable is None:
        return False

    return selectable.get("enabled", True)


def get_selectable_click_rect(world, entity):
    selectable = world.selectable.get(entity)
    if selectable is None:
        return None

    if entity not in world.transform:
        return None

    click_box = selectable.get("click_box")
    click_box_type = click_box.get("type")

    if click_box_type != "rect":
        raise NotImplementedError(
            f"Selectable click box type not implemented: {click_box_type!r}"
        )

    return build_selectable_rect(world, entity, click_box)


def build_selectable_rect(world, entity, click_box):
    anchor = click_box.get("anchor")
    size = click_box.get("size")
    offset = click_box.get("offset")

    width = scale_length_by_camera_zoom(world, size[0])
    height = scale_length_by_camera_zoom(world, size[1])

    offset_vec = scale_vec_by_camera_zoom(
        world,
        Vec2i(offset[0], offset[1]),
    )

    base_x, base_y = get_entity_base_screen_pos(world, entity)
    anchor_pos = (
        base_x + offset_vec.x,
        base_y + offset_vec.y,
    )

    return rect_from_anchor(
        anchor_pos,
        width,
        height,
        anchor,
    )


def rect_from_anchor(anchor_pos, width, height, anchor):
    x, y = anchor_pos

    if anchor == "bottom_center":
        return pygame.Rect(
            x - width // 2,
            y - height,
            width,
            height,
        )

    if anchor == "center":
        return pygame.Rect(
            x - width // 2,
            y - height // 2,
            width,
            height,
        )

    if anchor == "top_left":
        return pygame.Rect(
            x,
            y,
            width,
            height,
        )

    raise ValueError(f"Unknown selectable click box anchor: {anchor!r}")


def get_entity_base_screen_pos(world, entity):
    transform = world.transform[entity]
    base_x, base_y = cpos_to_screen(
        transform.cpos,
        world.tile_size,
    )
    return project_screen_point(
        world,
        base_x,
        base_y,
    )


def get_entity_base_screen_y(world, entity):
    transform = world.transform[entity]
    _, base_y = cpos_to_screen(
        transform.cpos,
        world.tile_size,
    )
    return base_y