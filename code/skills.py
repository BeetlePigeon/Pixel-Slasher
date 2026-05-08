from support import Vec2i, scale_dir, DashController
from settings import TILE_UNITS
from spawners import (
    spawn_test_projectile,
    spawn_spiral_projectile,
    create_magnet_emitter,
)

def execute_dash(world, caster, intent, skill):
    if caster not in world.transform:
        return False

    if caster not in world.motion_state:
        return False

    direction = world.facing.get(caster, Vec2i(1, -1))
    motion_state = world.motion_state[caster]

    motion_state["controller"] = DashController(
        direction=direction,
        age=0,
        duration=8,
        distance=TILE_UNITS * 3,
    )

    motion_state["influence_mode"] = "ignore_all"

    return True

def execute_test_projectile(world, caster, intent, skill):
    if caster not in world.transform:       # Since projectiles use caster for spawn point. Later, can change this: add a default arg for cast location and if none and also no caster THEN don't cast. Good for cutscene projectile spawning, 'ambient' casts of projectiles etc
        return False

    caster_cpos = world.transform[caster].cpos
    direction = world.facing.get(caster, Vec2i(1, -1))

    spawn_offset = scale_dir(direction, TILE_UNITS // 4)
    spawn_cpos = caster_cpos + spawn_offset

    spawn_test_projectile(world, spawn_cpos, direction)

    return True

def execute_spiral_projectile(world, caster, intent, skill):
    if caster not in world.transform:       # Since projectiles use caster for spawn point. Later, can change this: add a default arg for cast location and if none and also no caster THEN don't cast. Good for cutscene projectile spawning, 'ambient' casts of projectiles etc
        return False

    caster_cpos = world.transform[caster].cpos

    spawn_spiral_projectile(world, caster_cpos)

    return True

def execute_magnet(world, caster, intent, skill):
    if caster not in world.transform:
        return False

    caster_cpos = world.transform[caster].cpos
    direction = world.facing.get(caster, Vec2i(1, -1))

    spawn_offset = scale_dir(direction, TILE_UNITS)
    spawn_cpos = caster_cpos + spawn_offset

    create_magnet_emitter(world, spawn_cpos)

    return True

SKILL_HANDLERS = {
    "test_projectile": execute_test_projectile,
    "spiral_projectile": execute_spiral_projectile,
    "magnet_orb": execute_magnet,
    "dash": execute_dash,
}