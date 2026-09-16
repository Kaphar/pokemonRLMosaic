# https://glitchcity.wiki/wiki/Luck_manipulation_(Generation_I)

# 0xFFD3 (hRandomAdd)
# The main pseudo-random byte updated continuously every frame using the Game Boy's internal hardware divider register (DIV).
# This address handles the vast majority of in-game RNG checks 
# (such as wild encounter species and event outcomes).

# 0xFFD4 (hRandomSub): A secondary byte that works alongside

# 0xFFD3, though it is rarely called during standard gameplay sequences.

# 0xD148 – 0xD150
# A separate block of nine pseudo-random numbers allocated specifically
#  for processing random actions during Link Battles. [1] 
#  (https://datacrystal.tcrf.net/wiki/Pok%C3%A9mon_Red_and_Blue/RAM_map), [2] 
#  (https://tasvideos.org/Forum/Posts/354402), [3]
# (https://glitchcity.wiki/wiki/Luck_manipulation_(Generation_I))


# Random_::
# ; Generate a random 16-bit value.
# 	ld a, [rDIV]
# 	ld b, a
# 	ld a, [hRandomAdd]
# 	adc b              ; add [rDIV] and the carry flag (either 0 or 1) to hRandomAdd
# 	ld [hRandomAdd], a
# 	ld a, [rDIV]
# 	ld b, a
# 	ld a, [hRandomSub]
# 	sbc b              ; subtract [rDIV] and the carry flag (which will come from the above addition) from hRandomSub
# 	ld [hRandomSub], a
# 	ret