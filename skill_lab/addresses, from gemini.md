The absolute last address of the Work RAM (WRAM) on a Game Boy is 

0xDFFF
.The Game Boy maps its internal WRAM across a 8KB block spanning from 

0xC000
 to 

0xDFFF
. In Generation 1 Pokémon games, this space holds almost all of your active gameplay variables, including inventory, party stats, and screen tile data.Pokémon Gen 1 WRAM Memory MapThe core functional ranges within Gen 1's WRAM layout break down into these distinct blocks:Start AddressEnd AddressPurpose / Description

0xC000

0xC2FF
Sprite
 Buffers & OAM: Handles on-screen sprite attributes, positions, and animation states.

0xC300

0xC4FF
Audio
 Buffer: Controls active music tracks, sound effects playing, and channels.

0xC500

0xCCFF
Tile
 Map & VRAM Buffers: Caches current screen background data, window text layers, and menu tile properties.

0xCD00

0xD0FF
System
 & Menu State Variables: Manages temporary event buffers, text speed layouts, and screen sub-states (including 

0xD07D
 for naming screens).

0xD100

0xD2F6
Player
 Party Data: Holds counts, species IDs, HP, stats, and moves for all 6 Pokémon in your current team.

0xD2F7

0xD35C
Main
 Player State: Stores player name, current map ID, structural coordinates, and active direction.

0xD35D

0xD5A5
Game
 Progress & Inventory: Tracks Bag items, money, badges, and the standard item storage list.

0xD5A6

0xD72D
Daycare
 & Map Scripts: Tracks Daycare status and internal execution hooks for local area scripts.

0xD72E

0xD95D
Event
 Flags / Plot Progress: Massive bitmask checking which trainers you've fought, items picked up, and story events completed.

0xDA00

0xDCFF
Current
 PC Box Content: Temporarily mirrors structural data for the specific PC Storage Box you are browsing or saving to.

0xDD00

0xDFFF
Battle
 Memory Engine: Dynamically stores current wild/enemy Pokémon stats, your active battler, damage math modifiers, and temporary modifications.