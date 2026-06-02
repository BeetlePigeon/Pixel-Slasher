from utils.camera_utils import start_camera_shake


def feedback_system(world, events):
    # Presentation feedback ownership:
    # - This system may trigger camera shake, sound, particles, hit flashes,
    #   screen effects, and other non-gameplay responses.
    # - It should not start gameplay actions, apply damage, or mutate core
    #   combat state.
    for event in events:
        event_type = event["type"]

        if event_type == "entity_destroyed_by_static_collision":
            start_camera_shake(
                world,
                duration_ticks=10,
                strength=0,
            )