def effect_carrier_lifecycle_system(world):
    for carrier in sorted(list(world.effect_carrier_lifecycle)):
        lifecycle = world.effect_carrier_lifecycle[carrier]
        advance_effect_carrier_lifecycle(lifecycle)
        destroy_when = lifecycle["destroy_when"]

        if destroy_when == "effect_deliveries_complete":
            if effect_deliveries_complete(world, carrier):
                world.entities.destroy(carrier)
            continue

        if destroy_when == "age_reaches":
            if effect_carrier_age_reached(lifecycle):
                world.entities.destroy(carrier)
            continue

        raise NotImplementedError(
            f"Effect carrier lifecycle rule not implemented: {destroy_when}"
        )


def advance_effect_carrier_lifecycle(lifecycle):
    lifecycle["age"] = lifecycle.get("age", 0) + 1


def effect_carrier_age_reached(lifecycle):
    return lifecycle["age"] >= lifecycle["ticks"]


def effect_deliveries_complete(world, carrier):
    effect_deliveries = world.effect_deliveries.get(carrier, [])

    return (
        bool(effect_deliveries)
        and all(
            effect_delivery["runtime"].get("delivered", False)
            for effect_delivery in effect_deliveries
        )
    )