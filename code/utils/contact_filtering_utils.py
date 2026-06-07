from combat_ops import (
    entities_are_allies,
    entities_are_enemies,
)


def get_contact_filter(world, eid):
    return world.contact_filter.get(eid, {})


def get_entity_collision_group(world, eid):
    contact_filter = get_contact_filter(world, eid)
    return contact_filter.get("collision_group")


def contact_candidate_is_valid(world, mover, candidate):
    if candidate == mover:
        return False

    mover_filter = get_contact_filter(world, mover)

    ignore_entities = mover_filter.get(
        "ignore_entities",
        set(),
    )
    if candidate in ignore_entities:
        return False

    candidate_group = get_entity_collision_group(world, candidate)
    ignore_collision_groups = mover_filter.get(
        "ignore_collision_groups",
        set(),
    )
    if (
        candidate_group is not None
        and candidate_group in ignore_collision_groups
    ):
        return False

    if not contact_candidate_matches_relationship_filter(
        world,
        mover_filter,
        candidate,
    ):
        return False

    if not contact_candidate_matches_team_filter(
        world,
        mover_filter,
        candidate,
    ):
        return False

    return True


def contact_candidate_matches_relationship_filter(
    world,
    mover_filter,
    candidate,
):
    relationship = mover_filter.get("collides_with_relationship")
    if relationship is None:
        return True

    source = mover_filter.get("source")

    if relationship == "any":
        return True

    if source is None:
        return False

    if relationship == "enemies":
        return entities_are_enemies(
            world,
            source,
            candidate,
        )

    if relationship == "allies":
        return entities_are_allies(
            world,
            source,
            candidate,
        )

    raise NotImplementedError(
        "Contact relationship filter not implemented: "
        f"{relationship!r}"
    )


def contact_candidate_matches_team_filter(
    world,
    mover_filter,
    candidate,
):
    collides_with_teams = mover_filter.get("collides_with_teams")
    if collides_with_teams is None:
        return True

    candidate_team = world.team.get(candidate)
    return candidate_team in collides_with_teams


def filter_contact_candidates(world, mover, candidates):
    return tuple(
        candidate
        for candidate in sorted(candidates)
        if contact_candidate_is_valid(
            world,
            mover,
            candidate,
        )
    )