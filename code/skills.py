from placement_utils import find_nearest_valid_placement_tile
from support import (
    ANGLE_SCALE,
    TILE_UNITS,
    AIM_DIRECTION_LUTS,
    AIM_LUT_SIZES,
    DashController,
    Vec2i,
    sign,
    quantize_vector_to_lut_direction,
    scale_normalized_dir,
    normalize_vector_to_dir_scale,
    tile_center,
    tile_from_cpos,
)
from camera_utils import (
    internal_screen_to_world_tile,
    internal_screen_to_world_cpos,
    snap_camera_to_entity_now,
)
from motion_ops import teleport_entity_to_tile
from teleport_utils import resolve_path_tolerant_teleport_tile
from spawners import (
    spawn_test_projectile,
    spawn_spiral_projectile,
    spawn_magnet_orb,
)


def vector_from_caster_tile_to_mouse_tile(world, caster, intent):
    mouse_pos = intent.get("mouse_pos")

    if mouse_pos is None:
        return None

    caster_tile = world.transform[caster].tile
    mouse_tile = internal_screen_to_world_tile(world, mouse_pos)

    caster_tile_cpos = tile_center(caster_tile)
    mouse_tile_cpos = tile_center(mouse_tile)

    vector = mouse_tile_cpos - caster_tile_cpos

    if vector.x == 0 and vector.y == 0:
        return None

    return vector


def resolve_setting_ref(world, value):
    if isinstance(value, str) and value.startswith("setting:"):
        setting_name = value.split(":", 1)[1]

        if setting_name not in world.gameplay_settings:
            raise ValueError(
                f"Unknown gameplay setting reference: {value}"
            )

        return world.gameplay_settings[setting_name]

    return value


def get_context_aim_timing(context):
    return context["params"].get("aim_timing", "cast_start")


def get_context_intent_for_aim(world, caster, context):
    aim_timing = get_context_aim_timing(context)

    if aim_timing == "cast_start":
        return context["intent"]

    if aim_timing == "live":
        aim_state = world.aim_state.get(caster, {})

        live_intent = dict(context["intent"])

        if "mouse_pos" in aim_state:
            live_intent["mouse_pos"] = aim_state["mouse_pos"]

        return live_intent

    raise ValueError(f"Unknown aim_timing: {aim_timing}")


def aim_vector_to_tile_direction(aim_vector):
    return Vec2i(
        sign(aim_vector.x),
        sign(aim_vector.y),
    )


def build_slash_fan_tiles(origin_tile, direction):
    if direction.x == 0 and direction.y == 0:
        return []

    tiles = set()

    forward_tile = Vec2i(
        origin_tile.x + direction.x,
        origin_tile.y + direction.y,
    )

    tiles.add(forward_tile)

    if direction.x != 0 and direction.y != 0:
        # Diagonal slash: include the two orthogonal tiles that form the corner.
        tiles.add(Vec2i(
            origin_tile.x + direction.x,
            origin_tile.y,
        ))
        tiles.add(Vec2i(
            origin_tile.x,
            origin_tile.y + direction.y,
        ))

    elif direction.x != 0:
        # Horizontal tile-space slash: include tiles above/below the forward tile.
        tiles.add(Vec2i(
            forward_tile.x,
            forward_tile.y - 1,
        ))
        tiles.add(Vec2i(
            forward_tile.x,
            forward_tile.y + 1,
        ))

    else:
        # Vertical tile-space slash: include tiles left/right of the forward tile.
        tiles.add(Vec2i(
            forward_tile.x - 1,
            forward_tile.y,
        ))
        tiles.add(Vec2i(
            forward_tile.x + 1,
            forward_tile.y,
        ))

    return list(tiles)


DEFAULT_AIM_OFFSET_RESOLUTION = 32


def apply_aim_offset_steps(aim_vector: Vec2i, offset_steps: int, lut_size: int):
    if offset_steps == 0:
        return aim_vector

    if lut_size not in AIM_DIRECTION_LUTS:
        raise ValueError(f"Unsupported aim offset LUT size: {lut_size}")

    directions = AIM_DIRECTION_LUTS[lut_size]

    base_direction = quantize_vector_to_lut_direction(
        aim_vector,
        lut_size,
    )

    if base_direction is None:
        return aim_vector

    base_index = directions.index(base_direction)
    offset_index = (base_index + offset_steps) % len(directions)

    return directions[offset_index]


ALLOWED_AIM_OFFSET_DISTANCE_SCALING = {
    "none",
    "tighten_with_mouse_distance",
}


def get_mouse_aim_distance_cpos(world, caster, intent):
    mouse_pos = intent.get("mouse_pos")

    if mouse_pos is None:
        return None

    caster_cpos = world.transform[caster].cpos
    target_cpos = internal_screen_to_world_cpos(world, mouse_pos)

    delta = target_cpos - caster_cpos

    # Chebyshev-style distance. This fits the tile/grid feel.
    return max(
        abs(delta.x),
        abs(delta.y),
    )


def scale_aim_offset_steps_by_mouse_distance(
    world,
    caster,
    intent,
    params,
    offset_steps,
):
    scaling_mode = params.get("aim_offset_distance_scaling", "none")

    if scaling_mode == "none":
        return offset_steps

    if scaling_mode != "tighten_with_mouse_distance":
        raise ValueError(
            f"Unknown aim_offset_distance_scaling: {scaling_mode}"
        )

    distance_cpos = get_mouse_aim_distance_cpos(
        world,
        caster,
        intent,
    )

    if distance_cpos is None:
        return offset_steps

    near_cpos = params.get("aim_offset_near_tiles", 2) * TILE_UNITS
    far_cpos = params.get("aim_offset_far_tiles", 12) * TILE_UNITS
    far_percent = params.get("aim_offset_far_percent", 25)

    if far_cpos <= near_cpos:
        return offset_steps

    if distance_cpos <= near_cpos:
        scale_percent = 100

    elif distance_cpos >= far_cpos:
        scale_percent = far_percent

    else:
        progress = distance_cpos - near_cpos
        span = far_cpos - near_cpos

        scale_percent = 100 - (
            (100 - far_percent) * progress // span
        )

    sign_value = sign(offset_steps)
    abs_steps = abs(offset_steps)

    scaled_abs_steps = (
        abs_steps * scale_percent + 50
    ) // 100

    return sign_value * scaled_abs_steps


def resolve_context_aim_vector(world, caster, context):
    skill_def = context["skill_def"]
    params = context["params"]

    intent = get_context_intent_for_aim(
        world,
        caster,
        context,
    )

    aim_vector = resolve_skill_aim_vector(
        world,
        caster,
        intent,
        skill_def,
    )

    if aim_vector is None:
        return None

    offset_steps = params.get("aim_offset_steps", 0)

    if offset_steps == 0:
        return aim_vector

    offset_steps = scale_aim_offset_steps_by_mouse_distance(
        world,
        caster,
        intent,
        params,
        offset_steps,
    )

    if offset_steps == 0:
        return aim_vector

    offset_resolution = params.get(
        "aim_offset_resolution",
        DEFAULT_AIM_OFFSET_RESOLUTION,
    )

    return apply_aim_offset_steps(
        aim_vector,
        offset_steps,
        offset_resolution,
    )


def tile_direction_to_aim_vector(direction: Vec2i):
    # Convert existing 8-way facing direction into the same normalized-vector
    # format used by aimed skills.
    from support import DIRECTION_VECTORS

    return DIRECTION_VECTORS[direction]


def vector_from_caster_to_mouse(world, caster, intent):
    mouse_pos = intent.get("mouse_pos")

    if mouse_pos is None:
        return None

    caster_cpos = world.transform[caster].cpos
    target_cpos = internal_screen_to_world_cpos(world, mouse_pos)

    vector = target_cpos - caster_cpos

    if vector.x == 0 and vector.y == 0:
        return None

    return vector


def get_skill_aim_config(world, skill_def):
    aim_config = skill_def.get("aim")

    if aim_config is None:
        raise ValueError(
            f"Skill '{skill_def['id']}' does not define aim config"
        )

    if world.control_scheme == "traditional":
        raw_source = aim_config["traditional_source"]
    else:
        raw_source = aim_config["modern_source"]

    raw_resolution = aim_config["resolution"]

    source = resolve_setting_ref(world, raw_source)
    resolution = resolve_setting_ref(world, raw_resolution)

    return source, resolution


def resolve_skill_aim_vector(world, caster, intent, skill_def):
    source, resolution = get_skill_aim_config(world, skill_def)

    if source == "facing":
        return tile_direction_to_aim_vector(world.facing[caster])

    if source == "mouse_tile":
        vector = vector_from_caster_tile_to_mouse_tile(
            world,
            caster,
            intent,
        )

        if vector is None:
            return tile_direction_to_aim_vector(world.facing[caster])

        aim_vector = normalize_vector_to_dir_scale(vector)

        if aim_vector is None:
            return tile_direction_to_aim_vector(world.facing[caster])

        return aim_vector

    if source == "mouse":
        vector = vector_from_caster_to_mouse(world, caster, intent)

        if vector is None:
            return tile_direction_to_aim_vector(world.facing[caster])

        aim_vector = quantize_vector_to_lut_direction(
            vector,
            resolution,
        )

        if aim_vector is None:
            return tile_direction_to_aim_vector(world.facing[caster])

        return aim_vector

    raise ValueError(f"Unknown skill aim source: {source}")


def direction_from_cpos_to_cpos(start_cpos, target_cpos):
    direction = Vec2i(
        sign(target_cpos.x - start_cpos.x),
        sign(target_cpos.y - start_cpos.y),
    )

    if direction.x == 0 and direction.y == 0:
        return None

    return direction


def direction_toward_mouse(world, caster, intent):
    mouse_pos = intent.get("mouse_pos")

    if mouse_pos is None:
        return None

    caster_cpos = world.transform[caster].cpos
    target_cpos = internal_screen_to_world_cpos(world, mouse_pos)

    return direction_from_cpos_to_cpos(
        caster_cpos,
        target_cpos,
    )


def get_skill_aim_source(world, skill_def):
    params = skill_def["params"]

    if world.control_scheme == "traditional":
        raw_aim_source = params["traditional_aim_source"]
    else:
        raw_aim_source = params["modern_aim_source"]

    return resolve_setting_ref(world, raw_aim_source)


def resolve_skill_aim_direction(world, caster, intent, skill_def):
    aim_source = get_skill_aim_source(world, skill_def)

    if aim_source == "facing":
        return world.facing[caster]

    if aim_source == "mouse":
        direction = direction_toward_mouse(world, caster, intent)

        if direction is not None:
            return direction

        return world.facing[caster]

    raise ValueError(f"Unknown skill aim source: {aim_source}")


def build_action_events(action_def):
    events = []

    for event_def in action_def.get("events", []):
        events.append({
            "tick": event_def["tick"],
            "handler": event_def["handler"],
            "params": dict(event_def.get("params", {})),
            "fired": False,
        })

    return events


def build_action_repeat_events(action_def):
    repeat_events = []

    for event_def in action_def.get("repeat_events", []):
        repeat_events.append({
            "start_tick": event_def["start_tick"],
            "interval": event_def["interval"],
            "handler": event_def["handler"],
            "params": dict(event_def.get("params", {})),
        })

    return repeat_events


def build_action_phases(action_def):
    phases = []

    for phase_def in action_def.get("phases", []):
        phases.append({
            "name": phase_def["name"],
            "start": phase_def["start"],
            "end": phase_def["end"],
            "tags": set(phase_def["tags"]),
        })

    return phases


def start_skill_action(world, caster, context, action_def, action_type):
    from action_ops import start_action_state

    skill_def = context["skill_def"]
    intent = context["intent"]

    events = build_action_events(action_def)
    repeat_events = build_action_repeat_events(action_def)
    phases = build_action_phases(action_def)

    action_state = {
        "type": action_type,
        "skill_id": skill_def["id"],
        "slot": intent.get("slot"),

        "tags": set(action_def["tags"]),
        "age": 0,
        "duration": action_def["duration"],

        "min_duration": action_def.get("min_duration", 0),
        "ends_on_release": action_def.get("ends_on_release", False),
        "release_requested": False,

        "intent": dict(intent),
        "skill_def": skill_def,

        "events": events,
        "repeat_events": repeat_events,
    }

    if phases:
        action_state["phases"] = phases

    start_action_state(
        world,
        caster,
        action_state,
    )

    return True


def execute_cast_skill(world, caster, context):
    skill_def = context["skill_def"]
    cast = skill_def["cast"]

    return start_skill_action(
        world,
        caster,
        context,
        action_def=cast,
        action_type=cast.get("type", "cast"),
    )


def execute_channel_skill(world, caster, context):
    skill_def = context["skill_def"]
    channel = skill_def["channel"]

    return start_skill_action(
        world,
        caster,
        context,
        action_def=channel,
        action_type=channel.get("type", "channel"),
    )


def execute_dash(world, caster, context):
    params = context["params"]

    aim_vector = resolve_context_aim_vector(
        world,
        caster,
        context,
    )

    if aim_vector is None:
        return False

    from systems import cancel_voluntary_movement

    cancel_voluntary_movement(world, caster)

    motion_state = world.motion_state[caster]

    motion_state["controller"] = DashController(
        aim_vector=aim_vector,
        age=0,
        duration=params["duration"],
        distance=params["distance"],
        slide_min_tangent_ratio=params["slide_min_tangent_ratio"],
    )

    motion_state["controller_source"] = "skill_dash"
    motion_state["influence_mode"] = params["influence_mode"]

    return True


def execute_test_projectile(world, caster, context):
    params = context["params"]

    caster_cpos = world.transform[caster].cpos

    aim_vector = resolve_context_aim_vector(
        world,
        caster,
        context,
    )

    if aim_vector is None:
        return False

    spawn_offset = scale_normalized_dir(
        aim_vector,
        params["spawn_distance"],
    )

    spawn_cpos = caster_cpos + spawn_offset

    eid = spawn_test_projectile(
        world,
        spawn_cpos,
        aim_vector,
        speed=params["projectile_speed"],
        lifetime_ticks=params["projectile_lifetime"],
    )

    return eid is not None


def execute_spiral_projectile(world, caster, context):
    params = context["params"]

    caster_cpos = world.transform[caster].cpos

    eid = spawn_spiral_projectile(
        world,
        caster_cpos,
        lifetime_ticks=params["projectile_lifetime"],
        radius_per_tick=params["radius_per_tick"],
        angle_step_fp=params["angle_step_fp"],
    )

    return eid is not None


def execute_magnet_orb(world, caster, context):
    params = context["params"]
    intent = get_context_intent_for_aim(world, caster, context)

    mouse_pos = intent.get("mouse_pos")

    if mouse_pos is None:
        return False

    target_tile = internal_screen_to_world_tile(world, mouse_pos)

    caster_tile = world.transform[caster].tile

    spawn_tile = find_nearest_valid_placement_tile(
        world,
        target_tile=target_tile,
        search_radius=params["placement_search_radius"],
        max_miss_tiles=params["placement_max_miss_tiles"],
        bias_tile=caster_tile,
        bias_mode="toward",
    )

    if spawn_tile is None:
        return False

    spawn_cpos = tile_center(spawn_tile)

    eid = spawn_magnet_orb(
        world,
        spawn_cpos,
        radius=params["radius"],
        strength=params["strength"],
        lifetime_ticks=params["lifetime"],
    )

    return eid is not None


def execute_teleport(world, caster, context):
    params = context["params"]
    intent = get_context_intent_for_aim(world, caster, context)

    mouse_pos = intent.get("mouse_pos")

    if mouse_pos is None:
        return False

    transform = world.transform[caster]

    # Use cpos-derived tile because path-follow/continuous movement can leave
    # transform.tile stale while movement is active.
    start_tile = tile_from_cpos(transform.cpos)
    target_tile = internal_screen_to_world_tile(world, mouse_pos)

    final_tile = resolve_path_tolerant_teleport_tile(
        world,
        start_tile=start_tile,
        target_tile=target_tile,
        target_snap_radius_tiles=params["target_snap_radius_tiles"],
        ray_fallback_max_miss_tiles=params["ray_fallback_max_miss_tiles"],
        ray_fallback_min_progress_tiles=params["ray_fallback_min_progress_tiles"],
    )

    if final_tile is None:
        return False

    teleport_entity_to_tile(world, caster, final_tile)
    snap_camera_to_entity_now(world, caster)

    return True


def execute_debug_slash(world, caster, context):
    from systems import add_debug_tile_highlight
    from combat_ops import queue_area_damage

    aim_vector = resolve_context_aim_vector(
        world,
        caster,
        context,
    )

    if aim_vector is None:
        return False

    transform = world.transform[caster]
    origin_tile = tile_from_cpos(transform.cpos)

    direction = aim_vector_to_tile_direction(aim_vector)

    affected_tiles = build_slash_fan_tiles(
        origin_tile,
        direction,
    )

    params = context["params"]

    for tile in affected_tiles:
        add_debug_tile_highlight(
            world,
            tile,
            duration_ticks=params.get("debug_highlight_ticks", 12),
            color=params.get("debug_highlight_color", "yellow"),
        )

    hit_targets = queue_area_damage(
        world,
        source=caster,
        tiles=affected_tiles,
        amount=params["damage"],
        skill_id=context["skill_def"]["id"],
    )

    return True


REQUIRED_SKILL_FIELDS = {
    "id",
    "name",

    "cooldown_ticks",
    "trigger_mode",

    "blocked_by_motion_tags",
    "blocked_by_action_tags",
    "cancels_action_tags",

    "required_components",
    "required_params",
    "allowed_param_values",

    "aim",
    "cast",
    "channel",

    "params",

    "handler",
}

ALLOWED_TRIGGER_MODES = {
    "press",
    "held_repeat",
}


ALLOWED_AIM_TIMINGS = {
    "cast_start",
    "live",
}


SKILL_DEFS = {

    "dash": {
        "id": "dash",
        "name": "Dash",

        "cooldown_ticks": 0,
        "trigger_mode": "held_repeat",

        "blocked_by_motion_tags": {"dash"},
        "blocked_by_action_tags": {"stun", "uninterruptible", "dash_windup"},
        "cancels_action_tags": {"cast", "channel",},

        "required_components": {"transform", "motion_state", "facing"},
        "required_params": {"duration", "distance", "influence_mode", "slide_min_tangent_ratio",},
        "allowed_param_values": {"influence_mode": {"normal", "ignore_all"},},

        "aim": {"traditional_source": "mouse", "modern_source": "setting:modern_movement_skill_aim_source", "resolution": "setting:movement_skill_aim_resolution",},
        "cast": {
            "duration": 6,
            "tags": {
                "cast",
                "dash_windup",
                "movement_locked",
                "skill_locked",
            },
            "events": [
                {
                    "tick": 6,
                    "handler": execute_dash,
                },
            ],
        },
        "channel": None,

        "params": {
            "duration": 155,
            "distance": TILE_UNITS * 7,
            "influence_mode": "ignore_all",
            "slide_min_tangent_ratio": (1, 3),
        },

        "handler": execute_cast_skill,
    },


    "test_projectile": {
        "id": "test_projectile",
        "name": "Test Projectile",

        "cooldown_ticks": 0,
        "trigger_mode": "held_repeat",

        "blocked_by_motion_tags": {"dash"},
        "blocked_by_action_tags": {
            "cast",
            "channel",
            "recovery",
            "stun",
            "skill_locked",
        },
        "cancels_action_tags": set(),

        "required_components": {"transform"},
        "required_params": {
            "spawn_distance",
            "projectile_speed",
            "projectile_lifetime",
        },
        "allowed_param_values": {},

        "aim": {
            "traditional_source": "mouse_tile",
            "modern_source": "mouse_tile",
            "resolution": "tile_center",
        },
        "cast": {
            "duration": 20,
            "tags": {
                "cast",
                "movement_locked",
                "skill_locked",
            },
            "events": [
                {
                    "tick": 10,
                    "handler": execute_test_projectile,
                },
            ],
        },
        "channel": None,

        "params": {
            "spawn_distance": TILE_UNITS // 4,
            "projectile_speed": TILE_UNITS // 8,
            "projectile_lifetime": 120,
        },

        "handler": execute_cast_skill,
    },


    "spiral_projectile": {
        "id": "spiral_projectile",
        "name": "Spiral Projectile",

        "cooldown_ticks": 0,
        "trigger_mode": "held_repeat",

        "blocked_by_motion_tags": {"dash"},
        "blocked_by_action_tags": {
            "cast",
            "channel",
            "recovery",
            "stun",
            "skill_locked",
        },
        "cancels_action_tags": set(),

        "required_components": {"transform"},
        "required_params": {
            "projectile_lifetime",
            "radius_per_tick",
            "angle_step_fp",
        },
        "allowed_param_values": {},

        "aim": None,
        "cast": {
            "duration": 20,
            "tags": {
                "cast",
                "movement_locked",
                "skill_locked",
            },
            "events": [
                {
                    "tick": 10,
                    "handler": execute_spiral_projectile,
                },
            ],
        },
        "channel": None,

        "params": {
            "projectile_lifetime": 300,
            "radius_per_tick": TILE_UNITS // 32,
            "angle_step_fp": ANGLE_SCALE,
                       },

        "handler": execute_cast_skill,
    },


    "magnet_orb": {
        "id": "magnet_orb",
        "name": "Magnet Orb",

        "cooldown_ticks": 0,
        "trigger_mode": "held_repeat",

        "blocked_by_motion_tags": {"dash"},
        "blocked_by_action_tags": {
            "cast",
            "channel",
            "recovery",
            "stun",
            "skill_locked",
        },
        "cancels_action_tags": set(),

        "required_components": {"transform"},
        "required_params": {
            "placement_search_radius",
            "placement_max_miss_tiles",
            "radius",
            "strength",
            "lifetime",
        },
        "allowed_param_values": {},

        "aim": None,
        "cast": {
            "duration": 60,
            "tags": {
                "cast",
                "movement_locked",
                "skill_locked",
            },
            "events": [
                {
                    "tick": 55,
                    "handler": execute_magnet_orb,
                },
            ],
        },
        "channel": None,

        "params": {
            "placement_search_radius": 2,
            "placement_max_miss_tiles": 2,
            "radius": TILE_UNITS * 10,
            "strength": TILE_UNITS // 24,
            "lifetime": 720,
        },

        "handler": execute_cast_skill,
    },


    "teleport": {
        "id": "teleport",
        "name": "Teleport",

        "cooldown_ticks": 0,
        "trigger_mode": "held_repeat",

        "blocked_by_motion_tags": {"dash"},
        "blocked_by_action_tags": {
            "cast",
            "channel",
            "recovery",
            "stun",
            "skill_locked",
        },
        "cancels_action_tags": set(),

        "required_components": {"transform", "motion_state"},
        "required_params": {
            "target_mode",
            "collision",
            "target_snap_radius_tiles",
            "ray_fallback_max_miss_tiles",
            "ray_fallback_min_progress_tiles",
        },
        "allowed_param_values": {
            "target_mode": {"mouse_tile_center"},
            "collision": {"target_snap_then_ray_fallback"},
        },

        "aim": None,
        "cast": {
            "duration": 20,
            "tags": {
                "cast",
                "movement_locked",
                "skill_locked",
            },
            "events": [
                {
                    "tick": 10,
                    "handler": execute_teleport,
                },
            ],
        },
        "channel": None,

        "params": {
            "target_mode": "mouse_tile_center",
            "collision": "target_snap_then_ray_fallback",
            "target_snap_radius_tiles": 2,
            "ray_fallback_max_miss_tiles": 4,
            "ray_fallback_min_progress_tiles": 1,
        },

        "handler": execute_cast_skill,
    },


    "burst_projectile": {
        "id": "burst_projectile",
        "name": "Burst Projectile",

        "cooldown_ticks": 0,
        "trigger_mode": "held_repeat",

        "blocked_by_motion_tags": {"dash"},
        "blocked_by_action_tags": {
            "cast",
            "channel",
            "recovery",
            "stun",
            "skill_locked",
        },
        "cancels_action_tags": set(),

        "required_components": {"transform", "facing"},
        "required_params": {
            "spawn_distance",
            "projectile_speed",
            "projectile_lifetime",
        },
        "allowed_param_values": {},

        "aim": {
            "traditional_source": "mouse_tile",
            "modern_source": "mouse_tile",
            "resolution": "tile_center",
        },
        "cast": {
            "duration": 30,
            "tags": {
                "cast",
                "movement_locked",
                "skill_locked",
            },
            "events": [
                {
                    "tick": 15,
                    "handler": execute_test_projectile,
                    "params": {
                        "projectile_speed": TILE_UNITS // 8,
                        "aim_offset_steps": -8,
                    },
                },
                {
                    "tick": 15,
                    "handler": execute_test_projectile,
                    "params": {
                        "projectile_speed": TILE_UNITS // 8,
                        "aim_offset_steps": 0,
                    },
                },
                {
                    "tick": 15,
                    "handler": execute_test_projectile,
                    "params": {
                        "projectile_speed": TILE_UNITS // 8,
                        "aim_offset_steps": 8,
                    },
                },
            ],
        },
        "channel": None,

        "params": {
            "spawn_distance": TILE_UNITS // 4,
            "projectile_speed": TILE_UNITS // 8,
            "projectile_lifetime": 300,
            "aim_offset_resolution": 64,
            "aim_offset_distance_scaling": "tighten_with_mouse_distance",
            "aim_offset_near_tiles": 2,
            "aim_offset_far_tiles": 14,
            "aim_offset_far_percent": 10,
        },

        "handler": execute_cast_skill,
    },


    "debug_slash": {
        "id": "debug_slash",
        "name": "Debug Slash",

        "cooldown_ticks": 0,
        "trigger_mode": "held_repeat",

        "blocked_by_motion_tags": {"dash"},
        "blocked_by_action_tags": {
            "cast",
            "channel",
            "recovery",
            "stun",
            "skill_locked",
        },
        "cancels_action_tags": set(),

        "required_components": {"transform", "facing"},
        "required_params": {
            "debug_highlight_ticks",
            "debug_highlight_color",
            "damage",
        },
        "allowed_param_values": {},

        "aim": {
            "traditional_source": "mouse_tile",
            "modern_source": "mouse_tile",
            "resolution": "tile_center",
        },
        "cast": {
            "duration": 44,
            "tags": {
                "cast",
                "movement_locked",
                "skill_locked",
            },
            "phases": [
                {
                    "name": "startup",
                    "start": 0,
                    "end": 18,
                    "tags": {
                        "cast",
                        "movement_locked",
                        "skill_locked",
                    },
                },
                {
                    "name": "release",
                    "start": 18,
                    "end": 26,
                    "tags": {
                        "cast",
                        "movement_locked",
                        "skill_locked",
                    },
                },
                {
                    "name": "recovery",
                    "start": 26,
                    "end": 44,
                    "tags": {
                        "recovery",
                        "skill_locked",
                    },
                },
            ],
            "events": [
                {
                    "tick": 22,
                    "handler": execute_debug_slash,
                },
            ],
        },
        "channel": None,

        "params": {
            "debug_highlight_ticks": 12,
            "debug_highlight_color": "yellow",
            "damage": 1,
        },

        "handler": execute_cast_skill,
    },


    "debug_channel_projectile": {
        "id": "debug_channel_projectile",
        "name": "Debug Channel Projectile",

        "cooldown_ticks": 0,
        "trigger_mode": "held_repeat",

        "blocked_by_motion_tags": {"dash"},
        "blocked_by_action_tags": {
            "cast",
            "channel",
            "recovery",
            "stun",
            "skill_locked",
        },
        "cancels_action_tags": set(),

        "required_components": {"transform", "facing"},
        "required_params": {
            "spawn_distance",
            "projectile_speed",
            "projectile_lifetime",
        },
        "allowed_param_values": {},

        "aim": {
            "traditional_source": "mouse_tile",
            "modern_source": "mouse_tile",
            "resolution": "tile_center",
        },
        "cast": None,
        "channel": {
            "duration": 600,
            "min_duration": 20,
            "ends_on_release": True,
            "tags": {
                "channel",
                "movement_locked",
                "skill_locked",
            },
            "phases": [
                {
                    "name": "startup",
                    "start": 0,
                    "end": 20,
                    "tags": {
                        "channel",
                        "movement_locked",
                        "skill_locked",
                    },
                },
                {
                    "name": "channel",
                    "start": 20,
                    "end": 600,
                    "tags": {
                        "channel",
                        "movement_locked",
                        "skill_locked",
                    },
                },
            ],
            "events": [],
            "repeat_events": [
                {
                    "start_tick": 20,
                    "interval": 7,
                    "handler": execute_test_projectile,
                    "params": {
                        "aim_timing": "live",
                    },
                },
            ],
        },

        "params": {
            "spawn_distance": TILE_UNITS // 4,
            "projectile_speed": TILE_UNITS // 8,
            "projectile_lifetime": 90,
        },

        "handler": execute_channel_skill,
    },
}


def validate_skill_defs(skill_defs):
    for skill_id, skill_def in skill_defs.items():
        missing_fields = REQUIRED_SKILL_FIELDS - set(skill_def)

        if missing_fields:
            raise ValueError(
                f"Skill '{skill_id}' is missing required fields: "
                f"{sorted(missing_fields)}"
            )

        extra_id = skill_def["id"]

        if extra_id != skill_id:
            raise ValueError(
                f"Skill key '{skill_id}' does not match skill id '{extra_id}'"
            )

        if skill_def["trigger_mode"] not in ALLOWED_TRIGGER_MODES:
            raise ValueError(
                f"Skill '{skill_id}' has invalid trigger_mode: "
                f"{skill_def['trigger_mode']}"
            )

        if not isinstance(skill_def["blocked_by_motion_tags"], set):
            raise ValueError(
                f"Skill '{skill_id}' blocked_by_motion_tags must be a set"
            )

        if not isinstance(skill_def["blocked_by_action_tags"], set):
            raise ValueError(
                f"Skill '{skill_id}' blocked_by_action_tags must be a set"
            )

        if not isinstance(skill_def["cancels_action_tags"], set):
            raise ValueError(
                f"Skill '{skill_id}' cancels_action_tags must be a set"
            )

        if not isinstance(skill_def["required_components"], set):
            raise ValueError(
                f"Skill '{skill_id}' required_components must be a set"
            )

        if not isinstance(skill_def["required_params"], set):
            raise ValueError(
                f"Skill '{skill_id}' required_params must be a set"
            )

        if not isinstance(skill_def["allowed_param_values"], dict):
            raise ValueError(
                f"Skill '{skill_id}' allowed_param_values must be a dict"
            )

        if not isinstance(skill_def["params"], dict):
            raise ValueError(
                f"Skill '{skill_id}' params must be a dict"
            )

        missing_params = (
            skill_def["required_params"]
            - set(skill_def["params"])
        )

        if missing_params:
            raise ValueError(
                f"Skill '{skill_id}' is missing params: "
                f"{sorted(missing_params)}"
            )

        validate_aim_timing_param(
            skill_id,
            "params",
            skill_def["params"],
        )

        validate_aim_modifier_params(
            skill_id,
            "params",
            skill_def["params"],
        )

        validate_aim_offset_distance_scaling_params(
            skill_id,
            "params",
            skill_def["params"],
        )

        for param_name, allowed_values in skill_def["allowed_param_values"].items():
            if param_name not in skill_def["params"]:
                raise ValueError(
                    f"Skill '{skill_id}' has allowed values for unknown param "
                    f"'{param_name}'"
                )

            if not isinstance(allowed_values, set):
                raise ValueError(
                    f"Skill '{skill_id}' allowed_param_values['{param_name}'] "
                    f"must be a set"
                )

            actual_value = skill_def["params"][param_name]

            if actual_value not in allowed_values:
                raise ValueError(
                    f"Skill '{skill_id}' param '{param_name}' has invalid "
                    f"value {actual_value!r}; allowed values are "
                    f"{sorted(allowed_values)}"
                )

        if skill_def["aim"] is not None:
            validate_skill_aim(skill_id, skill_def["aim"])

        if skill_def["cast"] is not None:
            validate_skill_cast(skill_id, skill_def["cast"])

        if skill_def["channel"] is not None:
            validate_skill_channel(skill_id, skill_def["channel"])

        if not callable(skill_def["handler"]):
            raise ValueError(
                f"Skill '{skill_id}' handler is not callable"
            )


def validate_skill_aim(skill_id, aim):
    if not isinstance(aim, dict):
        raise ValueError(
            f"Skill '{skill_id}' aim must be None or a dict"
        )

    required_aim_fields = {
        "traditional_source",
        "modern_source",
        "resolution",
    }

    missing_aim_fields = required_aim_fields - set(aim)

    if missing_aim_fields:
        raise ValueError(
            f"Skill '{skill_id}' aim is missing fields: "
            f"{sorted(missing_aim_fields)}"
        )


def validate_aim_timing_param(skill_id, source_name, params):
    if "aim_timing" not in params:
        return

    if params["aim_timing"] not in ALLOWED_AIM_TIMINGS:
        raise ValueError(
            f"Skill '{skill_id}' {source_name} has invalid aim_timing: "
            f"{params['aim_timing']!r}"
        )


def validate_aim_modifier_params(skill_id, source_name, params):
    if "aim_offset_steps" in params:
        if not isinstance(params["aim_offset_steps"], int):
            raise ValueError(
                f"Skill '{skill_id}' {source_name} aim_offset_steps "
                f"must be an int"
            )

    if "aim_offset_resolution" in params:
        if params["aim_offset_resolution"] not in AIM_LUT_SIZES:
            raise ValueError(
                f"Skill '{skill_id}' {source_name} has invalid "
                f"aim_offset_resolution: {params['aim_offset_resolution']!r}"
            )


def validate_aim_offset_distance_scaling_params(
    skill_id,
    source_name,
    params,
):
    scaling_mode = params.get(
        "aim_offset_distance_scaling",
        "none",
    )

    if scaling_mode not in ALLOWED_AIM_OFFSET_DISTANCE_SCALING:
        raise ValueError(
            f"Skill '{skill_id}' {source_name} has invalid "
            f"aim_offset_distance_scaling: {scaling_mode!r}"
        )

    for field_name in (
        "aim_offset_near_tiles",
        "aim_offset_far_tiles",
        "aim_offset_far_percent",
    ):
        if field_name not in params:
            continue

        if not isinstance(params[field_name], int):
            raise ValueError(
                f"Skill '{skill_id}' {source_name} {field_name} "
                f"must be an int"
            )

    if params.get("aim_offset_far_percent", 0) < 0:
        raise ValueError(
            f"Skill '{skill_id}' {source_name} "
            f"aim_offset_far_percent cannot be negative"
        )


def validate_skill_cast(skill_id, cast):
    if not isinstance(cast, dict):
        raise ValueError(
            f"Skill '{skill_id}' cast must be None or a dict"
        )

    required_cast_fields = {
        "duration",
        "tags",
        "events",
    }

    missing_cast_fields = required_cast_fields - set(cast)

    if missing_cast_fields:
        raise ValueError(
            f"Skill '{skill_id}' cast is missing fields: "
            f"{sorted(missing_cast_fields)}"
        )

    if not isinstance(cast["duration"], int):
        raise ValueError(
            f"Skill '{skill_id}' cast duration must be an int"
        )

    if cast["duration"] < 0:
        raise ValueError(
            f"Skill '{skill_id}' cast duration cannot be negative"
        )

    if not isinstance(cast["tags"], set):
        raise ValueError(
            f"Skill '{skill_id}' cast tags must be a set"
        )

    if not isinstance(cast["events"], list):
        raise ValueError(
            f"Skill '{skill_id}' cast events must be a list"
        )

    for event_index, event in enumerate(cast["events"]):
        validate_skill_cast_event(
            skill_id,
            cast,
            event_index,
            event,
        )

    if "phases" in cast:
        if not isinstance(cast["phases"], list):
            raise ValueError(
                f"Skill '{skill_id}' cast phases must be a list"
            )

        for phase_index, phase in enumerate(cast["phases"]):
            validate_skill_cast_phase(
                skill_id,
                cast,
                phase_index,
                phase,
            )


def validate_skill_channel(skill_id, channel):
    if not isinstance(channel, dict):
        raise ValueError(
            f"Skill '{skill_id}' channel must be None or a dict"
        )

    required_channel_fields = {
        "duration",
        "min_duration",
        "ends_on_release",
        "tags",
        "events",
        "repeat_events",
    }

    missing_channel_fields = required_channel_fields - set(channel)

    if missing_channel_fields:
        raise ValueError(
            f"Skill '{skill_id}' channel is missing fields: "
            f"{sorted(missing_channel_fields)}"
        )

    if not isinstance(channel["duration"], int):
        raise ValueError(
            f"Skill '{skill_id}' channel duration must be an int"
        )

    if channel["duration"] <= 0:
        raise ValueError(
            f"Skill '{skill_id}' channel duration must be positive"
        )

    if not isinstance(channel["min_duration"], int):
        raise ValueError(
            f"Skill '{skill_id}' channel min_duration must be an int"
        )

    if channel["min_duration"] < 0:
        raise ValueError(
            f"Skill '{skill_id}' channel min_duration cannot be negative"
        )

    if channel["min_duration"] > channel["duration"]:
        raise ValueError(
            f"Skill '{skill_id}' channel min_duration cannot exceed duration"
        )

    if not isinstance(channel["ends_on_release"], bool):
        raise ValueError(
            f"Skill '{skill_id}' channel ends_on_release must be a bool"
        )

    if not isinstance(channel["tags"], set):
        raise ValueError(
            f"Skill '{skill_id}' channel tags must be a set"
        )

    if not isinstance(channel["events"], list):
        raise ValueError(
            f"Skill '{skill_id}' channel events must be a list"
        )

    for event_index, event in enumerate(channel["events"]):
        validate_skill_cast_event(
            skill_id,
            channel,
            event_index,
            event,
        )

    if not isinstance(channel["repeat_events"], list):
        raise ValueError(
            f"Skill '{skill_id}' channel repeat_events must be a list"
        )

    for event_index, event in enumerate(channel["repeat_events"]):
        validate_skill_repeat_event(
            skill_id,
            channel,
            event_index,
            event,
        )

    if "phases" in channel:
        if not isinstance(channel["phases"], list):
            raise ValueError(
                f"Skill '{skill_id}' channel phases must be a list"
            )

        for phase_index, phase in enumerate(channel["phases"]):
            validate_skill_cast_phase(
                skill_id,
                channel,
                phase_index,
                phase,
            )


def validate_skill_repeat_event(skill_id, action_def, event_index, event):
    if not isinstance(event, dict):
        raise ValueError(
            f"Skill '{skill_id}' repeat event {event_index} must be a dict"
        )

    required_event_fields = {
        "start_tick",
        "interval",
        "handler",
    }

    missing_event_fields = required_event_fields - set(event)

    if missing_event_fields:
        raise ValueError(
            f"Skill '{skill_id}' repeat event {event_index} "
            f"is missing fields: {sorted(missing_event_fields)}"
        )

    if not isinstance(event["start_tick"], int):
        raise ValueError(
            f"Skill '{skill_id}' repeat event {event_index} "
            f"start_tick must be an int"
        )

    if event["start_tick"] < 0:
        raise ValueError(
            f"Skill '{skill_id}' repeat event {event_index} "
            f"start_tick cannot be negative"
        )

    if event["start_tick"] > action_def["duration"]:
        raise ValueError(
            f"Skill '{skill_id}' repeat event {event_index} "
            f"starts after action duration"
        )

    if not isinstance(event["interval"], int):
        raise ValueError(
            f"Skill '{skill_id}' repeat event {event_index} "
            f"interval must be an int"
        )

    if event["interval"] <= 0:
        raise ValueError(
            f"Skill '{skill_id}' repeat event {event_index} "
            f"interval must be positive"
        )

    if not callable(event["handler"]):
        raise ValueError(
            f"Skill '{skill_id}' repeat event {event_index} "
            f"handler is not callable"
        )

    if "params" in event and not isinstance(event["params"], dict):
        raise ValueError(
            f"Skill '{skill_id}' repeat event {event_index} "
            f"params must be a dict"
        )

    validate_aim_timing_param(
        skill_id,
        f"repeat event {event_index} params",
        event.get("params", {}),
    )

    validate_aim_modifier_params(
        skill_id,
        f"repeat event {event_index} params",
        event.get("params", {}),
    )

    validate_aim_offset_distance_scaling_params(
        skill_id,
        f"repeat event {event_index} params",
        event.get("params", {}),
    )


def validate_skill_cast_event(skill_id, cast, event_index, event):
    if not isinstance(event, dict):
        raise ValueError(
            f"Skill '{skill_id}' cast event {event_index} must be a dict"
        )

    required_event_fields = {
        "tick",
        "handler",
    }

    missing_event_fields = required_event_fields - set(event)

    if missing_event_fields:
        raise ValueError(
            f"Skill '{skill_id}' cast event {event_index} "
            f"is missing fields: {sorted(missing_event_fields)}"
        )

    if not isinstance(event["tick"], int):
        raise ValueError(
            f"Skill '{skill_id}' cast event {event_index} "
            f"tick must be an int"
        )

    if event["tick"] < 0:
        raise ValueError(
            f"Skill '{skill_id}' cast event {event_index} "
            f"tick cannot be negative"
        )

    if event["tick"] > cast["duration"]:
        raise ValueError(
            f"Skill '{skill_id}' cast event {event_index} "
            f"fires after cast duration"
        )

    if not callable(event["handler"]):
        raise ValueError(
            f"Skill '{skill_id}' cast event {event_index} "
            f"handler is not callable"
        )

    if "params" in event and not isinstance(event["params"], dict):
        raise ValueError(
            f"Skill '{skill_id}' cast event {event_index} "
            f"params must be a dict"
        )

    validate_aim_timing_param(
        skill_id,
        f"cast event {event_index} params",
        event.get("params", {}),
    )

    validate_aim_modifier_params(
        skill_id,
        f"cast event {event_index} params",
        event.get("params", {}),
    )

    validate_aim_offset_distance_scaling_params(
        skill_id,
        f"cast event {event_index} params",
        event.get("params", {}),
    )


def validate_skill_cast_phase(skill_id, cast, phase_index, phase):
    if not isinstance(phase, dict):
        raise ValueError(
            f"Skill '{skill_id}' cast phase {phase_index} must be a dict"
        )

    required_phase_fields = {
        "name",
        "start",
        "end",
        "tags",
    }

    missing_phase_fields = required_phase_fields - set(phase)

    if missing_phase_fields:
        raise ValueError(
            f"Skill '{skill_id}' cast phase {phase_index} "
            f"is missing fields: {sorted(missing_phase_fields)}"
        )

    if not isinstance(phase["name"], str):
        raise ValueError(
            f"Skill '{skill_id}' cast phase {phase_index} "
            f"name must be a string"
        )

    if not isinstance(phase["start"], int):
        raise ValueError(
            f"Skill '{skill_id}' cast phase {phase_index} "
            f"start must be an int"
        )

    if not isinstance(phase["end"], int):
        raise ValueError(
            f"Skill '{skill_id}' cast phase {phase_index} "
            f"end must be an int"
        )

    if phase["start"] < 0:
        raise ValueError(
            f"Skill '{skill_id}' cast phase {phase_index} "
            f"start cannot be negative"
        )

    if phase["end"] <= phase["start"]:
        raise ValueError(
            f"Skill '{skill_id}' cast phase {phase_index} "
            f"end must be greater than start"
        )

    if phase["end"] > cast["duration"]:
        raise ValueError(
            f"Skill '{skill_id}' cast phase {phase_index} "
            f"ends after cast duration"
        )

    if not isinstance(phase["tags"], set):
        raise ValueError(
            f"Skill '{skill_id}' cast phase {phase_index} "
            f"tags must be a set"
        )