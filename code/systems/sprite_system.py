import pygame
from utils.camera_utils import project_screen_point, scale_surface_by_camera_zoom, scale_vec_by_camera_zoom, scale_length_by_camera_zoom
from support import Vec2i
from constants import TILE_UNITS
from utils.selectable_utils import get_selectable_click_rect
from utils.occupancy_utils import get_entity_occupied_tiles
from utils.tile_vec_utils import interp_cpos, cpos_to_screen, iso_to_screen, tile_center


def sprite_system(world, surface, render_alpha, draw_debug=False):
    draw_list = []
    debug_draw_list = []
    scaled_sprite_cache = {}

    for entity in world.sprite:
        if entity not in world.transform:
            continue

        transform = world.transform[entity]

        pos = interp_cpos(
            transform.prev_cpos,
            transform.cpos,
            render_alpha,
        )

        sprite = world.sprite[entity]

        base_x, base_y = cpos_to_screen(
            pos,
            world.tile_size,
        )

        screen_x, screen_y = project_screen_point(
            world,
            base_x,
            base_y,
        )

        image = sprite["image"]

        cache_key = id(image)

        if cache_key not in scaled_sprite_cache:
            scaled_sprite_cache[cache_key] = scale_surface_by_camera_zoom(
                world,
                image,
            )

        scaled_image = scaled_sprite_cache[cache_key]

        sprite_offset = get_sprite_offset(
            image,
            sprite["anchor"],
        )

        scaled_offset = scale_vec_by_camera_zoom(
            world,
            sprite_offset,
        )

        draw_list.append((
            base_y + sprite.get("z", 0),
            scaled_image,
            (
                screen_x + scaled_offset.x,
                screen_y + scaled_offset.y,
            ),
        ))

        if draw_debug:
            debug_draw_list.append((
                entity,
                base_x,
                base_y,
            ))

    draw_list.sort(key=lambda x: x[0])

    for _, image, pos in draw_list:
        surface.blit(
            image,
            pos,
        )

    if draw_debug:
        draw_sprite_debug_overlays(
            world,
            surface,
            debug_draw_list,
        )


def tile_render_system(world, surface, render_alpha=0.0):
    scaled_tile_images = {}

    for y, row in enumerate(world.tilemap):
        for x, tile in enumerate(row):
            base_x, base_y = iso_to_screen(x, y, world.tile_size)
            screen_x, screen_y = project_screen_point(
                world,
                base_x,
                base_y,
            )

            if tile not in scaled_tile_images:
                scaled_tile_images[tile] = scale_surface_by_camera_zoom(
                    world,
                    world.tile_images[tile],
                )

            surface.blit(
                scaled_tile_images[tile],
                (screen_x, screen_y),
            )

            if (x, y) in world.static_collision_tiles:
                circle_base_x = base_x + world.tile_size // 2
                circle_base_y = base_y + world.tile_size // 4

                circle_x, circle_y = project_screen_point(
                    world,
                    circle_base_x,
                    circle_base_y,
                )

                pygame.draw.circle(
                    surface,
                    "red",
                    (circle_x, circle_y),
                    scale_length_by_camera_zoom(world, 3),
                )

    for highlight in world.debug_tile_highlights:
        tile = highlight["tile"]
        tile_center_cpos = tile_center(tile)

        base_x, base_y = cpos_to_screen(
            tile_center_cpos,
            world.tile_size,
        )

        screen_x, screen_y = project_screen_point(
            world,
            base_x,
            base_y,
        )

        pygame.draw.circle(
            surface,
            highlight.get("color", "yellow"),
            (screen_x, screen_y),
            scale_length_by_camera_zoom(world, 7),
            scale_length_by_camera_zoom(world, 2),
        )


def get_sprite_offset(image, anchor):
    if anchor == "center":
        return Vec2i(-image.get_width() // 2, -image.get_height() // 2)
    if anchor == "bottom_center":
        return Vec2i(-image.get_width() // 2, -image.get_height())

    raise ValueError(f"Unknown anchor: {anchor}")


def facing_to_screen_delta(facing: Vec2i, tile_size: int, arrow_length: int) -> tuple[int, int]:
    start_cpos = Vec2i(0, 0)
    end_cpos = Vec2i(
        facing.x * TILE_UNITS,
        facing.y * TILE_UNITS,
    )

    start_x, start_y = cpos_to_screen(start_cpos, tile_size)
    end_x, end_y = cpos_to_screen(end_cpos, tile_size)

    dx = end_x - start_x
    dy = end_y - start_y

    max_abs = max(abs(dx), abs(dy))

    if max_abs == 0:
        return 0, 0

    return (
        dx * arrow_length // max_abs,
        dy * arrow_length // max_abs,
    )


def draw_sprite_debug_overlays(world, surface, debug_draw_list):
    debug_radius = scale_length_by_camera_zoom(world, 4)

    for entity, base_x, base_y in debug_draw_list:

        draw_debug_path_target_overlay(world, surface, entity)

        actor_x, actor_y = project_screen_point(
            world,
            base_x,
            base_y,
        )

        # Movement footprint tiles.
        draw_debug_entity_occupied_tiles(
            world,
            surface,
            entity,
        )

        draw_debug_selectable_click_box(
            world,
            surface,
            entity,
        )

        # Current cpos / logical center.
        pygame.draw.circle(
            surface,
            "red",
            (actor_x, actor_y),
            debug_radius,
        )

        if entity in world.facing:
            facing = world.facing[entity]

            arrow_dx, arrow_dy = facing_to_screen_delta(
                facing,
                world.tile_size,
                arrow_length=32,
            )

            arrow_end_x, arrow_end_y = project_screen_point(
                world,
                base_x + arrow_dx,
                base_y + arrow_dy,
            )

            pygame.draw.line(
                surface,
                "black",
                (actor_x, actor_y),
                (arrow_end_x, arrow_end_y),
                scale_length_by_camera_zoom(world, 2),
            )


def draw_debug_selectable_click_box(world, surface, entity):
    if entity not in world.selectable:
        return

    rect = get_selectable_click_rect(world, entity)
    if rect is None:
        return

    color = "yellow"
    if world.hovered_selectable == entity:
        color = "orange"

    pygame.draw.rect(
        surface,
        color,
        rect,
        scale_length_by_camera_zoom(world, 1),
    )


def draw_debug_entity_occupied_tiles(world, surface, entity):
    occupied_tiles = get_entity_occupied_tiles(
        world,
        entity,
    )

    radius = scale_length_by_camera_zoom(world, 5)
    width = scale_length_by_camera_zoom(world, 2)

    for tile in occupied_tiles:
        tile_center_cpos = tile_center(tile)

        base_x, base_y = cpos_to_screen(
            tile_center_cpos,
            world.tile_size,
        )

        screen_x, screen_y = project_screen_point(
            world,
            base_x,
            base_y,
        )

        pygame.draw.circle(
            surface,
            "black",
            (screen_x, screen_y),
            radius,
            width,
        )


def cpos_to_projected_screen(world, cpos):
    base_x, base_y = cpos_to_screen(cpos, world.tile_size)

    return project_screen_point(
        world,
        base_x,
        base_y,
    )


def draw_dashed_line(
    surface,
    color,
    start_pos,
    end_pos,
    dash_length=8,
    gap_length=5,
    width=1,
):
    start_x, start_y = start_pos
    end_x, end_y = end_pos

    dx = end_x - start_x
    dy = end_y - start_y

    length_sq = dx * dx + dy * dy

    if length_sq == 0:
        return

    length = length_sq ** 0.5

    step_length = dash_length + gap_length
    dash_count = max(1, int(length // step_length))

    for index in range(dash_count + 1):
        dash_start_distance = index * step_length
        dash_end_distance = min(
            dash_start_distance + dash_length,
            length,
        )

        if dash_start_distance >= length:
            break

        start_t = dash_start_distance / length
        end_t = dash_end_distance / length

        dash_start = (
            round(start_x + dx * start_t),
            round(start_y + dy * start_t),
        )

        dash_end = (
            round(start_x + dx * end_t),
            round(start_y + dy * end_t),
        )

        pygame.draw.line(
            surface,
            color,
            dash_start,
            dash_end,
            width,
        )


def draw_debug_path_target_overlay(world, surface, entity):
    target = world.move_target.get(entity)

    if target is None:
        return

    if target.get("type") != "target_tile":
        return

    target_tile = target["target_tile"]
    target_center_cpos = tile_center(target_tile)
    target_screen = cpos_to_projected_screen(
        world,
        target_center_cpos,
    )

    target_radius = scale_length_by_camera_zoom(world, 4)

    pygame.draw.circle(
        surface,
        "green",
        target_screen,
        target_radius,
    )

    motion_state = world.motion_state.get(entity)

    if motion_state is None:
        return

    controller = motion_state.get("controller")

    if controller is None:
        return

    if not (
        hasattr(controller, "nodes")
        and hasattr(controller, "current_index")
    ):
        return

    transform = world.transform.get(entity)

    if transform is None:
        return

    remaining_nodes = controller.nodes[controller.current_index:]

    if not remaining_nodes:
        return

    points = [
        transform.cpos,
        *remaining_nodes,
    ]

    line_width = scale_length_by_camera_zoom(world, 1)
    dash_length = scale_length_by_camera_zoom(world, 8)
    gap_length = scale_length_by_camera_zoom(world, 5)

    for start_cpos, end_cpos in zip(points, points[1:]):
        start_screen = cpos_to_projected_screen(
            world,
            start_cpos,
        )

        end_screen = cpos_to_projected_screen(
            world,
            end_cpos,
        )

        draw_dashed_line(
            surface,
            "green",
            start_screen,
            end_screen,
            dash_length=dash_length,
            gap_length=gap_length,
            width=line_width,
        )

    last_node = remaining_nodes[-1]

    if last_node != target_center_cpos:
        draw_dashed_line(
            surface,
            "green",
            cpos_to_projected_screen(world, last_node),
            target_screen,
            dash_length=dash_length,
            gap_length=gap_length,
            width=line_width,
        )