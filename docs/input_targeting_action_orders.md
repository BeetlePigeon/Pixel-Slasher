\# Input, Targeting, and Action Orders



This document explains how player input becomes moment-to-moment gameplay.



The system has three major layers:



```text

hardware input

&#x20; -> gameplay input filtering / hover detection

&#x20; -> immediate intents or persistent action orders

&#x20; -> movement / skill / interact systems

```



The main rule:



```text

intents are immediate requests

action orders are persistent goals

```



Examples:



```text

intent:

&#x20; move this tick

&#x20; use this skill this tick

&#x20; interact now



action order:

&#x20; move until close enough, then interact

&#x20; move until close enough, then attack

&#x20; keep attacking in place while Shift+LMB is held

&#x20; move while RMB is held, but attack nearby melee targets if they appear

```



\---



\# 1. UI filtering comes first



Mouse input is filtered before gameplay receives it.



If the cursor is over UI, gameplay should not treat the mouse press as a world click.



```text

raw mouse input

&#x20; -> GameplayUI filters it

&#x20; -> gameplay receives only non-UI mouse input

```



This prevents clicking a UI button from also moving, attacking, selecting a monster, or interacting with a chest.



\---



\# 2. Hovered selectable



Each tick, the game resolves the current hovered selectable entity.



```text

mouse screen position

&#x20; -> selectable click boxes

&#x20; -> world.hovered\_selectable

```



Selectable entities can be things like:



```text

enemy

interactable

```



Hover is a visual/input concept.



It answers:



```text

what is under the cursor right now?

```



It does \*\*not\*\* automatically mean:



```text

this is the current combat target

```



That distinction matters.



A monster can be attacked by soft acquisition without being visually highlighted.



\---



\# 3. Target types



The input system uses three different target concepts.



\## Hovered target



The entity currently under the cursor this frame.



```text

hovered target:

&#x20; used for highlight / name / health display

&#x20; can be sampled when a button is pressed

```



\## Hard target



A press-time target captured from hover.



```text

mouse down over enemy

&#x20; -> hard target = that enemy

```



Hard targets persist for the held action.



Example:



```text

RMB on enemy with Fireball:

&#x20; keep casting at that enemy while RMB is held

&#x20; if the enemy dies, stop casting

&#x20; do not automatically switch to another enemy

&#x20; wait for RMB release

```



This is why hard-target mouse actions feel different from keyboard skill keys.



\## Soft target



A target acquired by combat-assist logic, not by hover.



```text

Shift+LMB melee:

&#x20; find an enemy in melee range and facing FOV

&#x20; attack it if found

&#x20; otherwise attack air

```



Soft targets do not automatically show hover UI.



They are allowed to retarget according to policy.



\---



\# 4. Pointer action state



Mouse buttons create `pointer\_action\_state`.



This remembers what happened when the mouse button was pressed.



Example state:



```text

button

slot

skill\_id

input\_context

press\_mouse\_pos

press\_hovered\_entity

hard\_target

hard\_target\_kind

consumes\_button\_until\_release

```



This state is needed because held behavior depends on how the action started.



Example:



```text

RMB press over enemy:

&#x20; hard target action



RMB press over empty ground:

&#x20; ordinary skill use or move-with-soft-attack, depending skill

```



Those cannot be reconstructed only from the current mouse position.



\---



\# 5. Consumed until release



Some mouse actions consume their button until release.



Example:



```text

RMB press on enemy

&#x20; -> hard target order

&#x20; -> button consumed until release



enemy dies while RMB is still held

&#x20; -> action order clears

&#x20; -> RMB remains consumed

&#x20; -> normal held RMB skill use does not resume

```



This gives Diablo-like behavior:



```text

clicked target dies

&#x20; -> action stops

&#x20; -> player must release and click again

```



Without this rule, a held mouse button would fall back into normal movement or skill use after the hard target died.



\---



\# 6. Action orders



Action orders are stored per actor.



```text

world.action\_order\[actor] = order

```



Current player-facing order types:



```text

interact\_with\_entity

use\_skill\_on\_entity

move\_with\_soft\_skill\_use

soft\_skill\_use\_or\_attack\_air

```



The action order system runs before normal intent processing and appends ordinary intents.



```text

action\_order\_system

&#x20; -> adds move\_to\_tile / skill\_held / skill\_pressed / interact intents

```



The action order system does not apply damage, open chests, or move entities directly.



It only decides what the actor is trying to do this tick.



\---



\# 7. Interactable clicks



Interactables include things like:



```text

door

chest

item

waypoint

```



They share the same click behavior:



```text

click interactable

&#x20; -> interact\_with\_entity order

```



The target decides what interaction means.



```text

door:

&#x20; open door



chest:

&#x20; open chest



item:

&#x20; pick up item



waypoint:

&#x20; use waypoint

```



The current skill or button context can affect interact range.



Most skills use the default interact range.



A telekinesis-like skill could use a larger interact range.



Flow:



```text

click chest



if within interact range:

&#x20; interact now



else:

&#x20; move until within interact range

&#x20; then interact

```



The actor should approach a valid tile within interact range, not the interactable's exact tile.



\---



\# 8. Enemy hard-target clicks



If the mouse press starts over an enemy and the skill allows enemy hard targets:



```text

hover enemy

press mouse button

&#x20; -> hard target = enemy

&#x20; -> use\_skill\_on\_entity order

```



For ranged skills:



```text

RMB Fireball on enemy:

&#x20; cast toward that enemy

&#x20; keep casting at that enemy while RMB is held

&#x20; stop when the enemy dies or becomes invalid

```



For melee skills:



```text

RMB Debug Slash on enemy:

&#x20; if out of range:

&#x20;   move toward target until in range

&#x20; if in range:

&#x20;   attack target

&#x20; if target dies:

&#x20;   clear order

```



The hard-target action does not automatically switch to another enemy after the target dies.



\---



\# 9. Ground / no-hard-target mouse actions



If the mouse press starts on empty ground, behavior depends on button, modifier, control scheme, and bound skill policy.



\## Traditional LMB



Normal LMB on ground:



```text

LMB on ground:

&#x20; move to cursor position

```



Held LMB:



```text

hold LMB:

&#x20; keep moving toward current cursor position / held movement target

```



\## Traditional RMB with ranged skill



RMB with a ranged skill and no hovered target:



```text

RMB Fireball on ground:

&#x20; cast toward cursor

```



Held RMB:



```text

hold RMB:

&#x20; keep casting toward cursor

```



This does not create a hard target.



If the cursor later happens to pass over an enemy, that does not automatically convert the held action into a hard-target action.



\## Traditional RMB with melee skill



RMB with melee and no hovered target uses `move\_with\_soft\_skill\_use`.



```text

RMB Debug Slash on ground:

&#x20; move toward cursor



while held:

&#x20; if enemy enters soft-target range:

&#x20;   stop and attack it



&#x20; if enemy dies or leaves range:

&#x20;   resume moving toward cursor

```



This is a soft-target action, not a hard-target action.



It can retarget according to its policy.



\---



\# 10. Shift + LMB



Shift+LMB is attack-in-place.



It uses `soft\_skill\_use\_or\_attack\_air`.



```text

Shift + LMB:

&#x20; do not move

&#x20; try to soft-acquire a valid melee target

&#x20; if target found:

&#x20;   attack target

&#x20; else:

&#x20;   attack air toward cursor

```



The current Debug Slash policy uses:



```text

range:

&#x20; melee range



FOV:

&#x20; 180 degrees



reference direction:

&#x20; player facing direction

```



This means:



```text

monster in attack range and facing FOV:

&#x20; attack monster



no monster in range/FOV:

&#x20; attack air

```



Shift is a live modifier.



If LMB is already held and Shift is pressed:



```text

LMB moving

press Shift

&#x20; -> switch to attack-in-place

```



If Shift+LMB is held and Shift is released:



```text

release Shift

&#x20; -> stop attack-in-place order

&#x20; -> normal LMB movement can resume

```



Hard-target mouse presses are different. They remain stable until release.



\---



\# 11. Keyboard skill keys



Keyboard skill keys are direct skill inputs.



They do not create pointer action state or action orders by default.



```text

press keyboard skill key:

&#x20; emit skill\_pressed



hold keyboard skill key:

&#x20; emit skill\_held every tick



release keyboard skill key:

&#x20; emit skill\_released

```



Keyboard skills can still receive a hovered enemy as target context.



Example:



```text

mouse hovering enemy

press Homing Bolt key

&#x20; -> skill intent gets target\_entity = hovered enemy

```



But this is not a persistent hard target order.



The important distinction:



```text

RMB hard target:

&#x20; clicked enemy is locked for that held mouse action

&#x20; if it dies, action stops until release



keyboard held skill:

&#x20; key keeps producing skill intents while held

&#x20; no mouse-button hard target is consumed until release

```



So keyboard skill behavior is closer to:



```text

keep using this skill while key is held

```



not:



```text

keep this specific clicked target locked until release

```



This difference is intentional.



\---



\# 12. Homing target behavior



Homing projectiles can receive an explicit target from skill intent.



Example:



```text

RMB Homing Bolt on enemy:

&#x20; hard-target order emits skill intent with target\_entity



keyboard Homing Bolt while hovering enemy:

&#x20; keyboard skill intent gets target\_entity from hover



execute\_projectile:

&#x20; copies target\_entity into spawn\_params.explicit\_target



spawn\_projectile:

&#x20; stores explicit\_target on the projectile

```



Then homing behavior uses:



```text

explicit target range:

&#x20; may this cast lock onto the explicit target?



retarget radius:

&#x20; may this already-flying projectile acquire a nearby target?

```



Those are different knobs.



Desired behavior:



```text

hovered explicit target:

&#x20; projectile chases that target if it is within explicit target range

&#x20; closer monsters do not steal initial target



no explicit target:

&#x20; projectile flies forward initially

&#x20; it may retarget only if a monster enters the stricter projectile-centered retarget radius

```



\---



\# 13. Intent processing



After player input and action orders are resolved, the game runs normal systems.



Simplified flow:



```text

build\_player\_intents

&#x20; -> UI-filtered input

&#x20; -> hovered selectable

&#x20; -> pointer action state

&#x20; -> immediate player intents



ai\_system

&#x20; -> adds AI intents



action\_order\_system

&#x20; -> adds intents from persistent orders



intent\_system

&#x20; -> stores movement/interact requests



interact\_system

&#x20; -> resolves interact requests



skill\_intent\_resolution\_system

&#x20; -> checks whether skill requests are legal



skill\_execution\_system

&#x20; -> starts casts/channels/instant skills

```



Movement, combat, projectiles, and effects happen later in the tick.



The key point:



```text

action orders do not replace intents

they generate intents

```



\---



\# 14. Current traditional-control behavior summary



\## LMB on ground



```text

move

```



\## Hold LMB on ground



```text

continue moving

```



\## LMB on enemy



```text

hard-target enemy using left-bound skill

```



\## LMB on interactable



```text

move\_then\_interact or interact immediately

```



\## Shift+LMB



```text

attack in place

soft-acquire target if valid

otherwise attack air

```



\## Shift pressed while LMB already held



```text

switch from movement to attack-in-place

```



\## Shift released while LMB still held



```text

switch back from attack-in-place to normal held LMB behavior

```



\## RMB with ranged skill on ground



```text

cast toward cursor

```



\## RMB with ranged skill on enemy



```text

hard-target enemy

keep casting at that enemy while held

stop when enemy dies

```



\## RMB with melee skill on ground



```text

move with soft melee acquisition

```



\## RMB with melee skill on enemy



```text

hard-target enemy

move into range if needed

attack when in range

stop when target dies

```



\## RMB on interactable



```text

move\_then\_interact or interact immediately

```



\## Keyboard skill key



```text

fire skill directly

can use hovered enemy as target context

does not create hard-target mouse order

continues while key is held according to skill trigger mode

```



\---



\# 15. Where behavior is configured



Skill-specific targeting behavior lives in skill data.



Example concepts:



```text

hard\_targets:

&#x20; which target kinds this skill can hard-target



soft\_targeting:

&#x20; whether the skill can acquire invisible assist targets



input\_contexts:

&#x20; button/modifier-specific behavior

```



Example input contexts:



```text

traditional\_left

traditional\_shift\_left

traditional\_right

modern\_left

modern\_right

```



This lets the same skill behave differently depending on how it is used.



Example:



```text

Debug Slash + traditional\_right:

&#x20; move\_with\_soft\_skill\_use



Debug Slash + traditional\_shift\_left:

&#x20; soft\_skill\_use\_or\_attack\_air

```



\---



\# 16. Design rules



Keep these distinctions intact.



```text

hovered target:

&#x20; visual/input hover



hard target:

&#x20; press-time locked target



soft target:

&#x20; assist-acquired target



intent:

&#x20; immediate request



action order:

&#x20; persistent multi-tick goal

```



Do not make hover UI depend on soft targets.



Do not make keyboard skill keys create mouse-button hard-target state by default.



Do not make action orders perform combat or interaction directly.



Do not put pathfinding policy inside skills.



Action orders should say:



```text

approach this entity until in range

```



The movement/path layer should decide how to path there.



\---



\# 17. Remaining open design areas



Modern/WASD mouse-button behavior is not fully finalized.



Open questions:



```text

Should modern LMB/RMB be pure skill buttons?

Should they support interactable hard targets?

Should they support enemy hard targets?

Should they ever move the player?

Should hover target context apply to mouse skill buttons without hard locks?

```



These should be decided after traditional controls feel stable.



