In recent changes we weren't successful in determining how to be able to have/ turn on and toggle (check the audio flags ?).
There is always this duality between the python app and the web app, through the web app with the dev mode button it is working, we can control the dev emulator, it can go in interactive mode, but i couldn't have the sound. In the python Observation Inspector, we had the sound but our input weren't considered. it would be nice to fix everything but ultimately if I am moving after refactoring to a mostly web experience, we might not need to take care of everything. still leaving a note for later, I am not even sure why I am pushing this change.
ARE WE BLOCKED MASKED ACTION FOR DOWN AFTER GETTING OAK Parcel ?


fix breadcrumb tracker
fix pokemon center tracker
those 2 have a similiar behaviour, let's fix the pokemon center first, normally the breacrumb tracker is commented out (check)
so we need to design a way => maybe I need to ask for more insight.

* reduce write to disk :
- remove(cancel) the finalisation of the input files, we are recording the inputs to save them if we need them, if we are closing the app we don't need the files.

-> Make a simple pokemon manager that stores our pokemons saved states with good (PERFECT) DVS. we already have a function that computes the values of DV's so we can save the state and inputs of catched pokemon when the DV score is Better, we want a different version for Blue and Red ( depending on the ROM, the name of the state must now include the "red" or "blue" tag, corresponding to the ROM)

* investigate : bench/tune up the speed. Why is it that our emulator_with_debug in interactive mode is faster than the mosaic ? does it mean we are doing thing inefficiently with our mosaic and we could actually train faster ? or in interactive mode the model is not training ? we need to analyze why it's slower, because maybe we can improve our training speed.

* make sure the events milestones are flagged achieved, they are triggered in the events.json handling, but it seems that those type of milestone don't register properly.


# later 

one thing we need to check : at what moment is saved the state ? We should queue the saving of the emulator until the frequency of the input is about to or just starting the next input. So if the model resumes a state, the input would be reproduced at the same frame if the 2 playthrough were played at once "consecutively"


bug of state in the inspector an env select list (it updates and resets)
inside the inspector_tab
reorganize the collapsable panels, the collapsable header/label should be Environement Directives, don't put collapsable inside collapsable (get them out of the "parent"). We can also put the same style of collapsable for Trainer Information. move those 2 children lower, we want to show the reward history


# minor bugs
* fix the amount of step per iteration change "on the fly" by the config tab.

* when we close the window of the selected emulator, it reopens instantly, make the closing of the Inspector Window "unselect" the emulator of the mosaic.

* need to fix a slight offset error of the "grid" for the Zone Cell overlays, there is also an offset with the green dots, center the dot of the player inside the 16*16 tile

# minor tweaks
* not urgent but ideally, we should split the controls of the mosaic (currently draw with CV2... at the right of our main mosaic image) into another window.


# refactor :
* run_mosaic launcher :
- extend the width and a bit of heigth of the launcher screen, not every piece of text are shown.
- start the app by the launcher to set up the settingss for the stages/ profiles/steps / model : (add option when we create a new model to name it ! use a named folder for it.)
- run_mosaic should run with the parameters set by launcher, technically, if we don't change a value, or if we were to run that script "without parameters" (or default set) it should run the same settings as last session.
We hide the mosaic By Default, we need a boolean to disable the training statistic Window (you can ad the option in the launcher, put the settings at the end ( "legacy settings")). this would effectively make the app "headless" and web controlled/monitored. we will keep and option to toggle the window of the mosaic. 
while we are at it design a better splitting of the coder (e.g : extract the recording/replaying code from the main files if possible, etc. organize the code a bit better, let's analyze our options but the goal is to make the code clearer for everyone, more logical, and easier to implement and understand later, comments on Sections and codeblock are welcome)


