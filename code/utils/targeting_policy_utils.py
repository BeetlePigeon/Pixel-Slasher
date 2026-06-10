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

PLAYER_INPUT_TO_LEGACY_CONTEXT = {
    "left_click.normal": "traditional_left",
    "left_click.shift": "traditional_shift_left",
    "skill_button.normal": "traditional_right",
    "skill_button.shift": "traditional_shift_left",
}


def get_skill_def(skill_id):
    if skill_id is None:
        return None

    return SKILL_DEFS.get(skill_id)


def skill_has_player_input_policy(skill_id):
    skill_def = get_skill_def(skill_id)
    return (
        skill_def is not None
        and "player_input_policy" in skill_def
    )


def split_player_input_context(context_id):
    if "." not in context_id:
        raise ValueError(
            f"Player input context must be role.modifier, got {context_id!r}"
        )

    return context_id.split(".", 1)


def get_player_input_context_policy(skill_id, context_id):
    skill_def = get_skill_def(skill_id)

    if skill_def is None:
        raise ValueError(
            f"Skill {skill_id!r} has no definition"
        )

    policy = skill_def.get("player_input_policy")
    if policy is None:
        return None

    role, modifier = split_player_input_context(context_id)

    try:
        return policy[role][modifier]
    except KeyError as error:
        raise KeyError(
            f"Skill {skill_id!r} player_input_policy missing context "
            f"{context_id!r}"
        ) from error


def get_legacy_input_context_id(context_id):
    return PLAYER_INPUT_TO_LEGACY_CONTEXT.get(
        context_id,
        context_id,
    )


def get_skill_targeting_policy(skill_id):
    skill_def = get_skill_def(skill_id)

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


def get_skill_input_context_policy(skill_id, context_id):
    if skill_has_player_input_policy(skill_id):
        return get_player_input_context_policy(
            skill_id,
            context_id,
        )

    policy = get_skill_targeting_policy(skill_id)
    input_contexts = policy.get("input_contexts", {})

    return input_contexts.get(
        get_legacy_input_context_id(context_id),
        {},
    )


def get_no_hard_target_action_order_type(skill_id, context_id):
    context_policy = get_skill_input_context_policy(
        skill_id,
        context_id,
    )

    if "no_target" in context_policy:
        order_type = context_policy["no_target"]["order"]

        if order_type == "none":
            return None

        return order_type

    return context_policy.get("no_hard_target_order")


def get_soft_targeting_profile(skill_id, context_id=None):
    if skill_has_player_input_policy(skill_id):
        context_policy = get_player_input_context_policy(
            skill_id,
            context_id,
        )

        return dict(context_policy["soft_targeting"])

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


def get_input_context_hard_target_mode(
    skill_id,
    context_id,
    target_kind,
):
    if skill_has_player_input_policy(skill_id):
        context_policy = get_player_input_context_policy(
            skill_id,
            context_id,
        )

        if target_kind == "interactable":
            return context_policy["interactable"]["mode"]

        if target_kind == "enemy":
            return context_policy["enemy"]["mode"]

        raise ValueError(
            f"Unsupported hard target kind: {target_kind!r}"
        )

    context_policy = get_skill_input_context_policy(
        skill_id,
        context_id,
    )

    hard_target_modes = context_policy.get(
        "hard_target_modes",
        {},
    )

    if target_kind in hard_target_modes:
        return hard_target_modes[target_kind]

    if (
        target_kind == "enemy"
        and context_policy.get("attack_in_place", False)
    ):
        return "ignore"

    if skill_allows_hard_target_kind(
        skill_id,
        target_kind,
    ):
        return "hard_target"

    return "ignore"