from systems.event_system import emit_event


def combat_system(world):
    combat_damage_system(world)
    combat_heal_system(world)


def combat_damage_system(world):
    damage_requests = list(world.damage_requests)
    world.damage_requests.clear()

    for damage_request in damage_requests:
        target = damage_request["target"]

        if target not in world.health:
            continue

        health = world.health[target]
        amount = damage_request["amount"]

        health["current"] -= amount

        hit_tile = damage_request.get("hit_tile")

        if hit_tile is not None:
            world.game.debug.add_debug_tile_highlight(
                world,
                hit_tile,
                duration_ticks=10,
                color="pink",
            )

        emit_event(
            world,
            "entity_damaged",
            source=damage_request.get("source"),
            target=target,
            amount=amount,
            health_current=health["current"],
            health_max=health["max"],
            skill_id=damage_request.get("skill_id"),
        )

        if health["current"] <= 0:
            emit_event(
                world,
                "entity_killed",
                target=target,
                source=damage_request.get("source"),
                skill_id=damage_request.get("skill_id"),
            )

            world.entities.destroy(target)


def combat_heal_system(world):
    heal_requests = list(world.heal_requests)
    world.heal_requests.clear()

    for heal_request in heal_requests:
        target = heal_request["target"]
        if target not in world.health:
            continue

        health = world.health[target]
        amount = heal_request["amount"]

        old_current = health["current"]
        health["current"] = min(
            health["max"],
            health["current"] + amount,
        )
        healed_amount = health["current"] - old_current

        emit_event(
            world,
            "entity_healed",
            source=heal_request.get("source"),
            target=target,
            amount=healed_amount,
            health_current=health["current"],
            health_max=health["max"],
            skill_id=heal_request.get("skill_id"),
        )