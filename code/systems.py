import pygame
import math
from settings import TILE_UNITS, MAX_COLLISION_STEP
from skills import SKILL_HANDLERS
from support import (
    Vec2i,
    sign,
    tile_center,
    tile_from_cpos,
    iso_to_screen,
    cpos_to_screen,
    GridMoveController,
    scale_vec,
    clamp_vec_axis,
    lerp_cpos,
    close_enough_cpos,
    smooth_lerp_cpos,
)


def num_collision_substeps(delta: Vec2i) -> int:
    max_axis = max(abs(delta.x), abs(delta.y))

    if max_axis == 0:
        return 1

    return max(1, (max_axis + MAX_COLLISION_STEP - 1) // MAX_COLLISION_STEP)

def substep_position(start: Vec2i, delta: Vec2i, step: int, total_steps: int) -> Vec2i:
    return Vec2i(
        start.x + delta.x * step // total_steps,
        start.y + delta.y * step // total_steps,
    )

def is_tile_blocked(world, tile: Vec2i) -> bool:
    # Out of bounds is blocked.
    if tile.y < 0 or tile.y >= len(world.tilemap):
        return True

    if tile.x < 0 or tile.x >= len(world.tilemap[tile.y]):
        return True

    # Static collision from tilemap.
    return (tile.x, tile.y) in world.static_collision_tiles

def resolve_static_tile_movement(world, entity, start_cpos: Vec2i, delta: Vec2i):
    steps = num_collision_substeps(delta)

    previous_cpos = start_cpos

    for step in range(1, steps + 1):
        candidate_cpos = substep_position(start_cpos, delta, step, steps)
        candidate_tile = tile_from_cpos(candidate_cpos)

        collision_result = handle_static_tile_collision(
            world,
            entity,
            candidate_tile,
        )

        if collision_result == "destroy":
            return "destroy", previous_cpos

        if collision_result == "block":
            return "block", previous_cpos

        previous_cpos = candidate_cpos

    return "allow", start_cpos + delta

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

    for entity in sorted(entities):
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

def motion_accepts_influences(motion_state) -> bool:
    if motion_state is None:
        return True

    influence_mode = motion_state.get("influence_mode", "normal")

    if influence_mode == "ignore_all":
        return False

    return True

def influence_system(world):
    world.influence_delta.clear()

    receivers = (
        set(world.transform)
        & set(world.influence_receiver)
    )

    for entity in sorted(receivers):
        motion_state = world.motion_state.get(entity)

        if not motion_accepts_influences(motion_state):
            world.influence_delta[entity] = Vec2i(0, 0)
            continue

        receiver = world.influence_receiver[entity]
        accepted = receiver["accepts"]

        total = Vec2i(0, 0)

        for emitter_entity in sorted(world.influence_emitter):
            emitter = world.influence_emitter[emitter_entity]
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

def clear_motion_controller(motion_state):
    motion_state["controller"] = None
    motion_state["influence_mode"] = "normal"

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

        start_cpos = transform.cpos

        if delta.x != 0 or delta.y != 0:
            collision_result, resolved_cpos = resolve_static_tile_movement(
                world,
                entity,
                start_cpos,
                delta,
            )

            if collision_result == "destroy":
                world.entities.destroy(entity)
                continue

            if collision_result == "block":
                transform.cpos = resolved_cpos

                if transform.position_mode == "free":
                    transform.tile = tile_from_cpos(transform.cpos)

                motion_state["last_delta"] = transform.cpos - start_cpos

                if controller is not None:
                    clear_motion_controller(motion_state)

                continue

            transform.cpos = resolved_cpos

            if transform.position_mode == "free":
                transform.tile = tile_from_cpos(transform.cpos)

            motion_state["last_delta"] = transform.cpos - start_cpos

        if controller is not None:
            controller.advance()

            if controller.finished():
                if hasattr(controller, "end"):
                    transform.cpos = controller.end

                transform.tile = tile_from_cpos(transform.cpos)
                clear_motion_controller(motion_state)

def skill_intent_resolution_system(world, intents):
    world.resolved_skill_intents.clear()

    for entity, entity_intents in intents.items():
        for intent in entity_intents:
            if intent["type"] != "skill_pressed":
                continue

            slot = intent["slot"]
            skill = world.skills.get((entity, slot))

            if not skill:
                continue

            cooldown_key = (entity, slot)
            ready_tick = world.skill_cooldown.get(cooldown_key, 0)

            if world.tick < ready_tick:
                continue

            skill_id = skill["id"]
            handler = SKILL_HANDLERS.get(skill_id)

            if handler is None:
                continue

            world.resolved_skill_intents.append({
                "caster": entity,
                "slot": slot,
                "skill": skill,
                "intent": intent,
                "handler": handler,
            })

def skill_execution_system(world):
    for resolved in sorted(
            world.resolved_skill_intents,
            key=lambda r: (r["caster"], str(r["slot"])),
    ):
        caster = resolved["caster"]
        slot = resolved["slot"]
        skill = resolved["skill"]
        intent = resolved["intent"]
        handler = resolved["handler"]

        executed = handler(world, caster, intent, skill)

        if executed:
            cooldown_ticks = skill.get("cooldown_ticks", 0)
            world.skill_cooldown[(caster, slot)] = world.tick + cooldown_ticks

def lifetime_system(world):
    for entity in sorted(list(world.lifetime)):
        lifetime = world.lifetime[entity]

        lifetime["remaining_ticks"] -= 1

        if lifetime["remaining_ticks"] <= 0:
            world.entities.destroy(entity)

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
    camera = world.camera
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
    camera = world.camera

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
    camera = world.camera

    camera["mode"] = "fixed"
    camera["fixed_cpos"] = fixed_cpos
    camera["transition_mode"] = transition_mode

    if transition_mode == "smooth":
        camera["transition_ticks"] = 0
        camera["transition_duration"] = transition_duration
        camera["transition_start_cpos"] = camera["current_cpos"]

def start_camera_shake(world, duration_ticks: int, strength: int):
    camera = world.camera

    camera["shake_ticks"] = duration_ticks
    camera["shake_duration"] = duration_ticks
    camera["shake_strength"] = strength

def camera_shake_system(world):
    camera = world.camera

    if camera["shake_ticks"] > 0:
        camera["shake_ticks"] -= 1

        if camera["shake_ticks"] <= 0:
            camera["shake_duration"] = 0
            camera["shake_strength"] = 0

def camera_update_system(world):
    camera = world.camera
    target_cpos = get_camera_target_cpos(world)

    if target_cpos is None:
        return

    if camera["current_cpos"] is None:
        camera["current_cpos"] = target_cpos
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

def camera_system(world, surface):
    camera = world.camera
    target_cpos = camera.get("current_cpos")

    if target_cpos is None:
        return

    target_screen_x, target_screen_y = cpos_to_screen(
        target_cpos,
        world.tile_size,
    )

    surface_center_x = surface.get_width() // 2
    surface_center_y = surface.get_height() // 2

    screen_offset = camera.get("screen_offset", Vec2i(0, 0))
    shake_offset = sample_camera_shake(camera)

    world.camera_offset = (
        surface_center_x - target_screen_x + screen_offset.x + shake_offset.x,
        surface_center_y - target_screen_y + screen_offset.y + shake_offset.y,
    )

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
        sprite_offset = get_sprite_offset(sprite["image"], sprite["anchor"])
        pygame.draw.circle(surface, "red", (screen_x + offset_x, screen_y + offset_y), 4)
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