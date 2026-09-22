"""Shared reward values for Skill Lab.

Defines the canonical reward baseline table, category grouping, and the
``check_baseline_rewards`` validator that computes the *effective* per-reward
values used at runtime:

    effective[reward_name] = baseline * stage_multiplier * profile_multiplier * reward_scale

Stage multipliers come from the stage JSON (e.g. ``milestone_reward_multiplier``).
Profile multipliers come from the profile JSON / ``SPECIALIZATION_PRESETS``.
``reward_scale`` is a single shared scalar on the profile.
"""

from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------- #
# New reward system                                                            #
# --------------------------------------------------------------------------- #

REWARD_BASELINES: dict[str, float] = {
    "milestone":            1.0,
    "event":                4.0,
    "map_discovery":        5.0,
    "new_coord":            0.02,
    "badge":               25.0,
    "level":                1.0,
    "pokedex":              1.0,
    "heal":                 3.0,
    "capture":             1.0,
    "combat_wild":          0.2,
    "combat_trainer":       0.6,
    "item":                 0.5,
    "key_item":            20.0,
    "breadcrumb":           0.5,
    "breadcrumb_arrival":  10.0,
}

REWARD_CATEGORIES: dict[str, str] = {
    "milestone":          "milestone",
    "event":              "event",
    "map_discovery":      "exploration",
    "new_coord":          "exploration",
    "badge":              "milestone",
    "level":              "training",
    "pokedex":            "milestone",
    "heal":               "healing",
    "capture":            "combat",
    "combat_wild":        "combat",
    "combat_trainer":     "combat",
    "item":               "exploration",
    "key_item":           "milestone",
    "breadcrumb":         "breadcrumb",
    "breadcrumb_arrival": "breadcrumb",
}

CATEGORIES = ["milestone", "event", "exploration", "combat", "healing", "training", "breadcrumb"]

# Aliases that allow stage/profile JSONs to use legacy names.
# Value is a tuple of JSON key names, first match wins.
REWARD_MULTIPLIER_ALIASES: dict[str, tuple[str, ...]] = {
    "milestone":       ("milestone_reward_multiplier", "milestone_reward"),
    "event":           ("event_reward_multiplier", "event_reward"),
    "exploration":     ("exploration_reward_multiplier", "exploration_reward", "new_coord_reward_multiplier"),
    "combat":          ("combat_reward_multiplier", "combat_reward"),
    "capture":         ("capture_reward_multiplier", "capture_reward"),
    "healing":         ("healing_reward_multiplier", "healing_reward"),
    "training":        ("training_reward_multiplier", "level_reward_multiplier"),
    "breadcrumb":      ("breadcrumb_reward_multiplier", "breadcrumb_reward"),
}


def normalize_reward_multipliers(config: dict | None) -> dict[str, float | None]:
    """Normalize stage/profile config to canonical category multiplier names.

    Returns a dict mapping canonical category -> float or None (if not found).
    """
    config = config or {}
    normalized: dict[str, float | None] = {}
    for canonical_name, aliases in REWARD_MULTIPLIER_ALIASES.items():
        for key in aliases:
            if key in config and config[key] is not None:
                normalized[canonical_name] = float(config[key])
                break
        else:
            normalized[canonical_name] = None
    return normalized


def check_baseline_rewards(
    profile_config: dict | None,
    stage_config: dict | None,
    baseline_values: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Validate the profile/stage reward config and return *effective* reward values.

    The effective reward for each entry in ``REWARD_BASELINES`` is::

        effective[reward_name] = baseline * stage_multiplier * profile_multiplier * reward_scale

    Parameters
    ----------
    profile_config
        Profile dict. Must contain ``reward_scale``. May contain
        ``category_multipliers`` (dict of category -> float); defaults to 1.0.
    stage_config
        Stage dict. Should contain ``*_reward_multiplier`` keys for every
        required category. Missing keys raise ``ValueError``.
    baseline_values
        Override for ``REWARD_BASELINES`` (used in tests).

    Returns
    -------
    dict with keys:
        - ``reward_scale``: float
        - ``explore_weight``: float
        - ``stage_reward_multipliers``: dict[category -> float]
        - ``profile_category_multipliers``: dict[category -> float]
        - ``effective_rewards``: dict[reward_name -> float]
    """
    profile_config = profile_config or {}
    stage_config = stage_config or {}
    baseline_values = baseline_values or REWARD_BASELINES

    reward_scale = profile_config.get("reward_scale")
    if reward_scale is None:
        raise ValueError("Profile config is missing 'reward_scale'.")
    reward_scale = float(reward_scale)

    explore_weight = float(profile_config.get("explore_weight", 1.0))

    # Profile-level category multipliers (default 1.0 for every category).
    profile_multipliers: dict[str, float] = {}
    raw_profile_mults = profile_config.get("category_multipliers", {})
    if raw_profile_mults:
        profile_multipliers = {k: float(v) for k, v in raw_profile_mults.items()}
    for cat in CATEGORIES:
        profile_multipliers.setdefault(cat, 1.0)

    # Stage-level category multipliers.
    normalized_stage = normalize_reward_multipliers(stage_config)

    missing = [cat for cat, val in normalized_stage.items() if val is None]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(
            f"Stage config is missing reward multiplier(s): {joined}. "
            f"Expected aliases: {', '.join(sorted(REWARD_MULTIPLIER_ALIASES))}."
        )

    stage_multipliers: dict[str, float] = {
        cat: float(val) for cat, val in normalized_stage.items() if val is not None
    }
    for cat in CATEGORIES:
        stage_multipliers.setdefault(cat, 1.0)

    # Compute effective rewards for every baseline entry.
    effective: dict[str, float] = {}
    for reward_name, baseline in baseline_values.items():
        category = REWARD_CATEGORIES.get(reward_name, reward_name)
        stage_mult = stage_multipliers.get(category, 1.0)
        profile_mult = profile_multipliers.get(category, 1.0)
        effective[reward_name] = baseline * stage_mult * profile_mult * reward_scale

    return {
        "reward_scale": reward_scale,
        "explore_weight": explore_weight,
        "stage_reward_multipliers": stage_multipliers,
        "profile_category_multipliers": profile_multipliers,
        "effective_rewards": effective,
    }


# --------------------------------------------------------------------------- #
# Backward-compatible constants (used by legacy / teacher-bonus code)         #
# --------------------------------------------------------------------------- #

small_reward = 0.1
medium_reward = 2.0
big_reward = 10.0
huge_reward = 30.0
PERFECT_REWARD = 100.0
reward_penalty = -1.0
wrong_choice_penalty = -medium_reward


def calculate_starter_reward(
    attack_dv: int,
    defense_dv: int,
    speed_dv: int,
    special_dv: int,
) -> float:
    """Return a starter-pick reward based on all five effective DVs.

    Generation I derives the HP DV from the low bits of the other four DVs,
    so evaluating only the stored DVs can rank 14/14/14/14 above 13/13/13/13.
    """
    stored_dvs = (attack_dv, defense_dv, speed_dv, special_dv)
    if any(not 0 <= dv <= 15 for dv in stored_dvs):
        raise ValueError("DVs must be between 0 and 15")

    hp_dv = (
        ((attack_dv % 2) * 8)
        + ((defense_dv % 2) * 4)
        + ((speed_dv % 2) * 2)
        + (special_dv % 2)
    )
    effective_dvs = (*stored_dvs, hp_dv)

    modifier = 1.0 + (sum(effective_dvs) / (5 * 15))
    return big_reward * modifier
