def get_contact_filter(world, eid):
    return world.contact_filter.get(eid, {})


def get_entity_collision_group(world, eid):
    contact_filter = get_contact_filter(world, eid)
    return contact_filter.get("collision_group")


def contact_candidate_is_valid(world, mover, candidate):
    if candidate == mover:
        return False
    mover_filter = get_contact_filter(world, mover)
    ignore_entities = mover_filter.get("ignore_entities",
        set(),
    )

    if candidate in ignore_entities:
        return False

    candidate_group = get_entity_collision_group(world, candidate)

    ignore_collision_groups = mover_filter.get(
        "ignore_collision_groups",
        set(),
    )

    if candidate_group is not None and candidate_group in ignore_collision_groups:
        return False

    collides_with_teams = mover_filter.get("collides_with_teams")

    if collides_with_teams is not None:
        candidate_team = world.team.get(candidate)

        if candidate_team not in collides_with_teams:
            return False

    return True


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