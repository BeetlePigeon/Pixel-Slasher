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


def execute_cast_skill(world, caster, intent, skill_def):
    cast = skill_def["cast"]

    events = []

    for event_def in cast.get("events", []):
        events.append({
            "tick": event_def["tick"],
            "handler": event_def["handler"],
            "intent": dict(intent),
            "skill_def": skill_def,
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
            "events": events,
        },
    )

    return True

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


def execute_dash(world, caster, intent, skill_def):
    aim_vector = resolve_skill_aim_vector(
        world,
        caster,
        intent,
        skill_def,
    )

    motion_state = world.motion_state[caster]
    params = skill_def["params"]

    motion_state["controller"] = DashController(
        aim_vector=aim_vector,
        age=0,
        duration=params["duration"],
        distance=params["distance"],
        slide_min_tangent_ratio=params["slide_min_tangent_ratio"],
    )

    motion_state["influence_mode"] = params["influence_mode"]

    return True


def execute_test_projectile(world, caster, intent, skill_def):
    caster_cpos = world.transform[caster].cpos

    aim_vector = resolve_skill_aim_vector(
        world,
        caster,
        intent,
        skill_def,
    )

    params = skill_def["params"]
    spawn_distance = params["spawn_distance"]

    spawn_offset = scale_normalized_dir(
        aim_vector,
        spawn_distance,
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


def execute_spiral_projectile(world, caster, intent, skill_def):
    caster_cpos = world.transform[caster].cpos

    params = skill_def.get("params", {})

    eid = spawn_spiral_projectile(
        world,
        caster_cpos,
        lifetime_ticks=params["projectile_lifetime"],
        radius_per_tick=params["radius_per_tick"],
        angle_step_fp=params["angle_step_fp"],
    )

    return eid is not None

def execute_magnet_orb(world, caster, intent, skill_def):
    mouse_pos = intent.get("mouse_pos")

    if mouse_pos is None:
        return False

    params = skill_def["params"]

    target_tile = internal_screen_to_world_tile(
        world,
        mouse_pos,
    )

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


def execute_teleport(world, caster, intent, skill_def):
    params = skill_def["params"]

    mouse_pos = intent.get("mouse_pos")

    if mouse_pos is None:
        return False

    transform = world.transform[caster]

    start_tile = transform.tile
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


def execute_test_cast_lock(world, caster, intent, skill_def):
    def debug_action_event(world, caster, intent, skill_def):
        print("DEBUG ACTION EVENT FIRED", world.tick)
        return True

    params = skill_def["params"]

    start_action_state(
        world,
        caster,
        {
            "type": "cast",
            "skill_id": skill_def["id"],
            "tags": {
                "cast",
                "movement_locked",
                "skill_locked",
            },
            "age": 0,
            "duration": params["duration"],
            "events": [
                {
                    "tick": 20,
                    "handler": debug_action_event,
                    "intent": dict(intent),
                    "skill_def": skill_def,
                    "fired": False,
                },
            ],
        },
    )

    return True


SKILL_DEFS = {

    "dash": {
        "id": "dash",
        "name": "Dash",
        "cooldown_ticks": 40,
        "trigger_mode": "held_repeat",
        "blocked_by_motion_tags": {"dash"},
        "required_components": {"transform", "motion_state", "facing"},
        "required_params": {
            "duration",
            "distance",
            "influence_mode",
            "slide_min_tangent_ratio",
        },
        "allowed_param_values": {
            "influence_mode": {"normal", "ignore_all"},
        },
        "aim": {
            "traditional_source": "mouse",
            "modern_source": "setting:modern_movement_skill_aim_source",
            "resolution": "setting:movement_skill_aim_resolution",
        },
        "params": {
            "duration": 18,
            "distance": TILE_UNITS * 7,
            "influence_mode": "ignore_all",
            "slide_min_tangent_ratio": (1, 3),
        },
        "handler": execute_dash,
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
        "required_components": {"transform"},
        "required_params": {
            "spawn_distance",
            "projectile_speed",
            "projectile_lifetime",
        },
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
        "cooldown_ticks": 30,
        "trigger_mode": "held_repeat",
        "blocked_by_motion_tags": {"dash"},
        "clears_move_target_on_success": True,
        "required_components": {"transform"},
        "required_params": {
            "projectile_lifetime",
            "radius_per_tick",
            "angle_step_fp",
        },
        "params": {
            "projectile_lifetime": 180,
            "radius_per_tick": TILE_UNITS // 32,
            "angle_step_fp": ANGLE_SCALE,
                       },
        "handler": execute_spiral_projectile,
    },

    "magnet_orb": {
        "id": "magnet_orb",
        "name": "Magnet Orb",
        "cooldown_ticks": 60,
        "trigger_mode": "held_repeat",
        "blocked_by_motion_tags": {"dash"},
        "required_components": {"transform"},
        "required_params": {
            "placement_search_radius",
            "placement_max_miss_tiles",
            "radius",
            "strength",
            "lifetime",
        },
        "params": {
            "placement_search_radius": 2,
            "placement_max_miss_tiles": 2,
            "radius": TILE_UNITS * 10,
            "strength": TILE_UNITS // 24,
            "lifetime": 600,
        },
        "handler": execute_magnet_orb,
    },

    "teleport": {
        "id": "teleport",
        "name": "Teleport",
        "cooldown_ticks": 30,
        "trigger_mode": "held_repeat",
        "blocked_by_motion_tags": {"dash"},
        "blocked_by_action_tags": {
            "cast",
            "channel",
            "recovery",
            "stun",
            "skill_locked",
        },
        "clears_move_target_on_success": True,
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
        "params": {
            "target_mode": "mouse_tile_center",
            "collision": "target_snap_then_ray_fallback",
            "target_snap_radius_tiles": 2,
            "ray_fallback_max_miss_tiles": 4,
            "ray_fallback_min_progress_tiles": 1,
        },
        "handler": execute_teleport,
    },
    "test_cast_lock": {
        "id": "test_cast_lock",
        "name": "Test Cast Lock",
        "cooldown_ticks": 90,
        "trigger_mode": "press",
        "blocked_by_motion_tags": {"dash"},
        "blocked_by_action_tags": {
            "cast",
            "channel",
            "recovery",
            "stun",
            "skill_locked",
        },
        "required_components": {"transform"},
        "required_params": {
            "duration",
        },
        "params": {
            "duration": 120,
        },
        "handler": execute_test_cast_lock,
    },
}

def validate_skill_defs():
    for skill_id, skill_def in SKILL_DEFS.items():
        if skill_def.get("id") != skill_id:
            raise ValueError(
                f"Skill definition key '{skill_id}' does not match skill id "
                f"'{skill_def.get('id')}'"
            )

        required_top_level = {
            "id",
            "name",
            "cooldown_ticks",
            "trigger_mode",
            "blocked_by_motion_tags",
            "required_components",
            "required_params",
            "params",
            "handler",
        }

        missing_top_level = required_top_level - set(skill_def)

        if missing_top_level:
            raise ValueError(
                f"Skill '{skill_id}' is missing top-level fields: "
                f"{sorted(missing_top_level)}"
            )

        if not isinstance(skill_def["blocked_by_motion_tags"], set):
            raise ValueError(
                f"Skill '{skill_id}' blocked_by_motion_tags must be a set"
            )

        valid_trigger_modes = {"press", "held_repeat"}

        if skill_def["trigger_mode"] not in valid_trigger_modes:
            raise ValueError(
                f"Skill '{skill_id}' has invalid trigger_mode: "
                f"{skill_def['trigger_mode']}"
            )

        if not callable(skill_def["handler"]):
            raise ValueError(
                f"Skill '{skill_id}' handler is not callable"
            )

        required_params = skill_def["required_params"]
        params = skill_def["params"]

        missing_params = required_params - set(params)

        if missing_params:
            raise ValueError(
                f"Skill '{skill_id}' is missing params: "
                f"{sorted(missing_params)}"
            )

        allowed_param_values = skill_def.get("allowed_param_values", {})

        for param_name, allowed_values in allowed_param_values.items():
            if param_name not in params:
                raise ValueError(
                    f"Skill '{skill_id}' has allowed values for missing param "
                    f"'{param_name}'"
                )

            if params[param_name] not in allowed_values:
                raise ValueError(
                    f"Skill '{skill_id}' param '{param_name}' has invalid value "
                    f"'{params[param_name]}'. Expected one of {sorted(allowed_values)}"
                )

        if skill_def["cooldown_ticks"] < 0:
            raise ValueError(
                f"Skill '{skill_id}' has negative cooldown_ticks"
            )