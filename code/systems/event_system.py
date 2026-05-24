from .reaction_system import reaction_system
from .feedback_system import feedback_system


def event_system(world):
    events = list(world.events)
    world.events.clear()

    reaction_system(world, events)
    feedback_system(world, events)


def emit_event(world, event_type, **data):
    world.events.append({
        "type": event_type,
        **data,
    })