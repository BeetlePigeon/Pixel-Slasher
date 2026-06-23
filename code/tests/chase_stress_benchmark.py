import argparse
import copy
import math
import os
import sys
from pathlib import Path


# Keep this benchmark usable without opening a real window.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CODE_DIR = PROJECT_ROOT / "code"

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(CODE_DIR))


import pygame

from constants import INTERNAL_RES, SIM_DT
from entity import EntityManager
from gamestate import StateGameplay
from inputhandler import InputState
from motion_controllers import ChaseEntityController, PathFollowController
from settings_manager import DEFAULT_SETTINGS
from skill_handlers import HANDLERS
from skill_registry import SKILL_DEFS
from support import Vec2i
from utils.action_order_utils import (
    get_entity_skill_range_tiles,
    min_distance_to_tiles,
)
from utils.occupancy_utils import (
    is_tile_static_blocked,
    mark_dynamic_occupancy_dirty,
    rebuild_dynamic_occupancy,
)
from utils.perf_profiler import PerfProfiler
from utils.skill_utils import validate_skill_defs
from utils.tile_vec_utils import (
    chebyshev_tile_distance,
    tile_center,
    tile_from_cpos,
)
from world import World


DEFAULT_SCENARIO = "chase_stress_radial_open_collapse"
DEFAULT_PLAYER_TILE = Vec2i(19, 19)

PROFILE_NAMES = (
    "sim.tick",
    "ai_system",
    "action_order_system",
    "intent_system",
    "movement_arbiter",
    "movement_proposal_system",
    "movement_apply_system",
    "occupancy.rebuild",
)

COUNTER_NAMES = (
    "movement.proposal.total",
    "movement.proposal.approved.direct",
    "movement.proposal.approved.finish_current_tile",
    "movement.proposal.direct_rejected",
    "movement.proposal.direct_rejected.dynamic",
    "movement.proposal.direct_rejected.static",
    "movement.proposal.rejected.direct",
    "movement.proposal.reserved_path",
)


class FakeKeys:
    def __init__(self, held_keys=()):
        self.held_keys = set(held_keys)

    def __getitem__(self, key):
        return key in self.held_keys


class DummyDisplay:
    def __init__(self):
        self.render_surface = pygame.Surface(INTERNAL_RES)


class DummyImages(dict):
    def __missing__(self, key):
        surface = pygame.Surface((32, 32), pygame.SRCALPHA)
        self[key] = surface
        return surface


class DummyDebug:
    def add_debug_tile_highlight(
        self,
        world,
        tile,
        duration_ticks,
        color,
    ):
        pass


class DummyAssets:
    def __init__(self):
        self.images = DummyImages()


class HarnessGame:
    def __init__(self, history_frames):
        self.settings = copy.deepcopy(DEFAULT_SETTINGS)
        self.display = DummyDisplay()
        self.assets = DummyAssets()
        self.entities = EntityManager()
        self.debug_mode = False
        self.debug = DummyDebug()
        self.perf_profiler = PerfProfiler(history_frames=history_frames)

        validate_skill_defs(SKILL_DEFS, handler_ids=HANDLERS)

        self.world = World(self, self.entities)
        self.state = StateGameplay(self)
        self.state.startup({})


def make_input_state():
    return InputState(
        keys=FakeKeys(),
        keys_pressed=set(),
        keys_released=set(),
        mouse_buttons=(False, False, False),
        mouse_pressed=set(),
        mouse_released=set(),
        mouse_pos=(320, 180),
        quit=False,
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Stress benchmark for AI ChaseEntityController pursuit."
    )
    parser.add_argument(
        "--scenario",
        default=DEFAULT_SCENARIO,
        choices=(DEFAULT_SCENARIO,),
    )
    parser.add_argument("--enemies", type=int, default=60)
    parser.add_argument("--radius", type=int, default=16)
    parser.add_argument("--warmup-ticks", type=int, default=60)
    parser.add_argument("--measure-ticks", type=int, default=600)
    parser.add_argument("--commit-label", default="878ff2f")
    parser.add_argument(
        "--player-tile",
        default=f"{DEFAULT_PLAYER_TILE.x},{DEFAULT_PLAYER_TILE.y}",
        help="Player tile as x,y. Default: 19,19.",
    )
    return parser.parse_args()


def parse_tile(value):
    try:
        x_text, y_text = value.split(",", 1)
        return Vec2i(int(x_text), int(y_text))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"Expected tile as x,y, got {value!r}"
        ) from error


def clear_non_player_entities(world):
    for entity in sorted(set(world.transform)):
        if entity == world.player:
            continue
        world.remove_entity(entity)
        world.entities.dead.discard(entity)

    world.events.clear()
    world.move_intent.clear()
    world.buffered_move_intent.clear()
    world.move_target.clear()
    world.intent.clear()
    world.action_order.clear()
    world.resolved_skill_intents.clear()
    world.damage_requests.clear()
    world.heal_requests.clear()
    world.interact_request.clear()
    world.clear_movement_planning_runtime()

    mark_dynamic_occupancy_dirty(world)
    rebuild_dynamic_occupancy(world)


def set_entity_tile(world, entity, tile):
    cpos = tile_center(tile)
    transform = world.transform[entity]
    transform.tile = tile
    transform.cpos = cpos
    transform.prev_cpos = cpos
    transform.position_mode = "grid"


def configure_player(world, player_tile):
    set_entity_tile(world, world.player, player_tile)

    motion_state = world.motion_state.get(world.player)
    if motion_state is not None:
        motion_state["controller"] = None
        motion_state["last_delta"] = Vec2i(0, 0)
        motion_state["influence_mode"] = "normal"

    world.move_intent.pop(world.player, None)
    world.buffered_move_intent.pop(world.player, None)
    world.move_target.pop(world.player, None)
    world.action_order.pop(world.player, None)

    world.focus_camera_on_player()


def build_square_ring_tiles(center_tile, radius):
    tiles = []

    left = center_tile.x - radius
    right = center_tile.x + radius
    top = center_tile.y - radius
    bottom = center_tile.y + radius

    for x in range(left, right + 1):
        tiles.append(Vec2i(x, top))

    for y in range(top + 1, bottom + 1):
        tiles.append(Vec2i(right, y))

    for x in range(right - 1, left - 1, -1):
        tiles.append(Vec2i(x, bottom))

    for y in range(bottom - 1, top, -1):
        tiles.append(Vec2i(left, y))

    return tiles


def candidate_ring_tiles(center_tile, radius):
    # Build a square Chebyshev ring, then rotate the starting point so the
    # selected enemies collapse from all sides rather than from one edge first.
    tiles = build_square_ring_tiles(center_tile, radius)
    if not tiles:
        return []

    offset = len(tiles) // 8
    return tiles[offset:] + tiles[:offset]


def tile_conflicts_with_selected(tile, selected_tiles):
    # plus5 actors can be dense, but this avoids immediate center/body overlap
    # at spawn time and keeps the starting ring readable.
    return any(
        chebyshev_tile_distance(tile, selected_tile) < 2
        for selected_tile in selected_tiles
    )


def choose_ring_spawn_tiles(world, center_tile, radius, enemy_count):
    ring_tiles = candidate_ring_tiles(center_tile, radius)
    if not ring_tiles:
        raise RuntimeError("No ring tiles generated.")

    selected = []
    attempts = 0
    cursor = 0

    while len(selected) < enemy_count and attempts < len(ring_tiles) * 4:
        tile = ring_tiles[cursor % len(ring_tiles)]
        cursor += max(1, len(ring_tiles) // max(1, enemy_count))
        attempts += 1

        if is_tile_static_blocked(world, tile):
            continue

        if tile_conflicts_with_selected(tile, selected):
            continue

        selected.append(tile)

    if len(selected) < enemy_count:
        raise RuntimeError(
            f"Only placed {len(selected)} enemies on radius {radius}; "
            f"requested {enemy_count}. Increase --radius or lower --enemies."
        )

    return selected


def configure_radial_open_collapse(world, enemy_count, radius, player_tile):
    world.load_area("destacker_arena", "default")

    clear_non_player_entities(world)
    configure_player(world, player_tile)

    enemy_tiles = choose_ring_spawn_tiles(
        world,
        center_tile=player_tile,
        radius=radius,
        enemy_count=enemy_count,
    )

    enemies = []
    for index, tile in enumerate(enemy_tiles):
        enemy = world.spawn_training_dummy(tile)

        # Keep benchmark AI responsive and make start times deterministic
        # but not identical.
        world.ai_agent[enemy]["think_interval_ticks"] = 1
        world.ai_agent[enemy]["next_think_tick"] = world.tick + (index % 6)
        world.ai_agent[enemy]["target_entity"] = None

        enemies.append(enemy)

    mark_dynamic_occupancy_dirty(world)
    rebuild_dynamic_occupancy(world)

    return enemies


def run_one_tick(game):
    profiler = game.perf_profiler
    profiler.begin_frame()
    with profiler.scope("sim.tick"):
        game.state.update(SIM_DT, make_input_state())
    profiler.end_frame()


def run_ticks(game, tick_count):
    for _ in range(tick_count):
        run_one_tick(game)


def reset_profiler(game, history_frames):
    game.perf_profiler = PerfProfiler(history_frames=history_frames)


def get_enemies(world):
    return tuple(
        sorted(
            entity
            for entity in world.ai_agent
            if entity in world.transform
        )
    )


def summarize_chase_state(world):
    enemies = get_enemies(world)
    player = world.player
    player_tiles = get_entity_skill_range_tiles(world, player)

    chase_controller_count = 0
    path_follow_controller_count = 0
    in_range_count = 0
    distances = []

    for enemy in enemies:
        motion_state = world.motion_state.get(enemy, {})
        controller = motion_state.get("controller")

        if isinstance(controller, ChaseEntityController):
            chase_controller_count += 1

        if isinstance(controller, PathFollowController):
            path_follow_controller_count += 1

        enemy_tile = tile_from_cpos(world.transform[enemy].cpos)

        if player_tiles:
            distance = min_distance_to_tiles(enemy_tile, player_tiles)
            distances.append(distance)

            if distance <= 1:
                in_range_count += 1

    avg_distance = (
        sum(distances) / len(distances)
        if distances
        else 0.0
    )
    max_distance = max(distances) if distances else 0

    return {
        "enemy_count": len(enemies),
        "active_chase_controllers": chase_controller_count,
        "active_path_follow_controllers": path_follow_controller_count,
        "enemies_within_1_tile_of_player_body": in_range_count,
        "avg_distance_to_player_body": avg_distance,
        "max_distance_to_player_body": max_distance,
    }


def print_profile_rows(profiler):
    rows_by_name = {
        row["name"]: row
        for row in profiler.get_summary_rows(limit=1000)
    }

    print()
    print("timings:")
    print(
        f"{'name':42} "
        f"{'avg_total_ms':>12} "
        f"{'peak_total_ms':>13} "
        f"{'peak_call_ms':>12} "
        f"{'avg_calls':>9}"
    )

    for name in PROFILE_NAMES:
        row = rows_by_name.get(name)
        if row is None:
            continue

        print(
            f"{name:42} "
            f"{row['avg_total_ms']:12.4f} "
            f"{row['peak_total_ms']:13.4f} "
            f"{row['peak_call_ms']:12.4f} "
            f"{row['avg_calls']:9.2f}"
        )


def print_counter_rows(profiler):
    rows_by_name = {
        row["name"]: row
        for row in profiler.get_counter_summary_rows(limit=1000)
    }

    print()
    print("counters:")
    print(
        f"{'name':42} "
        f"{'avg_total':>12} "
        f"{'peak_total':>12} "
        f"{'peak_value':>11} "
        f"{'avg_records':>11}"
    )

    for name in COUNTER_NAMES:
        row = rows_by_name.get(name)
        if row is None:
            continue

        print(
            f"{name:42} "
            f"{row['avg_total']:12.2f} "
            f"{row['peak_total']:12.2f} "
            f"{row['peak_value']:11.2f} "
            f"{row['avg_records']:11.2f}"
        )


def print_chase_summary(summary):
    print()
    print("chase_state:")
    for key, value in summary.items():
        if isinstance(value, float):
            print(f"{key}: {value:.3f}")
        else:
            print(f"{key}: {value}")


def run_benchmark(args):
    player_tile = parse_tile(args.player_tile)

    game = HarnessGame(
        history_frames=max(args.measure_ticks, 1),
    )

    if args.scenario == DEFAULT_SCENARIO:
        enemies = configure_radial_open_collapse(
            game.world,
            enemy_count=args.enemies,
            radius=args.radius,
            player_tile=player_tile,
        )
    else:
        raise ValueError(f"Unknown scenario {args.scenario!r}")

    run_ticks(game, args.warmup_ticks)

    reset_profiler(
        game,
        history_frames=max(args.measure_ticks, 1),
    )

    run_ticks(game, args.measure_ticks)

    summary = summarize_chase_state(game.world)

    print(f"scenario: {args.scenario}")
    print(f"commit_label: {args.commit_label}")
    print(f"enemy_count_requested: {args.enemies}")
    print(f"enemy_count_spawned: {len(enemies)}")
    print(f"radius: {args.radius}")
    print(f"player_tile: {player_tile}")
    print(f"warmup_ticks: {args.warmup_ticks}")
    print(f"measure_ticks: {args.measure_ticks}")
    print(f"final_world_tick: {game.world.tick}")

    print_profile_rows(game.perf_profiler)
    print_counter_rows(game.perf_profiler)
    print_chase_summary(summary)


def main():
    pygame.init()
    try:
        args = parse_args()
        run_benchmark(args)
    finally:
        pygame.quit()


if __name__ == "__main__":
    main()