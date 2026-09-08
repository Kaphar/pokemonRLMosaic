Add a "Save Checkpoint" button in your mosaic UI that calls recorder.save() only when clicked.

check speed bonus: this obersavation might be wrong, look the code first.
I see an issue with the speed bonus, if it is slow or very slow, it is still a 1.0x modifier, i would make it like, would it be bad to make a bonus that doesn't multiply, more like a fixed bonus that decreases the more step has been done. i imagine it would help the model get the fact that it needs to be faster quicklier.


I will tell you more about the state of the training, but it would be nice to have a window that would have a scrollable list of all the reset and the scores. 




 
* calculate_starter_reward is it possible to have the model determine the ponderation of the different stats for the proper pokemon, and determine which is the most important stat ? (said to be special) so it could maybe ponder the rewards by himself ? (something i read gave me that idea, what do you think of it?)


* I think when the character is in motion, it's possible to 'buffer' an input movement, so it might be a bit confusing and we would have to debug with cv2 to make sure we can make the detection that the script uses can handle the new input rate / frame rate. it would be interesting to ask if we can have 2 input that last 8/10
apparently, the 17 first frame of the 24 will not buffer, if the button is pressed between frame 18 and last, it will buffer the move and be faster.