from placement_utils import find_nearest_valid_placement_tile
from support import (
    ANGLE_SCALE,
    TILE_UNITS,
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
from action_ops import start_action_state
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


def execute_cast_skill(world, caster, context):
    from action_ops import start_action_state

    skill_def = context["skill_def"]
    intent = context["intent"]
    cast = skill_def["cast"]

    events = []

    for event_def in cast.get("events", []):
        events.append({
            "tick": event_def["tick"],
            "handler": event_def["handler"],
            "params": dict(event_def.get("params", {})),
            "fired": False,
        })

    start_action_state(
        world,
        caster,
        {
            "type": "cast",
            "skill_id": skill_def["id"],
            "tags": set(cast["tags"]),
            "age": 0,
            "duration": cast["duration"],
            "intent": dict(intent),
            "skill_def": skill_def,
            "events": events,
        },
    )

    return True


def execute_dash(world, caster, context):
    skill_def = context["skill_def"]
    intent = context["intent"]
    params = context["params"]

    aim_vector = resolve_skill_aim_vector(
        world,
        caster,
        intent,
        skill_def,
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
    skill_def = context["skill_def"]
    intent = context["intent"]
    params = context["params"]

    caster_cpos = world.transform[caster].cpos

    aim_vector = resolve_skill_aim_vector(
        world,
        caster,
        intent,
        skill_def,
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
    skill_def = context["skill_def"]
    intent = context["intent"]
    params = context["params"]

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
    intent = context["intent"]

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

    "params",

    "handler",
}

ALLOWED_TRIGGER_MODES = {
    "press",
    "held_repeat",
}


SKILL_DEFS = {

    "dash": {
        "id": "dash",
        "name": "Dash",

        "cooldown_ticks": 0,
        "trigger_mode": "held_repeat",

        "blocked_by_motion_tags": {"dash"},
        "blocked_by_action_tags": {"stun", "uninterruptable", "dash_windup"},
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

        "params": {
            "duration": 15,
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
        "trigger_mode": "press",

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
                        "projectile_speed": TILE_UNITS // 16,
                    },
                },
                {
                    "tick": 20,
                    "handler": execute_test_projectile,
                    "params": {
                        "projectile_speed": TILE_UNITS // 12,
                    },
                },
                {
                    "tick": 25,
                    "handler": execute_test_projectile,
                    "params": {
                        "projectile_speed": TILE_UNITS // 8,
                    },
                },
            ],
        },

        "params": {
            "spawn_distance": TILE_UNITS // 4,
            "projectile_speed": TILE_UNITS // 8,
            "projectile_lifetime": 120,
        },

        "handler": execute_cast_skill,
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