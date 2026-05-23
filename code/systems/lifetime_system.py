def lifetime_system(world):
    for entity in sorted(list(world.lifetime)):
        lifetime = world.lifetime[entity]

        lifetime["remaining_ticks"] -= 1

        if lifetime["remaining_ticks"] <= 0:
            world.entities.destroy(entity)