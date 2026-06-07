import pygame
from random import randint
from support import Vec2i
from utils.camera_utils import internal_screen_to_world_cpos
from gameplay_ui import GameplayUI
from skill_registry import SKILL_DEFS
from utils.tile_vec_utils import tile_from_cpos, tile_center
from systems import (
    snapshot_system,
    action_state_system,
    lifetime_system,
    ai_system,
    movement_arbiter_system,
    movement_system,
    destacking_system,
    event_system,
    skill_intent_resolution_system,
    skill_execution_system,
    influence_system,
    intent_system,
    camera_update_system,
    camera_system,
    camera_shake_system,
    status_effect_system,
    effect_delivery_system,
    effect_carrier_lifecycle_system,
    sprite_system,
    tile_render_system,
    combat_system,
    projectile_impact_system,
    projectile_behavior_system,
)


class State:
    def __init__(self, game):
        self.game = game
        self.surface = game.display.render_surface  # The fixed internal surface all blits are applied to.
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
        self.gameplay_ui = GameplayUI()
        self.debug_dummy_patrol = {}


    def get_skill_trigger_mode(self, entity, slot):
        skill_id = self.game.world.skills.get((entity, slot))

        if not skill_id:
            return "press"

        skill_def = SKILL_DEFS.get(skill_id)

        if skill_def is None:
            return "press"

        return skill_def["trigger_mode"]


    def build_gameplay_input_state(self, input_state):
        return self.gameplay_ui.filter_input_for_gameplay(
            input_state,
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
            pygame.K_SPACE: 0,
            pygame.K_1: 1,
            pygame.K_2: 2,
            pygame.K_3: 3,
            pygame.K_4: 4,
            pygame.K_5: 5,
            pygame.K_6: 6,
            pygame.K_7: 7,
            pygame.K_8: 8,
            pygame.K_9: 10,
            pygame.K_0: 11,
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
                "path_policy": "player_click_move",
            })

        self.append_keyboard_skill_intents(intents, input_state)

        # In traditional mode, LMB is reserved for movement/context action.
        # RMB remains a skill slot.
        self.append_mouse_skill_intents(
            intents,
            input_state,
            {
                3: 9,
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

        # ------------------------------------------------------------------
        # Fixed-tick gameplay pipeline
        #
        # This function defines the authoritative simulation order for one
        # gameplay tick. The order is part of the engine contract. Do not
        # reorder systems casually.
        #
        # General rule:
        # - Earlier systems prepare or resolve state.
        # - Later systems consume that state.
        # - Most newly spawned gameplay effects are intended to resolve on a
        #   later tick, not immediately in the same tick they are created.
        #
        # Important movement rule:
        # movement_system intentionally runs before movement_arbiter_system.
        # This lets movement_system finish and clear an existing motion
        # controller, then lets movement_arbiter_system assign a new controller
        # in the same tick. This prevents a one-frame movement gap.
        #
        # Important event rule:
        # event_system currently acts as the event queue coordinator near the
        # end of the tick. Same-tick event chaining is intentionally avoided
        # for now. Gameplay reactions and feedback should stay explicit.
        # ------------------------------------------------------------------

        # Player Intents
        player = self.game.world.player
        player_intents, player_mouse_pos = self.build_player_intents(input_state)

        self.game.world.aim_state[player] = {
            "mouse_pos": player_mouse_pos,
        }

        intents = {
            player: player_intents,
        }

        # Debug /Test Move Enemy Intents
        self.append_debug_dummy_patrol_intents(intents)
        # AI Intents.
        #
        # AI is another input source. It reads world state and appends
        # intents; existing intent/movement/skill systems execute them.
        ai_system(self.game.world, intents)

        # Debug Inputs Bypass Arbiters
        if self.game.debug_mode:
            self.game.debug.process_gamestate_debug_inputs(input_state)

        # Phase 1: resolve state carried over from previous ticks.
        #
        # snapshot_system stores previous-frame state for interpolation and
        # comparison.
        #
        # action_state_system advances casts/channels and emits scheduled
        # skill events.
        #
        # status_effect_system advances existing statuses.
        #
        # effect_delivery_system resolves existing effect carriers, such as
        # delayed tile effects.
        #
        # combat_damage_system applies queued damage requests produced by
        # earlier systems.
        snapshot_system(self.game.world)
        action_state_system(self.game.world)
        status_effect_system(self.game.world)
        effect_delivery_system(self.game.world)
        effect_carrier_lifecycle_system(self.game.world)
        combat_system(self.game.world)

        if self.game.debug_mode:
            self.game.debug.debug_tile_highlight_system(self.game.world)

        # Phase 2: convert this tick's input/AI intents into gameplay requests.
        #
        # intent_system stores raw entity intents.
        #
        # skill_intent_resolution_system checks whether requested skills are
        # currently legal.
        #
        # skill_execution_system starts casts, channels, instant skills, and
        # other skill-driven behavior.
        intent_system(self.game.world, intents)
        skill_intent_resolution_system(self.game.world, intents)
        skill_execution_system(self.game.world)

        # Phase 3: resolve influence and movement.
        #
        # influence_system computes external movement influences.
        #
        # movement_system advances current motion controllers and clears
        # finished controllers.
        #
        # movement_arbiter_system assigns new movement controllers after the
        # movement system has had a chance to clear completed ones. This order
        # is intentional and prevents frame gaps when a motion controller finishes and is then reassigned.
        influence_system(self.game.world)
        movement_system(self.game.world)
        movement_arbiter_system(self.game.world)
        destacking_system(self.game.world)
        projectile_behavior_system(self.game.world)
        projectile_impact_system(self.game.world)

        # Phase 4: lifetime, camera, and events.
        #
        # lifetime_system expires temporary entities.
        #
        # camera_update_system updates camera target state.
        #
        # camera_shake_system applies presentation shake.
        #
        # event_system coordinates queued events near the end of the tick.
        lifetime_system(self.game.world)
        camera_update_system(self.game.world)
        camera_shake_system(self.game.world)
        event_system(self.game.world)

        # Cleanup Entities
        self.game.entities.cleanup(self.game.world)


    def draw(self, surface, render_alpha):
        camera_system(self.game.world, surface, render_alpha)
        tile_render_system(self.game.world, surface, render_alpha)
        sprite_system(self.game.world, surface, render_alpha, draw_debug=self.game.debug_mode)

        if self.game.debug_mode:
            pass
            #self.game.debug.draw_projectile_contact_footprints(self.game.world, surface)

        self.gameplay_ui.draw(surface)


    def append_debug_dummy_patrol_intents(self, intents):
        # Temporary logic for testing move blockers.
        world = self.game.world

        candidates = [
            entity
            for entity in sorted(world.team)
            if (
                world.team[entity] == "enemy"
                and entity not in world.ai_agent
                and entity in world.transform
                and entity in world.motion_state
                and entity in world.space_occupier
                and entity in world.locomotion
            )
        ]

        if not candidates:
            return

        for dummy in candidates:
            motion_state = world.motion_state[dummy]

            # Do not spam new targets while the dummy is already moving
            # or while a target is waiting to be consumed by the movement arbiter.
            if motion_state.get("controller") is not None:
                continue

            if dummy in world.move_target:
                continue

            transform = world.transform[dummy]
            current_tile = tile_from_cpos(transform.cpos)

            if dummy not in self.debug_dummy_patrol:
                start_tile = current_tile
                rand_center_tile = Vec2i(randint(15, 20), randint(15, 20))
                rand_close_tile = start_tile + Vec2i(randint(-3, 3), randint(-3, 3))
                rand_wait_ticks = randint(0, 25)
                self.debug_dummy_patrol[dummy] = {
                    "points": [
                        start_tile,
                        rand_close_tile,
                    ],
                    "target_index": 1,
                    "next_tick": world.tick,
                    "wait_ticks": rand_wait_ticks,
                }

            patrol = self.debug_dummy_patrol[dummy]
            points = patrol["points"]
            target_tile = points[patrol["target_index"]]

            # Advance the patrol target only after the dummy actually reaches
            # the current patrol point. Do not advance merely because a target
            # was issued.
            if current_tile == target_tile:
                patrol["target_index"] = (
                        patrol["target_index"] + 1
                ) % len(points)

                patrol["next_tick"] = (
                        world.tick
                        + patrol["wait_ticks"]
                )

                continue

            if world.tick < patrol["next_tick"]:
                continue

            intents.setdefault(
                dummy,
                [],
            ).append({
                "type": "move_to_tile",
                "target_tile": target_tile,
                "target_cpos": tile_center(target_tile),
                "path_policy": "actor_move",
            })