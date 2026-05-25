import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAPS_DIR = PROJECT_ROOT / "maps"


def load_area_map(map_file):
    path = MAPS_DIR / map_file

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    return normalize_area_map(data, path)


def normalize_area_map(data, path):
    required_fields = {
        "id",
        "tile_image_assets",
        "layers",
        "collision",
        "objects",
        "transitions",
    }

    missing_fields = required_fields - set(data)
    if missing_fields:
        raise ValueError(
            f"Map file {path} is missing fields: {sorted(missing_fields)}"
        )

    floor_layer = data["layers"].get("floor")
    if floor_layer is None:
        raise ValueError(
            f"Map file {path} is missing layers.floor"
        )

    validate_rectangular_int_grid(
        floor_layer,
        path,
        "layers.floor",
    )

    tile_image_assets = normalize_tile_image_assets(
        data["tile_image_assets"],
        path,
    )

    static_collision_tiles = build_static_collision_tiles(
        floor_layer,
        data["collision"],
        path,
    )

    spawn_points = {}
    placed_entities = []

    for object_def in data["objects"]:
        object_type = object_def.get("type")

        if object_type == "spawn_point":
            spawn_id = object_def["spawn_id"]

            if spawn_id in spawn_points:
                raise ValueError(
                    f"Map file {path} has duplicate spawn point "
                    f"{spawn_id!r}"
                )

            spawn_points[spawn_id] = {
                "tile": tuple(object_def["tile"]),
                "facing": tuple(object_def["facing"]),
            }
            continue

        placed_entity = dict(object_def)
        
        if "tile" in placed_entity:
            placed_entity["tile"] = tuple(placed_entity["tile"])

        placed_entities.append(placed_entity)

    if not spawn_points:
        raise ValueError(
            f"Map file {path} must define at least one spawn_point object"
        )

    transitions = []

    for transition_def in data["transitions"]:
        transition = dict(transition_def)

        if "tiles" in transition:
            transition["tiles"] = [
                tuple(tile)
                for tile in transition["tiles"]
            ]

        transitions.append(transition)

    return {
        "id": data["id"],
        "tilemap": [
            list(row)
            for row in floor_layer
        ],
        "tile_image_assets": tile_image_assets,
        "static_collision_tiles": static_collision_tiles,
        "spawn_points": spawn_points,
        "placed_entities": placed_entities,
        "transitions": transitions,
    }


def normalize_tile_image_assets(tile_image_assets, path):
    normalized = {}

    for tile_id, asset_key in tile_image_assets.items():
        try:
            normalized_tile_id = int(tile_id)
        except ValueError as error:
            raise ValueError(
                f"Map file {path} has non-integer tile id "
                f"{tile_id!r} in tile_image_assets"
            ) from error

        if not isinstance(asset_key, str):
            raise ValueError(
                f"Map file {path} tile_image_assets[{tile_id!r}] "
                f"must be a string asset key"
            )

        normalized[normalized_tile_id] = asset_key

    return normalized


def validate_rectangular_int_grid(grid, path, field_name):
    if not isinstance(grid, list) or not grid:
        raise ValueError(
            f"Map file {path} {field_name} must be a non-empty list"
        )

    expected_width = None

    for y, row in enumerate(grid):
        if not isinstance(row, list) or not row:
            raise ValueError(
                f"Map file {path} {field_name} row {y} "
                f"must be a non-empty list"
            )

        if expected_width is None:
            expected_width = len(row)
        elif len(row) != expected_width:
            raise ValueError(
                f"Map file {path} {field_name} row {y} has width "
                f"{len(row)}, expected {expected_width}"
            )

        for x, value in enumerate(row):
            if not isinstance(value, int):
                raise ValueError(
                    f"Map file {path} {field_name}[{y}][{x}] "
                    f"must be an int"
                )


def build_static_collision_tiles(floor_layer, collision_def, path):
    blocked_floor_tile_ids = set(
        collision_def.get("blocked_floor_tile_ids", [])
    )

    blocked_tiles = {
        tuple(tile)
        for tile in collision_def.get("blocked_tiles", [])
    }

    for tile_id in blocked_floor_tile_ids:
        if not isinstance(tile_id, int):
            raise ValueError(
                f"Map file {path} collision.blocked_floor_tile_ids "
                f"must contain ints"
            )

    for y, row in enumerate(floor_layer):
        for x, tile_id in enumerate(row):
            if tile_id in blocked_floor_tile_ids:
                blocked_tiles.add((x, y))

    return blocked_tiles