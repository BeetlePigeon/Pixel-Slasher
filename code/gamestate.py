from dataclasses import replace
from systems import *
from camera_utils import internal_screen_to_world_cpos
from status_ops import apply_status_effect


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

    def draw(self, surface, render_alpha):
        pass


class StateGameplay(State):
    def __init__(self, game):
        super().__init__(game)
        self.ui_captured_mouse_buttons = set()


    def toggle_control_scheme(self):
        world = self.game.world

        if world.control_scheme == "modern":
            world.control_scheme = "traditional"
        else:
            world.control_scheme = "modern"


    def get_skill_trigger_mode(self, entity, slot):
        skill_id = self.game.world.skills.get((entity, slot))

        if not skill_id:
            return "press"

        skill_def = SKILL_DEFS.get(skill_id)

        if skill_def is None:
            return "press"

        return skill_def["trigger_mode"]


    def build_gameplay_input_state(self, input_state):
        mouse_over_ui = self.mouse_over_gameplay_ui(input_state.mouse_pos)

        consumed_buttons = set()

        # If a button is pressed while over UI, UI captures it until release.
        for button in input_state.mouse_pressed:
            if mouse_over_ui:
                self.ui_captured_mouse_buttons.add(button)

        consumed_buttons.update(self.ui_captured_mouse_buttons)

        # Held buttons should also be suppressed while currently over UI.
        # This handles cases where the cursor is over UI while already holding.
        if mouse_over_ui:
            for button in range(1, len(input_state.mouse_buttons) + 1):
                if self.is_mouse_button_held(input_state, button):
                    consumed_buttons.add(button)

        filtered_mouse_pressed = {
            button
            for button in input_state.mouse_pressed
            if button not in consumed_buttons
        }

        filtered_mouse_released = {
            button
            for button in input_state.mouse_released
            if button not in consumed_buttons
        }

        filtered_mouse_buttons = tuple(
            False if (index + 1) in consumed_buttons else held
            for index, held in enumerate(input_state.mouse_buttons)
        )

        # Release ends UI capture after filtering, so the release does not leak
        # into gameplay on the same tick.
        for button in input_state.mouse_released:
            self.ui_captured_mouse_buttons.discard(button)

        return replace(
            input_state,
            mouse_buttons=filtered_mouse_buttons,
            mouse_pressed=filtered_mouse_pressed,
            mouse_released=filtered_mouse_released,
        )


    def is_mouse_button_held(self, input_state, button):
        index = button - 1

        if index < 0 or index >= len(input_state.mouse_buttons):
            return False

        return input_state.mouse_buttons[index]


    def append_wasd_move_intent(self, intents, input_state):
        keys = input_state.keys

        right = keys[pygame.K_d]
        left = keys[pygame.K_a]
        up = keys[pygame.K_w]
        down = keys[pygame.K_s]

        screen_dx = max(-1, min(1, right - left))
        screen_dy = max(-1, min(1, down - up))

        SCREEN_TO_TILE_DIR = {
            # visual right / left / up / down
            (1, 0): (1, -1),
            (-1, 0): (-1, 1),
            (0, -1): (-1, -1),
            (0, 1): (1, 1),

            # visual diagonals
            (1, -1): (0, -1),
            (1, 1): (1, 0),
            (-1, -1): (-1, 0),
            (-1, 1): (0, 1),
        }

        if (screen_dx, screen_dy) in SCREEN_TO_TILE_DIR:
            tile_dx, tile_dy = SCREEN_TO_TILE_DIR[(screen_dx, screen_dy)]

            intents.append({
                "type": "move",
                "direction": (tile_dx, tile_dy),
            })

    def append_keyboard_skill_intents(self, intents, input_state):
        KEY_TO_SLOT = {
            pygame.K_1: 1,
            pygame.K_2: 2,
            pygame.K_3: 3,
            pygame.K_4: 4,
            pygame.K_5: 5,
            pygame.K_6: 6,
            pygame.K_SPACE: "TEST_PROJECTILE",
        }

        for key, slot in KEY_TO_SLOT.items():
            if key in input_state.keys_pressed:
                intents.append({
                    "type": "skill_pressed",
                    "slot": slot,
                    "mouse_pos": input_state.mouse_pos,
                })

            if input_state.keys[key]:
                intents.append({
                    "type": "skill_held",
                    "slot": slot,
                    "mouse_pos": input_state.mouse_pos,
                })

            if key in input_state.keys_released:
                intents.append({
                    "type": "skill_released",
                    "slot": slot,
                    "mouse_pos": input_state.mouse_pos,
                })

    def append_mouse_skill_intents(self, intents, input_state, mouse_to_slot):
        for button, slot in mouse_to_slot.items():
            if button in input_state.mouse_pressed:
                intents.append({
                    "type": "skill_pressed",
                    "slot": slot,
                    "mouse_pos": input_state.mouse_pos,
                })

            if self.is_mouse_button_held(input_state, button):
                intents.append({
                    "type": "skill_held",
                    "slot": slot,
                    "mouse_pos": input_state.mouse_pos,
                })

            if button in input_state.mouse_released:
                intents.append({
                    "type": "skill_released",
                    "slot": slot,
                    "mouse_pos": input_state.mouse_pos,
                })


    def build_player_intents(self, input_state):
        gameplay_input_state = self.build_gameplay_input_state(input_state)

        control_scheme = self.game.world.control_scheme

        if control_scheme == "traditional":
            return self.build_traditional_player_intents(gameplay_input_state)

        return self.build_modern_player_intents(gameplay_input_state)


    def build_traditional_player_intents(self, input_state):
        intents = []

        # Traditional controls:
        # LMB on ground means move toward clicked tile.
        if 1 in input_state.mouse_pressed or self.is_mouse_button_held(input_state, 1):
            target_cpos = internal_screen_to_world_cpos(
                self.game.world,
                input_state.mouse_pos,
            )

            target_tile = tile_from_cpos(target_cpos)

            intents.append({
                "type": "move_to_tile",
                "target_tile": target_tile,
                "target_cpos": target_cpos,
                "mouse_pos": input_state.mouse_pos,
            })

        self.append_keyboard_skill_intents(intents, input_state)

        # In traditional mode, LMB is reserved for movement/context action.
        # RMB remains a skill slot.
        self.append_mouse_skill_intents(
            intents,
            input_state,
            {
                3: "RMB",
            },
        )

        return intents, input_state.mouse_pos


    def build_modern_player_intents(self, input_state):
        intents = []

        self.append_wasd_move_intent(intents, input_state)
        self.append_keyboard_skill_intents(intents, input_state)

        self.append_mouse_skill_intents(
            intents,
            input_state,
            {
                1: "LMB",
                3: "RMB",
            },
        )

        return intents, input_state.mouse_pos


    def update(self, dt, input_state):
        self.game.world.tick += 1

        # Player Intents
        player = self.game.world.player
        player_intents, player_mouse_pos = self.build_player_intents(input_state)

        self.game.world.aim_state[player] = {"mouse_pos": player_mouse_pos}

        intents = {player: player_intents}

        # AI Intents
        pass  # add intents to the intents dict created under Player Intents

        # Debug camera
        if pygame.K_F8 in input_state.keys_pressed:
            self.toggle_control_scheme()

        if pygame.K_F9 in input_state.keys_pressed:
            settings = self.game.world.gameplay_settings

            current = settings["modern_movement_skill_aim_source"]

            if current == "facing":
                settings["modern_movement_skill_aim_source"] = "mouse"
            else:
                settings["modern_movement_skill_aim_source"] = "facing"

        if pygame.K_LSHIFT in input_state.keys_pressed:
            camera = self.game.world.camera

            if camera["mode"] == "follow":
                player = self.game.world.player
                fixed_cpos = self.game.world.transform[player].cpos
                set_camera_fixed(self.game.world, fixed_cpos, transition_mode="snap")
            else:
                set_camera_follow(self.game.world, self.game.world.player, transition_mode="smooth", transition_duration=26)

        if pygame.K_v in input_state.keys_pressed:
            start_camera_shake(
                self.game.world,
                duration_ticks=18,
                strength=4,
            )

        if pygame.K_b in input_state.keys_pressed:
            apply_status_effect(
                self.game.world,
                self.game.world.player,
                "debug_stun",
                tags={
                    "stun",
                    "movement_locked",
                    "skill_locked",
                },
                duration=90,
                cancels_action_tags={
                    "cast",
                    "channel",
                    "recovery",
                },
                cancels_motion_tags={
                    "dash",
                    "directional_move",
                    "path_follow",
                },
            )

        if pygame.K_n in input_state.keys_pressed:
            apply_status_effect(
                self.game.world,
                self.game.world.player,
                "debug_freeze",
                tags={
                    "freeze",
                    "movement_locked",
                    "skill_locked",
                    "settle_locked",
                },
                duration=90,
                pauses_action_tags={
                    "cast",
                    "channel",
                    "recovery",
                },
                cancels_motion_tags={
                    "dash",
                    "directional_move",
                    "path_follow",
                    "settle",
                },
            )
        # End debug


        # Update Systems
        snapshot_system(self.game.world)
        action_state_system(self.game.world)
        status_effect_system(self.game.world)
        combat_damage_system(self.game.world)
        debug_tile_highlight_system(self.game.world)
        intent_system(self.game.world, intents)
        skill_intent_resolution_system(self.game.world, intents)
        skill_execution_system(self.game.world)
        influence_system(self.game.world)
        movement_system(self.game.world)
        movement_arbiter_system(self.game.world)
        lifetime_system(self.game.world)
        camera_update_system(self.game.world)
        camera_shake_system(self.game.world)
        event_system(self.game.world)

        # Cleanup Entities
        self.game.entities.cleanup(self.game.world)


    def draw(self, surface, render_alpha):
        camera_system(self.game.world, surface, render_alpha)
        render_tiles(self.game.world, surface, render_alpha)
        sprite_system(self.game.world, surface, render_alpha)

        for rect in self.get_gameplay_ui_rects():
            pygame.draw.rect(surface, "gray", rect)
            pygame.draw.rect(surface, "white", rect, 1)


    def get_gameplay_ui_rects(self):
        # Temporary debug UI region.
        # Later this should come from a real UI system/widget tree.
        return [
            pygame.Rect(8, 8, 32, 32),
        ]


    def mouse_over_gameplay_ui(self, mouse_pos):
        for rect in self.get_gameplay_ui_rects():
            if rect.collidepoint(mouse_pos):
                return True

        return False