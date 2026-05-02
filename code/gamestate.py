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
        dx = keys[pygame.K_d] - keys[pygame.K_a]
        dy = keys[pygame.K_w] - keys[pygame.K_s]

        if dx != 0 or dy != 0:
            intents.append({
                "type": "move",
                "direction": (dx, dy)
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
        movement_system(self.game.world, dt)
        skill_system(self.game.world, intents)

    def draw(self, surface):
        render_tiles(self.game.world, surface)
        sprite_system(self.game.world, surface)