import argparse
import copy
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
from world import World
from support import Vec2i
from constants import INTERNAL_RES, SIM_DT
from entity import EntityManager
from gamestate import StateGameplay
from inputhandler import InputState
from settings_manager import DEFAULT_SETTINGS
from skill_handlers import HANDLERS
from skill_registry import SKILL_DEFS
from utils.perf_profiler import PerfProfiler
from utils.skill_utils import validate_skill_defs
from dev_tools.chase_stress_scenarios import (
    CHASE_STRESS_RADIAL_OPEN_COLLAPSE,
    DEFAULT_CHASE_STRESS_PLAYER_TILE,
    configure_radial_open_collapse,
    get_chase_stress_enemies,
    summarize_chase_stress_state,
)
from motion_controllers import ChaseEntityController, PathFollowController


DEFAULT_SCENARIO = CHASE_STRESS_RADIAL_OPEN_COLLAPSE
DEFAULT_PLAYER_TILE = DEFAULT_CHASE_STRESS_PLAYER_TILE

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
    "chase.blockage.static",
    "chase.blockage.moving_dynamic",
    "chase.blockage.stalled_dynamic",
    "chase.blockage.engaged_dynamic",
    "chase.blockage.unknown",
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
    parser.add_argument("--warmup-ticks", type=int, default=0)
    parser.add_argument("--measure-ticks", type=int, default=600)
    parser.add_argument("--commit-label", default="latest")
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


class ChaseStressStats:
    def __init__(self):
        self.ticks = 0
        self.total_chase_controllers = 0
        self.peak_chase_controllers = 0
        self.total_path_follow_controllers = 0
        self.peak_path_follow_controllers = 0
        self.ticks_with_path_follow = 0

    def sample(self, world):
        chase_count = 0
        path_follow_count = 0

        for motion_state in world.motion_state.values():
            controller = motion_state.get("controller")

            if isinstance(controller, ChaseEntityController):
                chase_count += 1

            if isinstance(controller, PathFollowController):
                path_follow_count += 1

        self.ticks += 1
        self.total_chase_controllers += chase_count
        self.peak_chase_controllers = max(
            self.peak_chase_controllers,
            chase_count,
        )

        self.total_path_follow_controllers += path_follow_count
        self.peak_path_follow_controllers = max(
            self.peak_path_follow_controllers,
            path_follow_count,
        )

        if path_follow_count > 0:
            self.ticks_with_path_follow += 1

    def summary(self):
        if self.ticks == 0:
            return {
                "avg_active_chase_controllers": 0.0,
                "peak_active_chase_controllers": 0,
                "avg_active_path_follow_controllers": 0.0,
                "peak_active_path_follow_controllers": 0,
                "ticks_with_path_follow_controllers": 0,
            }

        return {
            "avg_active_chase_controllers": (
                self.total_chase_controllers / self.ticks
            ),
            "peak_active_chase_controllers": self.peak_chase_controllers,
            "avg_active_path_follow_controllers": (
                self.total_path_follow_controllers / self.ticks
            ),
            "peak_active_path_follow_controllers": (
                self.peak_path_follow_controllers
            ),
            "ticks_with_path_follow_controllers": (
                self.ticks_with_path_follow
            ),
        }


def print_chase_controller_stats(summary):
    print()
    print("chase_controller_stats:")
    for key, value in summary.items():
        if isinstance(value, float):
            print(f"{key}: {value:.3f}")
        else:
            print(f"{key}: {value}")


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

    stats = ChaseStressStats()

    for _ in range(args.measure_ticks):
        run_one_tick(game)
        stats.sample(game.world)


    summary = summarize_chase_stress_state(game.world)
    controller_summary = stats.summary()

    print(f"scenario: {args.scenario}")
    print(f"commit_label: {args.commit_label}")
    print(f"enemy_count_requested: {args.enemies}")
    print(f"enemy_count_spawned: {len(get_chase_stress_enemies(game.world))}")
    print(f"radius: {args.radius}")
    print(f"player_tile: {player_tile}")
    print(f"warmup_ticks: {args.warmup_ticks}")
    print(f"measure_ticks: {args.measure_ticks}")
    print(f"final_world_tick: {game.world.tick}")

    print_profile_rows(game.perf_profiler)
    print_counter_rows(game.perf_profiler)
    print_chase_controller_stats(controller_summary)
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