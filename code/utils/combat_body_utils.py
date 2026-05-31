from data.tables_tile_footprints import get_footprint_offsets
from utils.tile_vec_utils import tile_from_cpos


def get_combat_body(world, entity):
    return world.combat_body.get(
        entity,
        {},
    )


def get_entity_engagement_footprint_name(world, entity):
    combat_body = get_combat_body(
        world,
        entity,
    )

    return combat_body.get(
        "engagement_footprint",
        "single_tile",
    )


def get_entity_collision_footprint_name(world, entity):
    combat_body = get_combat_body(
        world,
        entity,
    )

    return combat_body.get(
        "collision_footprint",
        "single_tile",
    )


def get_entity_engagement_footprint_offsets(world, entity):
    return get_footprint_offsets(
        get_entity_engagement_footprint_name(
            world,
            entity,
        )
    )


def get_entity_collision_footprint_offsets(world, entity):
    return get_footprint_offsets(
        get_entity_collision_footprint_name(
            world,
            entity,
        )
    )


def get_footprint_tiles_for_origin_tile(offsets, origin_tile):
    return tuple(
        origin_tile + offset
        for offset in offsets
    )


def get_entity_engagement_tiles_for_origin_tile(
    world,
    entity,
    origin_tile,
):
    return get_footprint_tiles_for_origin_tile(
        get_entity_engagement_footprint_offsets(
            world,
            entity,
        ),
        origin_tile,
    )


def get_entity_collision_tiles_for_origin_tile(
    world,
    entity,
    origin_tile,
):
    return get_footprint_tiles_for_origin_tile(
        get_entity_collision_footprint_offsets(
            world,
            entity,
        ),
        origin_tile,
    )


def get_entity_engagement_tiles(world, entity):
    transform = world.transform.get(entity)

    if transform is None:
        return ()

    origin_tile = tile_from_cpos(
        transform.cpos,
    )

    return get_entity_engagement_tiles_for_origin_tile(
        world,
        entity,
        origin_tile,
    )


def get_entity_collision_tiles(world, entity):
    transform = world.transform.get(entity)

    if transform is None:
        return ()

    origin_tile = tile_from_cpos(
        transform.cpos,
    )

    return get_entity_collision_tiles_for_origin_tile(
        world,
        entity,
        origin_tile,
    )