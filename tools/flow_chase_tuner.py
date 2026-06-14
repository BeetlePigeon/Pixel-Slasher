import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk


REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "code"

if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from flow_chase_tuning import (  # noqa: E402
    DISPLAY_RAW,
    DISPLAY_TILE,
    DISPLAY_TILE_SQ,
    FLOW_CHASE_KNOB_DEFS,
    KIND_BOOL,
    TILE_UNITS,
    format_runtime_value,
    get_flow_chase_tuning_state,
    load_flow_chase_tuning,
    print_flow_chase_tuning_values,
    randomize_flow_chase_tuning,
    reset_flow_chase_tuning_to_defaults,
    write_flow_chase_tuning_state,
)


SLIDER_WIDTH = 520
SLIDER_HEIGHT = 42
SLIDER_PAD_X = 18
HANDLE_RADIUS = 6


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def is_logarithmic_knob(knob_state):
    display_unit = knob_state.get("display_unit", DISPLAY_RAW)
    hard_min = knob_state["hard_min"]
    hard_max = knob_state["hard_max"]

    if display_unit not in {DISPLAY_TILE, DISPLAY_TILE_SQ}:
        return False

    if hard_max <= hard_min:
        return False

    if hard_min < 0:
        return False

    return True


def normalized_to_value(t, knob_state):
    hard_min = int(knob_state["hard_min"])
    hard_max = int(knob_state["hard_max"])

    t = clamp(t, 0.0, 1.0)

    if hard_max <= hard_min:
        return hard_min

    if not is_logarithmic_knob(knob_state):
        return int(round(hard_min + t * (hard_max - hard_min)))

    if hard_min == 0:
        # Log-like range with a true zero endpoint.
        import math

        value = math.exp(t * math.log(hard_max + 1)) - 1
        return int(round(clamp(value, hard_min, hard_max)))

    import math

    log_min = math.log(hard_min)
    log_max = math.log(hard_max)
    value = math.exp(log_min + t * (log_max - log_min))
    return int(round(clamp(value, hard_min, hard_max)))


def value_to_normalized(value, knob_state):
    hard_min = int(knob_state["hard_min"])
    hard_max = int(knob_state["hard_max"])

    value = clamp(int(value), hard_min, hard_max)

    if hard_max <= hard_min:
        return 0.0

    if not is_logarithmic_knob(knob_state):
        return (value - hard_min) / (hard_max - hard_min)

    if hard_min == 0:
        import math

        return math.log(value + 1) / math.log(hard_max + 1)

    import math

    return (math.log(value) - math.log(hard_min)) / (
        math.log(hard_max) - math.log(hard_min)
    )


def value_to_x(value, knob_state):
    t = value_to_normalized(value, knob_state)
    usable_width = SLIDER_WIDTH - SLIDER_PAD_X * 2
    return SLIDER_PAD_X + t * usable_width


def x_to_value(x, knob_state):
    usable_width = SLIDER_WIDTH - SLIDER_PAD_X * 2
    t = (x - SLIDER_PAD_X) / usable_width
    return normalized_to_value(t, knob_state)


def format_knob_display_name(name):
    prefixes = [
        "FLOW_CHASE_PROACTIVE_",
        "FLOW_CHASE_LOCAL_STEERING_",
        "FLOW_CHASE_",
    ]

    for prefix in prefixes:
        if name.startswith(prefix):
            return name[len(prefix):].lower()

    return name.lower()


def format_compact_value(value, knob_state):
    display_unit = knob_state.get("display_unit", DISPLAY_RAW)

    if display_unit == DISPLAY_TILE:
        return f"{value * 100 / TILE_UNITS:.1f}%"

    if display_unit == DISPLAY_TILE_SQ:
        return f"{value * 100 / (TILE_UNITS * TILE_UNITS):.3f}%²"

    return str(value)


class IntKnobSlider(tk.Canvas):
    def __init__(self, parent, knob_state, on_change, on_commit):
        super().__init__(
            parent,
            width=SLIDER_WIDTH,
            height=SLIDER_HEIGHT,
            highlightthickness=0,
            bg="#202020",
        )

        self.knob_state = knob_state
        self.on_change = on_change
        self.on_commit = on_commit
        self.dragging = None

        self.bind("<Button-1>", self.on_mouse_down)
        self.bind("<B1-Motion>", self.on_mouse_drag)
        self.bind("<ButtonRelease-1>", self.on_mouse_up)

        self.redraw()

    def redraw(self):
        self.delete("all")

        y = SLIDER_HEIGHT // 2

        hard_min = self.knob_state["hard_min"]
        hard_max = self.knob_state["hard_max"]
        random_min = self.knob_state["random_min"]
        random_max = self.knob_state["random_max"]
        value = self.knob_state["value"]

        min_x = value_to_x(random_min, self.knob_state)
        max_x = value_to_x(random_max, self.knob_state)
        value_x = value_to_x(value, self.knob_state)

        left_x = SLIDER_PAD_X
        right_x = SLIDER_WIDTH - SLIDER_PAD_X

        self.create_line(
            left_x,
            y,
            right_x,
            y,
            fill="#666666",
            width=3,
        )

        self.create_line(
            min_x,
            y,
            max_x,
            y,
            fill="#4a90e2",
            width=6,
        )

        self.create_oval(
            min_x - HANDLE_RADIUS,
            y - HANDLE_RADIUS,
            min_x + HANDLE_RADIUS,
            y + HANDLE_RADIUS,
            fill="#dddddd",
            outline="#000000",
        )

        self.create_oval(
            max_x - HANDLE_RADIUS,
            y - HANDLE_RADIUS,
            max_x + HANDLE_RADIUS,
            y + HANDLE_RADIUS,
            fill="#dddddd",
            outline="#000000",
        )

        self.create_rectangle(
            value_x - HANDLE_RADIUS,
            y - HANDLE_RADIUS - 2,
            value_x + HANDLE_RADIUS,
            y + HANDLE_RADIUS + 2,
            fill="#f5a623",
            outline="#000000",
        )

        self.create_text(
            SLIDER_PAD_X,
            8,
            anchor="w",
            fill="#aaaaaa",
            text=format_compact_value(hard_min, self.knob_state),
        )

        self.create_text(
            SLIDER_WIDTH - SLIDER_PAD_X,
            8,
            anchor="e",
            fill="#aaaaaa",
            text=format_compact_value(hard_max, self.knob_state),
        )

    def nearest_handle(self, x):
        positions = {
            "random_min": value_to_x(self.knob_state["random_min"], self.knob_state),
            "value": value_to_x(self.knob_state["value"], self.knob_state),
            "random_max": value_to_x(self.knob_state["random_max"], self.knob_state),
        }

        return min(
            positions,
            key=lambda name: abs(positions[name] - x),
        )

    def on_mouse_down(self, event):
        self.dragging = self.nearest_handle(event.x)
        self.apply_drag(event.x)

    def on_mouse_drag(self, event):
        self.apply_drag(event.x)

    def on_mouse_up(self, event):
        self.apply_drag(event.x)
        self.dragging = None
        self.on_commit()

    def apply_drag(self, x):
        if self.dragging is None:
            return

        new_value = x_to_value(x, self.knob_state)

        hard_min = int(self.knob_state["hard_min"])
        hard_max = int(self.knob_state["hard_max"])

        if self.dragging == "random_min":
            self.knob_state["random_min"] = clamp(
                new_value,
                hard_min,
                int(self.knob_state["random_max"]),
            )

            if self.knob_state["value"] < self.knob_state["random_min"]:
                self.knob_state["value"] = self.knob_state["random_min"]

        elif self.dragging == "random_max":
            self.knob_state["random_max"] = clamp(
                new_value,
                int(self.knob_state["random_min"]),
                hard_max,
            )

            if self.knob_state["value"] > self.knob_state["random_max"]:
                self.knob_state["value"] = self.knob_state["random_max"]

        elif self.dragging == "value":
            self.knob_state["value"] = clamp(
                new_value,
                int(self.knob_state["random_min"]),
                int(self.knob_state["random_max"]),
            )

        self.redraw()
        self.on_change()


class IntKnobRow(ttk.Frame):
    def __init__(self, parent, knob_def, knob_state, on_dirty, on_commit):
        super().__init__(parent)

        self.knob_def = knob_def
        self.knob_state = knob_state
        self.on_dirty = on_dirty
        self.on_commit = on_commit

        self.name_label = ttk.Label(
            self,
            text=knob_def.name,
            width=50,
        )
        self.name_label.grid(
            row=0,
            column=0,
            sticky="w",
            padx=(4, 8),
        )

        self.value_label = ttk.Label(
            self,
            width=38,
        )
        self.value_label.grid(
            row=0,
            column=1,
            sticky="w",
            padx=(0, 8),
        )

        self.slider = IntKnobSlider(
            self,
            knob_state,
            on_change=self.refresh,
            on_commit=on_commit,
        )
        self.slider.grid(
            row=0,
            column=2,
            sticky="w",
        )

        self.refresh()

    def refresh(self):
        self.value_label.configure(
            text=(
                f"value={format_runtime_value(self.knob_state)}  "
                f"range=[{format_compact_value(self.knob_state['random_min'], self.knob_state)}, "
                f"{format_compact_value(self.knob_state['random_max'], self.knob_state)}]"
            )
        )
        self.on_dirty()


class BoolKnobRow(ttk.Frame):
    def __init__(self, parent, knob_def, knob_state, on_dirty, on_commit):
        super().__init__(parent)

        self.knob_def = knob_def
        self.knob_state = knob_state
        self.on_dirty = on_dirty
        self.on_commit = on_commit

        self.value_var = tk.BooleanVar(value=bool(knob_state["value"]))
        self.min_var = tk.BooleanVar(value=bool(knob_state["random_min"]))
        self.max_var = tk.BooleanVar(value=bool(knob_state["random_max"]))

        ttk.Label(
            self,
            text=knob_def.name,
            width=58,
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=(4, 8),
        )

        ttk.Checkbutton(
            self,
            text="value",
            variable=self.value_var,
            command=self.apply,
        ).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(0, 12),
        )

        ttk.Checkbutton(
            self,
            text="random_min",
            variable=self.min_var,
            command=self.apply,
        ).grid(
            row=0,
            column=2,
            sticky="w",
            padx=(0, 12),
        )

        ttk.Checkbutton(
            self,
            text="random_max",
            variable=self.max_var,
            command=self.apply,
        ).grid(
            row=0,
            column=3,
            sticky="w",
            padx=(0, 12),
        )

    def apply(self):
        self.knob_state["value"] = bool(self.value_var.get())
        self.knob_state["random_min"] = bool(self.min_var.get())
        self.knob_state["random_max"] = bool(self.max_var.get())

        self.on_dirty()
        self.on_commit()


class FlowChaseTunerApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("FlowChase Tuner")
        self.geometry("1220x760")

        self.state = None
        self.rows = []

        self.status_var = tk.StringVar(value="")

        self.create_widgets()
        self.reload_from_disk()

    def create_widgets(self):
        top = ttk.Frame(self)
        top.pack(
            side="top",
            fill="x",
            padx=8,
            pady=8,
        )

        ttk.Button(
            top,
            text="Reload",
            command=self.reload_from_disk,
        ).pack(
            side="left",
            padx=(0, 8),
        )

        ttk.Button(
            top,
            text="Save",
            command=self.save_to_disk,
        ).pack(
            side="left",
            padx=(0, 8),
        )

        ttk.Button(
            top,
            text="Randomize",
            command=self.randomize,
        ).pack(
            side="left",
            padx=(0, 8),
        )

        ttk.Button(
            top,
            text="Reset Defaults",
            command=self.reset_defaults,
        ).pack(
            side="left",
            padx=(0, 8),
        )

        ttk.Button(
            top,
            text="Print Values",
            command=print_flow_chase_tuning_values,
        ).pack(
            side="left",
            padx=(0, 8),
        )

        ttk.Label(
            top,
            textvariable=self.status_var,
        ).pack(
            side="left",
            padx=(16, 0),
        )

        self.canvas = tk.Canvas(self)
        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
        )

        self.scroll_frame = ttk.Frame(self.canvas)

        self.scroll_frame.bind(
            "<Configure>",
            lambda _event: self.canvas.configure(
                scrollregion=self.canvas.bbox("all"),
            ),
        )

        self.canvas_window = self.canvas.create_window(
            (0, 0),
            window=self.scroll_frame,
            anchor="nw",
        )

        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(
            side="left",
            fill="both",
            expand=True,
        )
        self.scrollbar.pack(
            side="right",
            fill="y",
        )

        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.bind_all("<MouseWheel>", self.on_mouse_wheel)

    def on_canvas_configure(self, event):
        self.canvas.itemconfigure(
            self.canvas_window,
            width=event.width,
        )

    def on_mouse_wheel(self, event):
        self.canvas.yview_scroll(
            int(-1 * (event.delta / 120)),
            "units",
        )

    def set_status(self, message):
        self.status_var.set(message)

    def clear_rows(self):
        for child in self.scroll_frame.winfo_children():
            child.destroy()

        self.rows = []

    def rebuild_rows(self):
        self.clear_rows()

        for row_index, knob_def in enumerate(FLOW_CHASE_KNOB_DEFS):
            knob_state = self.state[knob_def.name]

            if knob_def.kind == KIND_BOOL:
                row = BoolKnobRow(
                    self.scroll_frame,
                    knob_def,
                    knob_state,
                    on_dirty=self.mark_dirty,
                    on_commit=self.save_to_disk,
                )
            else:
                row = IntKnobRow(
                    self.scroll_frame,
                    knob_def,
                    knob_state,
                    on_dirty=self.mark_dirty,
                    on_commit=self.save_to_disk,
                )

            row.grid(
                row=row_index,
                column=0,
                sticky="ew",
                pady=2,
            )

            self.rows.append(row)

    def mark_dirty(self):
        self.set_status("Unsaved drag in progress")

    def reload_from_disk(self):
        load_flow_chase_tuning()
        self.state = get_flow_chase_tuning_state()
        self.rebuild_rows()
        self.set_status("Reloaded")

    def save_to_disk(self):
        self.state = write_flow_chase_tuning_state(self.state)
        self.set_status("Saved")

    def reset_defaults(self):
        self.state = reset_flow_chase_tuning_to_defaults()
        self.rebuild_rows()
        self.set_status("Reset defaults and saved")

    def randomize(self):
        self.state = randomize_flow_chase_tuning()
        self.rebuild_rows()
        self.set_status("Randomized and saved")


def main():
    app = FlowChaseTunerApp()
    app.mainloop()


if __name__ == "__main__":
    main()