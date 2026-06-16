from skill_handlers import get_skill_handler
from skill_use_validator import skill_use_is_valid
from .action_state_system import (
    cancel_action_state,
    build_skill_context,
    action_state_has_any_tags,
)


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

            validation = skill_use_is_valid(
                world,
                entity,
                slot,
                intent,
            )

            if not validation.is_valid:
                continue

            skill_id = validation.skill_id
            skill_def = validation.skill_def

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