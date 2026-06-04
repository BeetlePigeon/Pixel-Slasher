from data.tables_tile_footprints import get_footprint_offsets
from utils.tile_vec_utils import tile_from_cpos


def get_combat_body(world, entity):
    combat_body = world.combat_body.get(entity)
    if combat_body is None:
        raise KeyError(
            f"Entity {entity} has no combat_body component"
        )

    return combat_body


def get_entity_collision_footprint_name(world, entity):
    combat_body = get_combat_body(
        world,
        entity,
    )

    if "collision_footprint" not in combat_body:
        raise KeyError(
            f"Entity {entity} combat_body has no collision_footprint"
        )

    return combat_body["collision_footprint"]


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