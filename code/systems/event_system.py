from .reaction_system import reaction_system
from .projectile_effect_system import projectile_effect_system
from .feedback_system import feedback_system


def event_system(world):
    # Event system ownership:
    # - Snapshot the current event queue.
    # - Clear the queue before dispatch.
    # - Send the same event batch to gameplay reactions and presentation feedback.
    #
    # Events emitted while processing this batch remain in world.events and are
    # intentionally handled on a later tick. This keeps same-tick event chaining
    # out of the engine for now.
    current_events = list(world.events)
    world.events.clear()

    if not current_events:
        return

    reaction_system(world, current_events)
    projectile_effect_system(world, current_events)
    feedback_system(world, current_events)


def emit_event(world, event_type, **data):
    world.events.append({
        "type": event_type,
        **data,
    })