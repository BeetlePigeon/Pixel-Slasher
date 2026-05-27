from support import Vec2i
from utils.tile_vec_utils import (
    sign,
    scale_vec,
    clamp_vec_axis,
)


def influence_system(world):
    world.influence_delta.clear()

    receivers = (
        set(world.transform)
        & set(world.influence_receiver)
    )

    for entity in sorted(receivers):
        motion_state = world.motion_state.get(entity)

        if not motion_accepts_influences(motion_state):
            world.influence_delta[entity] = Vec2i(0, 0)
            continue

        receiver = world.influence_receiver[entity]
        accepted = receiver["accepts"]

        total = Vec2i(0, 0)

        for emitter_entity in sorted(world.influence_emitter):
            emitter = world.influence_emitter[emitter_entity]
            influence_type = emitter["type"]

            if influence_type not in accepted:
                continue

            delta = Vec2i(0, 0)

            if influence_type == "wind":
                delta = sample_wind_delta(world, emitter)

            elif influence_type == "magnet":
                delta = sample_magnet_delta(world, emitter_entity, emitter, entity)

            scale_num, scale_den = receiver.get("scales", {}).get(
                influence_type,
                (1, 1),
            )

            delta = scale_vec(delta, scale_num, scale_den)
            total = total + delta

        max_delta = receiver.get("max_delta")

        if max_delta is not None:
            total = clamp_vec_axis(total, max_delta)

        world.influence_delta[entity] = total


def motion_accepts_influences(motion_state) -> bool:
    if motion_state is None:
        return True

    influence_mode = motion_state.get("influence_mode", "normal")

    if influence_mode == "ignore_all":
        return False

    return True


def sample_wind_delta(world, emitter):
    mode = emitter.get("mode", "constant")

    if mode == "constant":
        return emitter["delta"]

    if mode == "cycle":
        cycle = emitter["cycle"]
        ticks_per_step = emitter["ticks_per_step"]
        index = (world.tick // ticks_per_step) % len(cycle)
        return cycle[index]

    return emitter["delta"]


def sample_magnet_delta(world, emitter_entity, emitter, target_entity):
    emitter_cpos = world.snapshot["cpos"].get(emitter_entity)
    target_cpos = world.snapshot["cpos"].get(target_entity)

    if emitter_cpos is None or target_cpos is None:
        return Vec2i(0, 0)

    dx = emitter_cpos.x - target_cpos.x
    dy = emitter_cpos.y - target_cpos.y

    # Simple square radius check for now.
    radius = emitter["radius"]
    if abs(dx) > radius or abs(dy) > radius:
        return Vec2i(0, 0)

    strength = emitter["strength"]

    return Vec2i(
        sign(dx) * strength,
        sign(dy) * strength,
    )