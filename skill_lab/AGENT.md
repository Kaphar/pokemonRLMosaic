--- skill_lab/AGENT.md (原始)


+++ skill_lab/AGENT.md (修改后)
# Skill Lab - Codebase Guide for AI Agents

## Overview

This project is a **reinforcement learning laboratory** built on top of the Pokemon Red V2 baseline. It allows researchers to train RL agents (PPO) to play Pokemon Red while providing extensive visualization, debugging, and experimentation tools.

**Main Entry Point**: `skill_lab/run_mosaic.py` - Run this script to start training with the mosaic UI.

## Directory Structure

```
/workspace/
├── skill_lab/              # Main laboratory code (THIS IS WHERE EVERYTHING HAPPENS)
│   ├── run_mosaic.py       # Main training script with mosaic UI
│   ├── emulator_with_debug.py  # Interactive emulator for human play/debugging
│   ├── env_wrapper.py      # Gymnasium wrapper with milestones, rewards, action masking
│   ├── rewards.py          # Shared reward values and calculations
│   ├── milestones.py       # Milestone tracking system
│   ├── inspector.py        # Observation inspector panel
│   ├── stats_window.py     # Environment statistics window
│   ├── map_window.py       # Global map visualization
│   ├── panel_data.py       # Debug panel data helpers
│   ├── mosaic.py           # Mosaic grid display
│   ├── launcher.py         # GUI launcher application
│   │
│   ├── profiles/           # Agent profile configurations
│   │   ├── trainer_profile.json    # Battle-focused profile
│   │   └── explorer_profile.json   # Exploration-focused profile
│   │
│   ├── stages/             # Stage/level configurations
│   │   ├── starter.json    # Starter selection stage
│   │   └── route1.json     # Route 1 exploration stage
│   │
│   ├── skills/             # Skill-based RL components (Phase 3)
│   │   ├── base.py         # Base skill class
│   │   ├── navigate.py     # Navigation skill
│   │   └── registry.py     # Skill registry
│   │
│   └── debug_scripts/      # Debug/testing utilities
│
├── v2/                     # Original V2 baseline (reference implementation)
│   ├── baseline_fast_v2.py
│   └── red_gym_env_v2.py
│
├── baselines/              # Original baseline code (legacy)
├── mosaic_sessions/        # Training outputs, checkpoints, logs
└── visualization/          # Map visualization tools
```

## Core Concepts

### 1. **Profiles** (`skill_lab/profiles/`)

Profiles define agent behavior through reward multipliers and directives:

- **reward_scale**: Multiplier for all rewards
- **explore_weight**: Weight for exploration rewards
- **catch_directive**: List of Pokemon to prioritize catching
- **train_directive**: List of Pokemon to prioritize training
- **save_on_catch**: Whether to save state after catching
- **reset_on_catch**: Whether to reset episode after catching

**Example**: `trainer_profile.json` has `reward_scale: 2.0` and focuses on battling, while `explorer_profile.json` has `explore_weight: 3.0` for mapping.

### 2. **Stages** (`skill_lab/stages/`)

Stages define specific training scenarios with:
- **max_steps**: Episode length limit
- **milestone_reward**: Reward per milestone achieved
- **exploration_reward**: Reward for exploring new tiles
- **combat_reward**: Reward for winning battles
- **capture_reward**: Reward for catching Pokemon
- **button_masks**: Which buttons to disable (action masking)
- **target_milestones**: Specific event bits to track
- **reset_on_catch**: Reset episode after catch

**Key Idea**: All stages have **baseline rewards**, but stages can apply **multipliers** to emphasize or ignore certain aspects. A stage can set a multiplier to 0 to ignore "noise" rewards.

### 3. **Reward System** (`skill_lab/rewards.py`)

Baseline reward values:
```python
small_reward = 0.1      # Minor progress
medium_reward = 2.0     # Standard achievements
big_reward = 20.0       # Significant milestones
huge_reward = 200.0     # Major accomplishments
PERFECT_REWARD = 10000.0  # Perfect IV starter
```

**Reward Flow**:
1. Base rewards defined in `rewards.py`
2. Profile applies `reward_scale` multiplier
3. Stage applies specific reward weights (exploration, combat, etc.)
4. Final reward = base × profile_scale × stage_weights

### 4. **Milestone System** (`skill_lab/milestones.py`)

Tracks game events via memory addresses (from `milestones.json`):
- Each milestone has an address and bit mask
- Milestones are checked every step
- Speed bonus: fewer steps = higher multiplier (max 3.0x)
- Already-set milestones on reset are ignored (no double rewards)

### 5. **Environment Wrapper** (`skill_lab/env_wrapper.py`)

The `SkillLabWrapper` adds:
- **Action Masking**: Disable Start/Select/B buttons based on stage config
- **Milestone Tracking**: Check and reward milestones with speed bonus
- **Early Termination**: End episode on wrong starter pick
- **Input Replay**: Deterministic replay from recorded inputs
- **Catch Detection**: Track new Pokemon catches
- **Objective Tracking**: Monitor training objectives

## Key Files Explained

### `run_mosaic.py` - Main Training Script

**What it does**:
1. Loads stage configuration from JSON
2. Sets up multiple parallel environments (default 42)
3. Creates mosaic grid display
4. Runs PPO training with live visualization
5. Shows batch reports with statistics

**Key Functions**:
- `make_config()`: Build environment config from profile + stage
- `setup_envs()`: Configure individual environment directives
- `main()`: Training loop with mosaic rendering

**CLI Arguments**:
```bash
--stage starter           # Stage to train on
--model path/to/model.zip # Load pretrained model
--specialization trainer  # Use preset profile (trainer/explorer/speedrunner)
--reward-scale 1.0        # Global reward multiplier
--explore-weight 1.0      # Exploration reward weight
--num-envs 42             # Number of parallel environments
--loop                    # Run indefinitely with batch reports
```

### `emulator_with_debug.py` - Interactive Emulator

**What it does**:
- Human-controlled emulator with full debugging
- Frame-exact input recording/replaying
- Plugin-based deterministic replay
- Used for testing and data collection

**Key Features**:
- Player-controlled inputs (arrow keys, A/S buttons)
- Input recording for later replay
- State saving/loading
- Debug overlays

### `env_wrapper.py` - Reward & Milestone Logic

**Step Function Flow**:
1. Apply action masking (block disabled buttons)
2. Execute step in underlying environment
3. Check milestones → add reward with speed bonus
4. Check starter status → apply DVs reward or penalty
5. Check for new catches → apply catch rewards
6. Return observation, reward, done, info

**Speed Bonus Calculation**:
```python
speed_multiplier = max(1.0, 3.0 - (steps_since_last / 100.0))
# Fewer steps = higher multiplier (max 3.0x)
```

### `inspector.py` - Observation Inspector

Displays for selected environment:
- Live game screen
- HP, level, map ID, badges, events
- Party Pokemon with stats
- Bag items
- Trainer info
- Memory watch panel
- Recent actions history
- Directive info (target starter, catch/train lists)

### `stats_window.py` - Environment Stats Table

Shows all environments in a table:
- Env number, HP%, Pokemon count
- Trainer wins, wild wins, wall collisions
- Steps, time elapsed, steps/minute
- Map ID, cumulative score

## Training Profiles

### Trainer Profile
- **Goal**: Battle trainers, level specific Pokemon
- **Behavior**: Grinding loop (defeat → progress → heal → repeat)
- **Rewards**: High combat rewards, moderate exploration

### Explorer Profile
- **Goal**: Map discovery, reach milestones
- **Behavior**: Push through screens, breadcrumb-driven
- **Rewards**: High exploration, milestone-focused

### Speedrunner Profile (preset)
- **Goal**: Fast completion
- **Behavior**: Optimize path, minimize steps
- **Rewards**: Speed bonuses, milestone efficiency

## How Rewards Work (Detailed)

### Baseline Rewards (in `rewards.py`)
Every stage inherits these base values:
- Killing wild Pokemon
- Defeating trainers
- Catching Pokemon
- Reaching milestones
- Exploring new tiles

### Profile Multipliers (in `profiles/*.json`)
Profiles scale rewards:
```json
{
  "reward_scale": 2.0,      // Double all rewards
  "explore_weight": 0.5,    // Reduce exploration focus
  "catch_directive": ["Pikachu"],  // Prioritize catching Pikachu
  "train_directive": ["Pikachu"]   // Prioritize training Pikachu
}
```

### Stage Multipliers (in `stages/*.json`)
Stages emphasize specific aspects:
```json
{
  "milestone_reward": 5.0,   // Reward per milestone
  "exploration_reward": 0.2, // Reward per new tile
  "combat_reward": 1.0,      // Reward per battle win
  "capture_reward": 3.0      // Reward per catch
}
```

### Final Reward Calculation
```
final_reward = (
    base_reward
    × profile.reward_scale
    × stage.combat_reward  # or exploration_reward, etc.
) + milestone_reward × speed_multiplier
```

**Important**: Stages can set multipliers to 0 to ignore certain rewards (avoid "noise" during specific training phases).

## Visualization Tools

### 1. Mosaic Display (`mosaic.py`)
- Grid of all running environments
- Click to select environment for inspector
- HUD overlay shows key stats
- Supervisor panel with control buttons

### 2. Observation Inspector (`inspector.py`)
- Detailed view of selected environment
- Game screen + all debug panels
- Memory watch with change highlighting
- Works in both `run_mosaic` and `emulator_with_debug`

### 3. Stats Window (`stats_window.py`)
- Table view of all environments
- Sortable columns (planned for web version)
- Real-time updates

### 4. Map Window (`map_window.py`)
- Global map visualization
- Shows environment positions
- Tracks explored tiles

### 5. Memory Watch Panel (`panel_data.py`)
- Raw memory address monitoring
- Highlights changed values
- Configurable address ranges

## Input Recording & Replay

### Frame-Exact Replay (`emulator_with_debug.py`)
- Records exact input events with frame timestamps
- Deterministic replay for debugging
- Plugin-based hook for accurate timing

### Legacy Replay (`recorder.py`)
- Step-level action recording
- Less precise but simpler
- Being phased out in favor of frame-exact

## Configuration Files

### `config.py`
Global settings:
- `EVENT_JSON_PATH`: Path to milestones.json
- `REWARD_MODIFIER_PRAISE/SLASH`: Teacher feedback values
- `SPECIALIZATION_PRESETS`: Profile presets
- `SAVE_ON_CATCH_ENABLED/MIN_DV`: Catch-save thresholds

### `controls.json`
Button mappings for emulator input.

### `milestones.json`
300+ game event milestones with:
- Memory address
- Bit mask
- Descriptive name

## Common Tasks

### Add New Profile
1. Create `skill_lab/profiles/my_profile.json`
2. Set reward_scale, explore_weight, directives
3. Reference in `run_mosaic.py` with `--specialization`

### Add New Stage
1. Create `skill_lab/stages/my_stage.json`
2. Define max_steps, rewards, button_masks, milestones
3. Run with `--stage my_stage`

### Adjust Rewards
1. Modify baseline values in `rewards.py`
2. Or adjust multipliers in profile/stage JSON
3. Check terminal logs for reward summary

### Debug Environment
1. Run `emulator_with_debug.py` for interactive control
2. Use inspector panel to view observations
3. Check memory watch for game state changes
4. Review milestone achievements in logs

## TODO Priorities (from `todo.md`)

### High Priority
1. **Reward Normalization**: Unify baseline rewards across stages with clear multiplier naming
2. **Healing Incentives**: Verify gym v2 rewards for meaningful healing (post-progress)
3. **Reward Verification**: Check function that ensures baseline rewards are consistent
4. **Terminal Logging**: Detailed reward settings summary per profile/stage

### Medium Priority
1. **Inspector Rework**: Add breadcrumb milestones list, progress feedback (green=done)
2. **Speed Bonus Adjustment**: Fix milestones that never trigger speed bonus
3. **Map Tooling**: Browser-based map visualization, click-to-mark "lava zones"
4. **Web Stats Dashboard**: Replace cv2 stats window with sortable web UI

### Low Priority
1. **Stats Watcher Expansion**: Show overall objectives/milestones beyond starter stage
2. **Catch Behavior**: Verify profile reward weights for catching mechanics
3. **Observation Enhancements**: Add RNG, combat info to observations
4. **Input Optimization**: Improve replay determinism without priming overhead

## Tips for AI Agents

1. **Always check `todo.md`** for current priorities before making changes
2. **Reward changes should be tested** in both `run_mosaic` and `emulator_with_debug`
3. **Profile/Stage JSON files** are the primary configuration mechanism
4. **Baseline rewards in `rewards.py`** should remain constant; use multipliers for variation
5. **Milestone tracking** automatically handles already-set events on reset
6. **Action masking** is critical for early-game training (block Start/Select)
7. **Frame-exact replay** is preferred over legacy recorder for determinism
8. **Web-based UI** is the goal for stats/map visualization (replace cv2 windows)

## Example Commands

```bash
# Run training with default settings
cd /workspace/skill_lab
python run_mosaic.py

# Train on Route 1 with trainer profile
python run_mosaic.py --stage route1 --specialization trainer

# Load pretrained model for inference
python run_mosaic.py --model mosaic_sessions/checkpoints/mosaic_100000_steps.zip

# Interactive debugging
python emulator_with_debug.py --rom ../PokemonRed.gb --init-state init.state

# Launch with custom reward scaling
python run_mosaic.py --reward-scale 2.0 --explore-weight 0.5
```

