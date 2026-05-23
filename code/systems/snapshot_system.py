def snapshot_system(world):
    world.snapshot["cpos"].clear()
    world.snapshot["tile"].clear()

    for entity in sorted(world.transform):
        transform = world.transform[entity]
        transform.prev_cpos = transform.cpos

        world.snapshot["cpos"][entity] = transform.cpos
        world.snapshot["tile"][entity] = transform.tile