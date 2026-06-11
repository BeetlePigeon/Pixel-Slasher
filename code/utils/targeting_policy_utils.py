from skill_registry import SKILL_DEFS


def get_skill_def(skill_id):
    if skill_id is None:
        return None

    return SKILL_DEFS.get(skill_id)


def require_skill_def(skill_id):
    skill_def = get_skill_def(skill_id)

    if skill_def is None:
        raise ValueError(
            f"Skill {skill_id!r} has no definition"
        )

    return skill_def


def split_player_input_context(context_id):
    if "." not in context_id:
        raise ValueError(
            f"Player input context must be role.modifier, got {context_id!r}"
        )

    return context_id.split(".", 1)


def get_player_input_context_policy(skill_id, context_id):
    skill_def = require_skill_def(skill_id)

    if "player_input_policy" not in skill_def:
        raise ValueError(
            f"Skill {skill_id!r} is missing player_input_policy"
        )

    role, modifier = split_player_input_context(context_id)

    try:
        return skill_def["player_input_policy"][role][modifier]

    except KeyError as error:
        raise KeyError(
            f"Skill {skill_id!r} player_input_policy missing context "
            f"{context_id!r}"
        ) from error


def get_no_hard_target_action_order_type(skill_id, context_id):
    if skill_id is None or context_id is None:
        return None

    context_policy = get_player_input_context_policy(
        skill_id,
        context_id,
    )

    order_type = context_policy["no_target"]["order"]

    if order_type == "none":
        return None

    return order_type


def get_soft_targeting_profile(skill_id, context_id):
    context_policy = get_player_input_context_policy(
        skill_id,
        context_id,
    )

    return dict(context_policy["soft_targeting"])


def get_input_context_hard_target_mode(
    skill_id,
    context_id,
    target_kind,
):
    if skill_id is None or context_id is None:
        return "ignore_as_no_target"

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