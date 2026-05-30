from dataclasses import dataclass


@dataclass(frozen=True)
class AIContext:
    world: object
    entity: int
    agent: dict
    tick: int


def build_ai_context(world, entity, agent):
    return AIContext(
        world=world,
        entity=entity,
        agent=agent,
        tick=world.tick,
    )