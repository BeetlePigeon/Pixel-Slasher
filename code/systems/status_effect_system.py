def status_effect_system(world):
    expired = []

    for entity, statuses in list(world.status_effects.items()):
        for status_id, status in list(statuses.items()):
            status["remaining_ticks"] -= 1

            if status["remaining_ticks"] <= 0:
                expired.append((entity, status_id))

    for entity, status_id in expired:
        statuses = world.status_effects.get(entity)

        if statuses is None:
            continue

        statuses.pop(status_id, None)

        if not statuses:
            world.status_effects.pop(entity, None)