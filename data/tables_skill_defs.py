from constants import TILE_UNITS, ANGLE_SCALE
from skill_loader import load_external_skill_defs


PYTHON_SKILL_DEFS = {

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
            "spawn_angle_step_offset",
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
                    "handler": "execute_spiral_projectile",
                    "params":{
                        "spawn_angle_step_offset": 0,
                    }
                },
                {
                    "tick": 10,
                    "handler": "execute_spiral_projectile",
                    "params":{
                        "spawn_angle_step_offset": 32,
                    }
                },
            ],
        },
        "channel": None,

        "params": {
            "projectile_lifetime": 300,
            "radius_per_tick": TILE_UNITS // 32,
            "angle_step_fp": ANGLE_SCALE,
            "spawn_angle_step_offset": 0,
                       },

        "handler": "execute_cast_skill",
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
                    "handler": "execute_magnet_orb",
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

        "handler": "execute_cast_skill",
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
                    "handler": "execute_debug_slash",
                },
            ],
        },
        "channel": None,

        "params": {
            "debug_highlight_ticks": 12,
            "debug_highlight_color": "yellow",
            "damage": 1,
        },

        "handler": "execute_cast_skill",
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
                    "handler": "execute_test_projectile",
                    "params": {
                        "aim_timing": "live",
                    },
                },
            ],
        },

        "params": {
            "spawn_distance": TILE_UNITS // 4,
            "projectile_speed": TILE_UNITS // 8,
            "projectile_lifetime": 300,
        },

        "handler": "execute_channel_skill",
    },


    "guard_counter": {
        "id": "guard_counter",
        "name": "Guard Counter",

        "cooldown_ticks": 0,
        "trigger_mode": "held_repeat",

        "blocked_by_motion_tags": {"dash"},
        "blocked_by_action_tags": {
            "cast",
            "channel",
            "recovery",
            "guard_counter",
            "counter_attack",
            "stun",
            "skill_locked",
        },
        "cancels_action_tags": set(),

        "required_components": {"transform", "facing"},
        "required_params": set(),
        "allowed_param_values": {},

        "aim": None,
        "cast": {
            "type": "guard_counter",
            "duration": 55,
            "tags": {
                "cast",
                "guard_counter",
                "movement_locked",
                "skill_locked",
            },
            "phases": [
                {
                    "name": "startup",
                    "start": 0,
                    "end": 5,
                    "tags": {
                        "guard_counter",
                        "movement_locked",
                        "skill_locked",
                    },
                },
                {
                    "name": "counter_ready",
                    "start": 5,
                    "end": 40,
                    "tags": {
                        "guard_counter",
                        "counter_ready",
                        "movement_locked",
                        "skill_locked",
                    },
                },
                {
                    "name": "recovery",
                    "start": 40,
                    "end": 55,
                    "tags": {
                        "recovery",
                        "movement_locked",
                        "skill_locked",
                    },
                },
            ],
            "events": [],
        },
        "channel": None,

        "params": {},

        "handler": "execute_cast_skill",
    },


    "counter_attack": {
        "id": "counter_attack",
        "name": "Counter Attack",

        "cooldown_ticks": 0,
        "trigger_mode": "press",

        "blocked_by_motion_tags": set(),
        "blocked_by_action_tags": set(),
        "cancels_action_tags": set(),

        "required_components": {"transform", "facing"},
        "required_params": {
            "damage",
            "range_tiles",
            "debug_highlight_ticks",
            "debug_highlight_color",
        },
        "allowed_param_values": {},

        "aim": None,
        "cast": {
            "type": "counter_attack",
            "duration": 20,
            "tags": {
                "counter_attack",
                "movement_locked",
                "skill_locked",
            },
            "phases": [
                {
                    "name": "startup",
                    "start": 0,
                    "end": 4,
                    "tags": {
                        "counter_attack",
                        "movement_locked",
                        "skill_locked",
                    },
                },
                {
                    "name": "release",
                    "start": 4,
                    "end": 10,
                    "tags": {
                        "counter_attack",
                        "movement_locked",
                        "skill_locked",
                    },
                },
                {
                    "name": "recovery",
                    "start": 10,
                    "end": 20,
                    "tags": {
                        "recovery",
                        "movement_locked",
                        "skill_locked",
                    },
                },
            ],
            "events": [
                {
                    "tick": 4,
                    "handler": "execute_counter_slash",
                },
            ],
        },
        "channel": None,

        "params": {
            "damage": 2,
            "range_tiles": 2,
            "debug_highlight_ticks": 12,
            "debug_highlight_color": "orange",
        },

        "handler": "execute_cast_skill",
    },


    "meteor": {
        "id": "meteor",
        "name": "Meteor",

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
            "radius_tiles",
            "damage",
            "impact_tick",
            "lifetime",
        },
        "allowed_param_values": {},

        "aim": None,
        "cast": {
            "type": "cast",
            "duration": 35,
            "tags": {
                "cast",
                "movement_locked",
                "skill_locked",
            },
            "phases": [
                {
                    "name": "startup",
                    "start": 0,
                    "end": 20,
                    "tags": {
                        "cast",
                        "movement_locked",
                        "skill_locked",
                    },
                },
                {
                    "name": "release",
                    "start": 20,
                    "end": 30,
                    "tags": {
                        "cast",
                        "movement_locked",
                        "skill_locked",
                    },
                },
                {
                    "name": "recovery",
                    "start": 30,
                    "end": 35,
                    "tags": {
                        "recovery",
                        "skill_locked",
                    },
                },
            ],
            "events": [
                {
                    "tick": 24,
                    "handler": "execute_meteor",
                },
            ],
        },
        "channel": None,

        "params": {
            "placement_search_radius": 2,
            "placement_max_miss_tiles": 2,
            "radius_tiles": 2,
            "damage": 3,
            "impact_tick": 75,
            "lifetime": 20,
        },

        "handler": "execute_cast_skill",
    },
}

EXTERNAL_SKILL_DEFS = load_external_skill_defs()

DUPLICATE_SKILL_IDS = (
    set(PYTHON_SKILL_DEFS)
    & set(EXTERNAL_SKILL_DEFS)
)

if DUPLICATE_SKILL_IDS:
    raise ValueError(
        f"Duplicate skill ids defined in Python and external data: "
        f"{sorted(DUPLICATE_SKILL_IDS)}"
    )

SKILL_DEFS = {
    **PYTHON_SKILL_DEFS,
    **EXTERNAL_SKILL_DEFS,
}