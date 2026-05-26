from skill_registry import SKILL_DEFS
from skill_handlers import get_skill_handler
from .action_state_system import cancel_action_state, build_skill_context, get_active_action_tags, action_state_has_any_tags
from .movement_system import get_active_motion_tag


def skill_intent_resolution_system(world, intents):
    world.resolved_skill_intents.clear()

    for entity, entity_intents in intents.items():
        for intent in entity_intents:
            if intent["type"] not in {
                "skill_pressed",
                "skill_held",
                "skill_released",
            }:
                continue

            if intent["type"] == "skill_released":
                if request_release_active_action_for_slot(
                        world,
                        entity,
                        intent["slot"],
                ):
                    continue

            slot = intent["slot"]
            skill_id = world.skills.get((entity, slot))

            if not skill_id:
                continue

            skill_def = SKILL_DEFS.get(skill_id)

            if skill_def is None:
                continue

            if not skill_trigger_matches_intent(skill_def, intent):
                continue

            cooldown_key = (entity, slot)
            ready_tick = world.skill_cooldown.get(cooldown_key, 0)

            if world.tick < ready_tick:
                continue

            if not entity_meets_skill_requirements(world, entity, skill_def):
                continue

            if not skill_allowed_by_motion_state(world, entity, skill_def):
                continue

            if not skill_allowed_by_action_state(world, entity, skill_def):
                continue

            resolved_skill = build_resolved_skill(world, entity, skill_def)

            handler = get_skill_handler(resolved_skill["handler"])

            world.resolved_skill_intents.append({
                "caster": entity,
                "slot": slot,
                "skill_id": skill_id,
                "skill_def": resolved_skill,
                "intent": intent,
                "handler": handler,
            })


def skill_execution_system(world):
    for resolved in sorted(
            world.resolved_skill_intents,
            key=lambda r: (r["caster"], str(r["slot"])),
    ):
        caster = resolved["caster"]
        slot = resolved["slot"]
        skill_def = resolved["skill_def"]
        intent = resolved["intent"]
        handler = resolved["handler"]

        if skill_cancels_active_action_state(world, caster, skill_def):
            cancel_action_state(world, caster)

        context = build_skill_context(
            skill_def=skill_def,
            intent=intent,
            kind="skill_start",
        )

        executed = handler(world, caster, context)

        if executed:
            cooldown_ticks = skill_def.get("cooldown_ticks", 0)
            world.skill_cooldown[(caster, slot)] = world.tick + cooldown_ticks


def skill_allowed_by_action_state(world, entity, skill_def):
    active_action_tags = get_active_action_tags(world, entity)

    if not active_action_tags:
        return True

    blocked_tags = skill_def.get("blocked_by_action_tags", set())

    return active_action_tags.isdisjoint(blocked_tags)


def skill_cancels_active_action_state(world, entity, skill_def):
    action_state = world.action_state.get(entity)

    if action_state is None:
        return False

    cancel_tags = skill_def.get("cancels_action_tags", set())

    if not cancel_tags:
        return False

    return action_state_has_any_tags(
        action_state,
        cancel_tags,
    )


def skill_trigger_matches_intent(skill_def, intent):
    trigger_mode = skill_def["trigger_mode"]
    intent_type = intent["type"]

    if trigger_mode == "press":
        return intent_type == "skill_pressed"

    if trigger_mode == "held_repeat":
        return intent_type == "skill_held"

    return False


def skill_allowed_by_motion_state(world, entity, skill_def):
    active_motion_tag = get_active_motion_tag(world, entity)

    if active_motion_tag is None:
        return True

    blocked_tags = skill_def["blocked_by_motion_tags"]

    return active_motion_tag not in blocked_tags


def entity_has_component(world, entity, component_name):
    component_map = getattr(world, component_name)
    return entity in component_map


def entity_meets_skill_requirements(world, entity, skill_def):
    required_components = skill_def.get("required_components", set())

    for component_name in required_components:
        if not entity_has_component(world, entity, component_name):
            return False

    return True


def build_resolved_skill(world, caster, skill_def):
    resolved = dict(skill_def)

    if "params" in skill_def:
        resolved["params"] = dict(skill_def["params"])

    return resolved


def request_release_active_action_for_slot(world, entity, slot):
    action_state = world.action_state.get(entity)

    if action_state is None:
        return False

    if not action_state.get("ends_on_release", False):
        return False

    if action_state.get("slot") != slot:
        return False

    action_state["release_requested"] = True
    return True