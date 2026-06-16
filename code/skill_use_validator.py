from dataclasses import dataclass

from skill_registry import SKILL_DEFS
from systems.action_state_system import get_active_action_tags
from systems.movement_system import get_active_motion_tag


@dataclass(frozen=True)
class SkillUseValidation:
    is_valid: bool
    reason: str
    skill_id: str = None
    skill_def: dict = None


def skill_use_is_valid(world, entity, slot, intent):
    skill_id = world.skills.get((entity, slot))

    if not skill_id:
        return SkillUseValidation(
            is_valid=False,
            reason="missing_skill",
        )

    skill_def = SKILL_DEFS.get(skill_id)

    if skill_def is None:
        return SkillUseValidation(
            is_valid=False,
            reason="missing_skill_def",
            skill_id=skill_id,
        )

    if not skill_trigger_matches_intent(skill_def, intent):
        return SkillUseValidation(
            is_valid=False,
            reason="trigger_mismatch",
            skill_id=skill_id,
            skill_def=skill_def,
        )

    cooldown_key = (entity, slot)
    ready_tick = world.skill_cooldown.get(cooldown_key, 0)

    if world.tick < ready_tick:
        return SkillUseValidation(
            is_valid=False,
            reason="cooldown",
            skill_id=skill_id,
            skill_def=skill_def,
        )

    if not entity_meets_skill_requirements(world, entity, skill_def):
        return SkillUseValidation(
            is_valid=False,
            reason="missing_required_component",
            skill_id=skill_id,
            skill_def=skill_def,
        )

    if not skill_allowed_by_motion_state(world, entity, skill_def):
        return SkillUseValidation(
            is_valid=False,
            reason="blocked_by_motion_tag",
            skill_id=skill_id,
            skill_def=skill_def,
        )

    if not skill_allowed_by_action_state(world, entity, skill_def):
        return SkillUseValidation(
            is_valid=False,
            reason="blocked_by_action_tag",
            skill_id=skill_id,
            skill_def=skill_def,
        )

    return SkillUseValidation(
        is_valid=True,
        reason="valid",
        skill_id=skill_id,
        skill_def=skill_def,
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


def skill_allowed_by_action_state(world, entity, skill_def):
    active_action_tags = get_active_action_tags(world, entity)

    if not active_action_tags:
        return True

    blocked_tags = skill_def.get("blocked_by_action_tags", set())
    return active_action_tags.isdisjoint(blocked_tags)


def entity_meets_skill_requirements(world, entity, skill_def):
    required_components = skill_def.get("required_components", set())

    for component_name in required_components:
        if not entity_has_component(world, entity, component_name):
            return False

    return True


def entity_has_component(world, entity, component_name):
    component_map = getattr(world, component_name)
    return entity in component_map