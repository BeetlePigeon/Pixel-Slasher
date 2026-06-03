from support import Vec2i
from systems import effect_delivery_system
from utils.tile_vec_utils import (
    scale_normalized_dir,
    tile_from_cpos,
    tile_center,
)
from utils.teleport_utils import resolve_path_tolerant_teleport_tile, teleport_entity_to_tile
from utils.placement_utils import find_nearest_valid_placement_tile_with_line_of_sight
from utils.camera_utils import internal_screen_to_world_tile, snap_camera_to_entity_now
from spawners import (
    spawn_test_projectile,
    spawn_spiral_projectile,
    spawn_magnet_orb,
    spawn_meteor,
)
from utils.skill_utils import (
    start_skill_action,
    get_context_intent_for_aim,
    resolve_context_aim_vector,
    aim_vector_to_tile_direction,
    get_direction_to_entity,
    build_slash_fan_tiles,
    build_ranged_slash_fan_tiles,
)
from motion_controllers import DashController



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

    from systems.movement_system import cancel_voluntary_movement

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
        spawn_angle_step_offset=params["spawn_angle_step_offset"],
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

    spawn_tile = find_nearest_valid_placement_tile_with_line_of_sight(
        world,
        target_tile=target_tile,
        search_radius=params["placement_search_radius"],
        max_miss_tiles=params["placement_max_miss_tiles"],
        source_tile=caster_tile,
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
        entity=caster,
        start_tile=start_tile,
        target_tile=target_tile,
        target_snap_radius_tiles=params["target_snap_radius_tiles"],
        ray_fallback_max_miss_tiles=params["ray_fallback_max_miss_tiles"],
        ray_fallback_min_progress_tiles=params["ray_fallback_min_progress_tiles"],
        placement_policy=params["placement_policy"],
    )

    if final_tile is None:
        return False

    teleport_entity_to_tile(world, caster, final_tile)
    snap_camera_to_entity_now(world, caster)

    return True


def execute_debug_slash(world, caster, context):
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
        world.game.debug.add_debug_tile_highlight(
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


def execute_counter_slash(world, caster, context):
    from combat_ops import queue_area_damage

    params = context["params"]
    intent = context["intent"]

    target_entity = intent.get("counter_target")

    direction = None

    if target_entity is not None:
        direction = get_direction_to_entity(
            world,
            caster,
            target_entity,
        )

    if direction is None:
        direction = world.facing.get(caster, Vec2i(1, 0))

    transform = world.transform[caster]
    origin_tile = tile_from_cpos(transform.cpos)

    affected_tiles = build_ranged_slash_fan_tiles(
        origin_tile,
        direction,
        params["range_tiles"],
    )

    for tile in affected_tiles:
        world.game.debug.add_debug_tile_highlight(
            world,
            tile,
            duration_ticks=params["debug_highlight_ticks"],
            color=params["debug_highlight_color"],
        )

    queue_area_damage(
        world,
        source=caster,
        tiles=affected_tiles,
        amount=params["damage"],
        skill_id=context["skill_def"]["id"],
    )

    if caster in world.facing:
        world.facing[caster] = direction

    return True


def execute_meteor(world, caster, context):
    params = context["params"]

    intent = get_context_intent_for_aim(
        world,
        caster,
        context,
    )

    mouse_pos = intent.get("mouse_pos")
    if mouse_pos is None:
        return False

    target_tile = internal_screen_to_world_tile(world, mouse_pos)
    caster_tile = tile_from_cpos(world.transform[caster].cpos)

    spawn_tile = find_nearest_valid_placement_tile_with_line_of_sight(
        world,
        target_tile=target_tile,
        search_radius=params["placement_search_radius"],
        max_miss_tiles=params["placement_max_miss_tiles"],
        source_tile=caster_tile,
        bias_mode="toward",
    )

    if spawn_tile is None:
        return False

    spawn_cpos = tile_center(spawn_tile)

    eid = spawn_meteor(
        world,
        spawn_cpos,
        source=caster,
        skill_id=context["skill_def"]["id"],
        effect_delivery_templates=params["effect_deliveries"],
        lifetime_ticks=params["lifetime"],
        visual=params["visual"],
    )

    return eid is not None


HANDLERS = {
    "execute_dash": execute_dash,
    "execute_cast_skill": execute_cast_skill,
    "execute_spiral_projectile": execute_spiral_projectile,
    "execute_magnet_orb": execute_magnet_orb,
    "execute_test_projectile": execute_test_projectile,
    "execute_teleport": execute_teleport,
    "execute_debug_slash": execute_debug_slash,
    "execute_counter_slash": execute_counter_slash,
    "execute_channel_skill": execute_channel_skill,
    "execute_meteor": execute_meteor,
}


def get_skill_handler(handler_id):
    if handler_id not in HANDLERS:
        raise ValueError(
            f"Unknown skill handler: {handler_id!r}"
        )

    return HANDLERS[handler_id]