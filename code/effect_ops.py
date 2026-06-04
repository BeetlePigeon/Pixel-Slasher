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
    materialization_context=None,
    effect_context=None,
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
        materialization_context=materialization_context,
        effect_context=effect_context,
    )

    world.effect_deliveries[eid] = effect_deliveries
    lifecycle = copy.deepcopy(effect_carrier_lifecycle)
    lifecycle["age"] = 0
    world.effect_carrier_lifecycle[eid] = lifecycle

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
    materialization_context=None,
    effect_context=None,
):
    effect_deliveries = []

    if materialization_context is None:
        materialization_context = {}

    if effect_context is None:
        effect_context = {}

    for effect_delivery_template in effect_delivery_templates:
        effect_delivery = copy.deepcopy(effect_delivery_template)

        selection = effect_delivery["selection"]
        materialize_snapshot_effect_selection(
            selection,
            anchor_tile=anchor_tile,
            materialization_context=materialization_context,
        )

        context = {
            "owner": source,
            "instigator": source,
            "source_kind": "skill",
            "source_id": skill_id,
        }
        context.update(effect_context)
        effect_delivery["context"] = context

        effect_delivery["runtime"] = {
            "age": 0,
            "delivered": False,
        }

        effect_deliveries.append(effect_delivery)

    return effect_deliveries


def materialize_snapshot_effect_selection(selection, anchor_tile, materialization_context):
    selection_type = selection["type"]

    if selection_type == "tiles":
        materialize_snapshot_tile_selection(
            selection,
            anchor_tile,
            materialization_context
        )
        return

    if selection_type in ("source", "owner", "contact_target"):
        return

    raise NotImplementedError(
        "Effect selection type not implemented for snapshot materialization: "
        f"{selection_type}"
    )


def materialize_snapshot_tile_selection(selection, anchor_tile, materialization_context):
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

    if shape_type == "slash_fan":
        direction = require_materialization_context_value(
            materialization_context,
            "direction",
            shape_type,
        )
        selection["tiles"] = build_slash_fan_tiles(
            anchor_tile,
            direction,
        )
        return

    if shape_type == "ranged_slash_fan":
        direction = require_materialization_context_value(
            materialization_context,
            "direction",
            shape_type,
        )
        selection["tiles"] = build_ranged_slash_fan_tiles(
            anchor_tile,
            direction,
            shape["range_tiles"],
        )
        return

    raise NotImplementedError(
        f"Effect tile selection shape not implemented: {shape_type}"
    )


def require_materialization_context_value(
    materialization_context,
    key,
    shape_type,
):
    if key not in materialization_context:
        raise ValueError(
            f"Effect selection shape {shape_type!r} requires "
            f"materialization context value {key!r}"
        )

    return materialization_context[key]


def build_slash_fan_tiles(origin_tile, direction):
    if direction.x == 0 and direction.y == 0:
        return []

    tiles = set()

    forward_tile = Vec2i(
        origin_tile.x + direction.x,
        origin_tile.y + direction.y,
    )
    tiles.add(forward_tile)

    if direction.x != 0 and direction.y != 0:
        tiles.add(Vec2i(
            origin_tile.x + direction.x,
            origin_tile.y,
        ))
        tiles.add(Vec2i(
            origin_tile.x,
            origin_tile.y + direction.y,
        ))
    elif direction.x != 0:
        tiles.add(Vec2i(
            forward_tile.x,
            forward_tile.y - 1,
        ))
        tiles.add(Vec2i(
            forward_tile.x,
            forward_tile.y + 1,
        ))
    else:
        tiles.add(Vec2i(
            forward_tile.x - 1,
            forward_tile.y,
        ))
        tiles.add(Vec2i(
            forward_tile.x + 1,
            forward_tile.y,
        ))

    return list(tiles)


def build_ranged_slash_fan_tiles(
    origin_tile,
    direction,
    range_tiles,
):
    tiles = set()

    if direction.x == 0 and direction.y == 0:
        return []

    for step in range(1, range_tiles + 1):
        forward_tile = Vec2i(
            origin_tile.x + direction.x * step,
            origin_tile.y + direction.y * step,
        )
        tiles.add(forward_tile)

        if direction.x != 0 and direction.y != 0:
            tiles.add(Vec2i(
                origin_tile.x + direction.x * step,
                origin_tile.y + direction.y * (step - 1),
            ))
            tiles.add(Vec2i(
                origin_tile.x + direction.x * (step - 1),
                origin_tile.y + direction.y * step,
            ))
        elif direction.x != 0:
            tiles.add(Vec2i(
                forward_tile.x,
                forward_tile.y - 1,
            ))
            tiles.add(Vec2i(
                forward_tile.x,
                forward_tile.y + 1,
            ))
        else:
            tiles.add(Vec2i(
                forward_tile.x - 1,
                forward_tile.y,
            ))
            tiles.add(Vec2i(
                forward_tile.x + 1,
                forward_tile.y,
            ))

    return list(tiles)


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