from support import scale_dir, ANGLE_SCALE, DashController
from settings import TILE_UNITS
from camera_utils import (
    internal_screen_to_world_tile,
    snap_camera_to_entity_now,
)
from motion_ops import teleport_entity_to_tile
from teleport_utils import resolve_path_tolerant_teleport_tile
from spawners import (
    spawn_test_projectile,
    spawn_spiral_projectile,
    spawn_magnet_orb,
)

def execute_dash(world, caster, intent, skill_def):
    direction = world.facing[caster]
    motion_state = world.motion_state[caster]

    params = skill_def["params"]

    motion_state["controller"] = DashController(
        direction=direction,
        age=0,
        duration=params["duration"],
        distance=params["distance"],
    )

    motion_state["influence_mode"] = params["influence_mode"]

    return True

def execute_test_projectile(world, caster, intent, skill_def):
    caster_cpos = world.transform[caster].cpos
    direction = world.facing[caster]

    params = skill_def.get("params", {})
    spawn_distance = params.get("spawn_distance", TILE_UNITS // 4)

    spawn_offset = scale_dir(direction, spawn_distance)
    spawn_cpos = caster_cpos + spawn_offset

    eid = spawn_test_projectile(
        world,
        spawn_cpos,
        direction,
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
    caster_cpos = world.transform[caster].cpos
    direction = world.facing[caster]

    params = skill_def.get("params", {})

    spawn_distance = params.get("spawn_distance", TILE_UNITS * 2)
    spawn_offset = scale_dir(direction, spawn_distance)
    spawn_cpos = caster_cpos + spawn_offset

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

SKILL_DEFS = {

    "dash": {
        "id": "dash",
        "name": "Dash",
        "cooldown_ticks": 40,
        "trigger_mode": "held_repeat",
        "required_components": {"transform", "motion_state", "facing"},
        "required_params": {
            "duration",
            "distance",
            "influence_mode",
        },
        "params": {
            "duration": 8,
            "distance": TILE_UNITS * 5,
            "influence_mode": "ignore_all",
        },
        "handler": execute_dash,
    },

    "test_projectile": {
        "id": "test_projectile",
        "name": "Test Projectile",
        "cooldown_ticks": 12,
        "trigger_mode": "held_repeat",
        "required_components": {"transform", "facing"},
        "required_params": {
            "spawn_distance",
            "projectile_speed",
            "projectile_lifetime",
        },
        "params": {
            "spawn_distance": TILE_UNITS // 4,
            "projectile_speed": TILE_UNITS // 8,
            "projectile_lifetime": 120,
        },
        "handler": execute_test_projectile,
    },

    "spiral_projectile": {
        "id": "spiral_projectile",
        "name": "Spiral Projectile",
        "cooldown_ticks": 30,
        "trigger_mode": "held_repeat",
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
        "required_components": {"transform", "facing"},
        "required_params": {
            "spawn_distance",
            "radius",
            "strength",
            "lifetime",
        },
        "params": {
            "spawn_distance": TILE_UNITS,
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
        "trigger_mode": "press",
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