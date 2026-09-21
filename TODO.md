# TODO

## Done
- [x] **Item Receipt Detection** (`env_wrapper.py`): Bag snapshot tracking at 0xD31D/0xD31E
  - Compares bag slots before/after each step to detect newly received items
  - Logs new items in yellow: `[EnvName] ITEM received: id=0xXX (Name)`
  - Resets signature on env reset
- [x] **Enemy Health Reward** (`v2/red_gym_env_v2.py`): Track enemy HP at 0xCFE6 (current) / 0xCFF4 (max)
  - Accumulates damage dealt in `_enemy_damage_dealt`
  - Adds `enemy_damage` entry to `get_game_state_reward()` scores
  - Exposed in agent stats and dashboard
- [x] **Web Dashboard Fixes** (`web_dashboard.py`):
  - Fixed missing `base64` and `Callable` imports
  - Fixed missing `__init__` tracking dict initializations
  - Fixed `_read_bag()` to pass `PyBoyMemoryReader` to `Gen1PlayerReader`
  - Fixed mosaic tab CSS for fit-to-screen (`object-fit: contain`)
- [x] **Death/KO Column**: Added deaths count column to stats table
- [x] **Item Won Count Column**: Added items won column to stats table
- [x] **Config Tab**: Added max steps slider + save-on-catch checkbox with `/api/config` POST endpoint
- [x] **Observation Inspector Tab**: Added memory watch addresses (badges, map, positions, party, bag,
  battle state, enemy HP) with live polling on `/api/inspector`
- [x] **INSPECTOR_WATCH_ADDRESSES**: Constant defined with descriptions mapping
- [x] **TODO.md**: This file

## In Progress
- (None)

## Backlog
- Add ruff lint CI configuration
- Add unit tests for item detection logic in `env_wrapper.py`
- Add unit tests for enemy HP tracking in `red_gym_env_v2.py`
- Add unit tests for web dashboard API endpoints
- Consider making enemy damage reward configurable via stage config
- Consider adding enemy health percentage bar to dashboard stats
