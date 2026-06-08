def interact_system(world):
    for request in list(world.interact_request):
        actor = request["actor"]
        target = request["target"]

        if actor not in world.transform:
            continue

        if target not in world.interactable:
            continue

        interactable = world.interactable[target]
        handler_id = interactable.get("handler", "debug_print")

        handle_interaction(
            world,
            actor,
            target,
            interactable,
            handler_id,
        )


def handle_interaction(
    world,
    actor,
    target,
    interactable,
    handler_id,
):
    if handler_id == "debug_print":
        interactable["used_count"] = interactable.get("used_count", 0) + 1

        print(
            "[interact] "
            f"tick={world.tick} "
            f"actor={actor} "
            f"target={target} "
            f"kind={interactable.get('kind')} "
            f"used_count={interactable['used_count']}"
        )
        return

    raise NotImplementedError(
        f"Interact handler not implemented: {handler_id!r}"
    )