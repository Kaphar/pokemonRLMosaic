* Fix the weights and their declaration.
we need a bigger baseline for progress, milestones should be 5 base points + bonus speed. I saw they were at 2 points.

THE MILESTONES SYSTEM WE HAVE is actually very very poor. it does detect the speak to Oak script, so it has functionalities we want to keep, but the "list" is not really a chronological order and many things are missing, I thought I would use this a sole "breadcrumb" but it is not going to cut it, we need a better breadcrumb system. We need to get to the shop, where we will receive the parcel,
we need a milstone system for Map, coordinate based, more or less like the milestones system, but with more "hoops"(breakcrumbs) but it must also handle some key fights (Like Peter, our first big objective)


Also our Config Tab has gone, we need to remake it.



# TODO Fix the weights and their declaration.
in effort for normalization we are going to continue unifying the rewards, so that every stage has the baselines rewards, the stage have multipliers, which need to appear more clearly in the variables' names so if a stage does need the baseline rewards (specific training, avoid 'noise' ) it could put a multiplier of 0 to ignore some aspects.

We need to see how is handled the rewards, in our function in the gym, because we are going to give a baseline rewards for killing a wild pokemon, trainers. and we need to tackle/verify what we do to incentivise meaningful healing (healing pokemons after making some progress, either on the map, either by catching/tr)
the flow is always : we have our settings file for our profiles (i as see it, the profile are also multiplier of rewards)
seeing how 'far' the training has come we need to verify the rewards from the gym v2 for healing the pokemons, a good point would be to have the model training a grinding loop (defeat pokemon, progress, heal repeat), especially for our "trainer" profile.


*  our progressers/speedrunner profile should be more breadcrumb milestone driven and more incline to push through the screens. check the breadcrumb I don't see any breadcrumb won after the first one.



We need a check function that verify that we have the baselines rewards, they should be the same values and included in every "final config" we need a good detailed log in the terminal that sums up nicely the rewards settings, from profiles, stages,


# rework the Ovsersvation Inspector data panel (and milestones) :
I think i will need tools to Add more breadcrumb, check the breacrumb, I will need a vertical list of the neighboring milestones and progress feedback (green : done : keeps track of the number of steps for each "checkpoint"). this view should work in run_mosaic, but in emulator_with_debug as well, even if the inputs are player controlled. 

* adjust the speed bonus based on the best number of step necessary, we can have a multiplier, especially for speedrunner, but as it is right now, some milestones can take more steps and never have the speed bonus triggered.

# TOOLING WITH THE MAP:
the original project built the map from the observed data I think, actually I think it even did more than that I think it could stream the position of each environement on the map. there was a side repo but i think the functionalities were merged and integrated in the V2. I currently do not know if the code of the run_mosaic script allows for such an option, like to visualize in the browser would be the best probably. also i could integrate some tooling to apply some specific map position action mapping. or an easi click on cell, to toggle a "lava zone" (continuous rewards penatly upon staying in the easily UI set position)
speaking of that can you look if the original scripts of the project (from the root)


# environement stats window : add a column to the left of the "score" column which would show "current core" the score the environement has since last reset.
but it would be better for those stats to be accessible on a browser, rather than have that window, have a webpage would be a win at many levels. we wouldn't need to use cv2 to generate an image with the stats, we could introduce some front end functions like sorting by score or by a clicked column



# the stats watcher could be reworked to show more information about objectives, milstones, further milestone reached by an emulator. we initially had that window to track the starter training stage, but we would want our statistic in that window to reflect overall actions, not only the starter, especially since we are now also working past that segment.


# HEALING REWARDS : MAKE SURE THEY DON'T GET THEM WHEN THEY ARE HEALED BECAUSE THEY DIED ? sorry caps lol they are rewarded for dying, not good.


================


and check how the "logic" of our milestone system to know that the rewards to get down to proffessor oak are "unlocked" or said differently i would like that we confirm the flow (and leave a note about it)

# when we have the abitility to catch pokemon :
verify the weigh and behaviour of different profile to see if we are giving proper rewards for best incentives.


* https://github.com/Baekalfen/PyBoy/pull/430/changes#diff-3c5a6b1ddcfa9e5017323513822689bb51b0b5e236a842eb462201675402e667
implemment the game link and allow our emulators to exchange between them, first a script that prove feasability between 2 emulators, then we will make a pool of available pokemon, maybe have some "Pokemon Library' profile that list the pokemon it can trade. some function that could trigger a script at first to exchange pokemon on demand. so if as a dev, in the mosaic, I click a pokemon that is tradeable, it will set up the transfert with another emulator owning the pokemon i want in its state, maybe handle automatic system with "givers" an "takers" to fulfil the pokedex, we are going to see also which pokemon require being exchanged to evolve and pokemon red / blue only.


* when we override the settings (checkbox) in the launcher.py I think it does not set up the stage steps. Fix that, if you can implement a Tab Config in our webserver, to start with it would need a slider, from 256 to 50k, this would update the setting used at environement reset to set the amount of steps for the next iteration, by default it should use the settings default for the given stage. this would allow me to adjust the training segment length more dynamically. we could also change the setting for save_on_catch there with a checkbox.

# for next (or next's next's next...) model reset :
# For later: rather cool and more ambitious, we will need to make sure the observation changes (we will need to check the opencv part of the detection too)

* add to observation RNG and maybe more combat information (hp of opponent, wild/trainer, try a readparty at the address the ennemy)

* I think when the character is in motion, it's possible to 'buffer' an input movement, so it might be a bit confusing and we would have to debug with cv2 to make sure we can make the detection that the script uses can handle the new input rate / frame rate. it would be interesting to ask if we can have 2 input that last 8/10
apparently, the 17 first frame of the 24 will not buffer, if the button is pressed between frame 18 and last, it will buffer the move and be faster.


* make the model aware of the RNG address and the DV to train to handle the manipulation of RNG that speedrunners do, save the game before we load a new zone, set the RNG with the trick it needs to learn, reset the game, load the game and go pick the manipulated pokemon.

* cleaning code:
- not delete the legacy input recorder/replayer, or fix it, or do something better that keeps the determinism? split recording/replaying logic to lighten the files. (see "* optimise the replay inputs" under)


### low priority, later or never


* Add a "Save Checkpoint" button in your mosaic UI that calls recorder.save() only when clicked. (the implementation is not finished)

* Check: the input recorder is based on the frequence of inputs for the replay of the model, but we should make sure we can make it work for a human replay, i didn't chck. we could have a mode "player to replayable input for model"

* calculate_starter_reward is it possible to have the model determine the ponderation of the different stats for the proper pokemon, and determine which is the most important stat ? (said to be special) so it could maybe ponder the rewards by himself ? (something i read gave me that idea, what do you think of it?)


* optimise the replay inputs, try to have an better implementation of the replay of the inputs with no priming, fast input played at the gym on the exact same frame to keep a determinism while having no downside.