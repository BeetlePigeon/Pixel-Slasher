from dataclasses import replace
import pygame


class GameplayUI:
    def __init__(self):
        self.captured_mouse_buttons = set()

    def get_rects(self):
        # Temporary debug UI region.
        # Later this should come from a real UI/widget tree.
        return [
            pygame.Rect(8, 8, 32, 32),
        ]

    def mouse_over_ui(self, mouse_pos):
        for rect in self.get_rects():
            if rect.collidepoint(mouse_pos):
                return True

        return False

    def is_mouse_button_held(self, input_state, button):
        index = button - 1

        if index < 0 or index >= len(input_state.mouse_buttons):
            return False

        return input_state.mouse_buttons[index]

    def filter_input_for_gameplay(self, input_state):
        mouse_over_ui = self.mouse_over_ui(input_state.mouse_pos)
        consumed_buttons = set()

        # If a button is pressed while over UI, UI captures it until release.
        for button in input_state.mouse_pressed:
            if mouse_over_ui:
                self.captured_mouse_buttons.add(button)

        consumed_buttons.update(self.captured_mouse_buttons)

        # Held buttons should also be suppressed while currently over UI.
        # This handles cases where the cursor moves over UI while already holding.
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
            self.captured_mouse_buttons.discard(button)

        return replace(
            input_state,
            mouse_buttons=filtered_mouse_buttons,
            mouse_pressed=filtered_mouse_pressed,
            mouse_released=filtered_mouse_released,
        )

    def draw(self, surface):
        for rect in self.get_rects():
            pygame.draw.rect(surface, "gray", rect)
            pygame.draw.rect(surface, "white", rect, 1)