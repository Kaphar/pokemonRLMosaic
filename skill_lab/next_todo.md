# THE FUCKING REWARDS :
why my rewards for events("milstones") is so low. 
we want a detailed log with the baseline weigths, (get rid of medium_rewards etc.)
in the logs for rewards we want : <the name/id of the environement> written in blue or red in function of the environement ROM.

profile
- speedrunner :
    + events
    + rewards hack for motion help
- trainer : 
    + combat : 2.0
    + healing
diminishing return on too much of the same rewards farming

Function that gives a one time reward everytime it gets close to a destination point. for example
* try to see what if would give

# MAP TOOL :
* we want a simple function that tells what X and Y of our MAP and also the mapped value in game with the map ID and the x/y position. (I would rather we employ more readable code than fast and effiencient code here.)



# MILESTONE TRACKER
The next thing we need is a proper "chronological UI tracker".

right now we need to define better the model around the aspects :
now that I am starting to getting more familiar with the codebase I understand better what the code around the milstones.json file does. This is nice, we definitely want to keep those rewards, but they alone don't do what i was hoping to get a good tracker for visual feedback on progress.

So we are going to build one. We are going to keep a list of important checkpoints. 
Let's say the first checkpoint will be : pick up oak parcel.



something that bothers me in the code :
access to RAM data by Variable name instead of hardcoded address. definition of the address at one place.
see if it is more convenient to use read_party to extract information, well actualy it probably is.


later : redundant save_on_catch and save_on_catch_enabled flag. 