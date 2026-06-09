from skill_registry import SKILL_DEFS


DEFAULT_TARGETING_POLICY = {
    "hard_targets": {
        "enemy": True,
        "interactable": True,
    },
    "soft_targeting": {
        "enabled": False,
    },
    "input_contexts": {},
}


def get_skill_targeting_policy(skill_id):
    if skill_id is None:
        return DEFAULT_TARGETING_POLICY

    skill_def = SKILL_DEFS.get(skill_id)
    if skill_def is None:
        return DEFAULT_TARGETING_POLICY

    return skill_def.get(
        "targeting_policy",
        DEFAULT_TARGETING_POLICY,
    )


def skill_allows_hard_target_kind(skill_id, target_kind):
    policy = get_skill_targeting_policy(skill_id)
    hard_targets = policy.get(
        "hard_targets",
        DEFAULT_TARGETING_POLICY["hard_targets"],
    )

    return hard_targets.get(target_kind, False)


def get_skill_soft_targeting_policy(skill_id):
    policy = get_skill_targeting_policy(skill_id)
    return policy.get(
        "soft_targeting",
        DEFAULT_TARGETING_POLICY["soft_targeting"],
    )


def skill_uses_soft_targeting(skill_id):
    return get_skill_soft_targeting_policy(
        skill_id,
    ).get("enabled", False)


def get_skill_input_context_policy(skill_id, context_id):
    policy = get_skill_targeting_policy(skill_id)
    input_contexts = policy.get("input_contexts", {})
    return input_contexts.get(context_id, {})


def get_no_hard_target_action_order_type(skill_id, context_id):
    context_policy = get_skill_input_context_policy(
        skill_id,
        context_id,
    )
    return context_policy.get("no_hard_target_order")


def get_soft_targeting_profile(skill_id, context_id=None):
    soft_policy = dict(
        get_skill_soft_targeting_policy(skill_id),
    )

    if context_id is not None:
        context_policy = get_skill_input_context_policy(
            skill_id,
            context_id,
        )
        context_soft_policy = context_policy.get("soft_targeting", {})
        soft_policy.update(context_soft_policy)

    return soft_policy


def input_context_uses_attack_in_place(skill_id, context_id):
    context_policy = get_skill_input_context_policy(
        skill_id,
        context_id,
    )

    return context_policy.get(
        "attack_in_place",
        False,
    )