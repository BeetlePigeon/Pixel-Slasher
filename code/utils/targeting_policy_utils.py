from skill_registry import SKILL_DEFS


DEFAULT_TARGETING_POLICY = {
    "hard_targets": {
        "enemy": True,
        "interactable": True,
    },
    "soft_targeting": {
        "enabled": False,
    },
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


def skill_uses_soft_targeting(skill_id):
    policy = get_skill_targeting_policy(skill_id)
    soft_targeting = policy.get("soft_targeting", {})
    return soft_targeting.get("enabled", False)