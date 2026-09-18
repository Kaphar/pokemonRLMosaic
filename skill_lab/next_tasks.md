# Skill Lab TODO - Organized Priorities

## 🎯 HIGH PRIORITY - Reward System Normalization

### 1. Unified Baseline Rewards
**Goal**: Every stage should have the same baseline rewards, with stages applying multipliers to emphasize or ignore aspects.

- [ ] **Define baseline reward values** in `rewards.py` for:
  - Killing wild Pokemon
  - Defeating trainers
  - Catching Pokemon
  - Healing Pokemon (meaningful healing after progress)
  - Reaching milestones
  - Exploring new tiles

- [ ] **Rename variables clearly** to show they are multipliers:
  - `exploration_reward_multiplier` instead of `exploration_reward`
  - `combat_reward_multiplier` instead of `combat_reward`
  - `milestone_reward_multiplier` instead of `milestone_reward`
  - `healing_reward_multiplier` (NEW - needs implementation)

- [ ] **Allow stages to set multipliers to 0** to ignore "noise" during specific training phases

### 2. Healing Incentives Verification
**Goal**: Ensure the model learns meaningful healing behavior (healing after making progress, not randomly).

- [ ] Check how rewards are handled in `env_wrapper.py` step function
- [ ] Verify gym v2 rewards for healing Pokemon
- [ ] Implement logic to reward healing ONLY after:
  - Map progress (new tiles explored)
  - Battle progress (defeated Pokemon/trainer)
  - Catch progress (caught Pokemon)
- [ ] Test grinding loop behavior for trainer profile: defeat → progress → heal → repeat

### 3. Reward Configuration Check Function
**Goal**: Ensure all baseline rewards are consistent across profiles and stages.

- [ ] Create `check_baseline_rewards()` function that:
  - Verifies all baseline reward values exist
  - Confirms they have the same base values
  - Checks they are included in every "final config"

- [ ] Add detailed terminal logging that shows:
  ```
  === REWARD CONFIGURATION SUMMARY ===
  Profile: trainer
    - reward_scale: 2.0
    - explore_weight: 0.5

  Stage: route1
    - milestone_reward_multiplier: 5.0
    - exploration_reward_multiplier: 0.2
    - combat_reward_multiplier: 1.0
    - capture_reward_multiplier: 3.0
    - healing_reward_multiplier: 0.0 (TBD)

  Final Effective Rewards:
    - Milestone: 10.0 (5.0 × 2.0)
    - Exploration: 0.2 (0.2 × 1.0)
    - Combat: 2.0 (1.0 × 2.0)
    - Capture: 6.0 (3.0 × 2.0)
  ====================================
  ```

---

## 🔧 MEDIUM PRIORITY - UI/UX Improvements

### 4. Observation Inspector Rework
**Goal**: Better milestone/breadcrumb tracking display.

- [ ] Add vertical list of neighboring milestones
- [ ] Show progress feedback with colors:
  - 🟢 Green = done (with step count for that checkpoint)
  - 🟡 Yellow = current target
  - ⚪ Gray = not yet reached
- [ ] Track number of steps taken for each milestone
- [ ] Make view work in both:
  - `run_mosaic` (AI-controlled)
  - `emulator_with_debug` (player-controlled)

### 5. Speed Bonus Adjustment
**Goal**: Fix milestones that never trigger speed bonus due to high step requirements.

- [ ] Adjust speed bonus calculation based on best-known step count
- [ ] Implement per-milestone step benchmarks
- [ ] Add multiplier especially for speedrunner profile
- [ ] Current formula: `speed_multiplier = max(1.0, 3.0 - (steps_since_last / 100.0))`
- [ ] New approach: compare against optimal steps for THAT specific milestone

### 6. Map Tooling & Visualization
**Goal**: Browser-based map visualization with interactive features.

- [ ] Research original project's map building code (from root/v2)
- [ ] Check if `run_mosaic.py` supports map streaming option
- [ ] Implement browser-based visualization (replace/augment cv2 window)
- [ ] Add tools for map position action mapping:
  - Click cell to toggle "lava zone"
  - Lava zones apply continuous reward penalty when agent stays in them
  - Easy UI to set positions visually

**Files to investigate**:
- `/workspace/v2/global_map.py`
- `/workspace/visualization/BetterMapVis_script_version*.py`
- Original side repo functionalities (merged into V2?)

### 7. Web-Based Stats Dashboard
**Goal**: Replace cv2 stats window with sortable web interface.

- [ ] Create Flask/FastAPI server to serve stats
- [ ] Move stats from `stats_window.py` to web endpoint
- [ ] Add columns:
  - "Current Score" (score since last reset) ← NEW COLUMN
  - Total Score (existing column)
  - All existing columns (HP, Pokemon, wins, steps, etc.)
- [ ] Implement frontend features:
  - Sort by any column (click header)
  - Filter by profile/stage
  - Real-time updates via WebSocket
  - Responsive design

**Benefits**:
- No need for cv2 image generation
- Better sorting/filtering capabilities
- Accessible from any browser
- Easier to extend with new metrics

---

## 📊 LOW PRIORITY - Enhanced Tracking

### 8. Stats Watcher Expansion
**Goal**: Show overall objectives/milestones beyond starter stage.

- [ ] Rework `stats_tracker.py` to show:
  - Overall actions (not just starter segment)
  - Objectives completed
  - Furthest milestone reached per emulator
  - Profile-specific statistics
- [ ] Track progress across multiple stages
- [ ] Compare performance between profiles

### 9. Catch Behavior Verification
**Goal**: Ensure proper reward weights for catching mechanics.

- [ ] Verify different profile behaviors when catching Pokemon
- [ ] Check reward weights incentivize correct behavior:
  - Trainer profile: catch only specified Pokemon
  - Explorer profile: catch for pokedex completion
  - Speedrunner profile: ignore catches unless critical
- [ ] Test save-on-catch logic with DV thresholds

---

## 🔮 FUTURE CONSIDERATIONS - Next Model Reset

### 10. Observation Enhancements
**Goal**: Richer observations for advanced training.

- [ ] Add RNG address to observation space
- [ ] Include combat information:
  - Opponent HP
  - Wild vs trainer battle flag
  - Enemy Pokemon species (read from enemy party address)
  - Enemy Pokemon level
- [ ] Test if model can learn RNG manipulation strategies

### 11. Input Buffer Mechanics
**Goal**: Understand and potentially exploit input buffering.

- [ ] Research: frames 1-17 don't buffer, frames 18-24 do buffer
- [ ] Debug with cv2 to verify detection handles new input rate
- [ ] Consider allowing 2 inputs lasting 8-10 frames each
- [ ] Test if faster input timing improves performance

### 12. RNG Manipulation Training
**Goal**: Teach model speedrunner RNG manipulation tricks.

- [ ] Make model aware of RNG address and DVs
- [ ] Train to manipulate RNG before encounters:
  - Save game before loading new zone
  - Set RNG with specific trick
  - Reset game, load, pick manipulated Pokemon
- [ ] Requires observation changes + reward shaping

---

## 🧹 CODE CLEANUP - Ongoing

### 13. Input Recorder/Replayer Cleanup
**Goal**: Maintain determinism while simplifying code.

- [ ] Decide: keep legacy recorder or fully migrate to frame-exact?
- [ ] Split recording/replaying logic to lighten files
- [ ] Optimize replay inputs:
  - Remove priming overhead
  - Fast input played at exact frame
  - Maintain determinism without downsides

### 14. Save Checkpoint Feature
**Goal**: Manual checkpoint saving in mosaic UI.

- [ ] Add "Save Checkpoint" button to mosaic UI
- [ ] Call `recorder.save()` only when clicked
- [ ] Implementation started but not finished

### 15. Human-to-Model Replay Conversion
**Goal**: Convert human play to replayable inputs for model.

- [ ] Check if current input recorder works for human replay
- [ ] Implement "player to replayable input for model" mode
- [ ] Ensure timing/frequency matches model expectations

---

## ❓ IDEAS TO EXPLORE

### 16. Dynamic Reward Ponderation
**Idea**: Let model determine stat importance weighting.

- [ ] Can model learn which DVs are most important?
- [ ] Dynamic reward ponderation based on learned preferences?
- [ ] Reference: "calculate_starter_reward" ponderation concept

---

## 📝 Notes

### Profile Types & Behaviors

| Profile | Goal | Behavior Pattern | Reward Focus |
|---------|------|------------------|--------------|
| **Trainer** | Battle trainers, level specific Pokemon | Grinding loop: defeat → progress → heal → repeat | High combat, moderate exploration |
| **Explorer** | Map discovery, reach milestones | Breadcrumb-driven, push through screens | High exploration, milestone-focused |
| **Speedrunner** | Fast completion | Optimize path, minimize steps | Speed bonuses, efficiency |

### Key Principles

1. **Baseline rewards stay constant** in `rewards.py`
2. **Profiles apply global multipliers** via `reward_scale`
3. **Stages apply specific multipliers** to emphasize training aspects
4. **Multipliers can be 0** to ignore noise during specific training
5. **All configs should include baseline rewards** for consistency

### Files to Review for Context

- `/workspace/skill_lab/todo.md` - Original TODO (this file replaces it)
- `/workspace/v2/laboratory-TODO.md` - V2 lab context
- `/workspace/skill_lab/AGENT.md` - Codebase guide for AI agents
- `/workspace/skill_lab/rewards.py` - Current reward definitions
- `/workspace/skill_lab/env_wrapper.py` - Reward application logic
- `/workspace/skill_lab/profiles/*.json` - Profile configurations
- `/workspace/skill_lab/stages/*.json` - Stage configurations
