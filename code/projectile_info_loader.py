import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECTILE_INFO_DIR = PROJECT_ROOT / "data" / "projectile_info"


def load_external_projectile_info(
    projectile_info_dir=PROJECTILE_INFO_DIR,
):
    if not projectile_info_dir.exists():
        raise FileNotFoundError(
            "External projectile info directory does not exist: "
            f"{projectile_info_dir}"
        )

    projectile_info_by_id = {}

    for path in sorted(projectile_info_dir.glob("*.json")):
        projectile_info = load_projectile_info_file(path)
        projectile_id = projectile_info["id"]

        if projectile_id in projectile_info_by_id:
            raise ValueError(
                f"Duplicate projectile info id {projectile_id!r} in {path}"
            )

        projectile_info_by_id[projectile_id] = projectile_info

    return projectile_info_by_id


def load_projectile_info_file(path):
    with path.open("r", encoding="utf-8") as file:
        projectile_info = json.load(file)

    expected_id = path.stem
    if projectile_info["id"] != expected_id:
        raise ValueError(
            f"Projectile info file {path} has id "
            f"{projectile_info['id']!r}; expected {expected_id!r}"
        )

    return projectile_info