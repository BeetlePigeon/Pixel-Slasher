import hashlib
import json
import os
from dataclasses import asdict, is_dataclass

# Keep this script usable on machines without opening a real window.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from constants import INTERNAL_RES, SIM_DT
from skill_registry import SKILL_DEFS
from entity import EntityManager
from gamestate import StateGameplay
from inputhandler import InputState
from skill_handlers import HANDLERS
from utils.skill_utils import validate_skill_defs
from world import World


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


class DummyAssets:
    def __init__(self):
        self.images = DummyImages()


class HarnessGame:
    def __init__(self):
        self.display = DummyDisplay()
        self.assets = DummyAssets()
        self.entities = EntityManager()
        self.debug_mode = False
        self.debug = None

        validate_skill_defs(SKILL_DEFS, handler_ids=HANDLERS)

        self.world = World(self, self.entities)
        self.state = StateGameplay(self)
        self.state.startup({})


def make_input_state(
    held_keys=(),
    pressed_keys=(),
    released_keys=(),
    mouse_buttons=(False, False, False),
    mouse_pressed=(),
    mouse_released=(),
    mouse_pos=(320, 180),
):
    return InputState(
        keys=FakeKeys(held_keys),
        keys_pressed=set(pressed_keys),
        keys_released=set(released_keys),
        mouse_buttons=tuple(mouse_buttons),
        mouse_pressed=set(mouse_pressed),
        mouse_released=set(mouse_released),
        mouse_pos=mouse_pos,
        quit=False,
    )


def build_scripted_inputs():
    inputs = []

    # Idle startup.
    for _ in range(10):
        inputs.append(make_input_state())

    # Hold D for direct movement.
    for tick in range(40):
        pressed = {pygame.K_d} if tick == 0 else set()
        inputs.append(
            make_input_state(
                held_keys={pygame.K_d},
                pressed_keys=pressed,
            )
        )

    # Release D.
    inputs.append(
        make_input_state(
            released_keys={pygame.K_d},
        )
    )

    # Idle after movement.
    for _ in range(20):
        inputs.append(make_input_state())

    return inputs


def stable_value(value):
    if value is None:
        return None

    if isinstance(value, (bool, int, float, str)):
        return value

    if is_dataclass(value):
        return stable_value(asdict(value))

    if isinstance(value, dict):
        items = []
        for key, item_value in value.items():
            stable_key = stable_value(key)
            stable_item_value = stable_value(item_value)
            items.append((stable_key, stable_item_value))

        return sorted(items, key=lambda pair: repr(pair[0]))

    if isinstance(value, (list, tuple)):
        return [stable_value(item) for item in value]

    if isinstance(value, set):
        return sorted(
            [stable_value(item) for item in value],
            key=repr,
        )

    if isinstance(value, pygame.Surface):
        return "<surface>"

    return repr(value)


def build_world_snapshot(world):
    component_names = [
        "transform",
        "motion_state",
        "action_state",
        "status_effects",
        "facing",
        "events",
        "move_intent",
        "buffered_move_intent",
        "move_target",
        "aim_state",
        "intent",
        "input_controlled",
        "skills",
        "skill_cooldown",
        "projectile",
        "lifetime",
        "health",
        "effect_delivery",
        "team",
        "hittable",
        "movement_collision",
        "locomotion",
        "placement_blocker",
        "influence_emitter",
        "influence_receiver",
        "influence_delta",
    ]

    snapshot = {
        "tick": world.tick,
        "entity_next_id": world.entities.next_id,
        "entity_dead": world.entities.dead,
        "player": world.player,
        "components": {},
    }

    for component_name in component_names:
        snapshot["components"][component_name] = getattr(
            world,
            component_name,
            None,
        )

    return stable_value(snapshot)


def hash_world(world):
    snapshot = build_world_snapshot(world)
    encoded = json.dumps(
        snapshot,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest(), snapshot


def run_once():
    game = HarnessGame()

    for input_state in build_scripted_inputs():
        game.state.update(SIM_DT, input_state)

    return hash_world(game.world)


def main():
    pygame.init()

    first_hash, first_snapshot = run_once()
    second_hash, second_snapshot = run_once()

    print(f"first_hash:  {first_hash}")
    print(f"second_hash: {second_hash}")

    if first_hash != second_hash:
        print("Determinism smoke test failed.")
        print()
        print("First snapshot:")
        print(json.dumps(first_snapshot, indent=2, sort_keys=True))
        print()
        print("Second snapshot:")
        print(json.dumps(second_snapshot, indent=2, sort_keys=True))
        raise SystemExit(1)

    print("Determinism smoke test passed.")


if __name__ == "__main__":
    main()