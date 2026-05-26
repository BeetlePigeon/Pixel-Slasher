from skill_loader import load_external_skill_defs


PYTHON_SKILL_DEFS = {}

EXTERNAL_SKILL_DEFS = load_external_skill_defs()

DUPLICATE_SKILL_IDS = (
    set(PYTHON_SKILL_DEFS)
    & set(EXTERNAL_SKILL_DEFS)
)

if DUPLICATE_SKILL_IDS:
    raise ValueError(
        f"Duplicate skill ids defined in Python and external data: "
        f"{sorted(DUPLICATE_SKILL_IDS)}"
    )

SKILL_DEFS = {
    **PYTHON_SKILL_DEFS,
    **EXTERNAL_SKILL_DEFS,
}