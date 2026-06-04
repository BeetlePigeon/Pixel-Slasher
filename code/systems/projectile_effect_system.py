from effect_ops import spawn_effect_carrier


def projectile_effect_system(world, events):
    for event in events:
        if event["type"] != "entity_destroyed_by_movement_collision":
            continue

        handle_projectile_movement_collision_event(
            world,
            event,
        )


def handle_projectile_movement_collision_event(world, event):
    projectile_entity = event["entity"]
    projectile = world.projectile.get(projectile_entity)

    if projectile is None:
        return False

    effect_delivery_templates = projectile.get("effect_deliveries")
    if not effect_delivery_templates:
        return False

    effect_context = {
        "projectile": projectile_entity,
        "impact_tile": event.get("tile"),
        "blocked_tile": event.get("blocked_tile"),
        "blocker_collision_type": event.get("blocker_collision_type"),
    }

    blocker_entity = event.get("blocker_entity")
    if blocker_entity is not None:
        effect_context["contact_target"] = blocker_entity

    eid = spawn_effect_carrier(
        world,
        event["cpos"],
        source=projectile["source"],
        skill_id=projectile["skill_id"],
        effect_delivery_templates=effect_delivery_templates,
        effect_carrier_lifecycle=projectile["effect_carrier_lifecycle"],
        visual=projectile.get("impact_visual"),
        static_tiles_placement_handling="allow",
        effect_context=effect_context,
    )

    return eid is not None