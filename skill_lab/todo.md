Add a "Save Checkpoint" button in your mosaic UI that calls recorder.save() only when clicked.

check speed bonus: this obersavation might be wrong, look the code first.
I see an issue with the speed bonus, if it is slow or very slow, it is still a 1.0x modifier, i would make it like, would it be bad to make a bonus that doesn't multiply, more like a fixed bonus that decreases the more step has been done. i imagine it would help the model get the fact that it needs to be faster quicklier.


I will tell you more about the state of the training, but it would be nice to have a window that would have a scrollable list of all the reset and the scores. 



# for next model reset :
change the milestone reward to big_reward for starter stage.
ACTION MASKING FOR B Button.





# rather cool and more ambitious, we will need to make sure the observation changes (we will need to check the opencv part of the detection too)
* I think when the character is in motion, it's possible to 'buffer' an input movement, so it might be a bit confusing and we would have to debug with cv2 to make sure we can make the detection that the script uses can handle the new input rate / frame rate. it would be interesting to ask if we can have 2 input that last 8/10
apparently, the 17 first frame of the 24 will not buffer, if the button is pressed between frame 18 and last, it will buffer the move and be faster.



# handle Save game load game after game reset.
*we need to make a copy of the rom for each env, as they will save their data inside/next to it, and the emulator will need to have separate rom location for sure.
*train the model to
# and would go with it
make the model aware of the RNG address and the DV to train to handle the manipulation of RNG that speedrunners do, save the game before we load a new zone, set the RNG with the trick it needs to learn, reset the game, load the game and go pick the manipulated pokemon.




### low priority, later or never

* calculate_starter_reward is it possible to have the model determine the ponderation of the different stats for the proper pokemon, and determine which is the most important stat ? (said to be special) so it could maybe ponder the rewards by himself ? (something i read gave me that idea, what do you think of it?)