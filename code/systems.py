def intent_system(world, intents):
    for entity, entity_intents in intents.items():
        for intent in entity_intents:
            if intent["type"] == "move":
                dx, dy = intent["direction"]

                vx, vy = world.velocity.get(entity, (0, 0))
                world.velocity[entity] = (vx + dx, vy + dy)

def movement_system(world, dt):
    for entity in world.velocity:
        vx, vy = world.velocity[entity]
        px, py = world.position[entity]
        world.position[entity] = (px + vx * dt, py + vy * dt)

def skill_system(world, intents):
    for entity, entity_intents in intents.items():

        for intent in entity_intents:

            if intent["type"] == "skill_pressed":
                slot = intent["slot"]
                skill = world.skills.get((entity, slot))

                if skill:
                    print(f"{skill=} was Pressed")

            elif intent["type"] == "skill_released":
                slot = intent["slot"]
                skill = world.skills.get((entity, slot))

                if skill:
                    print(f"{skill=} was just Released")

def iso_to_screen(x, y, tile_size):
    screen_x = (x - y) * (tile_size // 2)
    screen_y = (x + y) * (tile_size // 4)
    return screen_x, screen_y

def render_tiles(world, surface):
    offset_x, offset_y = world.camera_offset

    for y, row in enumerate(world.tilemap):
        for x, tile in enumerate(row):
            if tile == 0:
                continue

            screen_x, screen_y = iso_to_screen(x, y, world.tile_size)

            surface.blit(
                world.tile_images[tile],
                (screen_x + offset_x, screen_y + offset_y)
            )

def sprite_system(world, surface):
    draw_list = []
    offset_x, offset_y = world.camera_offset

    for entity in world.sprite:
        if entity not in world.position:
            continue

        pos = world.position[entity]
        sprite = world.sprite[entity]

        screen_x, screen_y = iso_to_screen(pos[0], pos[1], world.tile_size)

        draw_list.append((
            screen_y + sprite.get("z", 0),
            sprite["image"],
            (
                screen_x + offset_x + sprite["offset"][0],
                screen_y + offset_y + sprite["offset"][1]
            )
        ))

    draw_list.sort(key=lambda x: x[0])

    for _, image, pos in draw_list:
        surface.blit(image, pos)