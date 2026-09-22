# NEXT TODO — Rewards Overhaul, Milestone Tracker, RAM Consolidation

## ANALYSIS: Why Rewards Are Too Low

### Root causes (all in the env_wrapper / RedGymEnv coupling):

1. **`milestone_reward` is never wired to stage multipliers.** In `run_mosaic.py:make_config()` (line ~108) the config reads `stage_config.get("milestone_reward", medium_reward)` — but the stage JSONs have `milestone_reward_multiplier`, NOT `milestone_reward`. So it always falls through to `medium_reward` = **2.0**, not the 5.0 you expected.

2. **Stage multipliers (`*_reward_multiplier`) are never applied to rewards.** `check_baseline_rewards()` in `rewards.py:49` only *validates and logs* them — the actual `MilestoneTracker` and `RedGymEnv.get_game_state_reward()` do not multiply by them.

3. **Profile-specific category multipliers don't exist yet.** `profiles/trainer.json` and `profiles/speedrunner.json` only carry `reward_scale` and `explore_weight`. The `SPECIALIZATION_PRESETS` in `config.py:76` only override those two. Speedrunner/trainer category bonuses (combat, healing, event, breadcrumb) are **not implemented**.

4. **Event rewards are double-counted (confusingly).** `RedGymEnv.get_game_state_reward()` computes `event = reward_scale * max_event_rew * 4` (a max-based delta), AND `env_wrapper.py:step()` adds `milestone_reward` (flat 2.0) on top via `MilestoneTracker`. Both fire on the same event-bit transition, but neither is scaled by the desired 5.0 or by profile/category multipliers.

5. **Healing on level-up is rewarded.** `RedGymEnv.update_heal_reward()` (line 686) fires whenever HP increases and party size is unchanged — this includes **level-up healing**, which should be suppressed or heavily discounted.

6. **No `event_reward` or `breadcrumb` or `map_discovery` as first-class rewards.** Only the old `milestone` / `exploration` / `combat` / `capture` / `healing` categories exist, and they are inconsistently named across files.

---

## QUESTIONS TO RESOLVE BEFORE CODING (raise these)

1. **Baseline value semantics:** The baseline values you listed (milestone=1.0, event=4.0, map_discovery=5.0, etc.) — are these the *per-event* reward paid once when the event fires (before stage/profile multipliers and `reward_scale`), or are they already final values?

2. **Effective reward formula:** Should the final per-event reward be `baseline * stage_multiplier * profile_multiplier * reward_scale`? Or should `reward_scale` only apply to the "raw" RedGymEnv rewards and the new category system be separate?

3. **RedGymEnv vs env_wrapper:** `RedGymEnv.get_game_state_reward()` already computes `event`, `heal`, `badge`, `trainer_wins`, `wild_wins`, `explore`, `level` rewards. Should we (a) consolidate ALL reward logic into `env_wrapper.py` and tell RedGymEnv to only return a base reward of 0, or (b) keep both and make RedGymEnv apply the multipliers it currently ignores?

4. **Milestone checkpoints vs event-flag scanner:** The current `milestones.json` is a flat dump of all 2558 event bits. You want a curated *checkpoint list* (Oak's Parcel → PokeDex → ...). Should we keep the broad event-flag scanner for reward purposes AND add a separate curated checkpoint list just for the UI tracker? Or replace the scanner entirely with a curated milestone list?

5. **`milestones.json` fate:** You said "we don't need that rewritten version of events.json." Should we delete `milestones.json` and have `MilestoneTracker` read `events.json` directly via `GameState.event_flag`?

---

## TASK 1 — Redesign the Reward System

**Goal:** Every reward has a clear baseline, a category, and receives `stage_multiplier × profile_multiplier × reward_scale`.

### 1a. Rewrite `rewards.py` — drop `small_reward`/`medium_reward`/`big_reward`/`huge_reward` aliases
- Delete `small_reward`, `medium_reward`, `big_reward`, `huge_reward`, `PERFECT_REWARD`, `reward_penalty`, `wrong_choice_penalty`.
- Define a single `REWARD_BASELINES` dict with your positive components:

```python
REWARD_BASELINES = {
    "milestone":       1.0,     # per achieved checkpoint (chronological)
    "event":           4.0,     # per newly set story event flag (max-based)
    "map_discovery":   5.0,     # first time a new map is entered
    "new_coord":       0.02,    # each newly seen (x, y, map) tile
    "badge":          25.0,     # per badge gained (max-based)
    "level":           1.0,     # scaled party-level growth (max-based)
    "pokedex":         1.0,     # per newly owned Pokedex entry (max-based)
    "heal":            3.0,     # healing (squared fraction, see healing fix)
    "capture":        10.0,     # per new Pokemon caught
    "combat_wild":     2.0,     # per wild Pokemon defeated
    "combat_trainer":  5.0,     # per trainer defeated
    "item":           0.5,      # per non-key item acquired (low weight)
    "key_item":       20.0,     # per key story item (Oak's Parcel, etc.)
    "breadcrumb":      0.5,     # per closer-to-target step (one-time per improvement)
    "breadcrumb_arrival": 10.0, # arriving at a breadcrumb destination
}
```

- Define `REWARD_CATEGORIES` mapping each reward to its category:

```python
REWARD_CATEGORIES = {
    "milestone": "milestone",
    "event": "event",
    "map_discovery": "exploration",
    "new_coord": "exploration",
    "badge": "milestone",
    "level": "training",
    "pokedex": "milestone",
    "heal": "healing",
    "capture": "combat",
    "combat_wild": "combat",
    "combat_trainer": "combat",
    "item": "exploration",
    "key_item": "milestone",
    "breadcrumb": "breadcrumb",
    "breadcrumb_arrival": "breadcrumb",
}
```

- Define a canonical list of category names:
  `CATEGORIES = ["milestone", "event", "exploration", "combat", "healing", "training", "breadcrumb"]`

### 1b. Rewrite `check_baseline_rewards()` — make it actually compute effective rewards
- Input: `baseline_values`, `stage_multipliers` (dict of category→float), `profile_multipliers` (dict of category→float), `reward_scale`.
- Output: full `effective` dict where `effective[reward_name] = baseline * stage_mult * profile_mult * reward_scale`.
- Keep the validation (raise if a baseline is missing from stage config) but make it return the full effective reward table, not just 5 keys.
- This function should be the **single source of truth** for what values the env_wrapper uses at runtime.

### 1c. Update `SPECIALIZATION_PRESETS` in `config.py` (or replace with profile JSONs)
- `speedrunner`: `reward_scale=3.0`, `explore_weight=0.1`, and category multipliers:
  - `event`: 3.0, `milestone`: 3.0, `breadcrumb`: 3.0, `healing`: 0.5
  - all others: 1.0
- `trainer`: `reward_scale=1.0`, `explore_weight=1.0`, and category multipliers:
  - `combat`: 2.0, `healing`: 1.0
  - all others: 1.0
- `default`: `reward_scale=1.0`, `explore_weight=1.0`, all multipliers 1.0
- Add an `explorer` profile (from `explorer_profile.json`): high exploration, low combat.

### 1d. Add `profile_multipliers` to the Profile class and config flow
- `Profile.__init__` in `run_mosaic.py:46` needs a new field for category multipliers.
- `make_config()` must pass `profile_multipliers` into the env config dict.
- `SkillLabWrapper.__init__` must read `config["profile_multipliers"]` and `config["effective_rewards"]` and use them.

### 1e. Make `MilestoneTracker` use the new reward system
- `MilestoneTracker.__init__` receives `effective_rewards: dict` instead of a single `reward_per_milestone`.
- `check_and_reward()` returns `effective_rewards["milestone"]` per checkpoint event.
- Remove the singleton pattern (it prevents per-env reward customization).

### 1f. Apply `reward_scale` and multipliers in `env_wrapper.py`
- The `reward_scale` and `healing_reward_multiplier` are already read from config but `reward_scale` is **not applied** to milestone rewards. Fix this.
- Ensure `healing_reward_multiplier` from config is the stage-level multiplier (already works via `healing_reward_multiplier` key in stage JSON).

---

## TASK 2 — Diminishing Returns & Level Caps

### 2a. Diminishing returns on repeated rewards
- Add a per-reward decay tracker in `SkillLabWrapper`: each time a reward type fires, reduce its value for subsequent fires (e.g., `reward *= 1 / sqrt(1 + count)` or a simple halving after N repeats).
- Applies to: `combat_wild`, `combat_trainer`, `heal`, `capture`, `new_coord`, `map_discovery`.

### 2b. Level reward cap gated by milestones
- If the "Got Pokedex" event (0xD74B-5) is not set, cap `level_reward` at the starter level (level 5 + 4 = 9). No level gains beyond the cap are rewarded until the Pokedex is obtained.
- Implement this check in `SkillLabWrapper.step()` or in the RedGymEnv reward function using `GameState.event_flag(0xD74B, 5)`.

### 2c. Suppress healing from level-up
- In `RedGymEnv.update_heal_reward()` (v2/red_gym_env_v2.py:686), the heal is awarded whenever HP increases and party size is unchanged. Level-up healing satisfies both conditions.
- **Fix:** track the previous level sum; if level sum increased in the same step, do NOT award the heal reward (or award it at 10% of normal).
- Alternatively, in `env_wrapper.py` which already tracks `prior_party_size`, also compare prior and current level sum before applying the healing multiplier.

---

## TASK 3 — Milestone / Checkpoint Tracker System

### 3a. Create `skill_lab/checkpoints.py`
- A new `CheckpointTracker` class (separate from the event-flag `MilestoneTracker`).
- Holds a curated list of **checkpoints** in chronological order. Each checkpoint has:
  - `name`: human-readable label (e.g., "Deliver Oak's Parcel")
  - `event_key`: the events.json key that triggers it (e.g., `"0xD74E-1"` for "Got Oaks Parcel")
  - `reward_baseline`: default 1.0 (or per-checkpoint override)
  - `description`: longer text for the UI
- On reset: read current memory via `GameState`, mark any already-set events as achieved.
- On step: check for newly set events, award `effective_rewards["milestone"]` (or the checkpoint-specific reward), record step count.
- Expose `get_progress()` returning: total, achieved names, achieved steps, current target index.

### 3b. Curate the first checkpoint list (starter stage)
- Checkpoint 1: "Enter Viridian City" → event `"0xD74E-1"` ("Got Oaks Parcel")
- Checkpoint 2: "Obtain Pokedex" → event `"0xD74B-5"` ("Got Pokedex")
- Checkpoint 3: "Deliver Parcel to Oak" → event `"0xD74E-0"` ("Oak Got Parcel")
- (Expand as stages progress — this is stage-specific, loaded from stage JSON.)

### 3c. Integrate `CheckpointTracker` into `SkillLabWrapper`
- Replace or supplement `MilestoneTracker` with `CheckpointTracker` in `env_wrapper.py:116`.
- On each step, call `checkpoint_tracker.check_and_reward(game_state)` and add the reward to `total_milestone_reward`.
- Pass checkpoint data through to the inspector via `info` dict.

### 3d. Decide: keep or delete `milestones.json`
- If we keep it: `MilestoneTracker` continues scanning all 2558 events for *event_reward* (category "event"), separate from the curated checkpoint list.
- If we delete it: `MilestoneTracker` reads `events.json` directly, uses `GameState.event_flag()` for cleaner code. The checkpoint list handles the curated UI.

---

## TASK 4 — Milestone/Checkpoint UI Tracker in Inspector

### 4a. Add checkpoint panel to `inspector.py`
- In `ObservationInspector.render()`, after the existing milestone tracker section (line 182-217), add a **Checkpoint Tracker** section.
- Vertical list: name, status circle (green ✓ done / yellow ▶ current target / gray ○ pending), steps when achieved.
- Show the **next 3–4** checkpoints (current target + neighbors), like the existing milestone UI but using human-readable names from `CheckpointTracker`.

### 4b. Color env name by ROM
- In `inspector.py:141-149`, the env name is already shown. Add the env name in **blue** if ROM is PokemonBlue.gb, **red** if PokemonRed.gb. Currently only the ROM label is colored; make the env name itself colored too.
- Do the same in `stats_window.py` row rendering and in terminal reward logs (env_wrapper.py).

### 4c. Add checkpoint data to `web_dashboard.py`
- In `get_inspector_data()` (line 506+), add a `"checkpoints"` key with the same progress data, so the browser inspector tab can show it.

---

## TASK 5 — Reward Logging: Env Name with ROM Color

### 5a. Colorize terminal logs
- In `env_wrapper.py` everywhere `print(f"[{self.env_name}] ...")`, prepend an ANSI color code:
  - **Red** text if `self.rom_path` contains "Blue" → use `\033[31m` (Red ROM gets blue text? No — user said "blue or red in function of the environement ROM")
  - **Blue** text if ROM is PokemonBlue.gb → `\033[34m`
  - **Red** text if ROM is PokemonRed.gb → `\033[31m`
- Create a helper method `_colored_env_label()` that returns the env name wrapped in the right ANSI code + reset.

### 5b. Improve `log_reward_configuration_summary` in `run_mosaic.py`
- Currently calls `check_baseline_rewards()` which only returns 5 effective rewards.
- Update it to use the new system: list ALL baseline values, ALL stage multipliers, ALL profile multipliers, and ALL effective rewards in a clear table.
- Show the `reward_scale`, per-category stage multipliers, per-category profile multipliers, and final effective per-reward value.

---

## TASK 6 — RAM Access Consolidation (ram_map.py)

### 6a. Merge `ram_map.py` (GameState) with `party_reader.py` (Gen1PartyReader)
- `ram_map.py` already defines ALL RAM addresses in one place (D35E, D361, D362, D163, etc.).
- `party_reader.py` has hardcoded addresses (PARTY_ADDRESS=0xD16B, PARTY_SIZE_ADDRESS=0xD163, etc.) that **duplicate** ram_map.py but use a different party base (0xD16B vs ram_map's 0xD163 for count and 0xD164 for species).
  - Note: the v2 env uses party start at 0xD16B (the first Pokemon struct), while ram_map.py uses 0xD163 (party count) and 0xD164 (species list). These are compatible — 0xD163 is count, 0xD164 is the species array, 0xD16B is the first struct start.
- **Merge approach:** Make `GameState` (ram_map.py) the single source of truth. Add a `party_reader` that uses `GameState` internally but exposes the same rich dict output as `Gen1PartyReader.read_party()` (including DVs, IVs, moves, EXP, stats).
- Add the DV-reading fields that `Gen1PartyReader` has (ivAttack, ivDefense, etc.) to `PartyMon` in ram_map.py.

### 6b. Adapt `read_party` for opponent
- `GameState` currently only reads the player's party (addresses 0xD163–0xD268).
- For opponents in battle, the RAM layout is different (battle struct starts at 0xD16B for player, enemy is at different addresses like 0xCFE5–0xCFF4 for the current enemy mon).
- Add `GameState.enemy_party()` or `GameState.battle_mon()` that reads from `ADDR_ENEMY_SPECIES`, `ADDR_ENEMY_LEVEL`, `ADDR_ENEMY_HP`, `ADDR_ENEMY_MAXHP`.
- Research opponent party RAM in Pokemon Red (the enemy party in battle is stored at 0xD93B or similar — need to verify).

### 6c. Migrate all hardcoded addresses in the codebase
- Search all `.py` files for hex address literals (`0xD356`, `0xD163`, `0xD747`, etc.) and replace with `GameState` method calls or `ram_map` constants.
- Key files affected: `env_wrapper.py`, `v2/red_gym_env_v2.py`, `web_dashboard.py` (INSPECTOR_WATCH_ADDRESSES), `stats_window.py`, `inspector.py`.

---

## TASK 7 — Breadcrumb System

### 7a. Create `skill_lab/breadcrumb.py`
- A `BreadcrumbTracker` class that:
  - Holds a list of **destination waypoints** (x, y, map_id) for the current stage/profile.
  - Tracks the **best (closest) distance** seen so far to the nearest destination.
  - On each step: compute Manhattan (or Euclidean in global map space) distance to the destination.
  - If distance decreased vs. previous best → award `effective_rewards["breadcrumb"]` **once** (one-time per improvement, not per step).
  - If distance increases → no penalty, no reward. Just wait.
  - When within a threshold (e.g., 3 tiles) of the destination → award `effective_rewards["breadcrumb_arrival"]` and pop to the next waypoint.
  - If player moves away to a *different* destination region, switch target.

### 7b. Define breadcrumb waypoints per stage
- In stage JSON, add a `"breadcrumbs"` array:
  ```json
  "breadcrumbs": [
    {"target_x": 20, "target_y": 50, "target_map": 4, "label": "Viridian City gate"},
    {"target_x": 10, "target_y": 8, "target_map": 0, "label": "Oak's Lab"},
    ...
  ]
  ```
- Project to global map coordinates using `v2.map_projection.project_position`.

### 7c. Integrate into `SkillLabWrapper`
- Create `BreadcrumbTracker` on init if breadcrumbs exist in stage config.
- On each step, call `tracker.update(x, y, map_id)` and add reward to total.
- Print breadcrumb rewards with colored env name.

---

## TASK 8 — Exploration / Map Discovery Reward

### 8a. Award reward on first entry to a new map
- In `SkillLabWrapper.step()`, track `_last_summary_map_id` (already exists at line 76).
- If `current_map_id != prior_map_id`, check `GameState` and if this map hasn't been visited this episode → award `effective_rewards["map_discovery"]`.
- Track visited maps in a set on the wrapper (reset on episode).

### 8b. Apply diminishing returns
- After the first few new maps, reduce the reward (e.g., `map_discovery * 1/sqrt(1 + visited_count)`).

### 8c. Integrate with `new_coord` reward
- The existing `new_coord_reward` (0.02) is per newly seen tile. Currently handled as `seen_coords` delta in RedGymEnv. Make sure it uses the new baseline and multipliers.

---

## TASK 9 — Healing Reward Fix (no credit for level-up healing)

### 9a. Track level sum before/after step
- In `env_wrapper.py:step()`, read `prior_levels_sum` and `current_levels_sum` (via `current_level_sum` property).
- Pass this to the healing reward logic.

### 9b. Gate the heal reward
- In the healing reward block (env_wrapper.py:671), add condition:
  ```python
  level_up = current_levels_sum > prior_levels_sum
  if level_up:
      healing_reward *= 0.1  # 90% discount — healing from level-up barely rewards
  ```
- OR: skip the heal reward entirely if `level_up` and `progress_signal` is only from level-up.
- Document this decision clearly in the code.

---

## TASK 10 — Profile Multipliers Wire-Up

### 10a. Update `Profile` class (run_mosaic.py:46)
```python
class Profile:
    def __init__(self, name, count, model_path, explore_weight, reward_scale, category_multipliers):
        self.name = name
        self.count = count
        self.model_path = model_path
        self.explore_weight = explore_weight
        self.reward_scale = reward_scale
        self.category_multipliers = category_multipliers  # dict: category → float
```

### 10b. Update `make_config()` (run_mosaic.py:54)
- Load profile category multipliers from `SPECIALIZATION_PRESETS` (or profile JSON).
- Compute `effective_rewards` via `check_baseline_rewards()`.
- Pass both into the env config dict.

### 10c. Update `SkillLabWrapper.__init__` (env_wrapper.py:35)
- Read `config["effective_rewards"]` and `config["profile_category_multipliers"]`.
- Store as `self.effective_rewards` and `self.profile_multipliers`.
- Use `self.effective_rewards["milestone"]` instead of `self.milestone_reward`.

### 10d. Update `emulator.py:make_env()` (emulator.py:36)
- Pass `effective_rewards` and `profile_multipliers` from the top-level config into the wrapper config.

---

## TASK 11 — Update Stage JSONs with Full Multiplier Set

### 11a. `stages/starter.json`
- Add all category keys with explicit values:
```json
"milestone_reward_multiplier": 1.0,
"event_reward_multiplier": 1.0,
"exploration_reward_multiplier": 1.0,
"combat_reward_multiplier": 0.0,
"healing_reward_multiplier": 0.0,
"training_reward_multiplier": 1.0,
"breadcrumb_reward_multiplier": 0.0,
"capture_reward_multiplier": 1.0
```
- Add a `"checkpoints"` array with the starter-stage checkpoint list.
- Add a `"breadcrumbs"` array (or empty if none for this stage).

### 11b. `stages/route1.json`
- Similar full multiplier set, tuned for early game: combat > 0, exploration > 0, healing > 0.
- Add checkpoints: "Get Pokeballs", "Catch first Pokemon", "Beat first trainer".
- Add breadcrumbs for Route 1 navigation.

### 11c. Create `stages/progress.json` and `stages/combat.json` as JSON-driven equivalents of the old Python `STAGES` dict.

---

## TASK 12 — Stats Window Improvements

### 12a. Add "current core" score column
- In `stats_window.py`, add a column to the left of "Score" showing the env's reward since last reset (the "core" score).
- This is the cumulative reward in the current episode, accessible via `env.get_attr("total_reward")` or similar.

### 12b. Add checkpoint progress column
- Show current checkpoint index / total, or "✓ 2/4" for milestones achieved.

### 12c. Color env rows by ROM
- Red row text for PokemonRed envs, blue for PokemonBlue, matching the inspector convention.

---

## TASK 13 — Cleanup Items (later)

### 13a. Remove redundant `save_on_catch` / `save_on_catch_enabled`
- Unify to a single `save_on_catch` boolean (controlled by `save_on_catch_enabled` in settings.json).

### 13b. Consolidate `REWARD_MULTIPLIER_ALIASES` and `alias_map`
- Both `rewards.py:23` and `env_setup.py:107` define similar alias maps. Merge into one in `rewards.py`.

### 13c. Remove unused imports of `medium_reward` etc.
- After deleting the aliases, update all imports in `config.py`, `curriculum.py`, `env_wrapper.py`, `emulator.py`.
