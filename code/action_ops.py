MOVEMENT_CANCELING_ACTION_TAGS = {
    "movement_locked",
    "stun",
    "root",
}


def tags_block_voluntary_movement(tags):
    return not set(tags).isdisjoint(
        MOVEMENT_CANCELING_ACTION_TAGS
    )


def action_state_blocks_voluntary_movement(action_state):
    return tags_block_voluntary_movement(
        action_state.get("tags", set())
    )


def start_action_state(world, entity, action_state):
    world.action_state[entity] = action_state

    if action_state_blocks_voluntary_movement(action_state):
        # Imported here to avoid circular imports.
        from systems import cancel_voluntary_movement

        cancel_voluntary_movement(world, entity)