import os
import sys
import argparse
from pathlib import Path

# Must happen before pygame display/audio initialization.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(PROJECT_ROOT),
    )
CODE_DIR = PROJECT_ROOT / "code"

import pygame

from constants import SIM_DT
from inputhandler import InputState
from main import Game
from support import Vec2i
from utils.tile_vec_utils import (
    tile_center,
    tile_from_cpos,
)
from utils.action_order_utils import set_action_order
from utils.placement_utils import is_tile_valid_for_entity_placement
from utils.perf_profiler import profile_scope
from utils.occupancy_utils import (
    mark_dynamic_occupancy_dirty,
    rebuild_dynamic_occupancy,
)


class NullKeys:
    def __getitem__(self, key):
        return False


def make_empty_input_state(mouse_pos=(0, 0)):
    return InputState(
        keys=NullKeys(),
        keys_pressed=set(),
        keys_released=set(),
        mouse_buttons=(False, False, False, False, False),
        mouse_pressed=set(),
        mouse_released=set(),
        mouse_pos=mouse_pos,
        quit=False,
    )


def set_entity_tile(world, entity, tile):
    cpos = tile_center(tile)
    transform = world.transform[entity]
    transform.tile = tile
    transform.cpos = cpos
    transform.prev_cpos = cpos
    transform.position_mode = "grid"


def remove_existing_enemies(world):
    enemy_entities = [
        entity for entity, team in list(world.team.items())
        if team == "enemy"
    ]

    for entity in enemy_entities:
        world.remove_entity(entity)
        world.entities.dead.discard(entity)


def tile_is_inside_map(world, tile):
    if tile.y < 0 or tile.y >= len(world.tilemap):
        return False

    row = world.tilemap[tile.y]

    if tile.x < 0 or tile.x >= len(row):
        return False

    return True


def tile_is_usable_spawn_tile(world, tile):
    if not tile_is_inside_map(world, tile):
        return False

    if (tile.x, tile.y) in world.static_collision_tiles:
        return False

    return True


def deterministic_enemy_tiles_around_player(world, count):
    player_tile = world.transform[world.player].tile

    offsets = [
        Vec2i(-10, -8),
        Vec2i(-8, -8),
        Vec2i(-6, -8),
        Vec2i(-4, -8),
        Vec2i(-2, -8),
        Vec2i(0, -8),
        Vec2i(2, -8),
        Vec2i(4, -8),
        Vec2i(6, -8),
        Vec2i(8, -8),

        Vec2i(-10, -6),
        Vec2i(-8, -6),
        Vec2i(-6, -6),
        Vec2i(-4, -6),
        Vec2i(-2, -6),
        Vec2i(0, -6),
        Vec2i(2, -6),
        Vec2i(4, -6),
        Vec2i(6, -6),
        Vec2i(8, -6),

        Vec2i(-10, 6),
        Vec2i(-8, 6),
        Vec2i(-6, 6),
        Vec2i(-4, 6),
        Vec2i(-2, 6),
        Vec2i(0, 6),
        Vec2i(2, 6),
        Vec2i(4, 6),
        Vec2i(6, 6),
        Vec2i(8, 6),

        Vec2i(-10, 8),
        Vec2i(-8, 8),
        Vec2i(-6, 8),
        Vec2i(-4, 8),
        Vec2i(-2, 8),
        Vec2i(0, 8),
        Vec2i(2, 8),
        Vec2i(4, 8),
        Vec2i(6, 8),
        Vec2i(8, 8),
    ]

    tiles = []

    for offset in offsets:
        tile = player_tile + offset

        if not tile_is_usable_spawn_tile(world, tile):
            continue

        tiles.append(tile)

        if len(tiles) >= count:
            return tiles

    raise RuntimeError(
        f"Could only find {len(tiles)} usable enemy spawn tiles; "
        f"requested {count}."
    )


def spawn_benchmark_enemies(world, count):
    enemy_tiles = deterministic_enemy_tiles_around_player(
        world,
        count,
    )

    enemies = []

    for index, tile in enumerate(enemy_tiles):
        enemy = world.spawn_training_dummy(tile)

        # Force deterministic AI scheduling instead of entity-id modulo spread.
        world.ai_agent[enemy]["next_think_tick"] = world.tick
        world.ai_agent[enemy]["think_interval_ticks"] = 10
        world.ai_agent[enemy]["blackboard"] = {}
        world.ai_agent[enemy]["target_entity"] = None

        enemies.append(enemy)

    return enemies


def spawn_benchmark_enemies_at_tiles(world, enemy_tiles):
    enemies = []

    for tile in enemy_tiles:
        if not tile_is_usable_spawn_tile(world, tile):
            raise RuntimeError(
                f"path_stress_04 enemy spawn tile is not usable: {tile}"
            )

        enemy = world.spawn_training_dummy(tile)

        # Force deterministic AI scheduling instead of entity-id modulo spread.
        world.ai_agent[enemy]["next_think_tick"] = world.tick
        world.ai_agent[enemy]["think_interval_ticks"] = 10
        world.ai_agent[enemy]["blackboard"] = {}
        world.ai_agent[enemy]["target_entity"] = None

        enemies.append(enemy)

    return enemies


def clear_profiler_history(profiler):
    profiler.current_frame = {}
    profiler.current_counters = {}
    profiler.history.clear()
    profiler.counter_history.clear()


def print_benchmark_timing_rows(profiler, limit):
    rows = profiler.get_summary_rows(limit=limit)

    print("")
    print("TIMINGS avg/peak/maxcall/calls/last")
    print("-" * 88)

    for row in rows:
        print(
            f"{row['name']:<32} "
            f"avg={row['avg_total_ms']:8.3f}ms "
            f"peak={row['peak_total_ms']:8.3f}ms "
            f"maxcall={row['peak_call_ms']:8.3f}ms "
            f"calls={row['avg_calls']:6.2f} "
            f"last={row.get('last_total_ms', 0.0):8.3f}ms "
            f"last_calls={row.get('last_calls', 0):3}"
        )


def print_benchmark_counter_rows(profiler, limit):
    rows = profiler.get_counter_summary_rows(limit=limit)

    print("")
    print("COUNTERS avg/peak/max/records/last")
    print("-" * 88)

    for row in rows:
        print(
            f"{row['name']:<32} "
            f"avg={row['avg_total']:8.1f} "
            f"peak={row['peak_total']:8.1f} "
            f"max={row['peak_value']:8.1f} "
            f"records={row['avg_records']:6.2f} "
            f"last={row.get('last_total', 0.0):8.1f} "
            f"last_records={row.get('last_records', 0):3}"
        )


def run_fixed_tick(
    game,
    input_state,
    before_tick=None,
):
    game.perf_profiler.begin_frame()

    try:
        with profile_scope(game.world, "sim.tick"):
            if before_tick is not None:
                before_tick(game)

            game.update_state(
                SIM_DT,
                input_state,
            )

    finally:
        game.perf_profiler.end_frame()


def run_fixed_ticks(
    game,
    tick_count,
    input_state,
    before_tick=None,
):
    for _ in range(tick_count):
        run_fixed_tick(
            game,
            input_state,
            before_tick=before_tick,
        )


def setup_path_stress_01(game, enemy_count):
    world = game.world

    # Use a map with more obstacle/path pressure.
    world.load_area(
        "test_dungeon",
        "default",
    )

    remove_existing_enemies(world)

    # Fixed player location. Adjust this tile later if this scenario
    # is not stressful enough on your local map.
    player_tile = Vec2i(18, 14)
    set_entity_tile(
        world,
        world.player,
        player_tile,
    )

    enemies = spawn_benchmark_enemies(
        world,
        enemy_count,
    )

    mark_dynamic_occupancy_dirty(world)
    rebuild_dynamic_occupancy(world)
    world.focus_camera_on_player()

    return {
        "scenario": "path_stress_01",
        "area": world.current_area.area_id,
        "player_tile": player_tile,
        "enemy_count": len(enemies),
    }


def build_scripted_player_route(world):
    player = world.player
    origin_tile = world.transform[player].tile

    candidate_offsets = [
        Vec2i(0, 0),
        Vec2i(8, 0),
        Vec2i(8, 5),
        Vec2i(2, 7),
        Vec2i(-6, 6),
        Vec2i(-7, 0),
        Vec2i(-5, -5),
        Vec2i(3, -5),
    ]

    route = []

    for offset in candidate_offsets:
        tile = origin_tile + offset

        if not tile_is_inside_map(world, tile):
            continue

        if not is_tile_valid_for_entity_placement(
            world,
            tile,
            entity=player,
            include_dynamic=False,
        ):
            continue

        if route and route[-1] == tile:
            continue

        route.append(tile)

    if len(route) < 2:
        raise RuntimeError(
            "path_stress_02 could not build a usable player route. "
            "Adjust candidate_offsets in build_scripted_player_route(...)."
        )

    return route


def make_scripted_player_route_state(world):
    return {
        "route": build_scripted_player_route(world),
        "target_index": 1,
    }


def get_scripted_player_route_target(world, route_state):
    player = world.player
    route = route_state["route"]

    player_tile = tile_from_cpos(
        world.transform[player].cpos,
    )

    target_index = route_state["target_index"]
    target_tile = route[target_index]

    if player_tile == target_tile:
        target_index = (target_index + 1) % len(route)
        route_state["target_index"] = target_index
        target_tile = route[target_index]

    return target_tile


def issue_scripted_player_route_order(world, route_state):
    player = world.player

    if player is None:
        return

    target_tile = get_scripted_player_route_target(
        world,
        route_state,
    )

    current_order = world.action_order.get(player)

    if (
        current_order is not None
        and current_order.get("type") == "move_to_position"
        and current_order.get("target_tile") == target_tile
    ):
        return

    set_action_order(
        world,
        player,
        {
            "type": "move_to_position",
            "actor": player,
            "target_lock": "none",
            "target_tile": target_tile,
            "target_cpos": tile_center(target_tile),
            "path_policy": "player_click_move",
            "track_mouse_while_held": False,
            "created_tick": world.tick,
            "press_mouse_pos": (0, 0),
        },
    )


def setup_path_stress_02(game, enemy_count):
    setup_info = setup_path_stress_01(
        game,
        enemy_count,
    )

    route_state = make_scripted_player_route_state(
        game.world,
    )

    setup_info["scenario"] = "path_stress_02"
    setup_info["player_route"] = route_state["route"]

    return setup_info, route_state


def setup_path_stress_03_open_chase(game, enemy_count):
    world = game.world

    # Broad open arena: isolates dynamic enemy crowding from static terrain.
    world.load_area(
        "destacker_arena",
        "default",
    )

    remove_existing_enemies(world)

    # Center-ish tile for the current 38-wide open arena. This keeps the
    # existing deterministic spawn offsets in-bounds for 40 enemies.
    player_tile = Vec2i(19, 15)

    set_entity_tile(
        world,
        world.player,
        player_tile,
    )

    enemies = spawn_benchmark_enemies(
        world,
        enemy_count,
    )

    mark_dynamic_occupancy_dirty(world)
    rebuild_dynamic_occupancy(world)
    world.focus_camera_on_player()

    return {
        "scenario": "path_stress_03_open_chase",
        "area": world.current_area.area_id,
        "player_tile": player_tile,
        "enemy_count": len(enemies),
    }


def setup_path_stress_04_two_lane_chase(game):
    world = game.world

    # Broad open arena: isolates dynamic enemy crowding from static terrain.
    world.load_area(
        "destacker_arena",
        "default",
    )

    remove_existing_enemies(world)

    # Put the player south of two side-by-side enemies.
    # The enemies share the same greedy target and should expose
    # side-by-side zigzag / lane fighting.
    player_tile = Vec2i(19, 24)

    enemy_tiles = [
        Vec2i(18, 12),
        Vec2i(20, 12),
    ]

    set_entity_tile(
        world,
        world.player,
        player_tile,
    )

    enemies = spawn_benchmark_enemies_at_tiles(
        world,
        enemy_tiles,
    )

    mark_dynamic_occupancy_dirty(world)
    rebuild_dynamic_occupancy(world)

    world.focus_camera_on_player()

    return {
        "scenario": "path_stress_04_two_lane_chase",
        "area": world.current_area.area_id,
        "player_tile": player_tile,
        "enemy_tiles": enemy_tiles,
        "enemy_count": len(enemies),
    }


def run_path_stress_01(args):
    pygame.init()
    pygame.mixer.init()

    os.chdir(CODE_DIR)

    game = Game()
    game.debug_mode = False
    game.perf_profiler.enabled = True

    setup_info = setup_path_stress_01(
        game,
        args.enemies,
    )

    input_state = make_empty_input_state(
        mouse_pos=(0, 0),
    )

    run_fixed_ticks(
        game,
        args.warmup_ticks,
        input_state,
    )

    clear_profiler_history(game.perf_profiler)

    run_fixed_ticks(
        game,
        args.measure_ticks,
        input_state,
    )

    print("")
    print("=" * 88)
    print("[benchmark]")
    print(f"scenario={setup_info['scenario']}")
    print(f"area={setup_info['area']}")
    print(f"player_tile={setup_info['player_tile']}")
    print(f"enemy_count={setup_info['enemy_count']}")
    print(f"warmup_ticks={args.warmup_ticks}")
    print(f"measure_ticks={args.measure_ticks}")
    print(f"world_tick={game.world.tick}")
    print("=" * 88)

    print_benchmark_timing_rows(
        game.perf_profiler,
        args.limit,
    )
    print_benchmark_counter_rows(
        game.perf_profiler,
        args.limit,
    )

    pygame.quit()


def run_path_stress_02(args):
    pygame.init()
    pygame.mixer.init()

    os.chdir(CODE_DIR)

    game = Game()
    game.debug_mode = False
    game.perf_profiler.enabled = True

    setup_info, route_state = setup_path_stress_02(
        game,
        args.enemies,
    )

    input_state = make_empty_input_state(
        mouse_pos=(0, 0),
    )

    def before_tick(game):
        issue_scripted_player_route_order(
            game.world,
            route_state,
        )

    run_fixed_ticks(
        game,
        args.warmup_ticks,
        input_state,
        before_tick=before_tick,
    )

    clear_profiler_history(game.perf_profiler)

    run_fixed_ticks(
        game,
        args.measure_ticks,
        input_state,
        before_tick=before_tick,
    )

    print("")
    print("=" * 88)
    print("[benchmark]")
    print(f"scenario={setup_info['scenario']}")
    print(f"area={setup_info['area']}")
    print(f"player_tile={setup_info['player_tile']}")
    print(f"player_route={setup_info['player_route']}")
    print(f"enemy_count={setup_info['enemy_count']}")
    print(f"warmup_ticks={args.warmup_ticks}")
    print(f"measure_ticks={args.measure_ticks}")
    print(f"world_tick={game.world.tick}")
    print("=" * 88)

    print_benchmark_timing_rows(
        game.perf_profiler,
        args.limit,
    )
    print_benchmark_counter_rows(
        game.perf_profiler,
        args.limit,
    )

    pygame.quit()


def run_path_stress_03_open_chase(args):
    pygame.init()
    pygame.mixer.init()
    os.chdir(CODE_DIR)

    game = Game()
    game.debug_mode = False
    game.perf_profiler.enabled = True

    setup_info = setup_path_stress_03_open_chase(
        game,
        args.enemies,
    )

    input_state = make_empty_input_state(
        mouse_pos=(0, 0),
    )

    run_fixed_ticks(
        game,
        args.warmup_ticks,
        input_state,
    )
    clear_profiler_history(game.perf_profiler)

    run_fixed_ticks(
        game,
        args.measure_ticks,
        input_state,
    )

    print("")
    print("=" * 88)
    print("[benchmark]")
    print(f"scenario={setup_info['scenario']}")
    print(f"area={setup_info['area']}")
    print(f"player_tile={setup_info['player_tile']}")
    print(f"enemy_count={setup_info['enemy_count']}")
    print(f"warmup_ticks={args.warmup_ticks}")
    print(f"measure_ticks={args.measure_ticks}")
    print(f"world_tick={game.world.tick}")
    print("=" * 88)

    print_benchmark_timing_rows(
        game.perf_profiler,
        args.limit,
    )
    print_benchmark_counter_rows(
        game.perf_profiler,
        args.limit,
    )

    pygame.quit()


def run_path_stress_04_two_lane_chase(args):
    pygame.init()
    pygame.mixer.init()

    os.chdir(CODE_DIR)

    game = Game()
    game.debug_mode = False
    game.perf_profiler.enabled = True

    setup_info = setup_path_stress_04_two_lane_chase(game)

    input_state = make_empty_input_state(
        mouse_pos=(0, 0),
    )

    run_fixed_ticks(
        game,
        args.warmup_ticks,
        input_state,
    )

    clear_profiler_history(game.perf_profiler)

    run_fixed_ticks(
        game,
        args.measure_ticks,
        input_state,
    )

    print("")
    print("=" * 88)
    print("[benchmark]")
    print(f"scenario={setup_info['scenario']}")
    print(f"area={setup_info['area']}")
    print(f"player_tile={setup_info['player_tile']}")
    print(f"enemy_tiles={setup_info['enemy_tiles']}")
    print(f"enemy_count={setup_info['enemy_count']}")
    print(f"warmup_ticks={args.warmup_ticks}")
    print(f"measure_ticks={args.measure_ticks}")
    print(f"world_tick={game.world.tick}")
    print("=" * 88)

    print_benchmark_timing_rows(
        game.perf_profiler,
        args.limit,
    )
    print_benchmark_counter_rows(
        game.perf_profiler,
        args.limit,
    )

    pygame.quit()


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Run deterministic Pixel Slasher performance benchmarks.",
    )
    subparsers = parser.add_subparsers(
        dest="scenario",
        required=True,
    )

    path_stress = subparsers.add_parser(
        "path_stress_01",
        help="Deterministic sim-only pathfinding stress benchmark.",
    )
    path_stress.add_argument(
        "--enemies",
        type=int,
        default=25,
    )
    path_stress.add_argument(
        "--warmup-ticks",
        type=int,
        default=60,
    )
    path_stress.add_argument(
        "--measure-ticks",
        type=int,
        default=600,
    )
    path_stress.add_argument(
        "--limit",
        type=int,
        default=64,
    )


    path_stress_02 = subparsers.add_parser(
        "path_stress_02",
        help="Deterministic sim-only moving-player chase benchmark.",
    )
    path_stress_02.add_argument(
        "--enemies",
        type=int,
        default=25,
    )
    path_stress_02.add_argument(
        "--warmup-ticks",
        type=int,
        default=60,
    )
    path_stress_02.add_argument(
        "--measure-ticks",
        type=int,
        default=600,
    )
    path_stress_02.add_argument(
        "--limit",
        type=int,
        default=64,
    )


    path_stress_03 = subparsers.add_parser(
        "path_stress_03_open_chase",
        help="Deterministic open-map fixed-player enemy crowd benchmark.",
    )
    path_stress_03.add_argument(
        "--enemies",
        type=int,
        default=25,
    )
    path_stress_03.add_argument(
        "--warmup-ticks",
        type=int,
        default=60,
    )
    path_stress_03.add_argument(
        "--measure-ticks",
        type=int,
        default=600,
    )
    path_stress_03.add_argument(
        "--limit",
        type=int,
        default=64,
    )


    path_stress_04 = subparsers.add_parser(
        "path_stress_04_two_lane_chase",
        help="Deterministic two-enemy side-by-side chase benchmark.",
    )
    path_stress_04.add_argument(
        "--warmup-ticks",
        type=int,
        default=60,
    )
    path_stress_04.add_argument(
        "--measure-ticks",
        type=int,
        default=600,
    )
    path_stress_04.add_argument(
        "--limit",
        type=int,
        default=64,
    )
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)

    if args.scenario == "path_stress_01":
        run_path_stress_01(args)
        return 0

    if args.scenario == "path_stress_02":
        run_path_stress_02(args)
        return 0

    if args.scenario == "path_stress_03_open_chase":
        run_path_stress_03_open_chase(args)
        return 0

    if args.scenario == "path_stress_04_two_lane_chase":
        run_path_stress_04_two_lane_chase(args)
        return 0
    
    raise ValueError(
        f"Unknown benchmark scenario: {args.scenario!r}"
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))