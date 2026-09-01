_____ TODO FOR LATER ____
a menu with buttons for each emulator (control emulator button. slash control (bad emulator doing bad things !) "praise button" or highlight. a button to indicate something we liked to see (does it make sense to have 3 different levels or proudness/relevancy/oddity perceive? ))
 to have a button that will save the state of one emulator, and use it as a new starting point for one or many emulators.




_____ FIRST TODO ____
The original V2 is already a good RL baseline: it uses PPO, parallel environments, and a coordinate-based exploration reward, and is substantially faster/lighter than the original approach.

We're going to turn it into a laboratory for experimenting with learning, rather than immediately trying to make a better Pokémon-playing agent.

The important idea is:

We want to observe and understand what the agent learns, then build mechanisms that let it reuse that knowledge.

The three levels we discussed

Normal RL:

game state
    ↓
PPO
    ↓
action
    ↓
game
    ↓
reward
    ↓
PPO update

Hierarchical RL:

             HIGH LEVEL
          "train Pikachu"
                ↓
          "find grass"
                ↓
          "navigate there"
                ↓
             LOW LEVEL
          ↑ ↓ ← → A B

And eventually:

HIGH LEVEL
    ↓
"Use NavigateTo skill"
    ↓
SKILL / OPTION
    ↓
LOW LEVEL POLICY
    ↓
buttons

The exciting part is that skills can potentially become reusable knowledge.

Our phases
Phase 1 — Understand V2

We don't change the learning architecture yet.

We make it visible:

Observation
    ↓
Policy
    ↓
Action
    ↓
PyBoy
    ↓
Reward
    ↓
PPO
    ↓
weight update

And we want to inspect things such as:

what exactly enters the neural network
what action it chooses
what reward it receives
how often PPO updates weights
what state each emulator is in
how much progress each environment makes

The repository already renders individual game states to the session directory and supports TensorBoard, so we're building a more useful local laboratory around that existing infrastructure.

Phase 2 — The emulator laboratory

Our 12–15 emulator mosaic:

┌────┬────┬────┬────┐
│ 01 │ 02 │ 03 │ 04 │
├────┼────┼────┼────┤
│ 05 │ 06 │ 07 │ 08 │
├────┼────┼────┼────┤
│ 09 │ 10 │ 11 │ 12 │
├────┼────┼────┼────┤
│ 13 │ 14 │ 15 │    │
└────┴────┴────┴────┘

Click one → interactive emulator.

Initially these are not 15 independent brains.

They're 15 environments contributing experience to a shared learner:

Env 1 ─┐
Env 2 ─┤
Env 3 ─┤
...    ├──→ shared PPO
Env 15 ┘

Later we can deliberately specialize environments:

Explorer     Trainer     Speedrunner
   │             │            │
 Env 1-5       Env 6-10     Env 11-15

while still sharing useful knowledge.

Phase 3 — Objectives and skills

Then we introduce things like:

"Explore"
"Reach Pewter"
"Level Pikachu"
"Train Squirtle"

An objective can become subgoals:

Level Pikachu
    ↓
Find Pikachu
    ↓
Find training area
    ↓
Navigate there
    ↓
Battle
    ↓
Repeat

And eventually:

              OBJECTIVE
                  ↓
             SUBGOAL
                  ↓
                SKILL
                  ↓
             LOW-LEVEL
                  ↓
               ACTION

That's where our skill laboratory really starts becoming interesting.

So let's start building it

I agree with your idea of keeping the added code clean and separate from V2.

I don't want us hacking baseline_fast_v2.py into a giant Frankenstein script.

I'd start with a new top-level directory:

PokemonRedExperiments/
│
├── v2/                         # untouched baseline
│
├── skill_lab/
│   ├── __init__.py
│   │
│   ├── run_mosaic.py           # Phase 1 entry point
│   │
│   ├── config.py               # lab configuration
│   ├── emulator.py             # one PyBoy environment
│   ├── environment.py          # V2 adapter
│   ├── mosaic.py               # visual grid
│   ├── monitor.py              # state/reward monitoring
│   │
│   ├── agents/
│   │   └── ...
│   │
│   ├── skills/
│   │   └── ...
│   │
│   └── objectives/
│       └── ...
│
└── PokemonRed.gb

But for Phase 1 we should only implement the minimum:

skill_lab/
├── __init__.py
├── config.py
├── emulator.py
├── mosaic.py
└── run_mosaic.py

No hierarchical RL yet. No new rewards. No skills. No objectives.

The first milestone should simply be:

Run 12–15 V2-compatible PyBoy environments, display them in a mosaic, click one, and interact with it.

Once that works, we add the V2 model and instrument the observation/action/reward loop.

One architectural choice I'd make now

Let's not copy V2's environment code unless necessary.

The V2 code remains the source of truth:

                 V2
                  │
             existing env
                  │
                  ↓
          ┌───────────────┐
          │  Skill Lab    │
          │    adapter    │
          └───────────────┘
                  │
        ┌─────────┴─────────┐
        ↓                   ↓
   training             visualization