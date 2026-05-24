from combat_ops import queue_damage_request, find_hittable_entities_on_tiles
from support import Vec2i


def effect_delivery_system(world):
    for carrier, effect_delivery in list(world.effect_delivery.items()):
        delivery = effect_delivery["delivery"]
        delivery["age"] = delivery.get("age", 0) + 1

        delivery_type = delivery["type"]

        if delivery_type == "timed_tiles":
            update_timed_tiles_effect_delivery(
                world,
                carrier,
                effect_delivery,
            )
            continue

        raise ValueError(
            f"Unknown effect delivery type: {delivery_type}"
        )


def update_timed_tiles_effect_delivery(
    world,
    carrier,
    effect_delivery,
):
    delivery = effect_delivery["delivery"]

    if delivery.get("delivered", False):
        return

    age = delivery["age"]
    trigger_tick = delivery["trigger_tick"]
    tiles = delivery["tiles"]

    debug = effect_delivery.get("debug")

    if debug is not None and age < trigger_tick:
        world.game.debug.add_debug_tile_highlight(
            world,
            tiles,
            debug.get("telegraph_highlight_ticks", 2),
            debug.get("telegraph_highlight_color", "yellow"),
        )

    if age < trigger_tick:
        return

    if debug is not None:
        world.game.debug.add_debug_tile_highlight(
            world,
            tiles,
            debug.get("impact_highlight_ticks", 8),
            debug.get("impact_highlight_color", "red"),
        )

    context = build_effect_context(
        effect_delivery,
        carrier=carrier,
    )

    source = context.get("owner") or context.get("instigator")

    targets = find_hittable_entities_on_tiles(
        world,
        source,
        tiles,
    )

    apply_effects_to_targets(
        world,
        context,
        targets,
        effect_delivery["effects"],
    )

    delivery["delivered"] = True

    consume_policy = effect_delivery.get("consume_policy", {})

    if consume_policy.get("destroy_carrier_after_delivery", False):
        world.entities.destroy(carrier)


def apply_effect_to_target(
    world,
    context,
    target,
    effect,
    hit_tile=None,
):
    effect_type = effect["type"]
    params = effect.get("params", {})

    if effect_type == "damage":
        queue_damage_request(
            world,
            source=context.get("owner") or context.get("instigator"),
            target=target,
            amount=params["amount"],
            skill_id=context.get("source_id"),
            hit_tile=hit_tile,
        )
        return

    raise ValueError(
        f"Unknown effect type: {effect_type}"
    )


def apply_effects_to_targets(
    world,
    context,
    targets,
    effects,
    hit_tile_by_target=None,
):
    for target in targets:
        hit_tile = None

        if hit_tile_by_target is not None:
            hit_tile = hit_tile_by_target.get(target)

        for effect in effects:
            apply_effect_to_target(
                world,
                context,
                target,
                effect,
                hit_tile=hit_tile,
            )


def build_square_area_tiles(center_tile, radius_tiles):
    tiles = []

    for dy in range(-radius_tiles, radius_tiles + 1):
        for dx in range(-radius_tiles, radius_tiles + 1):
            tiles.append(
                Vec2i(
                    center_tile.x + dx,
                    center_tile.y + dy,
                )
            )

    return tiles


def build_effect_context(effect_delivery, carrier=None):
    context = dict(effect_delivery.get("context", {}))

    if carrier is not None:
        context["carrier"] = carrier

    return context