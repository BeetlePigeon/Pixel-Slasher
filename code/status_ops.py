def get_status_effect_tags(world, entity):
    tags = set()

    for status in world.status_effects.get(entity, {}).values():
        tags.update(status.get("tags", set()))

    return tags


def status_effect_blocks_voluntary_movement(status_effect):
    from action_ops import tags_block_voluntary_movement

    return tags_block_voluntary_movement(
        status_effect.get("tags", set())
    )


def apply_status_effect(
    world,
    entity,
    status_id,
    tags,
    duration,
    data=None,
    refresh_mode="replace",
):
    if entity not in world.status_effects:
        world.status_effects[entity] = {}

    existing = world.status_effects[entity].get(status_id)

    if existing is not None:
        if refresh_mode == "ignore":
            return False

        if refresh_mode == "extend":
            existing["remaining_ticks"] += duration
            existing["duration"] += duration
            return True

        if refresh_mode == "max":
            existing["remaining_ticks"] = max(
                existing["remaining_ticks"],
                duration,
            )
            existing["duration"] = max(
                existing["duration"],
                duration,
            )
            return True

        if refresh_mode != "replace":
            raise ValueError(
                f"Unknown status refresh_mode: {refresh_mode}"
            )

    status_effect = {
        "id": status_id,
        "tags": set(tags),
        "duration": duration,
        "remaining_ticks": duration,
        "data": dict(data or {}),
    }

    world.status_effects[entity][status_id] = status_effect

    if status_effect_blocks_voluntary_movement(status_effect):
        from systems import cancel_voluntary_movement

        cancel_voluntary_movement(world, entity)

    return True


def remove_status_effect(world, entity, status_id):
    statuses = world.status_effects.get(entity)

    if statuses is None:
        return False

    if status_id not in statuses:
        return False

    statuses.pop(status_id, None)

    if not statuses:
        world.status_effects.pop(entity, None)

    return True