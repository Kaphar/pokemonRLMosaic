# today :

fix the take control:
add web controls section in the config to store the control through the browser, reason for this is that the binding respond to different names o button for some reason, the simplest is just to use separate sets of keybinds.
I will then verify if everyting is fine

We finally can do our version of the run_pretrained_interactive.
We have to think how we are going to organize the code, the our emulator_with_debug doesn't have the Interactive mode. I would probably be better to add the fuctionality there, or maybe make a separate script, but I will want the data_panel.

then we can Implement a function that "save the state and input (and inputs) of selected env to /envs/Dev folder and opens our interactive emulator for the Dev loading that state.
one thing we need to check : at what moment is saved the state ? We should queue the saving of the emulator until the frequency of the input is about to or just starting the next input. So if the model resumes a state, the input would be reproduced at the same frame if the 2 playthrough were played at once "consecutively"




ARE WE BLOCKED MASKED ACTION FOR DOWN AFTER GETTING OAK Parcel ?


fix breadcrumb tracker
fix pokemon center tracker
those 2 have a similiar behaviour, let's fix the pokemon center first, normally the breacrumb tracker is commented out (check)
so we need to design a way


make sure the events milestones are flagged achieved, they are triggered in the events.json handling, but it seems that those type of milestone don't register properly.

tune up the speed. Why is it that our emulator_with_debug in interactive mode is faster than the mosaic ? does it mean we are doing thing inefficiently with our mosaic and we could actually train faster ?

reduce write to disk :
remove(cancel) the finalisation of the input files, we are recording the inputs to save them if we need them, if we are closing the app we don't need the files.
Make a pokemon manager that stores our pokemons saved states with good (PERFECT) DVS. we already have a function that computes the values of DV's so we can save the state of catched pokemon when the DV score is Better, we want a different version for Blue and Red ( depending on the ROM, the name of the state must now include the "red" or "blue" tag, corresponding to the ROM)


# later 

one thing we need to check : at what moment is saved the state ? We should queue the saving of the emulator until the frequency of the input is about to or just starting the next input. So if the model resumes a state, the input would be reproduced at the same frame if the 2 playthrough were played at once "consecutively"


bug of state in the inspector an env select list (it updates and resets)

fix the amount of step per iteration change "on the fly" by the config tab.

