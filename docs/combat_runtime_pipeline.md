# Combat Runtime Pipeline

This document explains the runtime combat/projectile/effect architecture at a high level.

It is meant to answer:

- What kind of object should a skill create?
- Which system owns which decision?
- How does a projectile hit turn into damage?
- When should we use a projectile versus an effect carrier?
- Where should future features fit?

This is not a line-by-line code guide. It is an ownership and mental-model guide.

---

## 1. Core mental model

```text
Skill
  -> spawner
    -> runtime object

Projectile / runtime object
  -> movement_system
  -> projectile_impact_system
    -> projectile event
      -> projectile_effect_system
        -> effect carrier
          -> effect_delivery_system
            -> payload
              -> damage / heal / status request
                -> resolver system
```

The important split is:

```text
Projectile pipeline:
  runtime objects that move, sit, contact actors, emit influence, or react to impact

Effect delivery pipeline:
  timed targeting/filtering/payload execution
```

Many gameplay features use both.

Example: Fireball is a projectile. Its impact creates an effect carrier. The effect carrier owns an explosion delivery. The delivery creates damage requests.

---

## 2. Glossary

### Skill

A skill definition describes player/AI usage:

- input trigger
- cooldown
- cast/channel timing
- aim rules
- cast events
- which runtime object or effect to spawn

A skill should not describe every internal projectile component. It should usually say something like:

```text
at cast tick 17, spawn projectile_id = fireball
```

### Projectile

A projectile is a runtime object archetype.

A projectile may:

- move
- sit still
- expire by lifetime
- have a contact footprint
- collide with static/dynamic movement blockers
- emit influence
- trigger effects from projectile events
- apply impact responses such as `destroy_self` or `continue`

Projectiles are not only arrows. Static hazards and non-damaging runtime objects can also use projectile info.

Examples:

```text
fireball
piercing bolt
spiral projectile
magnet orb
future flame patch
future Frozen Orb shard
```

### Projectile info

Projectile info is data that describes what a projectile/runtime object is:

- motion
- lifetime
- sprite
- movement footprint
- contact footprint
- movement collision policy
- impact responses
- effect triggers
- influence emitter/receiver data

Projectile info lives in:

```text
data/projectile_info/
```

### Projectile impact system

The projectile impact system owns projectile-specific impact/contact interpretation.

It:

- consumes raw movement collision facts for projectiles
- detects projectile contact footprint vs actor collision footprint
- applies projectile contact cadence
- applies projectile impact responses
- emits normalized projectile events

It does not:

- move projectiles
- spawn effect carriers
- apply damage directly

### Projectile effect system

The projectile effect system consumes normalized projectile events and spawns effect carriers from the projectile's effect triggers.

It does not decide whether a projectile hit something.

It does not decide whether the projectile dies.

It does not apply damage directly.

### Effect trigger

An effect trigger is projectile-owned data:

```text
when projectile event X happens,
spawn an effect carrier with these effect delivery templates
```

Example:

```text
projectile_dynamic_actor_contact
  -> spawn contact damage effect carrier
```

### Effect carrier

An effect carrier is a runtime ECS entity that owns one or more effect deliveries.

It answers:

- where is this effect happening?
- who caused it?
- what skill caused it?
- how long does it live?
- what deliveries does it own?

Examples:

```text
fireball explosion carrier
meteor delayed impact carrier
slash area carrier
burning field carrier
poison cloud carrier
```

### Effect delivery

An effect delivery is one timing/targeting/payload behavior owned by an effect carrier.

It answers:

- when do I activate?
- what targets do I select?
- how do I filter them?
- how often can a target be affected?
- what payloads do I apply?

Examples:

```text
immediate contact-target damage
once-at-tick-75 meteor impact damage
continuous field damage every 20 ticks
```

### Payload

A payload is the gameplay operation inside a delivery.

Current examples:

```text
damage
heal
status
```

Future examples may include:

```text
spawn_projectiles
spawn_effect_carrier
```

### Damage request / damage event

A damage payload creates a concrete damage request.

The damage resolver applies it to health and emits result events for reactions/feedback.

---

## 3. Ownership rules

### movement_system

Owns movement and raw movement collision facts.

It should answer:

```text
Where did the entity try to move?
Was movement blocked by static terrain?
Was movement blocked by dynamic movement blockers?
What movement collision result occurred?
```

It should not answer:

```text
Should Fireball explode?
Should this projectile deal fire damage?
Should this projectile pierce?
```

### projectile_impact_system

Owns projectile impact/contact meaning and projectile response.

It should answer:

```text
Did this projectile contact an actor?
Did a raw movement collision become a projectile_static_impact?
Did a raw movement collision become a projectile_dynamic_movement_impact?
Should this projectile destroy itself or continue?
```

### projectile_effect_system

Owns converting normalized projectile events into effect carriers.

It should answer:

```text
This projectile event happened. Does this projectile have an effect trigger for it?
If yes, what effect carrier should be spawned?
```

### effect_delivery_system

Owns activation, selection, filtering, cadence, and payload execution.

It should answer:

```text
Does this delivery fire now?
Who are the targets?
Are they valid?
Can they be affected this tick?
What payloads apply?
```

### spawners

Own entity/component construction.

They answer:

```text
Given this projectile/effect/entity archetype and spawn context,
which ECS components should be attached?
```

### skill JSON

Owns skill usage.

It should contain:

```text
cast timing
aim rules
input behavior
which projectile/effect/spawner to invoke
skill-only params such as spawn distance
```

### projectile_info JSON

Owns projectile/runtime object identity.

It should contain:

```text
motion
lifetime
sprite
footprints
movement collision
impact responses
effect triggers
influence components
```

---

## 4. Event categories

### Raw movement collision event

Produced by movement.

Describes movement-domain collision facts.

Examples:

```text
entity_movement_blocked
entity_destroyed_by_movement_collision
```

### Normalized projectile event

Produced by projectile impact system.

Describes projectile-domain contact/impact meaning.

Examples:

```text
projectile_dynamic_actor_contact
projectile_static_impact
projectile_dynamic_movement_impact
```

### Effect / damage result event

Produced after payload resolution.

Describes what actually happened.

Examples:

```text
damage_applied
entity_killed
status_applied
```

---

## 5. Common flows

### Fireball

```text
skill cast event
  -> execute_projectile
  -> spawn_projectile("fireball")

fireball moves
  -> movement_system updates position

fireball overlaps enemy or hits wall
  -> projectile_impact_system emits:
       projectile_dynamic_actor_contact
       or projectile_static_impact
  -> projectile_impact_system applies destroy_self

projectile_effect_system
  -> sees fireball effect trigger
  -> spawns explosion effect carrier

effect_delivery_system
  -> explosion delivery selects area targets
  -> damage payload creates damage requests
```

### Piercing projectile

```text
projectile overlaps enemy
  -> projectile_impact_system applies contact cadence
  -> emits projectile_dynamic_actor_contact
  -> impact response = continue

projectile_effect_system
  -> spawns contact damage effect carrier

effect_delivery_system
  -> damages contact target
```

### Magnet orb

```text
skill cast event
  -> execute_placed_projectile
  -> spawn_projectile("magnet_orb")

generic spawner attaches:
  transform
  sprite
  lifetime
  influence_emitter

influence emitter system
  -> reads influence_emitter
  -> affects influence receivers
```

Magnet orb does not need projectile contact/effect triggers unless it later becomes damaging or contact-reactive.

### Slash / counter slash

```text
skill or reaction
  -> spawns effect carrier
  -> effect delivery selects slash area
  -> damage payload applies to targets
```

Slash is not a projectile because it does not need movement, impact response, projectile contact runtime, or projectile lifetime.

### Meteor

Meteor is currently best modeled as an effect carrier:

```text
skill places meteor effect carrier at target tile

effect carrier
  -> delivery fires once at impact tick
  -> selects impact area
  -> damage payload applies impact damage

future:
  -> delivery-level payload spawns flame_patch projectiles
```

Meteor does not need to be a projectile unless it becomes a contact/impact-driven runtime object.

### Future flame patch

A flame patch should likely be a static hazard projectile:

```text
flame_patch projectile:
  motion = static
  lifetime = X
  contact footprint = plus5
  contact cadence = per_target_cooldown
  impact response on actor contact = continue
  effect trigger on projectile_dynamic_actor_contact = fire damage contact target
```

Each flame patch has its own contact runtime, so overlapping patches naturally stack damage.

---

## 6. When to use projectile vs effect carrier

Use projectile_info / projectile pipeline when the object:

- moves or sits as a runtime world object
- has lifetime
- has contact footprint
- needs projectile impact responses
- emits influence
- uses per-projectile contact cadence
- should be spawned as an independent runtime hazard

Use effect carrier / effect delivery when the effect:

- is a timed targeting/payload operation
- does not need projectile contact checks
- does not need movement or impact response
- is a slash, burst, delayed area hit, or simple continuous field

Use both when:

- a projectile hit creates an effect carrier
- an effect delivery later spawns hazard projectiles
- a runtime object creates timed/targeted payload effects

---

## 7. Meteor clarification

Meteor is not modeled as a projectile right now because its impact is not caused by a projectile contact event.

It is caused by scheduled activation:

```text
activation once at tick X
```

That maps naturally to an effect delivery.

If Meteor were modeled as a static placed projectile, we would need projectile-side support for a timed self-event such as:

```text
projectile_age_reached
projectile_timer_elapsed
projectile_scripted_impact
```

Then:

```text
meteor projectile exists
  -> projectile timer reaches impact tick
  -> projectile_impact_system or projectile_behavior_system emits projectile_scripted_impact
  -> projectile_effect_system spawns effect carrier
```

That is possible, but it is more machinery than the current effect carrier model requires.

Use projectile Meteor only if Meteor becomes projectile-like:

- falling object with movement
- can be intercepted
- collides/contacts before impact
- has projectile impact responses
- needs projectile contact events

Otherwise, effect carrier is simpler and correct.

---

## 8. Naming guidance

Prefer names that reveal ownership.

Good:

```text
projectile_impact_system
projectile_effect_system
effect_delivery_system
projectile_info
impact_responses
effect_triggers
```

Avoid vague names when possible:

```text
handler
effect
thing
special
```

---

## 9. Commenting guidance

Do not comment every line.

Use comments for ownership boundaries and non-obvious decisions.

Useful module header pattern:

```python
"""
Projectile impact system.

Owns projectile-domain contact/impact interpretation:
- converts raw movement collision events into projectile impact events
- detects projectile contact_footprint vs actor collision_footprint
- applies projectile impact responses
- emits normalized projectile events

Does not move projectiles.
Does not spawn effect carriers.
Does not apply damage directly.
"""
```

Good inline comments explain why, not what.

Bad:

```python
# Loop over projectiles.
```

Good:

```python
# Contact cadence lives on the projectile so overlapping flame patches
# stack independently and each patch owns its own next-hit timing.
```

---

## 10. Current classification

```text
Projectile pipeline:
  fireball
  test_projectile
  pierce_projectile
  burst_projectile
  spiral_projectile
  magnet_orb
  future flame_patch
  future Frozen Orb shard

Effect carrier / delivery:
  slash
  counter slash
  meteor delayed impact
  simple burning field

Hybrid:
  fireball = projectile -> explosion effect carrier
  meteor = effect carrier -> future flame_patch projectiles
```

---

## 11. Future notes

Likely future features:

```text
flame_patch projectile_info
delivery-level spawn_projectiles payload
Frozen-Orb-style projectile behavior
proc system that can spawn projectiles or effects
```

Keep the ownership rule stable:

```text
skills decide when/how to invoke
spawners construct runtime objects
projectile impact decides projectile contact/response
projectile effect converts projectile events to effect carriers
effect delivery executes targeting/payloads
resolvers apply concrete gameplay changes
```
