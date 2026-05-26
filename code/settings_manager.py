import json
from copy import deepcopy
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
SETTINGS_PATH = CONFIG_DIR / "settings.json"


DEFAULT_SETTINGS = {
    "display": {
        "display_mode": "windowed",
        "windowed_scale": 1,
        "vsync_enabled": True,
        "fps_cap": 30,
    },

    "controls": {
        "control_scheme": "modern",
        "modern_movement_skill_aim_source": "facing",
        "movement_skill_aim_resolution": 16,
        "projectile_aim_resolution": 128,
    },

    "audio": {
        "master_volume": 100,
        "music_volume": 100,
        "sound_effect_volume": 100,
    },
}


def load_settings(path=SETTINGS_PATH):
    settings = deepcopy(DEFAULT_SETTINGS)

    if not path.exists():
        save_settings(settings, path)
        return settings

    try:
        with path.open("r", encoding="utf-8") as file:
            loaded_settings = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        print(f"[settings] failed to load {path}: {error}")
        print("[settings] using defaults")
        save_settings(settings, path)
        return settings

    merge_settings(
        settings,
        loaded_settings,
    )

    normalize_settings(settings)

    return settings


def save_settings(settings, path=SETTINGS_PATH):
    CONFIG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open("w", encoding="utf-8") as file:
        json.dump(
            settings,
            file,
            indent=2,
            sort_keys=True,
        )
        file.write("\n")


def merge_settings(base, override):
    if not isinstance(override, dict):
        return

    for key, value in override.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            merge_settings(
                base[key],
                value,
            )
        else:
            base[key] = value


def normalize_settings(settings):
    normalize_display_settings(settings["display"])
    normalize_control_settings(settings["controls"])
    normalize_audio_settings(settings["audio"])


def normalize_display_settings(display_settings):
    if display_settings.get("display_mode") not in {
        "windowed",
        "borderless",
        "fullscreen",
    }:
        display_settings["display_mode"] = (
            DEFAULT_SETTINGS["display"]["display_mode"]
        )

    display_settings["windowed_scale"] = coerce_int(
        display_settings.get("windowed_scale"),
        DEFAULT_SETTINGS["display"]["windowed_scale"],
    )

    display_settings["windowed_scale"] = max(
        1,
        display_settings["windowed_scale"],
    )

    display_settings["vsync_enabled"] = bool(
        display_settings.get("vsync_enabled")
    )

    display_settings["fps_cap"] = coerce_int(
        display_settings.get("fps_cap"),
        DEFAULT_SETTINGS["display"]["fps_cap"],
    )


def normalize_control_settings(control_settings):
    if control_settings.get("control_scheme") not in {
        "modern",
        "traditional",
    }:
        control_settings["control_scheme"] = (
            DEFAULT_SETTINGS["controls"]["control_scheme"]
        )

    if control_settings.get("modern_movement_skill_aim_source") not in {
        "facing",
        "mouse",
    }:
        control_settings["modern_movement_skill_aim_source"] = (
            DEFAULT_SETTINGS["controls"]["modern_movement_skill_aim_source"]
        )

    control_settings["movement_skill_aim_resolution"] = coerce_int(
        control_settings.get("movement_skill_aim_resolution"),
        DEFAULT_SETTINGS["controls"]["movement_skill_aim_resolution"],
    )

    control_settings["projectile_aim_resolution"] = coerce_int(
        control_settings.get("projectile_aim_resolution"),
        DEFAULT_SETTINGS["controls"]["projectile_aim_resolution"],
    )


def normalize_audio_settings(audio_settings):
    for key in (
        "master_volume",
        "music_volume",
        "sound_effect_volume",
    ):
        audio_settings[key] = clamp(
            coerce_int(
                audio_settings.get(key),
                DEFAULT_SETTINGS["audio"][key],
            ),
            0,
            100,
        )


def coerce_int(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def clamp(value, minimum, maximum):
    return max(
        minimum,
        min(maximum, value),
    )