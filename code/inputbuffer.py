from inputhandler import InputState


class InputBuffer:
    def __init__(self):
        self.pending_keys_pressed = set()
        self.pending_keys_released = set()
        self.pending_mouse_pressed = set()
        self.pending_mouse_released = set()

    def add_frame_input(self, input_state: InputState):
        self.pending_keys_pressed.update(input_state.keys_pressed)
        self.pending_keys_released.update(input_state.keys_released)
        self.pending_mouse_pressed.update(input_state.mouse_pressed)
        self.pending_mouse_released.update(input_state.mouse_released)

    def build_sim_input_state(self, raw_input_state: InputState, include_edges: bool) -> InputState:
        if include_edges:
            keys_pressed = set(self.pending_keys_pressed)
            keys_released = set(self.pending_keys_released)
            mouse_pressed = set(self.pending_mouse_pressed)
            mouse_released = set(self.pending_mouse_released)
        else:
            keys_pressed = set()
            keys_released = set()
            mouse_pressed = set()
            mouse_released = set()

        return InputState(
            keys=raw_input_state.keys,
            keys_pressed=keys_pressed,
            keys_released=keys_released,

            mouse_buttons=raw_input_state.mouse_buttons,
            mouse_pressed=mouse_pressed,
            mouse_released=mouse_released,

            mouse_pos=raw_input_state.mouse_pos,
            quit=raw_input_state.quit,
        )

    def clear_edges(self):
        self.pending_keys_pressed.clear()
        self.pending_keys_released.clear()
        self.pending_mouse_pressed.clear()
        self.pending_mouse_released.clear()