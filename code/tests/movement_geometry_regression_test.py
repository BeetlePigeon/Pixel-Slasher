import os
import sys
from types import SimpleNamespace

CODE_DIR = os.path.dirname(os.path.dirname(__file__))

if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from constants import TILE_UNITS
from motion_controllers import SettleToGridController
from support import Transform, Vec2i
from systems.movement_system import (
    movement_collision_allows,
    trace_static_tile_path,
)
from utils.occupancy_utils import (
    get_entity_reserved_center_tile,
    get_first_tile_entered_from_cpos,
)
from utils.tile_vec_utils import tile_center


def make_world(static_collision_tiles=()):
    return SimpleNamespace(
        tilemap=[
            [0 for _ in range(32)]
            for _ in range(32)
        ],
        static_collision_tiles=set(static_collision_tiles),
        movement_collision={},
        space_occupier={},
        transform={},
        motion_state={},
        dynamic_occupancy_dirty=False,
        dynamic_center_occupancy={},
        dynamic_body_occupancy={},
        dynamic_reserved_centers={},
        dynamic_reserved_bodies={},
        dynamic_occupancy={},
        dynamic_blocking_occupancy={},
        dynamic_reservations={},
    )


def add_single_tile_mover(world, entity, tile, cpos):
    world.movement_collision[entity] = {
        "static_tiles": "block",
        "dynamic_blockers": "allow",
        "corner_cutting": "allow",
    }

    world.space_occupier[entity] = {
        "blocks_movement": True,
        "movement_footprint": "single_tile",
    }

    world.transform[entity] = Transform(
        tile=tile,
        cpos=cpos,
        prev_cpos=cpos,
        position_mode="grid",
    )

    world.motion_state[entity] = {
        "controller": None,
    }


def static_tile_key(tile):
    return (tile.x, tile.y)


def assert_trace_allows(world, entity, start_cpos, end_cpos):
    collision_result, resolved_cpos = trace_static_tile_path(
        world,
        entity,
        start_cpos,
        end_cpos - start_cpos,
    )

    assert movement_collision_allows(collision_result), (
        collision_result,
        resolved_cpos,
    )

    assert resolved_cpos == end_cpos, (
        resolved_cpos,
        end_cpos,
    )


def test_same_tile_settle_reserves_no_tile():
    entity = 1
    tile = Vec2i(10, 10)
    center = tile_center(tile)

    start_cpos = Vec2i(
        center.x + TILE_UNITS // 4,
        center.y - TILE_UNITS // 4,
    )

    world = make_world()
    add_single_tile_mover(
        world,
        entity,
        tile,
        start_cpos,
    )

    world.motion_state[entity]["controller"] = SettleToGridController(
        start=start_cpos,
        end=center,
        progress=0,
        duration=3,
    )

    assert get_first_tile_entered_from_cpos(
        start_cpos,
        center,
    ) is None

    assert get_entity_reserved_center_tile(
        world,
        entity,
    ) is None


def test_same_tile_trace_does_not_revalidate_current_tile():
    entity = 1
    tile = Vec2i(10, 10)
    center = tile_center(tile)

    start_cpos = Vec2i(
        center.x + TILE_UNITS // 4,
        center.y,
    )

    world = make_world(
        static_collision_tiles={
            static_tile_key(tile),
        },
    )

    add_single_tile_mover(
        world,
        entity,
        tile,
        start_cpos,
    )

    assert_trace_allows(
        world,
        entity,
        start_cpos,
        center,
    )


def make_corner_trace_world(entity, start_tile, end_tile):
    side_x_tile = Vec2i(
        end_tile.x,
        start_tile.y,
    )
    side_y_tile = Vec2i(
        start_tile.x,
        end_tile.y,
    )

    world = make_world(
        static_collision_tiles={
            static_tile_key(side_x_tile),
            static_tile_key(side_y_tile),
        },
    )

    add_single_tile_mover(
        world,
        entity,
        start_tile,
        tile_center(start_tile),
    )

    return world


def test_exact_ne_corner_crossing_uses_corner_path():
    entity = 1
    start_tile = Vec2i(10, 10)
    end_tile = Vec2i(11, 9)

    world = make_corner_trace_world(
        entity,
        start_tile,
        end_tile,
    )

    assert_trace_allows(
        world,
        entity,
        tile_center(start_tile),
        tile_center(end_tile),
    )


def test_exact_sw_corner_crossing_uses_corner_path():
    entity = 1
    start_tile = Vec2i(10, 10)
    end_tile = Vec2i(9, 11)

    world = make_corner_trace_world(
        entity,
        start_tile,
        end_tile,
    )

    assert_trace_allows(
        world,
        entity,
        tile_center(start_tile),
        tile_center(end_tile),
    )


def test_near_ne_corner_crossing_uses_corner_path():
    entity = 1
    start_tile = Vec2i(10, 10)
    end_tile = Vec2i(11, 9)

    start_cpos = tile_center(start_tile) + Vec2i(20, -5)
    end_cpos = tile_center(end_tile)

    world = make_corner_trace_world(
        entity,
        start_tile,
        end_tile,
    )

    world.transform[entity].cpos = start_cpos
    world.transform[entity].prev_cpos = start_cpos

    assert_trace_allows(
        world,
        entity,
        start_cpos,
        end_cpos,
    )


def main():
    test_same_tile_settle_reserves_no_tile()
    test_same_tile_trace_does_not_revalidate_current_tile()
    test_exact_ne_corner_crossing_uses_corner_path()
    test_exact_sw_corner_crossing_uses_corner_path()
    test_near_ne_corner_crossing_uses_corner_path()

    print("Movement geometry regression tests passed.")


if __name__ == "__main__":
    main()