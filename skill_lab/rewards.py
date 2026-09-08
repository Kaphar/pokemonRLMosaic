"""Shared reward values for Skill Lab."""

small_reward = 0.1
medium_reward = 2.0
big_reward = 20.0
huge_reward = 200.0
PERFECT_REWARD = 10000.0


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