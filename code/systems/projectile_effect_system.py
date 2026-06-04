from effect_ops import spawn_effect_carrier


def projectile_effect_system(world, events):
    for event in events:
        handle_projectile_effect_event(
            world,
            event,
        )


def handle_projectile_effect_event(world, event):
    projectile_entity = event.get("entity")
    if projectile_entity is None:
        return False

    projectile = world.projectile.get(projectile_entity)
    if projectile is None:
        return False

    triggered = False

    for effect_trigger in projectile.get("effect_triggers", []):
        if not projectile_effect_trigger_matches_event(
            effect_trigger,
            event,
        ):
            continue

        if spawn_projectile_effect_carrier(
            world,
            projectile_entity,
            projectile,
            effect_trigger,
            event,
        ):
            triggered = True

    return triggered


def projectile_effect_trigger_matches_event(effect_trigger, event):
    return effect_trigger["event"] == event["type"]


def spawn_projectile_effect_carrier(
    world,
    projectile_entity,
    projectile,
    effect_trigger,
    event,
):
    effect_context = build_projectile_effect_context(
        projectile_entity,
        event,
    )

    eid = spawn_effect_carrier(
        world,
        event["cpos"],
        source=projectile["source"],
        skill_id=projectile["skill_id"],
        effect_delivery_templates=effect_trigger["effect_deliveries"],
        effect_carrier_lifecycle=effect_trigger[
            "effect_carrier_lifecycle"
        ],
        visual=effect_trigger.get("visual"),
        static_tiles_placement_handling=(
            effect_trigger.get(
                "static_tiles_placement_handling",
                "allow",
            )
        ),
        effect_context=effect_context,
    )

    return eid is not None


def build_projectile_effect_context(projectile_entity, event):
    effect_context = {
        "projectile": projectile_entity,
        "impact_tile": event.get("tile"),
        "blocked_tile": event.get("blocked_tile"),
        "blocker_collision_type": event.get("blocker_collision_type"),
    }

    blocker_entity = event.get("blocker_entity")
    if blocker_entity is not None:
        effect_context["contact_target"] = blocker_entity

    return effect_context