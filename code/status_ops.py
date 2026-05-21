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
    # 1. Movement-blocking statuses cancel voluntary movement first.
    # This may start a settle controller for normal stun/root-like behavior.
    if status_effect_blocks_voluntary_movement(status_effect):
        from systems import cancel_voluntary_movement

        cancel_voluntary_movement(world, entity)

    # 2. Statuses may interrupt active action timelines.
    # This removes pending scheduled events inside the active action_state.
    if status_effect_cancels_active_action(
        world,
        entity,
        status_effect,
    ):
        from systems import cancel_action_state

        cancel_action_state(world, entity)

    # 3. Statuses may interrupt active motion controllers.
    # This intentionally does not auto-settle.
    #
    # Running this after voluntary movement cancellation means a freeze-like
    # status can include "settle" to cancel a settle controller that was just
    # created by cancel_voluntary_movement().
    cancels_motion_tags = status_effect.get(
        "cancels_motion_tags",
        set(),
    )

    if cancels_motion_tags:
        from systems import cancel_motion_by_tags_for_status

        cancel_motion_by_tags_for_status(
            world,
            entity,
            cancels_motion_tags,
        )


def build_status_effect(
    status_id,
    tags,
    duration,
    data=None,
    cancels_action_tags=None,
    cancels_motion_tags=None,
):
    return {
        "id": status_id,
        "tags": set(tags),
        "cancels_action_tags": set(cancels_action_tags or set()),
        "cancels_motion_tags": set(cancels_motion_tags or set()),
        "duration": duration,
        "remaining_ticks": duration,
        "data": dict(data or {}),
    }


def refresh_existing_status_effect(
    existing,
    tags,
    duration,
    data=None,
    refresh_mode="replace",
    cancels_action_tags=None,
    cancels_motion_tags=None,
):
    if refresh_mode == "ignore":
        return False

    if refresh_mode == "extend":
        existing["remaining_ticks"] += duration
        existing["duration"] += duration

    elif refresh_mode == "max":
        existing["remaining_ticks"] = max(
            existing["remaining_ticks"],
            duration,
        )
        existing["duration"] = max(
            existing["duration"],
            duration,
        )

    elif refresh_mode == "replace":
        existing["remaining_ticks"] = duration
        existing["duration"] = duration

    else:
        raise ValueError(
            f"Unknown status refresh_mode: {refresh_mode}"
        )

    existing["tags"] = set(tags)
    existing["cancels_action_tags"] = set(
        cancels_action_tags or set()
    )
    existing["cancels_motion_tags"] = set(
        cancels_motion_tags or set()
    )
    existing["data"] = dict(data or existing.get("data", {}))

    return True


def apply_status_effect(
    world,
    entity,
    status_id,
    tags,
    duration,
    data=None,
    refresh_mode="replace",
    cancels_action_tags=None,
    cancels_motion_tags=None,
):
    if entity not in world.status_effects:
        world.status_effects[entity] = {}

    existing = world.status_effects[entity].get(status_id)

    if existing is not None:
        refreshed = refresh_existing_status_effect(
            existing,
            tags=tags,
            duration=duration,
            data=data,
            refresh_mode=refresh_mode,
            cancels_action_tags=cancels_action_tags,
            cancels_motion_tags=cancels_motion_tags,
        )

        if not refreshed:
            return False

        apply_status_entry_policies(
            world,
            entity,
            existing,
        )

        return True

    status_effect = build_status_effect(
        status_id=status_id,
        tags=tags,
        duration=duration,
        data=data,
        cancels_action_tags=cancels_action_tags,
        cancels_motion_tags=cancels_motion_tags,
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