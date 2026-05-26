import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = PROJECT_ROOT / "data" / "skills"


TOP_LEVEL_SET_FIELDS = {
    "blocked_by_motion_tags",
    "blocked_by_action_tags",
    "cancels_action_tags",
    "required_components",
    "required_params",
}


PARAM_TUPLE_FIELDS = {
    "slide_min_tangent_ratio",
    "grid_slide_min_tangent_ratio",
    "mouse_slide_min_tangent_ratio",
}


def load_external_skill_defs(skills_dir=SKILLS_DIR):
    if not skills_dir.exists():
        raise FileNotFoundError(
            f"External skill directory does not exist: {skills_dir}"
        )

    skill_defs = {}

    for path in sorted(skills_dir.glob("*.json")):
        skill_def = load_skill_def_file(path)
        skill_id = skill_def["id"]

        if skill_id in skill_defs:
            raise ValueError(
                f"Duplicate external skill id {skill_id!r} in {path}"
            )

        skill_defs[skill_id] = skill_def

    return skill_defs


def load_skill_def_file(path):
    with path.open("r", encoding="utf-8") as file:
        raw_skill_def = json.load(file)

    skill_def = normalize_skill_def(raw_skill_def, path)

    expected_id = path.stem
    if skill_def["id"] != expected_id:
        raise ValueError(
            f"Skill file {path} has id {skill_def['id']!r}; "
            f"expected {expected_id!r}"
        )

    return skill_def


def normalize_skill_def(skill_def, path):
    skill_def = dict(skill_def)

    for field_name in TOP_LEVEL_SET_FIELDS:
        if field_name in skill_def:
            skill_def[field_name] = normalize_set_field(
                skill_def[field_name],
                path,
                field_name,
            )

    if "allowed_param_values" in skill_def:
        skill_def["allowed_param_values"] = normalize_allowed_param_values(
            skill_def["allowed_param_values"],
            path,
        )

    if "params" in skill_def:
        skill_def["params"] = normalize_params(
            skill_def["params"],
            path,
            "params",
        )

    if skill_def.get("cast") is not None:
        skill_def["cast"] = normalize_action_def(
            skill_def["cast"],
            path,
            "cast",
        )

    if skill_def.get("channel") is not None:
        skill_def["channel"] = normalize_action_def(
            skill_def["channel"],
            path,
            "channel",
        )

    return skill_def


def normalize_set_field(value, path, field_name):
    if not isinstance(value, list):
        raise ValueError(
            f"Skill file {path} field {field_name!r} must be a list"
        )

    return set(value)


def normalize_allowed_param_values(allowed_param_values, path):
    if not isinstance(allowed_param_values, dict):
        raise ValueError(
            f"Skill file {path} allowed_param_values must be a dict"
        )

    normalized = {}

    for param_name, allowed_values in allowed_param_values.items():
        if not isinstance(allowed_values, list):
            raise ValueError(
                f"Skill file {path} allowed_param_values[{param_name!r}] "
                f"must be a list"
            )

        normalized[param_name] = set(allowed_values)

    return normalized


def normalize_action_def(action_def, path, action_name):
    action_def = dict(action_def)

    if "tags" in action_def:
        action_def["tags"] = normalize_set_field(
            action_def["tags"],
            path,
            f"{action_name}.tags",
        )

    if "events" in action_def:
        action_def["events"] = [
            normalize_action_event(
                event,
                path,
                f"{action_name}.events[{index}]",
            )
            for index, event in enumerate(action_def["events"])
        ]

    if "repeat_events" in action_def:
        action_def["repeat_events"] = [
            normalize_action_event(
                event,
                path,
                f"{action_name}.repeat_events[{index}]",
            )
            for index, event in enumerate(action_def["repeat_events"])
        ]

    if "phases" in action_def:
        action_def["phases"] = [
            normalize_action_phase(
                phase,
                path,
                f"{action_name}.phases[{index}]",
            )
            for index, phase in enumerate(action_def["phases"])
        ]

    return action_def


def normalize_action_event(event, path, field_name):
    event = dict(event)

    if "params" in event:
        event["params"] = normalize_params(
            event["params"],
            path,
            f"{field_name}.params",
        )

    return event


def normalize_action_phase(phase, path, field_name):
    phase = dict(phase)

    if "tags" in phase:
        phase["tags"] = normalize_set_field(
            phase["tags"],
            path,
            f"{field_name}.tags",
        )

    return phase


def normalize_params(params, path, field_name):
    if not isinstance(params, dict):
        raise ValueError(
            f"Skill file {path} field {field_name!r} must be a dict"
        )

    params = dict(params)

    for param_name in PARAM_TUPLE_FIELDS:
        if param_name in params:
            value = params[param_name]

            if (
                not isinstance(value, list)
                or len(value) != 2
                or not all(isinstance(item, int) for item in value)
            ):
                raise ValueError(
                    f"Skill file {path} field "
                    f"{field_name}.{param_name} must be a two-int list"
                )

            params[param_name] = tuple(value)

    return params