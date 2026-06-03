from support import Vec2i
from utils.status_utils import apply_status_effect
from combat_ops import (
    entities_are_enemies,
    entities_are_allies,
    get_entity_current_tile,
    queue_damage_request,
    queue_heal_request,
)


def effect_delivery_system(world):
    for carrier, effect_deliveries in list(world.effect_deliveries.items()):
        for effect_delivery in list(effect_deliveries):
            process_effect_delivery(
                world,
                carrier,
                effect_delivery,
            )


def process_effect_delivery(world, carrier, effect_delivery):
    advance_effect_runtime(effect_delivery)

    if not activation_should_fire(effect_delivery):
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
    complete_effect_delivery(effect_delivery)


def advance_effect_runtime(effect_delivery):
    runtime = effect_delivery["runtime"]
    runtime["age"] = runtime.get("age", 0) + 1


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

    if payload_type == "heal":
        apply_heal_payload(
            world,
            context,
            target,
            payload,
        )
        return

    if payload_type == "status":
        apply_status_payload(
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


def apply_heal_payload(
    world,
    context,
    target,
    payload,
):
    params = payload["params"]

    queue_heal_request(
        world,
        source=get_effect_source(context),
        target=target,
        amount=params["amount"],
        skill_id=context.get("source_id"),
        hit_tile=get_entity_current_tile(world, target),
    )


def apply_status_payload(
    world,
    context,
    target,
    payload,
):
    params = payload["params"]

    apply_status_effect(
        world,
        target,
        status_id=params["status_id"],
        tags=params.get("tags", []),
        duration=params["duration"],
        data=params.get("data"),
        refresh_mode=params.get("refresh_mode", "replace"),
        cancels_action_tags=params.get("cancels_action_tags"),
        pauses_action_tags=params.get("pauses_action_tags"),
        cancels_motion_tags=params.get("cancels_motion_tags"),
    )


def build_effect_context(carrier, effect_delivery):
    context = dict(effect_delivery.get("context", {}))
    context["carrier"] = carrier

    return context


def get_effect_source(context):
    return context.get("owner") or context.get("instigator")


def activation_should_fire(effect_delivery):
    activation = effect_delivery["activation"]
    runtime = effect_delivery["runtime"]

    activation_type = activation["type"]

    if activation_type == "once":
        return once_activation_should_fire(
            activation,
            runtime,
        )

    raise NotImplementedError(
        f"Effect activation type not implemented: {activation_type}"
    )


def once_activation_should_fire(activation, runtime):
    return (
        not runtime.get("delivered", False)
        and runtime["age"] >= activation["tick"]
    )


def resolve_delivery_targets(world, carrier, effect_delivery, context):
    selection = effect_delivery["selection"]
    selection_type = selection["type"]

    if selection_type == "tiles":
        return resolve_tile_selection_targets(
            world,
            carrier,
            effect_delivery,
            context,
        )

    if selection_type == "source":
        return resolve_source_selection_targets(
            world,
            effect_delivery,
            context,
        )

    if selection_type == "owner":
        return resolve_owner_selection_targets(
            world,
            effect_delivery,
            context,
        )

    raise NotImplementedError(
        f"Effect selection type not implemented: {selection_type}"
    )


def resolve_tile_selection_targets(world, carrier, effect_delivery, context):
    selection = effect_delivery["selection"]
    filtering = get_effect_filtering(effect_delivery)

    return resolve_targets_on_tiles(
        world,
        context,
        filtering,
        selection["tiles"],
    )


def resolve_source_selection_targets(world, effect_delivery, context):
    source = get_effect_source(context)
    filtering = get_effect_filtering(effect_delivery)

    return resolve_direct_selection_target(
        world,
        source,
        filtering,
    )


def resolve_owner_selection_targets(world, effect_delivery, context):
    owner = context.get("owner")
    filtering = get_effect_filtering(effect_delivery)

    return resolve_direct_selection_target(
        world,
        owner,
        filtering,
    )


def resolve_direct_selection_target(world, entity, filtering):
    if entity is None:
        return []

    requirements = get_direct_selection_requirements(filtering)

    if not entity_satisfies_requirements(
        world,
        entity,
        requirements,
    ):
        return []

    return [entity]


def get_direct_selection_requirements(filtering):
    unsupported_keys = set(filtering) - {"requires"}

    if unsupported_keys:
        raise NotImplementedError(
            "Direct effect selection only supports requirements filtering, "
            f"got unsupported keys: {sorted(unsupported_keys)!r}"
        )

    return filtering.get("requires", [])


def get_effect_filtering(effect_delivery):
    return effect_delivery["filtering"]


def resolve_targets_on_tiles(world, context, filtering, tiles):
    tile_set = set(tiles)
    source = get_effect_source(context)

    targets = []

    for entity in sorted(world.transform):
        if entity == source and not filtering["include_source"]:
            continue

        if not entity_satisfies_requirements(
            world,
            entity,
            filtering["requires"],
        ):
            continue

        if not entity_matches_relationship(
            world,
            source,
            entity,
            filtering["relationship"],
        ):
            continue

        entity_tile = get_entity_current_tile(world, entity)
        if entity_tile not in tile_set:
            continue

        targets.append(entity)

    return targets


def entity_satisfies_requirements(world, entity, requirements):
    for requirement in requirements:
        if not entity_satisfies_requirement(
            world,
            entity,
            requirement,
        ):
            return False

    return True


def entity_satisfies_requirement(world, entity, requirement):
    if requirement == "hittable":
        hittable = world.hittable.get(entity)
        return (
            hittable is not None
            and hittable.get("enabled", True)
        )

    if requirement == "health":
        return entity in world.health

    raise NotImplementedError(
        f"Effect delivery target requirement not implemented: {requirement}"
    )


def entity_matches_relationship(world, source, target, relationship):
    if relationship == "enemies":
        return entities_are_enemies(world, source, target)

    if relationship == "allies":
        return entities_are_allies(world, source, target)

    if relationship == "any":
        return True

    raise NotImplementedError(
        f"Effect delivery target relationship not implemented: {relationship}"
    )


def complete_effect_delivery(effect_delivery):
    runtime = effect_delivery["runtime"]
    runtime["delivered"] = True


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


def materialize_snapshot_effect_selection(selection, anchor_tile):
    selection_type = selection["type"]

    if selection_type == "tiles":
        materialize_snapshot_tile_selection(
            selection,
            anchor_tile,
        )
        return

    if selection_type in ("source", "owner"):
        return

    raise NotImplementedError(
        "Effect selection type not implemented for snapshot materialization: "
        f"{selection_type}"
    )


def materialize_snapshot_tile_selection(selection, anchor_tile):
    shape = selection.pop("shape")
    shape_type = shape["type"]

    if shape_type == "square":
        selection["tiles"] = build_square_area_tiles(
            anchor_tile,
            shape["radius_tiles"],
        )
        return

    raise NotImplementedError(
        f"Effect tile selection shape not implemented: {shape_type}"
    )