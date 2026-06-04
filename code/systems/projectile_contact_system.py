from data.tables_tile_footprints import get_footprint_offsets
from systems.event_system import emit_event
from utils.combat_body_utils import (
    get_entity_collision_tiles_for_origin_tile,
)
from utils.contact_filtering_utils import filter_contact_candidates
from utils.tile_vec_utils import tile_from_cpos


def projectile_contact_system(world):
    for projectile in sorted(world.projectile):
        projectile_data = world.projectile[projectile]

        if "contact_footprint" not in projectile_data:
            continue

        if projectile not in world.transform:
            continue

        handle_projectile_dynamic_actor_contacts(
            world,
            projectile,
            projectile_data,
        )


def handle_projectile_dynamic_actor_contacts(
    world,
    projectile,
    projectile_data,
):
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
        return

    dynamic_actor_response = get_projectile_dynamic_actor_response(
        projectile_data,
    )

    if dynamic_actor_response == "destroy_self":
        contact_target = contact_targets[0]

        emit_projectile_dynamic_actor_contact(
            world,
            projectile,
            contact_target,
        )
        record_projectile_contact_cadence_hits(
            world,
            projectile_data,
            (contact_target,),
        )
        world.entities.destroy(projectile)
        return

    if dynamic_actor_response == "continue":
        for contact_target in contact_targets:
            emit_projectile_dynamic_actor_contact(
                world,
                projectile,
                contact_target,
            )

        record_projectile_contact_cadence_hits(
            world,
            projectile_data,
            contact_targets,
        )
        return

    raise NotImplementedError(
        "Projectile dynamic actor response not implemented: "
        f"{dynamic_actor_response}"
    )


def get_projectile_dynamic_actor_response(projectile_data):
    contact_response = projectile_data.get("contact_response", {})

    return contact_response.get(
        "dynamic_actor",
        "continue",
    )


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


def emit_projectile_dynamic_actor_contact(
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

    emit_event(
        world,
        "projectile_dynamic_actor_contact",
        entity=projectile,
        projectile=projectile,
        contact_target=contact_target,
        cpos=projectile_transform.cpos,
        tile=projectile_tile,
        contact_tile=target_tile,
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

    return tuple(
        target
        for target in candidates
        if projectile_contacts_dynamic_actor(
            world,
            projectile,
            projectile_data,
            target,
        )
    )


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

    return (
        projectile_tile in target_body_tiles
        or target_tile in projectile_body_tiles
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