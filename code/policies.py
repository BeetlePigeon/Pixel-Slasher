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

BASE_CLICK_MOVE_PATH_POLICY = {
    # None means uncapped. Player pathing should usually stay uncapped.
    "max_path_builds_per_tick": None,

    # Shared budget bucket name. If None, the path policy name is used.
    "path_build_budget_key": None,

    "max_expansions": 100,
    "max_path_length": 30,
    "smooth_max_path_length": 28,
    "target_snap_radius": 2,

    # None means all valid snap candidates may be tried.
    # Non-player policies can cap this to avoid many A* searches per request.
    "target_snap_candidate_limit": None,

    # Failed path cache key shape.
    #
    # "exact":
    #   entity + start tile + target tile + policy + dynamic blocker context
    #
    # "target_only":
    #   entity + target tile + policy
    #
    # Player movement should generally use "exact".
    # Enemy movement can use "target_only" to suppress repeated failed
    # attempts while clumped or blocked.
    "failed_query_key_scope": "exact",

    # Minimum ticks between expensive path-build attempts for this entity.
    #
    # This applies to:
    # - initial path creation when the entity has a move_target and no controller
    # - stale-path recovery repaths

    # Active path refresh is separate from initial path creation and stale
    # recovery. Keep it explicit so one click does not secretly rebuild paths.
    "active_path_refresh_enabled": False,

    "retarget_active_path_on_target_change": True,

    # What an active PathFollowController does when its movement step is
    # blocked by a dynamic actor after local avoidance has failed or is disabled.
    "dynamic_block_response": "abort",

    # Terminal path-command cleanup.
    "clear_target_on_path_finish": True,
    "clear_target_on_path_abort": True,
    "clear_target_on_path_fail": True,

    # Move targets may still update every tick; this only gates A*/path build work.
    "path_build_cooldown_ticks": 10,

    # If a path query fails, don't retry the exact same
    # start/target/policy query immediately.
    "failed_retry_ticks": 30,

    "stall_ticks_before_repath": 10,
    "repath_cooldown_ticks": 10,
    "max_repath_attempts": 0,
    "max_follow_ticks": 315,
    # Minimum meaningful improvement toward the current path node.
    "progress_min_cpos": 256,

    # Local escape threshold from the current path-follow anchor.
    "stall_escape_cpos": 4096,

    # Longer safety timeout for cases where the actor is moving but not
    # advancing or improving toward the current path node.
    "path_progress_timeout_ticks": 45,

    "direct_fallback_on_fail": True,
    "direct_fallback_max_tiles": 30,
    "direct_fallback_min_tiles": 1,


    # Local dynamic blocker awareness for path building.
    #
    # Pathfinding still sees static collision globally, but may also
    # see current dynamic blockers near the path start.
    "path_local_dynamic_blockers_enabled": True,
    "path_local_dynamic_blocker_radius_tiles": 8,
    "path_local_dynamic_blocker_max_entities": 30,

    # Current occupied bodies may be considered.
    # Future/reserved movement is intentionally ignored.
    "path_local_dynamic_blocker_include_moving": True,
    "path_local_dynamic_blocker_include_reservations": False,

    # Reactive local avoidance for PathFollowController.
    # Only used when the original move is blocked by a dynamic actor.
    "local_avoidance_enabled": False,

    # Candidate movement may move slightly farther from the current path node,
    # but not by more than this many cpos units.
    "local_avoidance_max_extra_node_distance_cpos": 1024,

    # If true, every accepted avoidance move must reduce distance to the
    # current path node.
    "local_avoidance_require_progress": False,
    "local_avoidance_min_progress_cpos": 0,

    # If several candidates work, prefer candidates that reduce distance
    # to the current path node.
    "local_avoidance_prefer_progress": True,

    # Perpendicular fallback scale. 1/1 means full-size perpendicular step.
    "local_avoidance_perpendicular_scale_num": 1,
    "local_avoidance_perpendicular_scale_den": 1,

    "local_avoidance_forward_side_scale_num": 1,
    "local_avoidance_forward_side_scale_den": 1,
}

PATH_POLICIES = {
    "player_click_move": {
        **BASE_CLICK_MOVE_PATH_POLICY,
    },

    "actor_move": {
        **BASE_CLICK_MOVE_PATH_POLICY,

        # Non-player actors should not repath as aggressively as the player.
        "path_build_cooldown_ticks": 20,
        "max_expansions": 80,

        "dynamic_block_response": "retry",
        "max_repath_attempts": 4,
#        "stall_ticks_before_repath": 5,

        "failed_retry_ticks": 45,
        "target_snap_candidate_limit": 4,
        "failed_query_key_scope": "target_only",

        "max_path_builds_per_tick": 2,
        "path_build_budget_key": "actor_move",
    },
}

DESTACK_POLICIES = {
    "default": {
        "max_search_radius": 4,
        "max_passes": 8,
        "debug_print": True,

        # Higher priority stays on the contested tile.
        "player_stay_priority": 100,
        "default_stay_priority": 50,
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

# Movement footprints are center + wings.
#
# Dynamic entity-vs-entity movement collision always allows
# wing-wing overlap.
#
# Static map collision is globally configurable:
#
# "allow":
#   Only the center tile is blocked by static map collision.
#   Wing tiles may overlap static blockers.
#
# "block":
#   The full movement footprint is blocked by static map collision.
STATIC_WING_COLLISION_POLICY = "block"

# Projectile contact footprint vs actor collision footprint.
#
# "center_body":
# Contact occurs if either center tile is inside the other entity's body.
# This allows projectile-center/actor-wing and actor-center/projectile-wing,
# but rejects wing-wing overlap.
#
# "any_tile":
# Contact occurs if any projectile contact footprint tile overlaps any
# actor collision footprint tile. This includes wing-wing overlap.
PROJECTILE_DYNAMIC_ACTOR_CONTACT_OVERLAP_POLICY = "any_tile"