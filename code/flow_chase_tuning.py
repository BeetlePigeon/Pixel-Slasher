import json
import random
from dataclasses import dataclass
from pathlib import Path

from constants import TILE_UNITS


CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
TUNING_PATH = CONFIG_DIR / "flow_chase_tuning.local.json"

KIND_INT = "int"
KIND_BOOL = "bool"

DISPLAY_RAW = "raw"
DISPLAY_TILE = "tile"
DISPLAY_TILE_SQ = "tile_sq"


@dataclass(frozen=True)
class FlowChaseKnobDef:
    name: str
    kind: str
    default: int | bool
    random_min: int | bool
    random_max: int | bool
    hard_min: int | bool
    hard_max: int | bool
    display_unit: str = DISPLAY_RAW


def tile_percent(percent: int) -> int:
    return TILE_UNITS * percent // 100


def tile_sq_percent(percent: int) -> int:
    return TILE_UNITS * TILE_UNITS * percent // 100


FLOW_CHASE_KNOB_DEFS = [
    # Local steering / reactive steering.
    FlowChaseKnobDef(
        name="FLOW_CHASE_LOCAL_STEERING_ENABLED",
        kind=KIND_BOOL,
        default=True,
        random_min=True,
        random_max=True,
        hard_min=False,
        hard_max=True,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_LOCAL_STEERING_SIDE_PERSIST_TICKS",
        kind=KIND_INT,
        default=12,
        random_min=4,
        random_max=24,
        hard_min=0,
        hard_max=120,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_LOCAL_STEERING_MAX_EXTRA_DISTANCE_CPOS",
        kind=KIND_INT,
        default=TILE_UNITS * 2,
        random_min=TILE_UNITS,
        random_max=TILE_UNITS * 4,
        hard_min=tile_percent(1),
        hard_max=tile_percent(1000),
        display_unit=DISPLAY_TILE,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_LOCAL_STEERING_TINY_MOVE_DIAGNOSTIC_CPOS",
        kind=KIND_INT,
        default=TILE_UNITS // 8,
        random_min=TILE_UNITS // 32,
        random_max=TILE_UNITS // 4,
        hard_min=0,
        hard_max=TILE_UNITS,
        display_unit=DISPLAY_TILE,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_LOCAL_STEERING_MIN_RESOLVED_NUMERATOR",
        kind=KIND_INT,
        default=3,
        random_min=2,
        random_max=4,
        hard_min=0,
        hard_max=16,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_LOCAL_STEERING_MIN_RESOLVED_DENOMINATOR",
        kind=KIND_INT,
        default=4,
        random_min=4,
        random_max=8,
        hard_min=1,
        hard_max=32,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_LOCAL_STEERING_SHARP_TURN_DOT_MAX",
        kind=KIND_INT,
        default=0,
        random_min=0,
        random_max=0,
        hard_min=-(TILE_UNITS * TILE_UNITS),
        hard_max=TILE_UNITS * TILE_UNITS,
        display_unit=DISPLAY_TILE_SQ,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_LOCAL_STEERING_PURE_SIDE_MIN_NO_PROGRESS_TICKS",
        kind=KIND_INT,
        default=9999,
        random_min=9999,
        random_max=9999,
        hard_min=0,
        hard_max=9999,
    ),

    # Proactive candidate selection.
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_STEERING_ENABLED",
        kind=KIND_BOOL,
        default=True,
        random_min=True,
        random_max=True,
        hard_min=False,
        hard_max=True,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_NEIGHBOR_RADIUS_CPOS",
        kind=KIND_INT,
        default=TILE_UNITS * 2,
        random_min=TILE_UNITS,
        random_max=TILE_UNITS * 3,
        hard_min=tile_percent(1),
        hard_max=tile_percent(1000),
        display_unit=DISPLAY_TILE,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_DYNAMIC_COLLISION_PENALTY",
        kind=KIND_INT,
        default=TILE_UNITS * 19,
        random_min=TILE_UNITS * 10,
        random_max=TILE_UNITS * 30,
        hard_min=0,
        hard_max=TILE_UNITS * 50,
        display_unit=DISPLAY_TILE,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_STATIC_COLLISION_PENALTY",
        kind=KIND_INT,
        default=TILE_UNITS * 42,
        random_min=TILE_UNITS * 20,
        random_max=TILE_UNITS * 50,
        hard_min=0,
        hard_max=TILE_UNITS * 80,
        display_unit=DISPLAY_TILE,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_PARTIAL_MOVE_PENALTY",
        kind=KIND_INT,
        default=TILE_UNITS * 4,
        random_min=TILE_UNITS,
        random_max=TILE_UNITS * 8,
        hard_min=0,
        hard_max=TILE_UNITS * 20,
        display_unit=DISPLAY_TILE,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_CLEARANCE_WEIGHT",
        kind=KIND_INT,
        default=4,
        random_min=1,
        random_max=8,
        hard_min=0,
        hard_max=32,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_SIDE_CONTINUITY_BONUS",
        kind=KIND_INT,
        default=TILE_UNITS // 3,
        random_min=0,
        random_max=TILE_UNITS * 2,
        hard_min=0,
        hard_max=TILE_UNITS * 10,
        display_unit=DISPLAY_TILE,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_SIDE_SWITCH_PENALTY",
        kind=KIND_INT,
        default=TILE_UNITS * 3,
        random_min=TILE_UNITS,
        random_max=TILE_UNITS * 6,
        hard_min=0,
        hard_max=TILE_UNITS * 20,
        display_unit=DISPLAY_TILE,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_DIRECT_BIAS",
        kind=KIND_INT,
        default=TILE_UNITS // 8,
        random_min=0,
        random_max=TILE_UNITS,
        hard_min=0,
        hard_max=TILE_UNITS * 10,
        display_unit=DISPLAY_TILE,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_HOLD_ON_ALL_COLLIDING",
        kind=KIND_BOOL,
        default=True,
        random_min=True,
        random_max=True,
        hard_min=False,
        hard_max=True,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_ALLOW_STATIC_SLIDE",
        kind=KIND_BOOL,
        default=False,
        random_min=False,
        random_max=False,
        hard_min=False,
        hard_max=True,
    ),

    # Candidate tier penalties.
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_TIER_1_PENALTY",
        kind=KIND_INT,
        default=0,
        random_min=0,
        random_max=0,
        hard_min=0,
        hard_max=TILE_UNITS * 10,
        display_unit=DISPLAY_TILE,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_TIER_2_PENALTY",
        kind=KIND_INT,
        default=TILE_UNITS // 2,
        random_min=0,
        random_max=TILE_UNITS + TILE_UNITS // 2,
        hard_min=0,
        hard_max=TILE_UNITS * 10,
        display_unit=DISPLAY_TILE,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_TIER_3_PENALTY",
        kind=KIND_INT,
        default=TILE_UNITS,
        random_min=0,
        random_max=TILE_UNITS * 3,
        hard_min=0,
        hard_max=TILE_UNITS * 10,
        display_unit=DISPLAY_TILE,
    ),

    # Recent movement / anti-backtracking.
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_RECENT_MOVE_BLEND_OLD_NUMERATOR",
        kind=KIND_INT,
        default=3,
        random_min=1,
        random_max=7,
        hard_min=0,
        hard_max=16,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_RECENT_MOVE_BLEND_NEW_NUMERATOR",
        kind=KIND_INT,
        default=1,
        random_min=1,
        random_max=4,
        hard_min=0,
        hard_max=16,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_RECENT_MOVE_BLEND_DENOMINATOR",
        kind=KIND_INT,
        default=4,
        random_min=2,
        random_max=8,
        hard_min=1,
        hard_max=32,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_BACKTRACK_DOT_DEADZONE",
        kind=KIND_INT,
        default=TILE_UNITS * TILE_UNITS // 64,
        random_min=0,
        random_max=tile_sq_percent(10),
        hard_min=0,
        hard_max=TILE_UNITS * TILE_UNITS,
        display_unit=DISPLAY_TILE_SQ,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_BACKTRACK_PENALTY",
        kind=KIND_INT,
        default=TILE_UNITS * 3,
        random_min=TILE_UNITS,
        random_max=TILE_UNITS * 8,
        hard_min=0,
        hard_max=TILE_UNITS * 20,
        display_unit=DISPLAY_TILE,
    ),
    FlowChaseKnobDef(
        name="FLOW_CHASE_PROACTIVE_CONTINUATION_BONUS",
        kind=KIND_INT,
        default=TILE_UNITS // 2,
        random_min=0,
        random_max=TILE_UNITS * 2,
        hard_min=0,
        hard_max=TILE_UNITS * 10,
        display_unit=DISPLAY_TILE,
    ),
]


_TUNING_STATE = None
_TUNING_MTIME_NS = None


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def coerce_int(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(fallback)


def normalize_bool_knob_state(knob_def, raw_state):
    if not isinstance(raw_state, dict):
        raw_state = {}

    return {
        "kind": KIND_BOOL,
        "display_unit": DISPLAY_RAW,
        "value": bool(raw_state.get("value", knob_def.default)),
        "random_min": bool(raw_state.get("random_min", knob_def.random_min)),
        "random_max": bool(raw_state.get("random_max", knob_def.random_max)),
        "hard_min": bool(knob_def.hard_min),
        "hard_max": bool(knob_def.hard_max),
    }


def normalize_int_knob_state(knob_def, raw_state):
    if not isinstance(raw_state, dict):
        raw_state = {}

    hard_min = int(knob_def.hard_min)
    hard_max = int(knob_def.hard_max)

    random_min = clamp(
        coerce_int(raw_state.get("random_min"), knob_def.random_min),
        hard_min,
        hard_max,
    )
    random_max = clamp(
        coerce_int(raw_state.get("random_max"), knob_def.random_max),
        hard_min,
        hard_max,
    )

    if random_min > random_max:
        random_min, random_max = random_max, random_min

    value = clamp(
        coerce_int(raw_state.get("value"), knob_def.default),
        random_min,
        random_max,
    )

    return {
        "kind": KIND_INT,
        "display_unit": knob_def.display_unit,
        "value": value,
        "random_min": random_min,
        "random_max": random_max,
        "hard_min": hard_min,
        "hard_max": hard_max,
    }


def normalize_knob_state(knob_def, raw_state):
    if knob_def.kind == KIND_BOOL:
        return normalize_bool_knob_state(knob_def, raw_state)

    return normalize_int_knob_state(knob_def, raw_state)


def build_default_tuning_state():
    return {
        knob_def.name: normalize_knob_state(knob_def, {})
        for knob_def in FLOW_CHASE_KNOB_DEFS
    }


def normalize_tuning_state(raw_state):
    if not isinstance(raw_state, dict):
        raw_state = {}

    return {
        knob_def.name: normalize_knob_state(
            knob_def,
            raw_state.get(knob_def.name),
        )
        for knob_def in FLOW_CHASE_KNOB_DEFS
    }


def write_flow_chase_tuning_state(state):
    global _TUNING_STATE
    global _TUNING_MTIME_NS

    normalized_state = normalize_tuning_state(state)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    temp_path = TUNING_PATH.with_suffix(TUNING_PATH.suffix + ".tmp")

    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(
            normalized_state,
            file,
            indent=2,
            sort_keys=True,
        )
        file.write("\n")

    temp_path.replace(TUNING_PATH)

    _TUNING_STATE = normalized_state

    try:
        _TUNING_MTIME_NS = TUNING_PATH.stat().st_mtime_ns
    except OSError:
        _TUNING_MTIME_NS = None

    return _TUNING_STATE


def load_flow_chase_tuning():
    global _TUNING_STATE
    global _TUNING_MTIME_NS

    if not TUNING_PATH.exists():
        return write_flow_chase_tuning_state(build_default_tuning_state())

    try:
        with TUNING_PATH.open("r", encoding="utf-8") as file:
            raw_state = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        print(f"[flow_chase_tuning] failed to load {TUNING_PATH}: {error}")
        raw_state = {}

    _TUNING_STATE = normalize_tuning_state(raw_state)

    try:
        _TUNING_MTIME_NS = TUNING_PATH.stat().st_mtime_ns
    except OSError:
        _TUNING_MTIME_NS = None

    # Re-save normalized state so missing/new knobs appear automatically.
    return write_flow_chase_tuning_state(_TUNING_STATE)


def reload_flow_chase_tuning_if_changed():
    global _TUNING_STATE
    global _TUNING_MTIME_NS

    if not TUNING_PATH.exists():
        load_flow_chase_tuning()
        print("[flow_chase_tuning] created default tuning file")
        return True

    try:
        mtime_ns = TUNING_PATH.stat().st_mtime_ns
    except OSError:
        return False

    if _TUNING_STATE is None or mtime_ns != _TUNING_MTIME_NS:
        load_flow_chase_tuning()
        print("[flow_chase_tuning] live reloaded")
        return True

    return False


def get_flow_chase_tuning_state():
    if _TUNING_STATE is None:
        return load_flow_chase_tuning()

    return _TUNING_STATE


def get_runtime_tuning_values():
    state = get_flow_chase_tuning_state()

    return {
        name: knob_state["value"]
        for name, knob_state in state.items()
    }


def apply_flow_chase_tuning_to_globals(target_globals):
    reload_flow_chase_tuning_if_changed()

    for name, value in get_runtime_tuning_values().items():
        target_globals[name] = value


def reset_flow_chase_tuning_to_defaults():
    return write_flow_chase_tuning_state(build_default_tuning_state())


def randomize_flow_chase_tuning():
    state = get_flow_chase_tuning_state()
    randomized_state = {}

    for knob_def in FLOW_CHASE_KNOB_DEFS:
        knob_state = dict(state[knob_def.name])

        if knob_def.kind == KIND_BOOL:
            if knob_state["random_min"] == knob_state["random_max"]:
                knob_state["value"] = bool(knob_state["random_min"])
            else:
                knob_state["value"] = bool(random.getrandbits(1))
        else:
            random_min = int(knob_state["random_min"])
            random_max = int(knob_state["random_max"])

            if random_min > random_max:
                random_min, random_max = random_max, random_min

            knob_state["value"] = random.randint(random_min, random_max)

        randomized_state[knob_def.name] = knob_state

    return write_flow_chase_tuning_state(randomized_state)


def format_runtime_value(knob_state):
    value = knob_state["value"]
    display_unit = knob_state.get("display_unit", DISPLAY_RAW)

    if display_unit == DISPLAY_TILE:
        return f"{value} cpos ({value * 100 / TILE_UNITS:.2f}% tile)"

    if display_unit == DISPLAY_TILE_SQ:
        return (
            f"{value} dot-units "
            f"({value * 100 / (TILE_UNITS * TILE_UNITS):.4f}% tile^2)"
        )

    return str(value)


def print_flow_chase_tuning_values(prefix="[flow_chase_tuning] values"):
    state = get_flow_chase_tuning_state()
    print(prefix)

    for knob_def in FLOW_CHASE_KNOB_DEFS:
        knob_state = state[knob_def.name]

        print(
            "  "
            f"{knob_def.name}: "
            f"value={format_runtime_value(knob_state)} "
            f"range=[{knob_state['random_min']}, {knob_state['random_max']}]"
        )