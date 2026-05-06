import pygame
import math
from settings import TILE_UNITS
from support import (
    Vec2i,
    Transform,
    tile_center,
    tile_from_cpos,
    iso_to_screen,
    cpos_to_screen,
    GridMoveController,
)

def test_projectile_spawn_system(world, intents):
    for entity, entity_intents in intents.items():
        for intent in entity_intents:
            if intent["type"] != "spawn_test_projectile":
                continue

            if entity not in world.transform:
                continue

            player_cpos = world.transform[entity].cpos

            direction = Vec2i(1, -1)

            world.spawn_test_projectile(player_cpos, direction)

def is_tile_blocked(world, tile: Vec2i) -> bool:
    # Out of bounds is blocked.
    if tile.y < 0 or tile.y >= len(world.tilemap):
        return True

    if tile.x < 0 or tile.x >= len(world.tilemap[tile.y]):
        return True

    # Static collision from tilemap.
    return (tile.x, tile.y) in world.static_collision_tiles

def intent_system(world, intents):
    world.move_intent.clear()

    for entity, entity_intents in intents.items():
        for intent in entity_intents:
            if intent["type"] != "move":
                continue

            dx, dy = intent["direction"]

            if dx == 0 and dy == 0:
                continue

            world.move_intent[entity] = Vec2i(dx, dy)
            break

def movement_arbiter_system(world):
    entities = (
        set(world.move_intent)
        & set(world.transform)
        & set(world.motion_state)
        & set(world.locomotion)
    )

    for entity in entities:
        direction = world.move_intent[entity]
        transform = world.transform[entity]
        motion_state = world.motion_state[entity]
        locomotion = world.locomotion[entity]

        if not locomotion["can_move_8way"]:
            if direction.x != 0 and direction.y != 0:
                continue

        if motion_state["controller"] is not None:
            continue

        current_tile = transform.tile
        target_tile = Vec2i(
            current_tile.x + direction.x,
            current_tile.y + direction.y,
        )

        if is_tile_blocked(world, target_tile):
            continue

        start = tile_center(current_tile)
        end = tile_center(target_tile)
        motion_state["controller"] = GridMoveController(
            start=start,
            end=end,
            progress=0,
            duration=locomotion["step_duration"],
        )

def movement_system(world):
    entities = (
        set(world.transform)
        & set(world.motion_state)
    )

    for entity in entities:
        motion_state = world.motion_state[entity]
        controller = motion_state["controller"]

        if controller is None:
            continue

        transform = world.transform[entity]

        delta = controller.sample_delta()
        next_cpos = transform.cpos + delta
        next_tile = tile_from_cpos(next_cpos)

        if entity in world.projectile and is_tile_blocked(world, next_tile):
            world.entities.destroy(entity)
            continue

        transform.cpos = next_cpos
        motion_state["last_delta"] = delta

        controller.advance()

        if controller.finished():
            if hasattr(controller, "end"):
                transform.cpos = controller.end

            transform.tile = tile_from_cpos(transform.cpos)
            motion_state["controller"] = None

def skill_system(world, intents):
    for entity, entity_intents in intents.items():

        for intent in entity_intents:

            if intent["type"] == "skill_pressed":
                slot = intent["slot"]
                skill = world.skills.get((entity, slot))

                if skill:
                    print(f"{skill=} was Pressed")

            elif intent["type"] == "skill_released":
                slot = intent["slot"]
                skill = world.skills.get((entity, slot))

                if skill:
                    print(f"{skill=} was just Released")

def render_tiles(world, surface):
    offset_x, offset_y = world.camera_offset

    for y, row in enumerate(world.tilemap):
        for x, tile in enumerate(row):
            screen_x, screen_y = iso_to_screen(x, y, world.tile_size)

            surface.blit(
                world.tile_images[tile],
                (screen_x + offset_x, screen_y + offset_y)
            )
            if (x, y) in world.static_collision_tiles:
                pygame.draw.circle(
                    surface,
                    "red",
                    (
                        screen_x + offset_x + world.tile_size // 2,
                        screen_y + offset_y + world.tile_size // 4,
                    ),
                    3,
                )

def sprite_system(world, surface):
    draw_list = []
    offset_x, offset_y = world.camera_offset

    for entity in world.sprite:
        if entity not in world.transform:
            continue

        pos = world.transform[entity].cpos
        sprite = world.sprite[entity]

        screen_x, screen_y = cpos_to_screen(pos, world.tile_size)
        draw_list.append((
            screen_y + sprite.get("z", 0),
            sprite["image"],
            (
                screen_x + offset_x + sprite["offset"][0],
                screen_y + offset_y + sprite["offset"][1]
            )
        ))

    draw_list.sort(key=lambda x: x[0])

    for _, image, pos in draw_list:
        surface.blit(image, pos)