from .camera_system import start_camera_shake


def feedback_system(world, events):
    for event in events:
        event_type = event["type"]

        if event_type == "entity_destroyed_by_static_collision":
            start_camera_shake(
                world,
                duration_ticks=10,
                strength=2,
            )