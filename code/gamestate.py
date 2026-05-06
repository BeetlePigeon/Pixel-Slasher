import pygame
from systems import *


class State:
    def __init__(self, game):
        self.game = game
        self.surface = game.render_surface  # The fixed internal surface all blits are applied to.
        self.surface_rect = self.surface.get_rect()

        # Internal state machine setup
        self.done = False
        self.quit = False
        self.next_state = None
        self.persist = {}

    def startup(self, persistent):
        self.persist = persistent

    def update(self, dt, input_state):
        pass

    def draw(self, surface):
        pass


class StateGameplay(State):
    def __init__(self, game):
        super().__init__(game)

    def build_player_intents(self, input_state):
        intents = []
        keys = input_state.keys

        screen_dx = 0
        screen_dy = 0

        if keys[pygame.K_d]:
            screen_dx += 1
        if keys[pygame.K_a]:
            screen_dx -= 1
        if keys[pygame.K_s]:
            screen_dy += 1
        if keys[pygame.K_w]:
            screen_dy -= 1

        screen_dx = max(-1, min(1, screen_dx))
        screen_dy = max(-1, min(1, screen_dy))

        SCREEN_TO_TILE_DIR = {
            (0, -1): (-1, -1),  # W     = visual up
            (0, 1): (1, 1),  # S     = visual down
            (-1, 0): (-1, 1),  # A     = visual left
            (1, 0): (1, -1),  # D     = visual right

            (-1, -1): (-1, 0),  # W+A   = visual up-left
            (1, -1): (0, -1),  # W+D   = visual up-right
            (-1, 1): (0, 1),  # S+A   = visual down-left
            (1, 1): (1, 0),  # S+D   = visual down-right
        }

        if (screen_dx, screen_dy) in SCREEN_TO_TILE_DIR:
            tile_dx, tile_dy = SCREEN_TO_TILE_DIR[(screen_dx, screen_dy)]
            intents.append({
                "type": "move",
                "direction": (tile_dx, tile_dy)
            })

        # -------------------------
        # KEYBOARD SKILLS (1–4)
        # -------------------------
        KEY_TO_SLOT = {
            pygame.K_1: 1,
            pygame.K_2: 2,
            pygame.K_3: 3,
            pygame.K_4: 4,
        }

        for key, slot in KEY_TO_SLOT.items():
            if key in input_state.keys_pressed:
                intents.append({"type": "skill_pressed", "slot": slot})

            if key in input_state.keys_released:
                intents.append({"type": "skill_released", "slot": slot})

        if pygame.K_SPACE in input_state.keys_pressed:
            intents.append({
                "type": "spawn_test_projectile",
            })

        # -------------------------
        # MOUSE SKILLS (LMB/RMB)
        # -------------------------
        MOUSE_TO_SLOT = {
            1: "LMB",
            3: "RMB",
        }

        for button, slot in MOUSE_TO_SLOT.items():
            if button in input_state.mouse_pressed:
                intents.append({"type": "skill_pressed", "slot": slot})

            if button in input_state.mouse_released:
                intents.append({"type": "skill_released", "slot": slot})

        return intents, input_state.mouse_pos

    def update(self, dt, input_state):
        # Player Intents
        player = self.game.world.player
        player_intents, _ = self.build_player_intents(input_state)
        intents = {player: player_intents}

        # AI Intents
        pass  # add intents to the intents dict created under Player Intents

        # Update Systems
        intent_system(self.game.world, intents)
        skill_system(self.game.world, intents)
        movement_system(self.game.world)
        movement_arbiter_system(self.game.world)
        test_projectile_spawn_system(self.game.world, intents)

        # Cleanup Entities
        self.game.entities.cleanup(self.game.world)

    def draw(self, surface):
        render_tiles(self.game.world, surface)
        sprite_system(self.game.world, surface)