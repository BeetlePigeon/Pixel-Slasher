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

    if not contact_targets:
        return

    dynamic_actor_response = get_projectile_dynamic_actor_response(
        projectile_data,
    )

    if dynamic_actor_response == "destroy_self":
        emit_projectile_dynamic_actor_contact(
            world,
            projectile,
            contact_targets[0],
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