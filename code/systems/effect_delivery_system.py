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
    advance_delivery_age(delivery)

    if not delivery_should_fire(delivery):
        return

    context = build_effect_context(
        carrier,
        effect_delivery,
    )
    targets = resolve_delivery_targets(
        world,
        carrier,
        effect_delivery,
        context,
    )
    apply_effect_payloads_to_targets(
        world,
        effect_delivery,
        context,
        targets,
    )
    consume_effect_delivery(
        world,
        carrier,
        effect_delivery,
    )


def advance_delivery_age(delivery):
    delivery["age"] = delivery.get("age", 0) + 1


def apply_effect_payloads_to_targets(
    world,
    effect_delivery,
    context,
    targets,
):
    payloads = effect_delivery["payloads"]

    for target in targets:
        for payload in payloads:
            apply_effect_payload_to_target(
                world,
                context,
                target,
                payload,
            )


def apply_effect_payload_to_target(
    world,
    context,
    target,
    payload,
):
    payload_type = payload["type"]

    if payload_type == "damage":
        apply_damage_payload(
            world,
            context,
            target,
            payload,
        )
        return

    raise NotImplementedError(
        f"Effect payload type not implemented: {payload_type}"
    )


def apply_damage_payload(
    world,
    context,
    target,
    payload,
):
    params = payload["params"]

    queue_damage_request(
        world,
        source=get_effect_source(context),
        target=target,
        amount=params["amount"],
        skill_id=context.get("source_id"),
        hit_tile=get_entity_current_tile(world, target),
    )


def build_effect_context(carrier, effect_delivery):
    context = dict(effect_delivery.get("context", {}))
    context["carrier"] = carrier

    return context


def get_effect_source(context):
    return context.get("owner") or context.get("instigator")


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


def resolve_delivery_targets(world, carrier, effect_delivery, context):
    delivery = effect_delivery["delivery"]
    delivery_type = delivery["type"]

    if delivery_type == "timed_tiles":
        return resolve_timed_tiles_targets(
            world,
            carrier,
            effect_delivery,
            context,
        )

    raise NotImplementedError(
        f"Effect delivery type not implemented: {delivery_type}"
    )


def resolve_timed_tiles_targets(world, carrier, effect_delivery, context):
    delivery = effect_delivery["delivery"]
    targeting = get_effect_targeting(effect_delivery)

    return resolve_targets_on_tiles(
        world,
        context,
        targeting,
        delivery["tiles"],
    )


def get_effect_targeting(effect_delivery):
    return effect_delivery["targeting"]


def resolve_targets_on_tiles(world, context, targeting, tiles):
    relationship = targeting.get("relationship", "enemies")
    requires = targeting.get("requires", ["hittable"])
    include_source = targeting.get("include_source", False)

    if (
        relationship == "enemies"
        and requires == ["hittable"]
        and not include_source
    ):
        return find_hittable_entities_on_tiles(
            world,
            get_effect_source(context),
            tiles,
        )

    raise NotImplementedError(
        "Effect delivery targeting not implemented: "
        f"relationship={relationship!r}, "
        f"requires={requires!r}, "
        f"include_source={include_source!r}"
    )


def consume_effect_delivery(world, carrier, effect_delivery):
    delivery = effect_delivery["delivery"]
    delivery["delivered"] = True

    consume_policy = get_consume_policy(effect_delivery)
    if should_destroy_carrier_after_delivery(consume_policy):
        world.entities.destroy(carrier)


def get_consume_policy(effect_delivery):
    return effect_delivery.get("consume_policy", {})


def should_destroy_carrier_after_delivery(consume_policy):
    return consume_policy.get("destroy_carrier_after_delivery", False)


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