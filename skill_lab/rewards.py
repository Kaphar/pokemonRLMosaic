"""Shared reward values for Skill Lab."""

small_reward = 0.1
medium_reward = 2.0
big_reward = 10.0
huge_reward = 100.0
PERFECT_REWARD = 10000.0

# Canonical baseline values used across profiles and stage definitions.
# As multipliers, stage values can be tuned per phase; they are still expected
# to exist in the final stage config and be applied to a profile-level scale.
BASELINE_REWARD_VALUES = {
    "milestone": big_reward,
    "exploration": small_reward,
    "combat": medium_reward,
    "capture": medium_reward, # if doesn't have it yet...
    "healing": big_reward,
    "wild_pokemon": medium_reward,
    "trainer": big_reward,
}

REWARD_MULTIPLIER_ALIASES = {
    "milestone": ("milestone_reward_multiplier", "milestone_reward"),
    "exploration": ("exploration_reward_multiplier", "exploration_reward"),
    "combat": ("combat_reward_multiplier", "combat_reward"),
    "capture": ("capture_reward_multiplier", "capture_reward"),
    "healing": ("healing_reward_multiplier", "healing_reward"),
}


def normalize_reward_multipliers(config: dict | None) -> dict[str, float | None]:
    """Normalize stage/profile config to canonical multiplier names."""
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
) -> dict[str, float | dict[str, float]]:
    """Validate the profile/stage reward config and return effective values.

    The canonical reward multipliers are defined in the stage JSON, while the
    profile supplies the shared reward_scale. This ensures every final config has
    a consistent set of reward knobs and the terminal log reflects the actual
    values loaded from JSON.
    """
    profile_config = profile_config or {}
    stage_config = stage_config or {}
    baseline_values = baseline_values or BASELINE_REWARD_VALUES

    reward_scale = profile_config.get("reward_scale")
    if reward_scale is None:
        raise ValueError("Profile config is missing 'reward_scale'.")

    normalized_stage = normalize_reward_multipliers(stage_config)
    missing = [
        canonical_name
        for canonical_name, value in normalized_stage.items()
        if value is None
    ]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(
            "Stage config is missing reward multiplier(s): "
            f"{joined}. Expected aliases: {', '.join(sorted(REWARD_MULTIPLIER_ALIASES))}."
        )

    for canonical_name, expected_value in baseline_values.items():
        if canonical_name in normalized_stage and normalized_stage[canonical_name] is not None:
            # Keep the stage values flexible per phase while still ensuring every
            # required multiplier is present and numeric.
            normalized_stage[canonical_name] = float(normalized_stage[canonical_name])

    effective = {
        "milestone": float(reward_scale) * float(normalized_stage["milestone"]),
        "exploration": float(reward_scale) * float(normalized_stage["exploration"]),
        "combat": float(reward_scale) * float(normalized_stage["combat"]),
        "capture": float(reward_scale) * float(normalized_stage["capture"]),
        "healing": float(reward_scale) * float(normalized_stage["healing"]),
    }

    return {
        "reward_scale": float(reward_scale),
        "stage_reward_multipliers": {k: float(v) for k, v in normalized_stage.items() if v is not None},
        "effective_rewards": effective,
    }


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
	if all(dv == 15 for dv in effective_dvs):
		return PERFECT_REWARD

	modifier = 1.0 + (sum(effective_dvs) / (5 * 15))
	return big_reward * modifier

reward_penalty = -1.0
wrong_choice_penalty = -medium_reward