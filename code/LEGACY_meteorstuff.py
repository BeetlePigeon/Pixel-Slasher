from support import (
    Vec2i,
    tile_from_cpos,
)


def update_meteor_marker_runtime_entity(world, entity, runtime_entity):
    from combat_ops import queue_area_damage

    transform = world.transform.get(entity)

    if transform is None:
        world.entities.destroy(entity)
        return

    center_tile = tile_from_cpos(transform.cpos)

    affected_tiles = build_square_area_tiles(
        center_tile,
        runtime_entity["radius_tiles"],
    )

    if not runtime_entity.get("impacted", False):
        for tile in affected_tiles:
            world.game.debug.add_debug_tile_highlight(
                world,
                tile,
                duration_ticks=runtime_entity["telegraph_highlight_ticks"],
                color=runtime_entity["telegraph_highlight_color"],
            )

    if (
        not runtime_entity.get("impacted", False)
        and runtime_entity["age"] >= runtime_entity["impact_tick"]
    ):
        runtime_entity["impacted"] = True

        for tile in affected_tiles:
            world.game.debug.add_debug_tile_highlight(
                world,
                tile,
                duration_ticks=runtime_entity["impact_highlight_ticks"],
                color=runtime_entity["impact_highlight_color"],
            )

        queue_area_damage(
            world,
            source=runtime_entity["source"],
            tiles=affected_tiles,
            amount=runtime_entity["damage"],
            skill_id=runtime_entity["skill_id"],
        )

        world.entities.destroy(entity)
        return

    if runtime_entity["age"] >= runtime_entity["duration"]:
        world.entities.destroy(entity)


def runtime_entity_system(world):
    for entity, runtime_entity in list(world.runtime_entity.items()):
        runtime_entity["age"] += 1

        runtime_type = runtime_entity["type"]

        if runtime_type == "meteor_marker":
            update_meteor_marker_runtime_entity(
                world,
                entity,
                runtime_entity,
            )

        else:
            raise ValueError(
                f"Unknown runtime skill type: {runtime_type}"
            )


def build_square_area_tiles(center_tile, radius_tiles):
    tiles = []

    for dy in range(-radius_tiles, radius_tiles + 1):
        for dx in range(-radius_tiles, radius_tiles + 1):
            tiles.append(Vec2i(
                center_tile.x + dx,
                center_tile.y + dy,
            ))

    return tiles