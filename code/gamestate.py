import pygame
from random import randint
from support import Vec2i
from utils.camera_utils import internal_screen_to_world_cpos
from gameplay_ui import GameplayUI
from skill_registry import SKILL_DEFS
from utils.tile_vec_utils import tile_from_cpos, tile_center
from utils.selectable_utils import resolve_hovered_selectable
from utils.targeting_policy_utils import (
    get_no_hard_target_action_order_type,
    input_context_uses_attack_in_place,
    skill_allows_hard_target_kind,
)
from utils.action_order_utils import (
    clear_action_order,
    entities_are_within_tile_range,
    get_skill_use_range_tiles,
    set_action_order,
)
from systems import (
    snapshot_system,
    action_state_system,
    lifetime_system,
    action_order_system,
    ai_system,
    movement_arbiter_system,
    movement_system,
    destacking_system,
    event_system,
    skill_intent_resolution_system,
    skill_execution_system,
    influence_system,
    intent_system,
    interact_system,
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


KEY_TO_SKILL_SLOT = {
    pygame.K_0: 0,
    pygame.K_1: 1,
    pygame.K_2: 2,
    pygame.K_3: 3,
    pygame.K_4: 4,
    pygame.K_5: 5,
    pygame.K_6: 6,
    pygame.K_7: 7,
    pygame.K_8: 8,
    pygame.K_9: 9,
    pygame.K_SPACE: 10,
}


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


    def get_keyboard_input_context(self, key):
        if key in KEY_TO_SKILL_SLOT:
            return "keyboard_skill"

        return None


    def should_create_no_hard_target_keyboard_order(
            self,
            skill_id,
            input_context,
    ):
        if input_context is None:
            return False

        order_type = get_no_hard_target_action_order_type(
            skill_id,
            input_context,
        )

        return order_type is not None


    def build_keyboard_no_hard_target_action_order(
            self,
            actor,
            skill_id,
            slot,
            key,
            input_context,
            input_state,
    ):
        world = self.game.world

        order_type = get_no_hard_target_action_order_type(
            skill_id,
            input_context,
        )

        if order_type == "soft_skill_use_or_attack_air":
            return {
                "type": "soft_skill_use_or_attack_air",
                "actor": actor,
                "skill_id": skill_id,
                "slot": slot,
                "input_kind": "keyboard",
                "key": key,
                "input_context": input_context,
                "target_lock": "none",
                "created_tick": world.tick,
                "press_mouse_pos": input_state.mouse_pos,
                "fired_once": False,
            }

        raise NotImplementedError(
            f"Keyboard no-hard-target order type not implemented: {order_type!r}"
        )


    def keyboard_hard_target_is_allowed_now(
            self,
            actor,
            target,
            skill_id,
            input_context,
    ):
        if not input_context_uses_attack_in_place(
                skill_id,
                input_context,
        ):
            return True

        use_range_tiles = get_skill_use_range_tiles(skill_id)

        if use_range_tiles is None:
            return True

        return entities_are_within_tile_range(
            self.game.world,
            actor,
            target,
            use_range_tiles,
        )


    def is_mouse_button_held(self, input_state, button):
        index = button - 1

        if index < 0 or index >= len(input_state.mouse_buttons):
            return False

        return input_state.mouse_buttons[index]


    def get_pointer_action_slot(self, button):
        control_scheme = self.game.world.control_scheme

        if control_scheme == "traditional":
            if button == 1:
                return 0

            if button == 3:
                return 9

            return None

        if control_scheme == "modern":
            if button == 1:
                return "LMB"

            if button == 3:
                return "RMB"

            return None

        return None


    def get_bound_skill_id_for_pointer_action(self, actor, button):
        slot = self.get_pointer_action_slot(button)
        if slot is None:
            return None

        return self.game.world.skills.get((actor, slot))


    def capture_pointer_action_presses(self, input_state):
        world = self.game.world
        actor = world.player

        if actor is None:
            return

        for button in sorted(input_state.mouse_pressed):
            if button not in {1, 3}:
                continue

            self.capture_pointer_action_press(
                input_state,
                actor,
                button,
            )


    def capture_pointer_action_press(self, input_state, actor, button):
        world = self.game.world

        hovered = world.hovered_selectable
        hovered_kind = None

        if hovered is not None:
            hovered_kind = world.selectable.get(
                hovered,
                {},
            ).get("kind")

        slot = self.get_pointer_action_slot(button)
        skill_id = self.get_bound_skill_id_for_pointer_action(
            actor,
            button,
        )
        input_context = self.get_pointer_input_context(
            button,
            input_state,
        )

        action_state = {
            "button": button,
            "slot": slot,
            "skill_id": skill_id,
            "input_context": input_context,
            "press_tick": world.tick,
            "press_mouse_pos": input_state.mouse_pos,
            "press_hovered_entity": hovered,
            "press_hovered_kind": hovered_kind,
            "hard_target": None,
            "hard_target_kind": None,
            "consumes_button_until_release": False,
            "hard_target_invalidated": False,
        }

        attack_in_place = input_context_uses_attack_in_place(
            skill_id,
            input_context,
        )

        if (
                hovered_kind == "interactable"
                and skill_allows_hard_target_kind(skill_id, hovered_kind)
        ):
            action_state["hard_target"] = hovered
            action_state["hard_target_kind"] = hovered_kind
            action_state["consumes_button_until_release"] = True

            set_action_order(
                world,
                actor,
                self.build_hard_target_action_order(
                    actor,
                    hovered,
                    hovered_kind,
                    skill_id,
                    slot,
                    button,
                ),
            )

        elif (
                hovered_kind == "enemy"
                and not attack_in_place
                and skill_allows_hard_target_kind(skill_id, hovered_kind)
        ):
            action_state["hard_target"] = hovered
            action_state["hard_target_kind"] = hovered_kind
            action_state["consumes_button_until_release"] = True

            set_action_order(
                world,
                actor,
                self.build_hard_target_action_order(
                    actor,
                    hovered,
                    hovered_kind,
                    skill_id,
                    slot,
                    button,
                ),
            )

        elif self.should_create_no_hard_target_pointer_order(
                skill_id,
                input_context,
        ):
            action_state["consumes_button_until_release"] = True

            set_action_order(
                world,
                actor,
                self.build_no_hard_target_action_order(
                    actor,
                    skill_id,
                    slot,
                    button,
                    input_context,
                    input_state,
                ),
            )

        else:
            clear_action_order(world, actor)

        pointer_actions = world.pointer_action_state.setdefault(
            actor,
            {},
        )
        pointer_actions[button] = action_state


    def shift_modifier_is_held(self, input_state):
        return (
                input_state.keys[pygame.K_LSHIFT]
                or input_state.keys[pygame.K_RSHIFT]
        )


    def get_pointer_input_context(self, button, input_state):
        control_scheme = self.game.world.control_scheme

        if control_scheme == "traditional":
            if button == 1:
                if self.shift_modifier_is_held(input_state):
                    return "traditional_shift_left"
                return "traditional_left"

            if button == 3:
                return "traditional_right"

        if control_scheme == "modern":
            if button == 1:
                return "modern_left"
            if button == 3:
                return "modern_right"

        return None


    def should_create_no_hard_target_pointer_order(
            self,
            skill_id,
            input_context,
    ):
        if input_context is None:
            return False

        order_type = get_no_hard_target_action_order_type(
            skill_id,
            input_context,
        )

        return order_type is not None

    def build_no_hard_target_action_order(
            self,
            actor,
            skill_id,
            slot,
            button,
            input_context,
            input_state,
    ):
        world = self.game.world

        order_type = get_no_hard_target_action_order_type(
            skill_id,
            input_context,
        )

        if order_type == "move_with_soft_skill_use":
            return {
                "type": "move_with_soft_skill_use",
                "actor": actor,
                "skill_id": skill_id,
                "slot": slot,
                "button": button,
                "input_context": input_context,
                "target_lock": "none",
                "created_tick": world.tick,
                "press_mouse_pos": input_state.mouse_pos,
                "fired_once": False,
            }

        if order_type == "soft_skill_use_or_attack_air":
            return {
                "type": "soft_skill_use_or_attack_air",
                "actor": actor,
                "skill_id": skill_id,
                "slot": slot,
                "button": button,
                "input_context": input_context,
                "target_lock": "none",
                "created_tick": world.tick,
                "press_mouse_pos": input_state.mouse_pos,
                "fired_once": False,
            }

        raise NotImplementedError(
            f"No-hard-target order type not implemented: {order_type!r}"
        )

    def update_held_pointer_action_contexts(self, input_state):
        world = self.game.world
        actor = world.player

        if actor is None:
            return

        pointer_actions = world.pointer_action_state.get(actor)
        if pointer_actions is None:
            return

        for button, action_state in sorted(list(pointer_actions.items())):
            if not self.is_mouse_button_held(input_state, button):
                continue

            self.update_held_pointer_action_context(
                input_state,
                actor,
                button,
                action_state,
            )

    def update_held_pointer_action_context(
            self,
            input_state,
            actor,
            button,
            action_state,
    ):
        # Hard-target presses are intentionally stable until release.
        # Example: click monster, monster dies, button stays consumed.
        if action_state.get("hard_target") is not None:
            return

        old_context = action_state.get("input_context")
        new_context = self.get_pointer_input_context(
            button,
            input_state,
        )

        if new_context == old_context:
            return

        action_state["input_context"] = new_context

        skill_id = action_state.get("skill_id")
        slot = action_state.get("slot")

        if self.should_create_no_hard_target_pointer_order(
                skill_id,
                new_context,
        ):
            action_state["consumes_button_until_release"] = True

            set_action_order(
                self.game.world,
                actor,
                self.build_no_hard_target_action_order(
                    actor,
                    skill_id,
                    slot,
                    button,
                    new_context,
                    input_state,
                ),
            )
            return

        action_state["consumes_button_until_release"] = False
        self.clear_no_hard_target_order_for_button(
            actor,
            button,
        )

    def clear_no_hard_target_order_for_button(self, actor, button):
        order = self.game.world.action_order.get(actor)
        if order is None:
            return

        if order.get("button") != button:
            return

        if order.get("target_lock") != "none":
            return

        clear_action_order(
            self.game.world,
            actor,
        )


    def get_hovered_combat_target_for_skill(self, skill_id):
        world = self.game.world
        hovered = world.hovered_selectable

        if hovered is None:
            return None

        hovered_kind = world.selectable.get(
            hovered,
            {},
        ).get("kind")

        if hovered_kind != "enemy":
            return None

        if hovered not in world.transform:
            return None

        if hovered not in world.health:
            return None

        if hovered not in world.hittable:
            return None

        return hovered

    def add_skill_target_context_to_intent(self, intent, actor):
        slot = intent.get("slot")
        if slot is None:
            return intent

        skill_id = self.game.world.skills.get((actor, slot))
        target = self.get_hovered_combat_target_for_skill(skill_id)

        if target is None:
            return intent

        intent = dict(intent)
        intent["target_entity"] = target
        intent["target_source"] = "hovered"
        return intent


    def clear_pointer_action_releases(self, input_state):
        world = self.game.world
        actor = world.player

        if actor is None:
            return

        pointer_actions = world.pointer_action_state.get(actor)
        if pointer_actions is None:
            return

        for button in sorted(input_state.mouse_released):
            pointer_actions.pop(button, None)

        if not pointer_actions:
            world.pointer_action_state.pop(actor, None)


    def pointer_button_has_hard_target_order(self, actor, button):
        order = self.game.world.action_order.get(actor)
        if order is None:
            return False

        if order.get("button") != button:
            return False

        return order.get("target_lock") == "hard"


    def pointer_button_is_consumed_until_release(self, actor, button):
        pointer_actions = self.game.world.pointer_action_state.get(
            actor,
            {},
        )
        action_state = pointer_actions.get(button)

        if action_state is None:
            return False

        return action_state.get(
            "consumes_button_until_release",
            False,
        )


    def mark_consumed_pointer_action_invalidated(self, actor, button):
        pointer_actions = self.game.world.pointer_action_state.get(
            actor,
            {},
        )
        action_state = pointer_actions.get(button)

        if action_state is None:
            return

        if not action_state.get("consumes_button_until_release", False):
            return

        action_state["hard_target_invalidated"] = True


    def build_hard_target_action_order(
            self,
            actor,
            target,
            target_kind,
            skill_id,
            slot,
            button,
    ):
        world = self.game.world

        if target_kind == "interactable":
            return {
                "type": "interact_with_entity",
                "actor": actor,
                "target": target,
                "target_kind": target_kind,
                "skill_id": skill_id,
                "slot": slot,
                "button": button,
                "target_lock": "hard",
                "created_tick": world.tick,
                "fired_once": False,
            }

        if target_kind == "enemy":
            return {
                "type": "use_skill_on_entity",
                "actor": actor,
                "target": target,
                "target_kind": target_kind,
                "skill_id": skill_id,
                "slot": slot,
                "button": button,
                "target_lock": "hard",
                "created_tick": world.tick,
                "fired_once": False,
            }

        raise ValueError(
            f"Unsupported hard target kind: {target_kind!r}"
        )

    def get_bound_skill_id_for_keyboard_action(self, actor, key):
        slot = KEY_TO_SKILL_SLOT.get(key)
        if slot is None:
            return None

        return self.game.world.skills.get((actor, slot))

    def capture_keyboard_action_presses(self, input_state):
        world = self.game.world
        actor = world.player

        if actor is None:
            return

        for key in sorted(input_state.keys_pressed):
            if key not in KEY_TO_SKILL_SLOT:
                continue

            self.capture_keyboard_action_press(
                input_state,
                actor,
                key,
            )

    def capture_keyboard_action_press(self, input_state, actor, key):
        world = self.game.world

        hovered = world.hovered_selectable
        hovered_kind = None

        if hovered is not None:
            hovered_kind = world.selectable.get(
                hovered,
                {},
            ).get("kind")

        slot = KEY_TO_SKILL_SLOT[key]
        skill_id = self.get_bound_skill_id_for_keyboard_action(
            actor,
            key,
        )
        input_context = self.get_keyboard_input_context(key)

        action_state = {
            "key": key,
            "slot": slot,
            "skill_id": skill_id,
            "input_context": input_context,
            "press_tick": world.tick,
            "press_mouse_pos": input_state.mouse_pos,
            "press_hovered_entity": hovered,
            "press_hovered_kind": hovered_kind,
            "hard_target": None,
            "hard_target_kind": None,
            "consumes_key_until_release": False,
            "hard_target_invalidated": False,
        }

        if (
                hovered_kind == "enemy"
                and skill_allows_hard_target_kind(skill_id, hovered_kind)
                and self.keyboard_hard_target_is_allowed_now(
            actor,
            hovered,
            skill_id,
            input_context,
        )
        ):
            action_state["hard_target"] = hovered
            action_state["hard_target_kind"] = hovered_kind
            action_state["consumes_key_until_release"] = True

            set_action_order(
                world,
                actor,
                self.build_keyboard_hard_target_action_order(
                    actor,
                    hovered,
                    hovered_kind,
                    skill_id,
                    slot,
                    key,
                ),
            )

        elif self.should_create_no_hard_target_keyboard_order(
                skill_id,
                input_context,
        ):
            action_state["consumes_key_until_release"] = True

            set_action_order(
                world,
                actor,
                self.build_keyboard_no_hard_target_action_order(
                    actor,
                    skill_id,
                    slot,
                    key,
                    input_context,
                    input_state,
                ),
            )

        keyboard_actions = world.keyboard_action_state.setdefault(
            actor,
            {},
        )
        keyboard_actions[key] = action_state


    def build_keyboard_hard_target_action_order(
            self,
            actor,
            target,
            target_kind,
            skill_id,
            slot,
            key,
    ):
        world = self.game.world

        if target_kind != "enemy":
            raise ValueError(
                f"Unsupported keyboard hard target kind: {target_kind!r}"
            )

        return {
            "type": "use_skill_on_entity",
            "actor": actor,
            "target": target,
            "target_kind": target_kind,
            "skill_id": skill_id,
            "slot": slot,
            "input_kind": "keyboard",
            "key": key,
            "target_lock": "hard",
            "created_tick": world.tick,
            "fired_once": False,
        }


    def clear_keyboard_action_releases(self, input_state):
        world = self.game.world
        actor = world.player

        if actor is None:
            return

        keyboard_actions = world.keyboard_action_state.get(actor)
        if keyboard_actions is None:
            return

        for key in sorted(input_state.keys_released):
            keyboard_actions.pop(key, None)

        if not keyboard_actions:
            world.keyboard_action_state.pop(actor, None)


    def keyboard_key_is_consumed_until_release(self, actor, key):
        keyboard_actions = self.game.world.keyboard_action_state.get(
            actor,
            {},
        )
        action_state = keyboard_actions.get(key)

        if action_state is None:
            return False

        return action_state.get(
            "consumes_key_until_release",
            False,
        )


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
        actor = self.game.world.player

        for key, slot in KEY_TO_SKILL_SLOT.items():
            key_is_consumed = self.keyboard_key_is_consumed_until_release(
                actor,
                key,
            )

            if key in input_state.keys_pressed and not key_is_consumed:
                intent = {
                    "type": "skill_pressed",
                    "slot": slot,
                    "mouse_pos": input_state.mouse_pos,
                }
                intents.append(
                    self.add_skill_target_context_to_intent(
                        intent,
                        actor,
                    )
                )

            if input_state.keys[key] and not key_is_consumed:
                intent = {
                    "type": "skill_held",
                    "slot": slot,
                    "mouse_pos": input_state.mouse_pos,
                }
                intents.append(
                    self.add_skill_target_context_to_intent(
                        intent,
                        actor,
                    )
                )

            if key in input_state.keys_released:
                intents.append({
                    "type": "skill_released",
                    "slot": slot,
                    "mouse_pos": input_state.mouse_pos,
                })


    def append_mouse_skill_intents(self, intents, input_state, mouse_to_slot):
        actor = self.game.world.player

        for button, slot in mouse_to_slot.items():
            button_is_consumed = self.pointer_button_is_consumed_until_release(
                actor,
                button,
            )

            if button in input_state.mouse_pressed and not button_is_consumed:
                intents.append({
                    "type": "skill_pressed",
                    "slot": slot,
                    "mouse_pos": input_state.mouse_pos,
                })

            if (
                    self.is_mouse_button_held(input_state, button)
                    and not button_is_consumed
            ):
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
        self.update_hovered_selectable(input_state)

        gameplay_input_state = self.build_gameplay_input_state(input_state)

        self.capture_pointer_action_presses(gameplay_input_state)
        self.capture_keyboard_action_presses(gameplay_input_state)

        self.update_held_pointer_action_contexts(gameplay_input_state)

        self.clear_pointer_action_releases(gameplay_input_state)
        self.clear_keyboard_action_releases(gameplay_input_state)

        control_scheme = self.game.world.control_scheme
        if control_scheme == "traditional":
            return self.build_traditional_player_intents(gameplay_input_state)
        return self.build_modern_player_intents(gameplay_input_state)


    def build_traditional_player_intents(self, input_state):
        intents = []

        if 1 in input_state.mouse_pressed or self.is_mouse_button_held(input_state, 1):
            if (
                    not self.shift_modifier_is_held(input_state)
                    and not self.pointer_button_is_consumed_until_release(
                self.game.world.player,
                1,
            )
            ):
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

    def update_hovered_selectable(self, input_state):
        world = self.game.world

        if self.gameplay_ui.mouse_over_ui(input_state.mouse_pos):
            world.hovered_selectable = None
            return

        world.hovered_selectable = resolve_hovered_selectable(
            world,
            input_state.mouse_pos,
        )


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
        action_order_system(self.game.world, intents)

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
        interact_system(self.game.world)
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