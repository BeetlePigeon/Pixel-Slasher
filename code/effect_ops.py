from support import Vec2i, Transform
import copy
from utils.tile_vec_utils import tile_from_cpos
from spawn_ops import can_spawn_at


def spawn_effect_carrier(
    world,
    cpos,
    source,
    skill_id,
    effect_delivery_templates,
    effect_carrier_lifecycle,
    visual=None,
    static_tiles_placement_handling="allow",
):
    if not can_spawn_at(world, cpos, static_tiles=static_tiles_placement_handling):
        return None

    eid = world.entities.create()
    tile = tile_from_cpos(cpos)

    world.transform[eid] = Transform(
        tile=tile,
        cpos=cpos,
        prev_cpos=cpos,
        position_mode="free",
    )

    effect_deliveries = materialize_effect_deliveries(
        effect_delivery_templates,
        anchor_tile=tile,
        source=source,
        skill_id=skill_id,
    )

    world.effect_deliveries[eid] = effect_deliveries
    world.effect_carrier_lifecycle[eid] = copy.deepcopy(
        effect_carrier_lifecycle
    )

    if visual is not None:
        image_id = visual["image"]
        world.sprite[eid] = {
            "image": world.game.assets.images[image_id],
            "anchor": visual["anchor"],
            "z": visual["z"],
        }

    return eid


def materialize_effect_deliveries(
    effect_delivery_templates,
    anchor_tile,
    source,
    skill_id,
):
    effect_deliveries = []

    for effect_delivery_template in effect_delivery_templates:
        effect_delivery = copy.deepcopy(effect_delivery_template)

        selection = effect_delivery["selection"]
        materialize_snapshot_effect_selection(
            selection,
            anchor_tile=anchor_tile,
        )

        effect_delivery["context"] = {
            "owner": source,
            "instigator": source,
            "source_kind": "skill",
            "source_id": skill_id,
        }

        effect_delivery["runtime"] = {
            "age": 0,
            "delivered": False,
        }

        effect_deliveries.append(effect_delivery)

    return effect_deliveries


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
    if "tiles" in selection:
        return

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