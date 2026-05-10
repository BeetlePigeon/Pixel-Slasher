import pygame
from skills import SKILL_DEFS
from camera_utils import internal_screen_to_world_tile
from support import (
    TILE_UNITS,
    Vec2i,
    sign,
    tile_center,
    tile_from_cpos,
    interp_cpos,
    iso_to_screen,
    cpos_to_screen,
    screen_to_cpos,
    scale_vec,
    clamp_vec_axis,
    lerp_cpos,
    GridMoveController,
    SettleToGridController,
)


def emit_event(world, event_type, **data):
    world.events.append({
        "type": event_type,
        **data,
    })

def snapshot_system(world):
    world.snapshot["cpos"].clear()
    world.snapshot["tile"].clear()

    for entity in sorted(world.transform):
        transform = world.transform[entity]
        transform.prev_cpos = transform.cpos

        world.snapshot["cpos"][entity] = transform.cpos
        world.snapshot["tile"][entity] = transform.tile

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
    emitter_cpos = world.snapshot["cpos"].get(emitter_entity)
    target_cpos = world.snapshot["cpos"].get(target_entity)

    if emitter_cpos is None or target_cpos is None:
        return Vec2i(0, 0)

    dx = emitter_cpos.x - target_cpos.x
    dy = emitter_cpos.y - target_cpos.y

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

def is_at_cpos(a: Vec2i, b: Vec2i) -> bool:
    return a.x == b.x and a.y == b.y

def axis_cross_position(start: Vec2i, delta: Vec2i, axis_distance: int, axis_abs_delta: int) -> Vec2i:
    return Vec2i(
        start.x + delta.x * axis_distance // axis_abs_delta,
        start.y + delta.y * axis_distance // axis_abs_delta,
    )

def safe_before_x_cross(boundary_cpos: Vec2i, step_x: int) -> Vec2i:
    return Vec2i(
        boundary_cpos.x - step_x,
        boundary_cpos.y,
    )

def safe_before_y_cross(boundary_cpos: Vec2i, step_y: int) -> Vec2i:
    return Vec2i(
        boundary_cpos.x,
        boundary_cpos.y - step_y,
    )

def safe_before_corner_cross(boundary_cpos: Vec2i, step_x: int, step_y: int) -> Vec2i:
    return Vec2i(
        boundary_cpos.x - step_x,
        boundary_cpos.y - step_y,
    )

def passes_slide_threshold(tangent: int, normal: int, ratio) -> bool:
    num, den = ratio

    tangent_abs = abs(tangent)
    normal_abs = abs(normal)

    if tangent_abs == 0:
        return False

    return tangent_abs * den >= normal_abs * num

def is_tile_blocked(world, tile: Vec2i) -> bool:
    # Out of bounds is blocked.
    if tile.y < 0 or tile.y >= len(world.tilemap):
        return True

    if tile.x < 0 or tile.x >= len(world.tilemap[tile.y]):
        return True

    # Static collision from tilemap.
    return (tile.x, tile.y) in world.static_collision_tiles

def resolve_static_tile_movement(world, entity, start_cpos: Vec2i, delta: Vec2i):
    collision_result, resolved_cpos = trace_static_tile_path(
        world,
        entity,
        start_cpos,
        delta,
    )

    if collision_result == "slide":
        return resolve_slide_static_tile_movement(
            world,
            entity,
            start_cpos,
            delta,
        )

    return collision_result, resolved_cpos

def resolve_slide_static_tile_movement(world, entity, start_cpos: Vec2i, delta: Vec2i):
    policy = world.movement_collision.get(entity, {})
    ratio = policy.get("slide_min_tangent_ratio", (1, 2))

    options = []

    # Try x-only movement.
    if delta.x != 0:
        x_delta = Vec2i(delta.x, 0)
        x_result, x_cpos = trace_static_tile_path(
            world,
            entity,
            start_cpos,
            x_delta,
        )

        if x_result == "allow":
            tangent = delta.x
            normal = delta.y

            if passes_slide_threshold(tangent, normal, ratio):
                options.append(("x", abs(tangent), x_cpos))

    # Try y-only movement.
    if delta.y != 0:
        y_delta = Vec2i(0, delta.y)
        y_result, y_cpos = trace_static_tile_path(
            world,
            entity,
            start_cpos,
            y_delta,
        )

        if y_result == "allow":
            tangent = delta.y
            normal = delta.x

            if passes_slide_threshold(tangent, normal, ratio):
                options.append(("y", abs(tangent), y_cpos))

    if not options:
        return "block", start_cpos

    # Pick the stronger valid slide component.
    # Tie-breaker is deterministic because "x" sorts before "y".
    options.sort(key=lambda item: (-item[1], item[0]))

    _, _, chosen_cpos = options[0]
    return "allow", chosen_cpos

def trace_static_tile_path(world, entity, start_cpos: Vec2i, delta: Vec2i):
    end_cpos = start_cpos + delta

    current_tile = tile_from_cpos(start_cpos)
    target_tile = tile_from_cpos(end_cpos)

    if current_tile == target_tile:
        collision_result = handle_static_tile_collision(
            world,
            entity,
            target_tile,
        )

        if collision_result != "allow":
            return collision_result, start_cpos

        return "allow", end_cpos

    dx = delta.x
    dy = delta.y

    step_x = sign(dx)
    step_y = sign(dy)

    abs_dx = abs(dx)
    abs_dy = abs(dy)

    # Distance along x/y, in canonical units, until the first tile boundary crossing.
    if step_x > 0:
        next_x_boundary = (current_tile.x + 1) * TILE_UNITS
        next_cross_x = next_x_boundary - start_cpos.x
    elif step_x < 0:
        next_x_boundary = current_tile.x * TILE_UNITS - 1
        next_cross_x = start_cpos.x - next_x_boundary
    else:
        next_cross_x = None

    if step_y > 0:
        next_y_boundary = (current_tile.y + 1) * TILE_UNITS
        next_cross_y = next_y_boundary - start_cpos.y
    elif step_y < 0:
        next_y_boundary = current_tile.y * TILE_UNITS - 1
        next_cross_y = start_cpos.y - next_y_boundary
    else:
        next_cross_y = None

    while current_tile != target_tile:
        if next_cross_x is None:
            step_axis = "y"
        elif next_cross_y is None:
            step_axis = "x"
        else:
            # Compare:
            #     next_cross_x / abs_dx
            # vs.
            #     next_cross_y / abs_dy
            #
            # without floats.
            left = next_cross_x * abs_dy
            right = next_cross_y * abs_dx

            if left < right:
                step_axis = "x"
            elif right < left:
                step_axis = "y"
            else:
                step_axis = "corner"

        if step_axis == "x":
            boundary_cpos = axis_cross_position(
                start_cpos,
                delta,
                next_cross_x,
                abs_dx,
            )

            current_tile = Vec2i(
                current_tile.x + step_x,
                current_tile.y,
            )

            collision_result = handle_static_tile_collision(
                world,
                entity,
                current_tile,
            )

            if collision_result != "allow":
                return collision_result, safe_before_x_cross(
                    boundary_cpos,
                    step_x,
                )

            next_cross_x += TILE_UNITS

        elif step_axis == "y":
            boundary_cpos = axis_cross_position(
                start_cpos,
                delta,
                next_cross_y,
                abs_dy,
            )

            current_tile = Vec2i(
                current_tile.x,
                current_tile.y + step_y,
            )

            collision_result = handle_static_tile_collision(
                world,
                entity,
                current_tile,
            )

            if collision_result != "allow":
                return collision_result, safe_before_y_cross(
                    boundary_cpos,
                    step_y,
                )

            next_cross_y += TILE_UNITS

        else:
            # Exact corner crossing. Be conservative and check the two side-adjacent
            # tiles as well as the diagonal tile.
            boundary_cpos = axis_cross_position(
                start_cpos,
                delta,
                next_cross_x,
                abs_dx,
            )

            side_x_tile = Vec2i(
                current_tile.x + step_x,
                current_tile.y,
            )

            side_y_tile = Vec2i(
                current_tile.x,
                current_tile.y + step_y,
            )

            diagonal_tile = Vec2i(
                current_tile.x + step_x,
                current_tile.y + step_y,
            )

            safe_cpos = safe_before_corner_cross(
                boundary_cpos,
                step_x,
                step_y,
            )

            for candidate_tile in (side_x_tile, side_y_tile, diagonal_tile):
                collision_result = handle_static_tile_collision(
                    world,
                    entity,
                    candidate_tile,
                )

                if collision_result != "allow":
                    return collision_result, safe_cpos

            current_tile = diagonal_tile

            next_cross_x += TILE_UNITS
            next_cross_y += TILE_UNITS

    return "allow", end_cpos

def start_settle_to_grid_if_needed(world, entity, transform, motion_state) -> bool:
    # Only grid-positioned actors should settle.
    if transform.position_mode != "grid":
        return False

    # Only entities with locomotion are currently considered grid actors.
    if entity not in world.locomotion:
        return False

    target_tile = tile_from_cpos(transform.cpos)
    target_cpos = tile_center(target_tile)

    transform.tile = target_tile

    if is_at_cpos(transform.cpos, target_cpos):
        return False

    motion_state["controller"] = SettleToGridController(
        start=transform.cpos,
        end=target_cpos,
        progress=0,
        duration=4,
    )

    motion_state["influence_mode"] = "normal"

    return True

def handle_static_tile_collision(world, entity, next_tile):
    policy = world.movement_collision.get(entity)

    if policy is None:
        return "allow"

    behavior = policy.get("static_tiles", "allow")

    if not is_tile_blocked(world, next_tile):
        return "allow"

    return behavior

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
                emit_event(
                    world,
                    "entity_destroyed_by_static_collision",
                    entity=entity,
                    cpos=transform.cpos,
                    tile=transform.tile,
                )

                world.entities.destroy(entity)
                continue

            if collision_result == "block":
                transform.cpos = resolved_cpos

                if transform.position_mode == "free":
                    transform.tile = tile_from_cpos(transform.cpos)

                motion_state["last_delta"] = transform.cpos - start_cpos

                if controller is not None:
                    clear_motion_controller(motion_state)
                    start_settle_to_grid_if_needed(world, entity, transform, motion_state)

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
                start_settle_to_grid_if_needed(world, entity, transform, motion_state)

def skill_trigger_matches_intent(skill_def, intent):
    trigger_mode = skill_def["trigger_mode"]
    intent_type = intent["type"]

    if trigger_mode == "press":
        return intent_type == "skill_pressed"

    if trigger_mode == "held_repeat":
        return intent_type == "skill_held"

    return False

def entity_has_component(world, entity, component_name):
    component_map = getattr(world, component_name)
    return entity in component_map

def entity_meets_skill_requirements(world, entity, skill_def):
    required_components = skill_def.get("required_components", set())

    for component_name in required_components:
        if not entity_has_component(world, entity, component_name):
            return False

    return True

def build_resolved_skill(world, caster, skill_def):
    resolved = dict(skill_def)

    if "params" in skill_def:
        resolved["params"] = dict(skill_def["params"])

    return resolved

def skill_intent_resolution_system(world, intents):
    world.resolved_skill_intents.clear()

    for entity, entity_intents in intents.items():
        for intent in entity_intents:
            if intent["type"] not in {
                "skill_pressed",
                "skill_held",
                "skill_released",
            }:
                continue

            slot = intent["slot"]
            skill_id = world.skills.get((entity, slot))

            if not skill_id:
                continue

            skill_def = SKILL_DEFS.get(skill_id)

            if skill_def is None:
                continue

            if not skill_trigger_matches_intent(skill_def, intent):
                continue

            cooldown_key = (entity, slot)
            ready_tick = world.skill_cooldown.get(cooldown_key, 0)

            if world.tick < ready_tick:
                continue

            if not entity_meets_skill_requirements(world, entity, skill_def):
                continue

            resolved_skill = build_resolved_skill(world, entity, skill_def)
            handler = resolved_skill["handler"]

            world.resolved_skill_intents.append({
                "caster": entity,
                "slot": slot,
                "skill_id": skill_id,
                "skill_def": resolved_skill,
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
        skill_def = resolved["skill_def"]
        intent = resolved["intent"]
        handler = resolved["handler"]

        executed = handler(world, caster, intent, skill_def)

        if executed:
            cooldown_ticks = skill_def.get("cooldown_ticks", 0)
            world.skill_cooldown[(caster, slot)] = world.tick + cooldown_ticks

def lifetime_system(world):
    for entity in sorted(list(world.lifetime)):
        lifetime = world.lifetime[entity]

        lifetime["remaining_ticks"] -= 1

        if lifetime["remaining_ticks"] <= 0:
            world.entities.destroy(entity)

def event_system(world):
    for event in world.events:
        event_type = event["type"]

        if event_type == "entity_destroyed_by_static_collision":
            start_camera_shake(
                world,
                duration_ticks=8,
                strength=2,
            )

    world.events.clear()

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

def camera_system(world, surface, render_alpha):
    camera = world.camera

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

    target_screen_x, target_screen_y = cpos_to_screen(
        visual_camera_cpos,
        world.tile_size,
    )

    surface_center_x = surface.get_width() // 2
    surface_center_y = surface.get_height() // 2

    screen_offset = camera.get("screen_offset", Vec2i(0, 0))
    shake_offset = sample_camera_shake(camera)

    base_offset = (
        surface_center_x - target_screen_x + screen_offset.x,
        surface_center_y - target_screen_y + screen_offset.y,
    )

    world.camera_base_offset = base_offset

    world.camera_offset = (
        base_offset[0] + shake_offset.x,
        base_offset[1] + shake_offset.y,
    )
def render_tiles(world, surface, render_alpha=0.0):
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

def sprite_system(world, surface, render_alpha):
    draw_list = []
    offset_x, offset_y = world.camera_offset

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