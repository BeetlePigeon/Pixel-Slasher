from support import Vec2i
from combat_ops import (
    find_hittable_entities_on_tiles,
    get_entity_current_tile,
    queue_damage_request,
)


def effect_delivery_system(world):
    for carrier, effect_delivery in list(world.effect_delivery.items()):
        process_effect_delivery(
            world,
            carrier,
            effect_delivery,
        )


def process_effect_delivery(world, carrier, effect_delivery):
    delivery = effect_delivery["delivery"]

    delivery["age"] = delivery.get("age", 0) + 1


    if not delivery_should_fire(delivery):
        return

    targets = resolve_delivery_targets(
        world,
        carrier,
        effect_delivery,
    )

    apply_effects_to_targets(
        world,
        carrier,
        effect_delivery,
        targets,
    )

    consume_effect_delivery(
        world,
        carrier,
        effect_delivery,
    )


def apply_effects_to_targets(
    world,
    carrier,
    effect_delivery,
    targets,
):
    context = build_effect_context(
        carrier,
        effect_delivery,
    )

    for target in targets:
        for effect in effect_delivery["effects"]:

            effect_type = effect["type"]

            if effect_type == "damage":
                queue_damage_request(
                    world,
                    source=context.get("owner") or context.get("instigator"),
                    target=target,
                    amount=effect["params"]["amount"],
                    skill_id=context.get("source_id"),
                    hit_tile=get_entity_current_tile(world, target),
                )
                continue


def build_effect_context(carrier, effect_delivery):
    context = dict(effect_delivery.get("context", {}))
    context["carrier"] = carrier

    return context


def delivery_should_fire(delivery):
    delivery_type = delivery["type"]

    if delivery_type == "timed_tiles":
        return timed_tiles_delivery_should_fire(delivery)

    raise NotImplementedError(
        f"Effect delivery type not implemented: {delivery_type}"
    )


def timed_tiles_delivery_should_fire(delivery):
    if delivery.get("delivered", False):
        return False

    trigger = delivery["trigger"]

    return trigger_should_fire(
        trigger,
        delivery["age"],
    )


def trigger_should_fire(trigger, age):
    trigger_type = trigger["type"]

    if trigger_type == "once":
        return once_trigger_should_fire(
            trigger,
            age,
        )

    raise NotImplementedError(
        f"Effect delivery trigger type not implemented: {trigger_type}"
    )


def once_trigger_should_fire(trigger, age):
    return age >= trigger["tick"]


def resolve_delivery_targets(world, carrier, effect_delivery):
    delivery = effect_delivery["delivery"]
    delivery_type = delivery["type"]

    if delivery_type == "timed_tiles":
        return resolve_timed_tiles_targets(
            world,
            carrier,
            effect_delivery,
        )

    raise NotImplementedError(
        f"Effect delivery type not implemented: {delivery_type}"
    )


def resolve_timed_tiles_targets(world, carrier, effect_delivery):
    delivery = effect_delivery["delivery"]
    context = build_effect_context(
        carrier,
        effect_delivery,
    )

    source = context.get("owner") or context.get("instigator")

    return find_hittable_entities_on_tiles(
        world,
        source,
        delivery["tiles"],
    )


def consume_effect_delivery(world, carrier, effect_delivery):
    delivery = effect_delivery["delivery"]
    delivery["delivered"] = True

    consume_policy = effect_delivery.get("consume_policy", {})

    if consume_policy.get("destroy_carrier_after_delivery", False):
        world.entities.destroy(carrier)


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