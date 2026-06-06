from support import Vec2i
from spawners import spawn_projectile
from utils.tile_vec_utils import tile_center, tile_from_cpos
from utils.status_utils import apply_status_effect
from combat_ops import (
    entities_are_enemies,
    entities_are_allies,
    get_entity_current_tile,
    queue_damage_request,
    queue_heal_request,
)


TARGET_PAYLOAD_TYPES = {
    "damage",
    "heal",
    "status",
}

DELIVERY_PAYLOAD_TYPES = {
    "spawn_projectiles",
}


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

    targets = []

    if effect_delivery_has_target_payloads(effect_delivery):
        targets = resolve_delivery_targets(
            world,
            carrier,
            effect_delivery,
            context,
        )
        targets = filter_targets_by_context_excluded_entities(
            effect_delivery,
            context,
            targets,
        )
        targets = filter_targets_by_target_cadence(
            effect_delivery,
            targets,
        )

    apply_effect_payloads_to_targets(
        world,
        effect_delivery,
        context,
        targets,
    )

    apply_delivery_level_payloads(
        world,
        effect_delivery,
        context,
    )

    record_target_cadence_hits(
        effect_delivery,
        targets,
    )

    if effect_delivery_completes_after_activation(effect_delivery):
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
            if get_effect_payload_scope(payload) != "target":
                continue

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


def apply_delivery_level_payloads(
    world,
    effect_delivery,
    context,
):
    payloads = effect_delivery["payloads"]

    for payload in payloads:
        if get_effect_payload_scope(payload) != "delivery":
            continue

        apply_delivery_level_payload(
            world,
            context,
            payload,
        )


def apply_delivery_level_payload(world, context, payload):
    payload_type = payload["type"]

    if payload_type == "spawn_projectiles":
        apply_spawn_projectiles_payload(
            world,
            context,
            payload,
        )
        return

    raise NotImplementedError(
        f"Delivery-level payload type not implemented: {payload_type}"
    )


def apply_spawn_projectiles_payload(world, context, payload):
    params = payload["params"]

    origin_tile = resolve_spawn_projectiles_origin_tile(
        world,
        context,
        params,
    )
    spawn_tiles = build_spawn_projectile_pattern_tiles(
        origin_tile,
        params["pattern"],
    )

    source = get_effect_source(context)
    skill_id = context.get("source_id")
    projectile_id = params["projectile_id"]
    spawn_params = params.get("spawn_params", {})

    for spawn_tile in spawn_tiles:
        spawn_projectile(
            world,
            projectile_id,
            tile_center(spawn_tile),
            aim_vector=None,
            source=source,
            skill_id=skill_id,
            spawn_params=spawn_params,
        )


def resolve_spawn_projectiles_origin_tile(
    world,
    context,
    params,
):
    origin = params["origin"]

    if origin == "carrier":
        carrier = context["carrier"]
        return tile_from_cpos(
            world.transform[carrier].cpos,
        )

    raise NotImplementedError(
        f"spawn_projectiles origin not implemented: {origin!r}"
    )


def build_spawn_projectile_pattern_tiles(origin_tile, pattern):
    pattern_type = pattern["type"]

    if pattern_type == "tile_offsets":
        return build_spawn_projectile_tile_offset_pattern(
            origin_tile,
            pattern,
        )

    raise NotImplementedError(
        f"spawn_projectiles pattern not implemented: {pattern_type!r}"
    )


def build_spawn_projectile_tile_offset_pattern(
    origin_tile,
    pattern,
):
    tiles = []

    for offset_pair in pattern["offsets"]:
        offset = Vec2i(
            offset_pair[0],
            offset_pair[1],
        )
        tiles.append(origin_tile + offset)

    return tiles


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

    if activation_type == "immediate":
        return immediate_activation_should_fire(runtime)

    if activation_type == "once":
        return once_activation_should_fire(
            activation,
            runtime,
        )

    if activation_type == "continuous":
        return continuous_activation_should_fire(
            activation,
            runtime,
        )

    raise NotImplementedError(
        f"Effect activation type not implemented: {activation_type}"
    )


def immediate_activation_should_fire(runtime):
    return not runtime.get("delivered", False)


def once_activation_should_fire(activation, runtime):
    return (
        not runtime.get("delivered", False)
        and runtime["age"] >= activation["tick"]
    )


def continuous_activation_should_fire(activation, runtime):
    check_interval_ticks = activation.get("check_interval_ticks", 1)

    if check_interval_ticks <= 0:
        raise ValueError(
            "continuous effect activation requires "
            "check_interval_ticks > 0"
        )

    return (runtime["age"] - 1) % check_interval_ticks == 0


def effect_delivery_completes_after_activation(effect_delivery):
    activation = effect_delivery["activation"]
    activation_type = activation["type"]

    if activation_type in ("immediate", "once"):
        return True

    if activation_type == "continuous":
        return False

    raise NotImplementedError(
        "Effect delivery completion behavior not implemented for "
        f"activation type: {activation_type}"
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

    if selection_type == "contact_target":
        return resolve_contact_target_selection_targets(
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


def resolve_contact_target_selection_targets(world, effect_delivery, context):
    contact_target = context.get("contact_target")
    filtering = get_effect_filtering(effect_delivery)

    return resolve_direct_selection_target(
        world,
        contact_target,
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
    unsupported_keys = set(filtering) - {
        "requires",
        "exclude_context_entities",
    }

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


def filter_targets_by_context_excluded_entities(
    effect_delivery,
    context,
    targets,
):
    filtering = get_effect_filtering(effect_delivery)
    excluded_context_entities = filtering.get(
        "exclude_context_entities",
        [],
    )

    if not excluded_context_entities:
        return targets

    excluded_entities = {
        context[context_key]
        for context_key in excluded_context_entities
        if context_key in context
    }

    return [
        target
        for target in targets
        if target not in excluded_entities
    ]


def filter_targets_by_target_cadence(effect_delivery, targets):
    target_cadence = effect_delivery.get("target_cadence")

    if target_cadence is None:
        return targets

    cadence_type = target_cadence["type"]

    if cadence_type == "once_per_delivery":
        return filter_targets_once_per_delivery(
            effect_delivery,
            targets,
        )

    if cadence_type == "per_target_cooldown":
        return filter_targets_per_target_cooldown(
            effect_delivery,
            target_cadence,
            targets,
        )

    raise NotImplementedError(
        f"Effect target cadence type not implemented: {cadence_type}"
    )


def filter_targets_once_per_delivery(effect_delivery, targets):
    runtime = effect_delivery["runtime"]
    hit_targets = runtime.setdefault("hit_targets", {})

    return [
        target
        for target in targets
        if target not in hit_targets
    ]


def filter_targets_per_target_cooldown(
    effect_delivery,
    target_cadence,
    targets,
):
    runtime = effect_delivery["runtime"]
    current_age = runtime["age"]
    next_eligible_by_target = runtime.setdefault(
        "next_eligible_by_target",
        {},
    )

    return [
        target
        for target in targets
        if current_age >= next_eligible_by_target.get(target, 0)
    ]


def record_target_cadence_hits(effect_delivery, targets):
    target_cadence = effect_delivery.get("target_cadence")

    if target_cadence is None:
        return

    cadence_type = target_cadence["type"]

    if cadence_type == "once_per_delivery":
        record_once_per_delivery_hits(
            effect_delivery,
            targets,
        )
        return

    if cadence_type == "per_target_cooldown":
        record_per_target_cooldown_hits(
            effect_delivery,
            target_cadence,
            targets,
        )
        return

    raise NotImplementedError(
        f"Effect target cadence type not implemented: {cadence_type}"
    )


def record_once_per_delivery_hits(effect_delivery, targets):
    runtime = effect_delivery["runtime"]
    hit_targets = runtime.setdefault("hit_targets", {})

    for target in targets:
        hit_targets[target] = True


def record_per_target_cooldown_hits(
    effect_delivery,
    target_cadence,
    targets,
):
    runtime = effect_delivery["runtime"]
    current_age = runtime["age"]
    cooldown_ticks = target_cadence["cooldown_ticks"]
    next_eligible_by_target = runtime.setdefault(
        "next_eligible_by_target",
        {},
    )

    for target in targets:
        next_eligible_by_target[target] = (
            current_age + cooldown_ticks
        )


def complete_effect_delivery(effect_delivery):
    runtime = effect_delivery["runtime"]
    runtime["delivered"] = True


def get_effect_payload_scope(payload):
    payload_type = payload["type"]

    if payload_type in TARGET_PAYLOAD_TYPES:
        return "target"

    if payload_type in DELIVERY_PAYLOAD_TYPES:
        return "delivery"

    raise NotImplementedError(
        f"Effect payload type not implemented: {payload_type}"
    )


def effect_delivery_has_target_payloads(effect_delivery):
    return any(
        get_effect_payload_scope(payload) == "target"
        for payload in effect_delivery["payloads"]
    )
