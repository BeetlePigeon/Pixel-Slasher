from data.tables_dirs import CIRCLE_DIRECTION_LUT
from spawners import spawn_projectile
from combat_ops import (
    entities_are_allies,
    entities_are_enemies,
    entity_is_hittable,
)
from motion_controllers import LinearProjectileController
from utils.tile_vec_utils import (
    chebyshev_tile_distance,
    scale_normalized_dir,
    tile_from_cpos,
    turn_direction_toward_vector,
    squared_cpos_distance,
)


def projectile_behavior_system(world):
    for projectile in sorted(list(world.projectile)):
        if projectile not in world.projectile:
            continue

        if projectile not in world.transform:
            continue

        projectile_data = world.projectile[projectile]
        behaviors = projectile_data.get("behaviors", [])

        if not behaviors:
            continue

        behavior_runtime = projectile_data.setdefault(
            "behavior_runtime",
            {},
        )

        for behavior_index, behavior in enumerate(behaviors):
            process_projectile_behavior(
                world,
                projectile,
                projectile_data,
                behavior,
                behavior_runtime.setdefault(
                    behavior_index,
                    {},
                ),
            )


def process_projectile_behavior(
    world,
    projectile,
    projectile_data,
    behavior,
    runtime,
):
    behavior_type = behavior["type"]

    if behavior_type == "emit_projectiles":
        process_emit_projectiles_behavior(
            world,
            projectile,
            projectile_data,
            behavior,
            runtime,
        )
        return

    if behavior_type == "homing":
        process_homing_behavior(
            world,
            projectile,
            projectile_data,
            behavior,
            runtime,
        )
        return

    raise NotImplementedError(
        f"Projectile behavior type not implemented: {behavior_type}"
    )


def process_homing_behavior(
    world,
    projectile,
    projectile_data,
    behavior,
    runtime,
):
    target = resolve_homing_target(
        world,
        projectile,
        projectile_data,
        behavior,
        runtime,
    )
    if target is None:
        return

    steer_projectile_toward_target(
        world,
        projectile,
        target,
        behavior,
    )


def resolve_homing_target(
    world,
    projectile,
    projectile_data,
    behavior,
    runtime,
):
    current_target = runtime.get("target")
    retarget_mode = behavior.get(
        "retarget",
        {},
    ).get(
        "mode",
        "when_invalid",
    )

    if retarget_mode == "when_invalid":
        if homing_target_is_valid(
            world,
            projectile,
            projectile_data,
            behavior,
            current_target,
        ):
            return current_target

        target = acquire_homing_target(
            world,
            projectile,
            projectile_data,
            behavior,
        )
        runtime["target"] = target
        return target

    raise NotImplementedError(
        f"Homing retarget mode not implemented: {retarget_mode!r}"
    )


def acquire_homing_target(
    world,
    projectile,
    projectile_data,
    behavior,
):
    targeting = behavior["targeting"]
    mode = targeting.get("mode", "nearest")

    if mode != "nearest":
        raise NotImplementedError(
            f"Homing targeting mode not implemented: {mode!r}"
        )

    candidates = []

    for candidate in sorted(world.transform):
        if not homing_target_is_valid(
            world,
            projectile,
            projectile_data,
            behavior,
            candidate,
        ):
            continue

        distance_sq = squared_cpos_distance(
            world.transform[projectile].cpos,
            world.transform[candidate].cpos,
        )
        candidates.append(
            (
                distance_sq,
                candidate,
            )
        )

    if not candidates:
        return None

    candidates.sort()
    return candidates[0][1]


def homing_target_is_valid(
    world,
    projectile,
    projectile_data,
    behavior,
    target,
):
    if target is None:
        return False

    if target == projectile:
        return False

    if target == projectile_data.get("source"):
        return False

    if target not in world.transform:
        return False

    targeting = behavior["targeting"]

    if not homing_target_matches_relationship(
        world,
        projectile_data,
        target,
        targeting,
    ):
        return False

    if not homing_target_is_within_radius(
        world,
        projectile,
        target,
        targeting,
    ):
        return False

    if not homing_target_satisfies_requirements(
        world,
        target,
        targeting.get("requires", []),
    ):
        return False

    return True


def homing_target_matches_relationship(
    world,
    projectile_data,
    target,
    targeting,
):
    relationship = targeting.get("relationship", "enemies")
    source = projectile_data.get("source")

    if relationship == "any":
        return True

    if source is None:
        return False

    if relationship == "enemies":
        return entities_are_enemies(
            world,
            source,
            target,
        )

    if relationship == "allies":
        return entities_are_allies(
            world,
            source,
            target,
        )

    raise NotImplementedError(
        f"Homing relationship not implemented: {relationship!r}"
    )


def homing_target_is_within_radius(
    world,
    projectile,
    target,
    targeting,
):
    radius_tiles = targeting.get("radius_tiles")
    if radius_tiles is None:
        return True

    projectile_tile = tile_from_cpos(
        world.transform[projectile].cpos,
    )
    target_tile = tile_from_cpos(
        world.transform[target].cpos,
    )

    return (
        chebyshev_tile_distance(
            projectile_tile,
            target_tile,
        )
        <= radius_tiles
    )


def homing_target_satisfies_requirements(
    world,
    target,
    requirements,
):
    for requirement in requirements:
        if not homing_target_satisfies_requirement(
            world,
            target,
            requirement,
        ):
            return False

    return True


def homing_target_satisfies_requirement(
    world,
    target,
    requirement,
):
    if requirement == "transform":
        return target in world.transform

    if requirement == "health":
        return target in world.health

    if requirement == "hittable":
        return entity_is_hittable(
            world,
            target,
        )

    if requirement == "team":
        return target in world.team

    raise NotImplementedError(
        f"Homing target requirement not implemented: {requirement!r}"
    )


def steer_projectile_toward_target(
    world,
    projectile,
    target,
    behavior,
):
    motion_state = world.motion_state.get(projectile)
    if motion_state is None:
        return

    controller = motion_state.get("controller")
    if not isinstance(controller, LinearProjectileController):
        return

    to_target = (
        world.transform[target].cpos
        - world.transform[projectile].cpos
    )
    if to_target.x == 0 and to_target.y == 0:
        return

    controller.aim_vector = turn_direction_toward_vector(
        controller.aim_vector,
        to_target,
        behavior["turn_rate_steps_per_tick"],
    )


def process_emit_projectiles_behavior(
    world,
    projectile,
    projectile_data,
    behavior,
    runtime,
):
    age = runtime.get("age", 0)

    if not emit_projectiles_behavior_is_active(
        behavior,
        age,
    ):
        runtime["age"] = age + 1
        return

    if emit_projectiles_behavior_should_fire(
        behavior,
        age,
    ):
        emit_behavior_projectiles(
            world,
            projectile,
            projectile_data,
            behavior,
            runtime,
        )

    runtime["age"] = age + 1


def emit_projectiles_behavior_is_active(behavior, age):
    start_tick = behavior.get("start_tick", 0)
    end_tick = behavior.get("end_tick")

    if age < start_tick:
        return False

    if end_tick is not None and age > end_tick:
        return False

    return True


def emit_projectiles_behavior_should_fire(behavior, age):
    start_tick = behavior.get("start_tick", 0)
    interval_ticks = behavior["interval_ticks"]

    return (age - start_tick) % interval_ticks == 0


def emit_behavior_projectiles(
    world,
    projectile,
    projectile_data,
    behavior,
    runtime,
):
    origin_cpos = resolve_emit_projectiles_origin_cpos(
        world,
        projectile,
        behavior,
    )
    directions = build_emit_projectiles_directions(
        behavior,
        runtime,
    )

    source = projectile_data["source"]
    skill_id = projectile_data["skill_id"]
    projectile_id = behavior["projectile_id"]
    spawn_params = behavior.get("spawn_params", {})
    spawn_distance = behavior.get("spawn_distance", 0)

    for direction in directions:
        spawn_cpos = origin_cpos

        if spawn_distance:
            spawn_cpos = (
                spawn_cpos
                + scale_normalized_dir(
                    direction,
                    spawn_distance,
                )
            )

        spawn_projectile(
            world,
            projectile_id,
            spawn_cpos,
            direction,
            source=source,
            skill_id=skill_id,
            spawn_params=spawn_params,
        )


def resolve_emit_projectiles_origin_cpos(
    world,
    projectile,
    behavior,
):
    origin = behavior.get("origin", "self")

    if origin == "self":
        return world.transform[projectile].cpos

    raise NotImplementedError(
        f"emit_projectiles origin not implemented: {origin!r}"
    )


def build_emit_projectiles_directions(behavior, runtime):
    pattern = behavior["pattern"]
    pattern_type = pattern["type"]

    if pattern_type == "rotating_radial":
        return build_rotating_radial_directions(
            pattern,
            runtime,
        )

    raise NotImplementedError(
        f"emit_projectiles pattern not implemented: {pattern_type!r}"
    )


def build_rotating_radial_directions(pattern, runtime):
    emit_count = runtime.get("emit_count", 0)

    start_angle_index = pattern.get("start_angle_index", 0)
    angle_step = pattern["angle_step"]
    directions_per_burst = pattern.get(
        "directions_per_burst",
        1,
    )

    direction_spacing = pattern.get(
        "direction_spacing",
        len(CIRCLE_DIRECTION_LUT) // directions_per_burst,
    )

    base_angle_index = (
        start_angle_index
        + emit_count * angle_step
    )

    directions = []

    for direction_index in range(directions_per_burst):
        angle_index = (
            base_angle_index
            + direction_index * direction_spacing
        ) % len(CIRCLE_DIRECTION_LUT)

        directions.append(
            CIRCLE_DIRECTION_LUT[angle_index],
        )

    runtime["emit_count"] = emit_count + 1

    return directions