from support import Vec2i


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