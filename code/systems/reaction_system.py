from data.tables_skill_defs import SKILL_DEFS
from .action_state_system import action_state_has_any_tags, cancel_action_state


def reaction_system(world, events):
    for event in events:
        event_type = event["type"]

        if event_type == "entity_damaged":
            try_trigger_guard_counter(
                world,
                event,
            )


def entity_is_counter_ready(world, entity):
    action_state = world.action_state.get(entity)

    if action_state is None:
        return False

    return action_state_has_any_tags(
        action_state,
        {"counter_ready"},
    )


def start_counter_attack_action(world, defender, attacker):

    skill_def = SKILL_DEFS["counter_attack"]
    action_def = skill_def["cast"]

    cancel_action_state(world, defender)

    intent = {
        "type": "reactive_counter",
        "counter_target": attacker,
    }

    from skill_utils import start_skill_action_from_def

    return start_skill_action_from_def(
        world,
        defender,
        skill_def,
        action_def,
        intent=intent,
        action_type="counter_attack",
    )


def try_trigger_guard_counter(world, damage_event):
    defender = damage_event.get("target")
    attacker = damage_event.get("source")

    if defender is None or attacker is None:
        return False

    if defender not in world.transform:
        return False

    if attacker not in world.transform:
        return False

    if not entity_is_counter_ready(world, defender):
        return False

    return start_counter_attack_action(
        world,
        defender,
        attacker,
    )