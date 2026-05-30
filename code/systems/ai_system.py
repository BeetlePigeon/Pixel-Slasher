from ai.ai_context import build_ai_context
from ai.ai_queries import entity_is_valid_ai_actor
from ai.ai_registry import get_ai_behavior
from utils.perf_profiler import profiled


@profiled("ai_system")
def ai_system(world, intents):
    for entity in sorted(world.ai_agent):
        agent = world.ai_agent.get(entity)

        if agent is None:
            continue

        if not agent.get("enabled", True):
            continue

        if not entity_is_valid_ai_actor(
            world,
            entity,
        ):
            continue

        if world.tick < agent.get("next_think_tick", 0):
            continue

        think_interval_ticks = max(
            1,
            agent.get("think_interval_ticks", 6),
        )

        agent["next_think_tick"] = (
            world.tick
            + think_interval_ticks
        )

        ai_type = agent.get("type")

        behavior = get_ai_behavior(
            ai_type,
        )

        ctx = build_ai_context(
            world,
            entity,
            agent,
        )

        behavior_intents = behavior(ctx)

        if not behavior_intents:
            continue

        intents.setdefault(
            entity,
            [],
        ).extend(behavior_intents)