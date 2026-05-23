from support import tile_from_cpos


def get_entity_current_tile(world, entity):
    transform = world.transform.get(entity)

    if transform is None:
        return None

    return tile_from_cpos(transform.cpos)


def entity_is_hittable(world, entity):
    hittable = world.hittable.get(entity)

    if hittable is None:
        return False

    return hittable.get("enabled", True)


def entities_are_enemies(world, source, target):
    source_team = world.team.get(source)
    target_team = world.team.get(target)

    if source_team is None or target_team is None:
        return False

    return source_team != target_team


def find_hittable_entities_on_tiles(world, source, tiles):
    tile_set = set(tiles)
    targets = []

    for entity in sorted(world.hittable):
        if entity == source:
            continue

        if entity not in world.transform:
            continue

        if not entity_is_hittable(world, entity):
            continue

        if not entities_are_enemies(world, source, entity):
            continue

        entity_tile = get_entity_current_tile(world, entity)

        if entity_tile in tile_set:
            targets.append(entity)

    return targets


def queue_damage_event(
    world,
    source,
    target,
    amount,
    skill_id=None,
    hit_tile=None,
):
    world.damage_requests.append({
        "source": source,
        "target": target,
        "amount": amount,
        "skill_id": skill_id,
        "hit_tile": hit_tile,
    })


def queue_area_damage(
    world,
    source,
    tiles,
    amount,
    skill_id=None,
):
    targets = find_hittable_entities_on_tiles(
        world,
        source,
        tiles,
    )

    for target in targets:
        queue_damage_event(
            world,
            source=source,
            target=target,
            amount=amount,
            skill_id=skill_id,
            hit_tile=get_entity_current_tile(world, target),
        )

    return targets