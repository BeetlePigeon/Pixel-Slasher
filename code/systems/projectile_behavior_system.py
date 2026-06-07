from data.tables_dirs import CIRCLE_DIRECTION_LUT
from spawners import spawn_projectile
from utils.tile_vec_utils import scale_normalized_dir


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

    raise NotImplementedError(
        f"Projectile behavior type not implemented: {behavior_type}"
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