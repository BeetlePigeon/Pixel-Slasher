import pygame
import math
from settings import TILE_UNITS
from skills import SKILL_HANDLERS
from support import (
    Vec2i,
    Transform,
    sign,
    tile_center,
    tile_from_cpos,
    iso_to_screen,
    cpos_to_screen,
    GridMoveController,
    scale_dir,
    scale_vec,
    clamp_vec_axis
)

def is_tile_blocked(world, tile: Vec2i) -> bool:
    # Out of bounds is blocked.
    if tile.y < 0 or tile.y >= len(world.tilemap):
        return True

    if tile.x < 0 or tile.x >= len(world.tilemap[tile.y]):
        return True

    # Static collision from tilemap.
    return (tile.x, tile.y) in world.static_collision_tiles

def handle_static_tile_collision(world, entity, next_tile):
    policy = world.movement_collision.get(entity)

    if policy is None:
        return "allow"

    behavior = policy.get("static_tiles", "allow")

    if not is_tile_blocked(world, next_tile):
        return "allow"

    return behavior

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

            if entity in world.facing:
                world.facing[entity] = Vec2i(dx, dy)

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

def sample_wind_delta(world, emitter):
    mode = emitter.get("mode", "constant")

    if mode == "constant":
        return emitter["delta"]

    if mode == "cycle":
        cycle = emitter["cycle"]
        ticks_per_step = emitter["ticks_per_step"]
        index = (world.tick // ticks_per_step) % len(cycle)
        return cycle[index]

    return emitter["delta"]

def sample_magnet_delta(world, emitter_entity, emitter, target_entity):
    emitter_transform = world.transform.get(emitter_entity)
    target_transform = world.transform.get(target_entity)

    if emitter_transform is None or target_transform is None:
        return Vec2i(0, 0)

    dx = emitter_transform.cpos.x - target_transform.cpos.x
    dy = emitter_transform.cpos.y - target_transform.cpos.y

    # Simple square radius check for now.
    radius = emitter["radius"]
    if abs(dx) > radius or abs(dy) > radius:
        return Vec2i(0, 0)

    strength = emitter["strength"]

    return Vec2i(
        sign(dx) * strength,
        sign(dy) * strength,
    )

def influence_system(world):
    world.influence_delta.clear()

    receivers = (
        set(world.transform)
        & set(world.influence_receiver)
    )

    for entity in receivers:
        receiver = world.influence_receiver[entity]
        accepted = receiver["accepts"]

        total = Vec2i(0, 0)

        for emitter_entity, emitter in world.influence_emitter.items():
            influence_type = emitter["type"]

            if influence_type not in accepted:
                continue

            delta = Vec2i(0, 0)

            if influence_type == "wind":
                delta = sample_wind_delta(world, emitter)

            elif influence_type == "magnet":
                delta = sample_magnet_delta(world, emitter_entity, emitter, entity)

            scale_num, scale_den = receiver.get("scales", {}).get(
                influence_type,
                (1, 1),
            )

            delta = scale_vec(delta, scale_num, scale_den)

            total = total + delta

        max_delta = receiver.get("max_delta")

        if max_delta is not None:
            total = clamp_vec_axis(total, max_delta)

        world.influence_delta[entity] = total

def movement_system(world):
    entities = (
        set(world.transform)
        & set(world.motion_state)
    )

    for entity in sorted(entities):
        motion_state = world.motion_state[entity]
        controller = motion_state["controller"]
        transform = world.transform[entity]

        base_delta = Vec2i(0, 0)

        if controller is not None:
            base_delta = controller.sample_delta()

        influence_delta = world.influence_delta.get(entity, Vec2i(0, 0))
        delta = base_delta + influence_delta

        if delta.x != 0 or delta.y != 0:
            next_cpos = transform.cpos + delta
            next_tile = tile_from_cpos(next_cpos)

            collision_result = handle_static_tile_collision(world, entity, next_tile)

            if collision_result == "destroy":
                world.entities.destroy(entity)
                continue

            if collision_result == "block":
                motion_state["last_delta"] = Vec2i(0, 0)

                if controller is not None:
                    motion_state["controller"] = None

                continue

            transform.cpos = next_cpos

            if transform.position_mode == "free":
                transform.tile = tile_from_cpos(transform.cpos)

            motion_state["last_delta"] = delta

        if controller is not None:
            controller.advance()

            if controller.finished():
                if hasattr(controller, "end"):
                    transform.cpos = controller.end

                transform.tile = tile_from_cpos(transform.cpos)
                motion_state["controller"] = None

def skill_system(world, intents):
    for entity, entity_intents in intents.items():
        for intent in entity_intents:
            if intent["type"] != "skill_pressed":
                continue

            slot = intent["slot"]
            skill = world.skills.get((entity, slot))

            if not skill:
                continue

            skill_id = skill["id"]
            handler = SKILL_HANDLERS.get(skill_id)
            if handler is None:
                continue

            handler(world, entity, intent, skill)

def lifetime_system(world):
    for entity in list(world.lifetime):
        lifetime = world.lifetime[entity]

        lifetime["remaining_ticks"] -= 1

        if lifetime["remaining_ticks"] <= 0:
            world.entities.destroy(entity)

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
def get_sprite_offset(image, anchor):
    if anchor == "center":
        return Vec2i(-image.get_width() // 2, -image.get_height() // 2)
    if anchor == "bottom_center":
        return Vec2i(-image.get_width() // 2, -image.get_height())

    raise ValueError(f"Unknown anchor: {anchor}")

def sprite_system(world, surface):
    draw_list = []
    offset_x, offset_y = world.camera_offset

    for entity in world.sprite:
        if entity not in world.transform:
            continue

        pos = world.transform[entity].cpos
        sprite = world.sprite[entity]

        screen_x, screen_y = cpos_to_screen(pos, world.tile_size)

        # Debug
        tile = world.transform[entity].tile
        tile_center_cpos = tile_center(tile)
        tile_screen_x, tile_screen_y = cpos_to_screen(tile_center_cpos, world.tile_size)
        pygame.draw.circle(surface, "black",(tile_screen_x + offset_x, tile_screen_y + offset_y), 4)
        # End Debug

        sprite_offset = get_sprite_offset(sprite["image"], sprite["anchor"])
        draw_list.append((
            screen_y + sprite.get("z", 0),
            sprite["image"],
            (
                screen_x + offset_x + sprite_offset.x,
                screen_y + offset_y + sprite_offset.y
            )
        ))

    draw_list.sort(key=lambda x: x[0])

    for _, image, pos in draw_list:
        surface.blit(image, pos)