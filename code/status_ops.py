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


def action_state_has_any_tags(action_state, tags):
    if action_state is None:
        return False

    return not set(action_state.get("tags", set())).isdisjoint(tags)


def status_effect_cancels_active_action(world, entity, status_effect):
    cancel_tags = status_effect.get("cancels_action_tags", set())

    if not cancel_tags:
        return False

    action_state = world.action_state.get(entity)

    if action_state is None:
        return False

    return action_state_has_any_tags(
        action_state,
        cancel_tags,
    )


def apply_status_entry_policies(world, entity, status_effect):
    if status_effect_blocks_voluntary_movement(status_effect):
        from systems import cancel_voluntary_movement

        cancel_voluntary_movement(world, entity)

    if status_effect_cancels_active_action(
        world,
        entity,
        status_effect,
    ):
        from systems import cancel_action_state

        cancel_action_state(world, entity)


def apply_status_effect(
    world,
    entity,
    status_id,
    tags,
    duration,
    data=None,
    refresh_mode="replace",
    cancels_action_tags=None,
):
    if entity not in world.status_effects:
        world.status_effects[entity] = {}

    status_effect = {
        "id": status_id,
        "tags": set(tags),
        "cancels_action_tags": set(cancels_action_tags or set()),
        "duration": duration,
        "remaining_ticks": duration,
        "data": dict(data or {}),
    }

    existing = world.status_effects[entity].get(status_id)

    if existing is not None:
        if refresh_mode == "ignore":
            return False

        if refresh_mode == "extend":
            existing["remaining_ticks"] += duration
            existing["duration"] += duration
            existing["tags"] = set(tags)
            existing["cancels_action_tags"] = set(
                cancels_action_tags or set()
            )
            existing["data"] = dict(data or existing.get("data", {}))

            apply_status_entry_policies(
                world,
                entity,
                existing,
            )

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
            existing["tags"] = set(tags)
            existing["cancels_action_tags"] = set(
                cancels_action_tags or set()
            )
            existing["data"] = dict(data or existing.get("data", {}))

            apply_status_entry_policies(
                world,
                entity,
                existing,
            )

            return True

        if refresh_mode != "replace":
            raise ValueError(
                f"Unknown status refresh_mode: {refresh_mode}"
            )

    world.status_effects[entity][status_id] = status_effect

    apply_status_entry_policies(
        world,
        entity,
        status_effect,
    )

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