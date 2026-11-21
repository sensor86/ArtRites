================================================================================
  LAST RITES (1997) - LIVE AUTOMAP   v1.5
  A real-time map mod for the Ocean / Mindscape game "Last Rites"
================================================================================

A small semi-transparent map panel sits in the corner of your screen and follows
your character as you play - like a GTA minimap or the Doom automap, but for
Last Rites. Items (medkits, ammo, weapons, batteries) appear automatically as
symbols, enemies show on a radar, and you can pin your own notes onto the map.
Press O any time to switch between the corner panel and a full resizable window.

NO game files are modified. The map only READS the game's memory to know where
you are. It cannot change or break your game or saves.

--------------------------------------------------------------------------------
  WHAT YOU NEED
--------------------------------------------------------------------------------
- Last Rites running in DOSBox on Windows (GOG or Steam - both ship the game
  inside DOSBox). The map works with DOSBox, DOSBox-X and DOSBox Staging - it
  finds the game's memory itself and does not care which emulator build you use.
- Either:
    * the self-contained .exe release (no Python needed - recommended), or
    * Python 3 (free) from https://www.python.org/downloads/  (tick "Add to
      PATH") if you run the source version.

(Windows only for now - the map reads DOSBox's memory through a Windows API.)

--------------------------------------------------------------------------------
  INSTALL  (the easy way)
--------------------------------------------------------------------------------
1. Unzip the WHOLE release somewhere (do not download files one by one from the
   GitHub page - use the release .zip).
2. Double-click "Install Last Rites Automap.bat" and follow it. It finds your
   game folder, copies the mod in, and can add a Desktop shortcut.

  (Manual way, if you prefer)
  Copy this whole "LastRitesAutomap" folder INTO your Last Rites game folder -
  the folder that contains dosbox.exe:
      GOG:   ...\GOG Games\Last Rites\
      Steam: ...\steamapps\common\Last Rites\
  Then double-click "Play Last Rites with Automap.bat".

3. The MAP window opens first and says "Waiting for a running level". Start a
   mission; it attaches by itself within a few seconds. From then on it detects
   which level you are in and switches automatically when you finish a level.

If the game is already running, use "Map only (game already running).bat".

--------------------------------------------------------------------------------
  CONTROLS  (these work even while the GAME window has focus;
             no F-keys and no +/- - the game itself uses F1-F8 and +/-)
--------------------------------------------------------------------------------
  O          corner panel <-> full window   (there is no "0" key - it is O)
  V          panel transparency (4 steps)
  B          bring the map back on top (it also re-asserts itself every 2 s)
  Tab        2D top-down map <-> 3D view
  M          drop a numbered pin where you stand (instant - no typing;
             click the pin later to rename it, or type "-" there to delete it)
  Delete     remove the pin nearest to where you stand
  C          re-center on you / follow mode
  R          zoom out to the whole level (symbols shrink so the map stays
             readable; zoom back in for full-size symbols)
  N          auto-rotate on/off (default: off, north is up)
  PgUp/PgDn  look at the floor above / below (multi-storey levels)
  L          item legend on/off
  I          text labels on/off (item names + your pin labels; default OFF -
             the legend identifies the symbols without the clutter)
  U          ambient pins on/off (pins named "light"/"vending" etc. are pure
             scenery you can't interact with; hidden by default)
  [ and ]    zoom out / in (works while the game has focus; +/- belong
             to the game - they resize the game screen)
  mouse wheel  zoom
  drag       pan the map to look at areas away from you (press C to snap
             back); in the corner panel, drag the TITLE STRIP at the top
             to move the panel itself
  right-drag (3D)  rotate / tilt
  Esc / the small x in the panel corner   close the map
  (the map also closes by itself a few seconds after you quit the game,
   and starting it again replaces a still-running map - never two at once)

--------------------------------------------------------------------------------
  WHAT YOU SEE
--------------------------------------------------------------------------------
- Bright dot / arrow ..... you
- Red circles ............ live creatures (undead / your allies) - an enemy radar
- Round badges ........... items, automatically detected and identified:
                           + medkit   E battery   a ammo   W weapon   S scanner
                           (press L for the legend; the colours tell ammo
                           types apart)
- Orange triangles (!) ... static objects: explosive barrels/crates, but also
                           ceiling lamps, vending machines and other scenery
                           the engine stores the same way. Click a triangle
                           and type what it is - if the name contains "light",
                           "lamp" or "vending" that kind disappears from the
                           map (it's just decoration); press U to show such
                           ambient things again.
- Gold pins .............. notes you placed with M (saved per level, kept forever)
- Blue squares (S) ....... switches, extracted from the level files themselves.
                           Click one to see what it does - which door it moves
                           and which other switches must be on first.
- Brown squares (D) ...... doors/objects that are operated REMOTELY (by a
                           switch somewhere else). Click to see which switch.
- Tiles light up ......... areas you have explored

A few item kinds are still unidentified (gray "?" badges). Click the badge
itself and type what it is - the name is remembered and from then on every
item of that kind is labelled on all levels. (No need to drop M-pins next to
items: the badges ARE the items, at their exact positions.) The same works
for the orange triangles - one click teaches the map what that object kind
is everywhere. If a named lamp/vending kind still shows the triangle in a
few spots, its sprite animates through several ids - just click and name
those too.

On multi-storey levels (the mall, the sewers) only your current floor is drawn
solid; the rest are faint. It switches automatically as you take stairs/lifts.
Your markers are saved in a "markers" folder created next to this file.

--------------------------------------------------------------------------------
  TROUBLESHOOTING
--------------------------------------------------------------------------------
- The map window opens and says "Waiting for a running level": that is normal -
  it waits until you load a mission, then attaches. If it never attaches, see
  the log bullet below.
- The map never shows above the game: the game is in real (exclusive)
  fullscreen - NOTHING can be drawn above that, it is a Windows limitation.
  Press Alt+Enter in the game to switch it to a window. The included
  launcher already starts the game in a desktop-sized window for this reason
  (automap_window.conf; delete that file to get fullscreen back).
- Map opens but the dot doesn't move: load an actual level (not the menu).
- Dot stops after you restart DOSBox: it re-finds the game within a few seconds.
  If it stays stuck, close and reopen the map.
- The corner panel is in the way: drag it anywhere with the mouse, V makes it
  more transparent, O turns it into a normal window.
- The map disappeared behind the game: press B to bring it back on top.
- "Python is required": install Python 3 from python.org and tick "Add to PATH",
  or grab the standalone .exe release instead.
- It still won't attach: close the map, then send the file "automap.log" (it is
  written next to the map every run) with your report. It shows exactly what the
  map found - DOSBox process, memory base, level - and makes diagnosis quick.

--------------------------------------------------------------------------------
Built by reverse-engineering the .CLF level files and the game's memory layout.
Level shapes were extracted directly from the game's own files. Share freely.
================================================================================
