from data.tables_tile_footprints import get_footprint_offsets
from systems.event_system import emit_event
from utils.combat_body_utils import (
    get_entity_collision_tiles_for_origin_tile,
)
from utils.contact_filtering_utils import filter_contact_candidates
from utils.tile_vec_utils import tile_from_cpos
from policies import PROJECTILE_DYNAMIC_ACTOR_CONTACT_OVERLAP_POLICY


RAW_PROJECTILE_MOVEMENT_EVENT_TYPES = {
    "entity_movement_blocked",
    "entity_destroyed_by_movement_collision",
}


def projectile_impact_system(world):
    raw_events = list(world.events)
    destroyed_projectiles = set()

    destroyed_projectiles.update(
        handle_projectile_movement_impacts(
            world,
            raw_events,
        )
    )

    handle_projectile_dynamic_actor_contacts(
        world,
        destroyed_projectiles,
    )


def handle_projectile_movement_impacts(world, raw_events):
    destroyed_projectiles = set()

    for event in raw_events:
        if event["type"] not in RAW_PROJECTILE_MOVEMENT_EVENT_TYPES:
            continue

        projectile = event.get("entity")
        if projectile not in world.projectile:
            continue

        projectile_data = world.projectile[projectile]
        impact_event = build_projectile_movement_impact_event(
            event,
        )
        if impact_event is None:
            continue

        emit_projectile_impact_event(
            world,
            impact_event,
        )

        if apply_projectile_impact_response(
            world,
            projectile,
            projectile_data,
            impact_event,
        ):
            destroyed_projectiles.add(projectile)

    return destroyed_projectiles


def build_projectile_movement_impact_event(event):
    blocker_collision_type = event.get("blocker_collision_type")

    if blocker_collision_type == "static":
        impact_type = "projectile_static_impact"
    elif blocker_collision_type == "dynamic":
        impact_type = "projectile_dynamic_movement_impact"
    else:
        return None

    return {
        "type": impact_type,
        "source_event_type": event["type"],
        "entity": event["entity"],
        "projectile": event["entity"],
        "cpos": event["cpos"],
        "tile": event["tile"],
        "blocked_tile": event.get("blocked_tile"),
        "blocker_collision_type": blocker_collision_type,
        "blocker_entity": event.get("blocker_entity"),
    }


def handle_projectile_dynamic_actor_contacts(
    world,
    destroyed_projectiles,
):
    for projectile in sorted(world.projectile):
        if projectile in destroyed_projectiles:
            continue

        projectile_data = world.projectile[projectile]

        if "contact_footprint" not in projectile_data:
            continue

        if projectile not in world.transform:
            continue

        contact_targets = find_projectile_dynamic_actor_contacts(
            world,
            projectile,
            projectile_data,
        )

        contact_targets = filter_targets_by_projectile_contact_cadence(
            world,
            projectile_data,
            contact_targets,
        )

        if not contact_targets:
            continue

        handle_projectile_dynamic_actor_contact_targets(
            world,
            projectile,
            projectile_data,
            contact_targets,
        )


def handle_projectile_dynamic_actor_contact_targets(
    world,
    projectile,
    projectile_data,
    contact_targets,
):
    impact_response = get_projectile_impact_response(
        projectile_data,
        "projectile_dynamic_actor_contact",
    )

    if impact_response == "destroy_self":
        contact_target = contact_targets[0]

        impact_event = build_projectile_dynamic_actor_contact_event(
            world,
            projectile,
            contact_target,
        )
        emit_projectile_impact_event(
            world,
            impact_event,
        )
        record_projectile_contact_cadence_hits(
            world,
            projectile_data,
            (contact_target,),
        )
        world.entities.destroy(projectile)
        return

    if impact_response == "continue":
        for contact_target in contact_targets:
            impact_event = build_projectile_dynamic_actor_contact_event(
                world,
                projectile,
                contact_target,
            )
            emit_projectile_impact_event(
                world,
                impact_event,
            )

        record_projectile_contact_cadence_hits(
            world,
            projectile_data,
            contact_targets,
        )
        return

    raise NotImplementedError(
        "Projectile impact response not implemented for "
        f"projectile_dynamic_actor_contact: {impact_response}"
    )


def build_projectile_dynamic_actor_contact_event(
    world,
    projectile,
    contact_target,
):
    projectile_transform = world.transform[projectile]
    target_transform = world.transform[contact_target]

    projectile_tile = tile_from_cpos(
        projectile_transform.cpos,
    )
    target_tile = tile_from_cpos(
        target_transform.cpos,
    )

    return {
        "type": "projectile_dynamic_actor_contact",
        "entity": projectile,
        "projectile": projectile,
        "contact_target": contact_target,
        "cpos": projectile_transform.cpos,
        "tile": projectile_tile,
        "contact_tile": target_tile,
    }


def emit_projectile_impact_event(world, impact_event):
    emit_event(
        world,
        impact_event["type"],
        **{
            key: value
            for key, value in impact_event.items()
            if key != "type"
        },
    )


def apply_projectile_impact_response(
    world,
    projectile,
    projectile_data,
    impact_event,
):
    impact_response = get_projectile_impact_response(
        projectile_data,
        impact_event["type"],
    )

    if impact_response == "continue":
        return False

    if impact_response == "destroy_self":
        if projectile_data.get("id") == "homing_bolt":
            print(
                "[homing_bolt_destroy]",
                "tick=", world.tick,
                "impact_type=", impact_event["type"],
                "source_event_type=", impact_event.get("source_event_type"),
                "cpos=", impact_event.get("cpos"),
                "tile=", impact_event.get("tile"),
                "blocked_tile=", impact_event.get("blocked_tile"),
                "blocker_collision_type=", impact_event.get("blocker_collision_type"),
                "blocker_entity=", impact_event.get("blocker_entity"),
            )
        world.entities.destroy(projectile)
        return True

    raise NotImplementedError(
        "Projectile impact response not implemented for "
        f"{impact_event['type']}: {impact_response}"
    )


def get_projectile_impact_response(projectile_data, event_type):
    impact_responses = projectile_data.get("impact_responses", {})

    return impact_responses.get(
        event_type,
        "continue",
    )


def find_projectile_dynamic_actor_contacts(
    world,
    projectile,
    projectile_data,
):
    candidates = get_projectile_contact_candidates(
        world,
        projectile,
    )
    candidates = filter_targets_by_projectile_actor_contact_filter(
        world,
        projectile_data,
        candidates,
    )

    return tuple(
        target for target in candidates
        if projectile_contacts_dynamic_actor(
            world,
            projectile,
            projectile_data,
            target,
        )
    )


def filter_targets_by_projectile_actor_contact_filter(
    world,
    projectile_data,
    targets,
):
    actor_contact_filter = projectile_data.get("actor_contact_filter")

    if actor_contact_filter is None:
        return targets

    mode = actor_contact_filter["mode"]

    if mode == "normal":
        return targets

    if mode == "by_initial_homing_context":
        context_filter = get_actor_contact_context_filter(
            projectile_data,
            actor_contact_filter,
        )
        return filter_targets_by_actor_contact_context_filter(
            world,
            projectile_data,
            context_filter,
            targets,
        )

    raise NotImplementedError(
        f"Projectile actor contact filter mode not implemented: {mode!r}"
    )


def get_actor_contact_context_filter(
    projectile_data,
    actor_contact_filter,
):
    context_name = get_projectile_initial_homing_context_for_contact_filter(
        projectile_data,
        actor_contact_filter,
    )
    context_filters = actor_contact_filter["contexts"]

    if context_name in context_filters:
        return context_filters[context_name]

    if "default" in context_filters:
        return context_filters["default"]

    raise KeyError(
        f"Projectile actor contact filter has no context {context_name!r}"
    )


def get_projectile_initial_homing_context_for_contact_filter(
    projectile_data,
    actor_contact_filter,
):
    homing_behavior_index = actor_contact_filter.get(
        "homing_behavior_index",
        0,
    )
    behavior_runtime = projectile_data.get("behavior_runtime", {})
    homing_runtime = behavior_runtime.get(homing_behavior_index, {})

    return homing_runtime.get(
        "initial_homing_context",
        "unseeded",
    )


def filter_targets_by_actor_contact_context_filter(
    world,
    projectile_data,
    context_filter,
    targets,
):
    mode = context_filter["mode"]

    if mode == "normal":
        return targets

    if mode == "explicit_target_only":
        return filter_targets_by_explicit_target_only_actor_contact(
            world,
            projectile_data,
            context_filter,
            targets,
        )

    raise NotImplementedError(
        f"Projectile actor contact context filter mode not implemented: "
        f"{mode!r}"
    )


def filter_targets_by_explicit_target_only_actor_contact(
    world,
    projectile_data,
    context_filter,
    targets,
):
    explicit_target = get_projectile_contact_filter_explicit_target(
        projectile_data,
        context_filter,
    )

    if explicit_target_is_valid_actor_contact_target(
        world,
        explicit_target,
    ):
        return tuple(
            target for target in targets
            if target == explicit_target
        )

    on_lost = context_filter.get(
        "on_explicit_target_lost",
        "return_to_normal",
    )

    if on_lost == "return_to_normal":
        return targets

    if on_lost == "preserve_filter":
        return tuple()

    raise NotImplementedError(
        f"Explicit target lost behavior not implemented: {on_lost!r}"
    )


def get_projectile_contact_filter_explicit_target(
    projectile_data,
    context_filter,
):
    source = context_filter.get("target_source", "homing_runtime")

    if source == "homing_runtime":
        homing_behavior_index = context_filter.get(
            "homing_behavior_index",
            0,
        )
        behavior_runtime = projectile_data.get("behavior_runtime", {})
        homing_runtime = behavior_runtime.get(homing_behavior_index, {})
        return homing_runtime.get(
            "explicit_target",
            projectile_data.get("explicit_target"),
        )

    if source == "projectile_explicit_target":
        return projectile_data.get("explicit_target")

    raise NotImplementedError(
        f"Explicit actor contact target source not implemented: {source!r}"
    )


def explicit_target_is_valid_actor_contact_target(world, target):
    if target is None:
        return False

    if target not in world.transform:
        return False

    if target not in world.combat_body:
        return False

    health = world.health.get(target)

    if health is not None and health.get("current", 1) <= 0:
        return False

    return True


def get_projectile_contact_candidates(world, projectile):
    candidates = sorted(
        set(world.combat_body)
        & set(world.transform)
    )
    candidates = [
        candidate
        for candidate in candidates
        if candidate != projectile
    ]

    return filter_contact_candidates(
        world,
        projectile,
        candidates,
    )


def projectile_contacts_dynamic_actor(
    world,
    projectile,
    projectile_data,
    target,
):
    projectile_transform = world.transform[projectile]
    target_transform = world.transform[target]

    projectile_tile = tile_from_cpos(
        projectile_transform.cpos,
    )
    target_tile = tile_from_cpos(
        target_transform.cpos,
    )

    projectile_body_tiles = get_projectile_contact_tiles_for_origin_tile(
        projectile_data,
        projectile_tile,
    )
    target_body_tiles = get_entity_collision_tiles_for_origin_tile(
        world,
        target,
        target_tile,
    )

    return projectile_contact_footprints_overlap(
        projectile_tile,
        projectile_body_tiles,
        target_tile,
        target_body_tiles,
    )


def projectile_contact_footprints_overlap(
    projectile_tile,
    projectile_body_tiles,
    target_tile,
    target_body_tiles,
):
    policy = PROJECTILE_DYNAMIC_ACTOR_CONTACT_OVERLAP_POLICY

    if policy == "center_body":
        return (
            projectile_tile in target_body_tiles
            or target_tile in projectile_body_tiles
        )

    if policy == "any_tile":
        return bool(
            set(projectile_body_tiles)
            & set(target_body_tiles)
        )

    raise ValueError(
        "Unknown projectile dynamic actor contact overlap policy: "
        f"{policy!r}"
    )


def get_projectile_contact_tiles_for_origin_tile(
    projectile_data,
    origin_tile,
):
    contact_footprint = get_projectile_contact_footprint_name(
        projectile_data,
    )

    return tuple(
        origin_tile + offset
        for offset in get_footprint_offsets(contact_footprint)
    )


def get_projectile_contact_footprint_name(projectile_data):
    if "contact_footprint" not in projectile_data:
        raise KeyError(
            "Projectile has no contact_footprint"
        )

    return projectile_data["contact_footprint"]


def filter_targets_by_projectile_contact_cadence(
    world,
    projectile_data,
    targets,
):
    contact_cadence = projectile_data.get("contact_cadence")

    if contact_cadence is None:
        return targets

    cadence_type = contact_cadence["type"]

    if cadence_type == "once_per_projectile":
        return filter_targets_once_per_projectile(
            projectile_data,
            targets,
        )

    if cadence_type == "per_target_cooldown":
        return filter_targets_per_target_cooldown(
            world,
            projectile_data,
            contact_cadence,
            targets,
        )

    raise NotImplementedError(
        f"Projectile contact cadence type not implemented: {cadence_type}"
    )


def filter_targets_once_per_projectile(projectile_data, targets):
    runtime = projectile_data.setdefault("contact_runtime", {})
    hit_targets = runtime.setdefault("hit_targets", {})

    return tuple(
        target
        for target in targets
        if target not in hit_targets
    )


def filter_targets_per_target_cooldown(
    world,
    projectile_data,
    contact_cadence,
    targets,
):
    runtime = projectile_data.setdefault("contact_runtime", {})
    next_eligible_by_target = runtime.setdefault(
        "next_eligible_by_target",
        {},
    )

    return tuple(
        target
        for target in targets
        if world.tick >= next_eligible_by_target.get(target, 0)
    )


def record_projectile_contact_cadence_hits(
    world,
    projectile_data,
    targets,
):
    contact_cadence = projectile_data.get("contact_cadence")

    if contact_cadence is None:
        return

    cadence_type = contact_cadence["type"]

    if cadence_type == "once_per_projectile":
        record_once_per_projectile_hits(
            projectile_data,
            targets,
        )
        return

    if cadence_type == "per_target_cooldown":
        record_per_target_cooldown_hits(
            world,
            projectile_data,
            contact_cadence,
            targets,
        )
        return

    raise NotImplementedError(
        f"Projectile contact cadence type not implemented: {cadence_type}"
    )


def record_once_per_projectile_hits(projectile_data, targets):
    runtime = projectile_data.setdefault("contact_runtime", {})
    hit_targets = runtime.setdefault("hit_targets", {})

    for target in targets:
        hit_targets[target] = True


def record_per_target_cooldown_hits(
    world,
    projectile_data,
    contact_cadence,
    targets,
):
    runtime = projectile_data.setdefault("contact_runtime", {})
    cooldown_ticks = contact_cadence["cooldown_ticks"]
    next_eligible_by_target = runtime.setdefault(
        "next_eligible_by_target",
        {},
    )

    for target in targets:
        next_eligible_by_target[target] = (
            world.tick + cooldown_ticks
        )