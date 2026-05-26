from skill_loader import load_external_skill_defs


def build_skill_defs():
    return load_external_skill_defs()


def replace_skill_defs(new_skill_defs):
    # Mutate in place instead of rebinding SKILL_DEFS.
    #
    # Some modules import SKILL_DEFS directly. If live reload later assigned a
    # new dict object, those modules would keep pointing at the old dict.
    # Clearing/updating keeps existing references connected to the live table.
    SKILL_DEFS.clear()
    SKILL_DEFS.update(new_skill_defs)


SKILL_DEFS = build_skill_defs()