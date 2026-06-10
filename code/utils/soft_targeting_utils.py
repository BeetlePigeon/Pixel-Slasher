from combat_ops import (
    entities_are_allies,
    entities_are_enemies,
    entity_is_hittable,
)

from utils.tile_vec_utils import (
    chebyshev_tile_distance,
    tile_from_cpos,
)


def acquire_soft_target(
    world,
    actor,
    policy,
    reference_direction=None,
    origin_cpos=None,
):
    if not policy.get("enabled", False):
        return None

    search_origin_cpos = get_soft_target_search_origin_cpos(
        world,
        actor,
        policy,
        origin_cpos,
    )
    if search_origin_cpos is None:
        return None

    candidates = []

    for candidate in sorted(world.transform):
        if not soft_target_is_valid(
            world,
            actor,
            candidate,
            policy,
            reference_direction=reference_direction,
            origin_cpos=search_origin_cpos,
        ):
            continue

        candidate_cpos = world.transform[candidate].cpos
        delta = candidate_cpos - search_origin_cpos

        candidates.append(
            (
                soft_target_angle_score(delta, reference_direction),
                soft_target_tile_distance_from_cpos(
                    world,
                    search_origin_cpos,
                    candidate,
                ),
                soft_target_distance_sq_from_cpos(
                    world,
                    search_origin_cpos,
                    candidate,
                ),
                candidate,
            )
        )

    if not candidates:
        return None

    candidates.sort()
    return candidates[0][-1]


def get_soft_target_search_origin_cpos(
    world,
    actor,
    policy,
    origin_cpos=None,
):
    origin = policy["origin"]

    if origin == "actor":
        return world.transform[actor].cpos

    if origin == "cursor":
        return origin_cpos

    raise NotImplementedError(
        f"Soft target origin not implemented: {origin!r}"
    )


def soft_target_is_valid(
    world,
    actor,
    target,
    policy,
    reference_direction=None,
    origin_cpos=None,
):
    if target == actor:
        return False

    if target not in world.transform:
        return False

    if not soft_target_matches_relationship(
        world,
        actor,
        target,
        policy,
    ):
        return False

    if not soft_target_satisfies_requirements(
        world,
        target,
        policy.get("requires", []),
    ):
        return False

    search_origin_cpos = get_soft_target_search_origin_cpos(
        world,
        actor,
        policy,
        origin_cpos,
    )
    if search_origin_cpos is None:
        return False

    if not soft_target_is_within_range(
        world,
        target,
        policy,
        search_origin_cpos,
    ):
        return False

    if not soft_target_is_inside_fov(
        world,
        target,
        policy,
        search_origin_cpos,
        reference_direction=reference_direction,
    ):
        return False

    return True


def soft_target_matches_relationship(world, actor, target, policy):
    relationship = policy.get("relationship", "enemies")

    if relationship == "any":
        return True

    if relationship == "enemies":
        return entities_are_enemies(
            world,
            actor,
            target,
        )

    if relationship == "allies":
        return entities_are_allies(
            world,
            actor,
            target,
        )

    if relationship == "none":
        return False

    raise NotImplementedError(
        f"Soft target relationship not implemented: {relationship!r}"
    )


def soft_target_satisfies_requirements(world, target, requirements):
    for requirement in requirements:
        if requirement == "transform":
            if target not in world.transform:
                return False

            continue

        if requirement == "health":
            if target not in world.health:
                return False

            if world.health[target].get("current", 1) <= 0:
                return False

            continue

        if requirement == "hittable":
            if not entity_is_hittable(world, target):
                return False

            continue

        if requirement == "team":
            if target not in world.team:
                return False

            continue

        raise NotImplementedError(
            f"Soft target requirement not implemented: {requirement!r}"
        )

    return True


def soft_target_is_within_range(
    world,
    target,
    policy,
    origin_cpos,
):
    range_tiles = policy.get("range_tiles")

    if range_tiles is None:
        return True

    return (
        soft_target_tile_distance_from_cpos(
            world,
            origin_cpos,
            target,
        )
        <= range_tiles
    )


def soft_target_tile_distance_from_cpos(
    world,
    origin_cpos,
    target,
):
    origin_tile = tile_from_cpos(origin_cpos)
    target_tile = tile_from_cpos(
        world.transform[target].cpos,
    )

    return chebyshev_tile_distance(
        origin_tile,
        target_tile,
    )


def soft_target_tile_distance(world, actor, target):
    return soft_target_tile_distance_from_cpos(
        world,
        world.transform[actor].cpos,
        target,
    )


def soft_target_is_inside_fov(
    world,
    target,
    policy,
    origin_cpos,
    reference_direction=None,
):
    fov_degrees = policy.get("fov_degrees", 360)

    if fov_degrees >= 360:
        return True

    if reference_direction is None:
        return False

    target_cpos = world.transform[target].cpos
    to_target = target_cpos - origin_cpos

    if to_target.x == 0 and to_target.y == 0:
        return True

    dot = (
        to_target.x * reference_direction.x
        + to_target.y * reference_direction.y
    )

    if fov_degrees == 180:
        return dot >= 0

    raise NotImplementedError(
        f"Soft target FOV not implemented: {fov_degrees!r}"
    )


def soft_target_angle_score(delta, reference_direction):
    if reference_direction is None:
        return 0

    return -(
        delta.x * reference_direction.x
        + delta.y * reference_direction.y
    )


def soft_target_distance_sq_from_cpos(world, origin_cpos, target):
    delta = (
        world.transform[target].cpos
        - origin_cpos
    )

    return delta.x * delta.x + delta.y * delta.y


def soft_target_distance_sq(world, actor, target):
    return soft_target_distance_sq_from_cpos(
        world,
        world.transform[actor].cpos,
        target,
    )