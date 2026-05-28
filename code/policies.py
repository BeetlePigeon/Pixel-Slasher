DIRECTIONAL_MOVEMENT_MODE = "continuous"
SETTLE_LOCKED_TAG = "settle_locked"
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

MOVEMENT_CANCELING_ACTION_TAGS = {
    "movement_locked",
    "stun",
    "root",
}

PATH_POLICIES = {
    "traditional_click_move": {
        "max_expansions": 300,
        "max_path_length": 30,
        "smooth_max_path_length": 28,
        "target_snap_radius": 2,
        # While LMB is held, allow the active path to refresh periodically.
        # 15 ticks = 0.25 seconds at 60 sim FPS.
        "refresh_ticks": 10,
        # If a path query fails, don't retry the same start/target immediately
        # while the mouse is still held.
        "failed_retry_ticks": 30,

        "stall_ticks_before_repath": 10,
        "repath_cooldown_ticks": 12,
        "max_repath_attempts": 4,
        "max_follow_ticks": 340,
        "progress_min_cpos": 256,   # Change back to 128 maybe

        "direct_fallback_on_fail": True,
        "direct_fallback_max_tiles": 30,
        "direct_fallback_min_tiles": 1,
    },
}

# game configuration settings
data_file = {
    # Audio Options
    'master_volume': 100,
    'music_volume': 100,
    'sound_effect_volume': 100,

    # Video Options
    'gamma': 50,
    'screen_resolution': [1920, 1080],
    'fullscreen': False,
}