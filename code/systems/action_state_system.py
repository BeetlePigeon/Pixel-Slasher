from policies import MOVEMENT_CANCELING_ACTION_TAGS
from status_ops import (
    get_status_effect_tags,
    get_status_pauses_action_tags,
)


def action_state_has_any_tags(action_state, tags):
    action_tags = get_action_state_tags(action_state)

    return not action_tags.isdisjoint(tags)


def cancel_action_state(world, entity):
    world.action_state.pop(entity, None)


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
        from .movement_system import cancel_voluntary_movement

        cancel_voluntary_movement(world, entity)


def action_state_system(world):
    expired_entities = []

    for entity, action_state in list(world.action_state.items()):
        if action_state_is_paused_by_status(
            world,
            entity,
            action_state,
        ):
            continue

        action_state["age"] += 1

        events = action_state.get("events", [])

        for event in events:
            if event.get("fired", False):
                continue

            tick = event["tick"]

            if action_state["age"] < tick:
                continue

            execute_action_event(
                world,
                entity,
                action_state,
                event,
            )

            event["fired"] = True

        execute_repeat_action_events(
            world,
            entity,
            action_state,
        )

        min_duration = action_state.get("min_duration", 0)

        if (
            action_state.get("release_requested", False)
            and action_state["age"] >= min_duration
        ):
            expired_entities.append(entity)
            continue

        duration = action_state.get("duration")

        if duration is not None:
            if action_state["age"] >= duration:
                expired_entities.append(entity)

    for entity in expired_entities:
        world.action_state.pop(entity, None)


def action_state_is_paused_by_status(world, entity, action_state):
    pause_tags = get_status_pauses_action_tags(world, entity)

    if not pause_tags:
        return False

    action_tags = get_action_state_tags(action_state)

    return not action_tags.isdisjoint(pause_tags)


def get_action_state_tags(action_state):
    if action_state is None:
        return set()

    phase = get_action_phase_at_age(action_state)

    if phase is not None:
        return set(phase.get("tags", set()))

    tags = action_state.get("tags")

    if tags is not None:
        return set(tags)

    action_type = action_state.get("type")

    if action_type is None:
        return set()

    return {action_type}


def get_active_action_tags(world, entity):
    active_tags = set()

    action_state = world.action_state.get(entity)

    if action_state is not None:
        active_tags.update(
            get_action_state_tags(action_state)
        )

    active_tags.update(
        get_status_effect_tags(world, entity)
    )

    return active_tags


def get_action_phase_at_age(action_state):
    phases = action_state.get("phases")

    if not phases:
        return None

    age = action_state.get("age", 0)

    for phase in phases:
        if phase["start"] <= age < phase["end"]:
            return phase

    return None


def execute_repeat_action_events(world, entity, action_state):
    repeat_events = action_state.get("repeat_events", [])

    for event in repeat_events:
        start_tick = event["start_tick"]
        interval = event["interval"]

        age = action_state["age"]

        if age < start_tick:
            continue

        if (age - start_tick) % interval != 0:
            continue

        execute_action_event(
            world,
            entity,
            action_state,
            event,
        )


def execute_action_event(world, entity, action_state, event):
    handler_id = event.get("handler")

    from skill_handlers import get_skill_handler

    handler = get_skill_handler(handler_id)

    if handler is None:
        return False

    skill_def = action_state["skill_def"]

    context = build_skill_context(
        skill_def=skill_def,
        intent=action_state.get("intent", {}),
        params=build_action_event_params(skill_def, event),
        action_state=action_state,
        event=event,
        kind="action_event",
    )

    return handler(world, entity, context)


def build_skill_context(
    skill_def,
    intent=None,
    params=None,
    action_state=None,
    event=None,
    kind="skill_start",
):
    if params is None:
        params = dict(skill_def.get("params", {}))

    return {
        "kind": kind,
        "skill_def": skill_def,
        "intent": dict(intent or {}),
        "params": params,
        "action_state": action_state,
        "event": event,
    }


def build_action_event_params(skill_def, event):
    params = dict(skill_def.get("params", {}))
    params.update(event.get("params", {}))

    return params