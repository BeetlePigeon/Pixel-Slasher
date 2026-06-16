from support import Vec2i
from systems.movement_system import (
    set_move_target,
    clear_move_target,
    buffer_move_intent,
    cancel_voluntary_movement,
    start_or_update_recenter_for_action,
)


def intent_system(world, intents):
    world.move_intent.clear()
    world.interact_request.clear()

    for entity, entity_intents in intents.items():
        found_move_intent = False

        for intent in entity_intents:
            if intent["type"] == "interact":
                world.interact_request.append(
                    {
                        "actor": entity,
                        "target": intent["target"],
                        "skill_id": intent.get("skill_id"),
                        "button": intent.get("button"),
                    }
                )
                continue

            if intent["type"] == "stop_moving":
                cancel_voluntary_movement(
                    world,
                    entity,
                )
                continue

            if intent["type"] == "recenter_for_action":
                start_or_update_recenter_for_action(
                    world,
                    entity,
                    intent["target_tile"],
                    intent["target_cpos"],
                    intent.get("owner_order_id"),
                )
                continue

            if intent["type"] == "clear_move_target":
                clear_move_target(
                    world,
                    entity,
                )
                continue

            if intent["type"] == "move_to_tile":
                set_move_target(
                    world,
                    entity,
                    intent["target_tile"],
                    intent.get("target_cpos"),
                    path_policy=intent.get("path_policy", "actor_move"),
                    owner_order_id=intent.get("owner_order_id"),
                )
                continue

            if intent["type"] != "move":
                continue

            if found_move_intent:
                continue

            dx, dy = intent["direction"]

            if dx == 0 and dy == 0:
                continue

            direction = Vec2i(dx, dy)
            world.move_intent[entity] = direction

            # Manual directional movement cancels click-to-move target.
            clear_move_target(world, entity)

            motion_state = world.motion_state.get(entity)

            if motion_state is not None:
                if motion_state.get("controller") is not None:
                    buffer_move_intent(world, entity, direction)

            if entity in world.facing:
                world.facing[entity] = direction

            found_move_intent = True