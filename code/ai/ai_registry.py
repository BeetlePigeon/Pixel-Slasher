from ai.behavior_modules.melee_pawn import think


AI_BEHAVIORS = {
    "melee_pawn": think,
}


def get_ai_behavior(ai_type):
    behavior = AI_BEHAVIORS.get(ai_type)

    if behavior is None:
        raise ValueError(
            f"Unknown AI behavior type: {ai_type!r}"
        )

    return behavior