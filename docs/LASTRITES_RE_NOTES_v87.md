# Last Rites RE — Session 87 notes (v87)

Status: **Automap v1.1 shipped.** Overlay (corner-panel) mode with global hotkeys,
automatic item symbols with engine item-type ids, authoritative level detection
from the game's own level-name string, launcher + frozen-exe persistence bugs fixed.

Supersedes v84. All v84 facts still hold; session-85 additions below.

---

## Session 85 — overlay, item ids, level-name string (2026-06-11)

### CONFIRMED: current-level name string at flat+0xCE0D0
The game keeps a fixed asset-path table for the loaded mission (flat DS offsets):
```
flat+0xCE050  "music\killer3.dsf"      current music
flat+0xCE090  "lastrite\miss02.eng"    mission TEXT file (numbered by MISSION)
flat+0xCE0D0  "levels\miss07"          current LEVEL file  <-- read this
flat+0xCE110  "bitmaps\brief06"        briefing bitmap
```
Verified live: game Mission 2 -> "levels\miss07" while position-detection had
failed to switch (MISS07 positions fall inside MISS01's bbox margin, so the
out-of-bounds trigger never fired — root cause of the stale-map bug).
The string also distinguishes MISS01 from MISS06 (identical geometry), which
position matching never could. automap reads it every tick; 3 consecutive
agreeing ticks trigger the level hot-swap. Found with
`session_51-automap/probe_levelname.py` (scans emulated RAM for miss\d\d/.clf).

### CONFIRMED: object-struct classification + real item-type id at +0x52
EntityReader's zone-field offset `off` (stride 0xA0). Discriminator u16 at
off-0x10, sprite-frame u16 at off+0x86, ITEM TYPE u16 at off+0x52:
```
class 39  + sprite 87/88  -> pickup, type id at +0x52
class 1025                -> explosive barrel/crate (sprite 120-129 = variants)
class 2087 / sprite 0     -> decals & decorations (skip)
```
Item-type ids (engine-global; CONFIRMED by correlating the user's 85 hand-placed
MISS07 markers against the live object array — probe_objects.py/probe_itemtypes.py):
```
63 Uzi (weapon)   70 Shotgun shells  71 Uzi clip       72 Shredder pack
73 Scavenger rockets  75 Inferno canister  78 Battery  80 Medkit  84 Scanner
unknown yet: 64, 66, 82 (likely the other weapons) — nameable in-app, saved to
item_names.json
```
The old +0x86 "sprite id" lumped ALL pickups as 87/88 — it is the sprite frame,
not the item type. (v84 automap drew it as anonymous colored diamonds.)

### Bugs fixed (v1.1)
1. **Launcher bat empty DOS prompt**: `start "" dosbox.exe` inherited the
   LastRitesAutomap subfolder as CWD, so DOSBox never loaded the game-root
   dosbox.conf ([autoexec] mounts + starts LR). Fix: `start "" /d "%~dp0.."
   "%DOSBOX%" -conf dosbox.conf`. (GOG's own shortcut works only because its
   WorkingDirectory is the game root.)
2. **Frozen exe never persisted .membase**: `_BASE_FILE` used `__file__`, which
   in a PyInstaller onefile build points into the temp _MEIPASS dir (wiped on
   exit). Now next to the exe (_HERE).
3. **Level switch never fired** — see level-name string above.

### Automap v1.1 features (automap.py == session_51-automap/automap_rt.py)
- Overlay corner panel default: borderless, topmost, alpha (V cycles), drag to
  move, O toggles full window, B brings to front; overlay re-asserts topmost
  every ~2 s in _tick; geometry/opacity persisted in ui_state.json.
  NO F-KEY HOTKEYS — the game itself uses F1-F8 (first build used F7/F8 and the
  game kept toggling the map; user-reported, fixed same session).
- Global hotkeys via WH_KEYBOARD_LL hook, active only while the DOSBox process
  owns the foreground window; keys pass through to the game; 0.25 s repeat guard;
  delivered to Tk through a queue drained in _tick (Tk is not thread-safe).
- M = instant numbered pin (no dialog/focus steal); click a pin to rename;
  click an item symbol to (re)name its type id.
- Item symbols: round badges (+ medkit, E battery, a ammo by color, W weapon,
  S scanner, gray ? unknown), orange ! triangle for barrels; L = legend,
  I = names next to symbols.
- Packages rebuilt: dist_automap/LastRitesAutomap_v1.1{_standalone}.zip,
  installed to C:\games\Last Rites\LastRitesAutomap\ (markers preserved).

### Session-85 pitfalls
- **Last Rites uses F1-F8** — never bind map hotkeys to F-keys; the pass-through
  hook means the game AND the map both react. Confirmed free: M, C, Tab, O, V, B.
- **Tk overrideredirect windows report empty MainWindowTitle** — verify the exe
  via side effects (.membase/ui_state.json), not window title.
- **Start-Process redirected python output is empty** unless `python -u` (buffering).
- The mission-script text (levels\missNN lists with "; level g..." comments) also
  appears on the heap near flat+0xC0Bxxx — those are PARSE LEFTOVERS listing ALL
  missions, not the current one. Only 0xCE0D0 is the live current-level buffer.

---
# (v84 notes below, all still valid)
---

## 1. Self-healing MemBase discovery (CONFIRMED)
The automap no longer needs a manual `membase_static2.py` run after a DOSBox
restart. `automap_rt.py` now re-discovers the base itself:

- Scan every committed region ≥4 MB for the **BIOS Data Area fingerprint**:
  `u16 @ phys+0x413 == 640` (conv. KB), `byte @ +0x449 < 0x20` (video mode),
  `u16 @ +0x44A in {40,80}` (text cols).
- **Decisive liveness gate**: read the BIOS tick dword `@ phys+0x46C` twice ~1.15 s
  apart; keep only candidates whose tick advanced by 10–40 (≈18.2 Hz). Exactly one
  survives. This rejects the *stale copies* of the BDA that exist in DOSBox memory
  (an earlier static scan picked a frozen copy — that was the v84 false start).
- Flat (CauseWay DS) base = `phys0 + 0x18C000` (unchanged from v83).
- Result validated by `_base_is_live` (player maps near a real zone) before use,
  so a wrong fingerprint can never stick. Saved to `.membase` and reused.

Functions: `find_base_static(handle)` and the AUTO-mode loop in `automap_rt.py`.
The base **changes between DOSBox launches** (e.g. 0xCBCC020 → 0xCBC5020 →
0xCBC5020) — always re-discover, never hardcode.

## 2. Level numbering — game mission ↔ CLF file (CONFIRMED)
The game's mission numbers do **not** map 1:1 to MISS files, and there is no
MISS02.CLF. Confirmed live this session:

- **Game "Mission 2" = MISS07.CLF** (the shopping mall — "secure the mall, find
  the main generator" per `MISSIONS/LASTRITE/MISS02.ENG`).

Mission briefings are plain text in `C:\games\Last Rites\game\lr\MISSIONS\LASTRITE\MISS01-10.ENG`.
The automap now **auto-detects** the loaded level by testing the live player
position against every `MISSxx_automap.json` zone-bbox set, so the file/mission
mapping no longer matters operationally — just load and watch the console line
`[automap] detected level: MISSxx`.

## 3. CLF format — COMPLETE to end-of-file (CONFIRMED, leftover=0)
The post-zone sections are now fully walked. After the zone loop (`sub_508D4` ×
n_zones), four sections run, transcribed 1:1 from `LR_Exe_disassembly.txt`:

```
sub_50B30   adjacency/visibility table
  u16 n1
  n1 ×  { 16 bytes ; u16 n2 ; n2 × (10 bytes + u32 flags + (flags&0x1000 ? u16 : 0)) }

sub_50C00   geometry-event table
  u16 cnt ; cnt × ( u32 type ; 4-byte hdr ; payload )
  payload sizes by type: {1,4,5,6:4}{2,3:8}{7,8,12:4}{9,11:6}{10:2}{13:4}{14:6}

sub_50DC4   ENTITY / trigger table  ← keys, switches, supplies, spawns
  u16 v17 (group count, ≤ n_zones)
  v17 × {
     u16 m ; m × (u32 a ; a<2 ? +2)            // per-group prelude
     u16 ec ; ec × ( u32 type ; u16 hdr ; payload )
  }
  payload sizes by type (FROM sub_50DC4 disasm, CONFIRMED):
     0,1:0  2:6  3:42  4:16  5:3  6:3  7:4  8:33  9:4  10:16
     11,13:8  12:6  14:8  15:14  16:2  17:5
     18: u16 n then n×2   19:8   20,21:10
     22: 1 byte; if first byte==1 then 13   23:25

sub_511DC   trailing index
  cnt × ( u16 k ; k×2 bytes )   (cnt = the sub_50C00 count)
```
Verified: MISS01 ends at file size exactly (leftover 0). MISS07 too.
Tool: `parse_entities.py MISSxx` prints every section + a per-type payload dump.

**IMPORTANT correction**: `extract_automap.py` previously hardcoded the polygon
lightmap stride to `vcnt*1`; it must be `vcnt*e523c`. The bug truncated MISS07 to
1 zone. Fixed — all 11 levels now extract fully.

### Entity positions — NOT in type-3 records
Type-3 "trigger" records are switch/door **definitions** (id, sub-id, action
params + an object-ID reference), **not** XYZ. Brute-forcing coordinate fields
gave a false 54/54 "in-bounds" (small values + origin land inside some bbox); the
record nearest the player decodes to ~39 000 units away — i.e. no position.
Switch/door world-positions live behind the object-ID reference in the object
placement system — a separate decode, deferred. See "deferred" below.

## 4. Live entity arrays (CONFIRMED on MISS07)
Found by scanning the data segment for structs whose position provably sits
inside their **own** zone's bbox (zone field valid + xyz in bbox + ×256 magnitude):

- **NPC array** (undead + allies): stride **0x234**, around `flat+0xD0000`.
  Struct begins `i32 zone, i32 x×256, i32 y×256, i32 z×256` (same layout as the
  CF840 player block). The CF840 player block at `flat+0xCF840` is effectively
  slot 0 of this system.
- **Object array** (furniture/items/pickups): stride **0xA0**, around
  `flat+0x158000`. Same leading zone/x/y/z. A **sprite-id u16 @ +0x86** gives a
  stable per-kind value (e.g. 87 recurs for shelving). Picked-up items disappear
  from the array → the map auto-updates.

The automap reads these in a dedicated thread (`EntityReader`) with windows
NPC `(0xCF000, 0x4000)` / OBJ `(0x157000, 0x16000)`, re-validating every struct
each frame (no fixed base trusted). MemReader (player position) is untouched.

Sprite-id → item-name table is **unknown** — needs the user to eyeball diamonds
in-game (`I` toggles id labels). Furniture vs. pickups not yet separated.

## 5. UI overhaul (this session)
- 2D top-down light theme: rounded zone tiles, visited/current coloring, 8000-unit
  grid, breadcrumb trail, north indicator, explored counter. No box side-faces,
  no adjacency lines (the v83 complaints).
- **Per-floor visibility**: a zone is "solid" only if its y-extent overlaps the
  player's live y ± `Y_SOLID_MARGIN` (350). Other floors are faint outlines.
  Auto-switches on stairs/ramps; `PgUp`/`PgDn` manual peek; `C` resets.
- **3D mode (`Tab`)**: renders the **real level mesh** (`extract_geo.py` output),
  flat-shaded with a fixed light, **backface-culled** (near walls vanish →
  dollhouse view into rooms), **cutaway** just below the current zone's ceiling so
  the storey above never buries the player. Right-drag orbit/tilt. Feedback LOD
  keeps ~25–90 ms/frame; far small faces drop first, near detail always survives.
  Backface sign: floors viewed from above have **positive** screen area → cull
  `area < 0`.
- **Auto-rotate is OFF by default** (`N` toggles). Velocity-derived heading lags
  the real view between polls and was nauseating; north-up + travel-direction
  arrow is the default. A true realtime rotation needs the camera-yaw memory
  global (not yet found — quick spin-in-place probe will get it).
- Auto-detect level on launch (no argument needed) + hot-swap when the player
  changes level in-game.

## 6. One-click launcher (CONFIRMED)
`C:\games\Last Rites\Last Rites with Map.bat` starts `dosbox.exe` + `pythonw
automap_rt.py` (no console). The map self-configures. This is the "ship as add-on"
experience the user asked for. GOG DOSBox is `C:\games\Last Rites\dosbox.exe`
(plain command line, mounts `game`, imgmounts the CD ISO, runs `lr`).

## 7. Infinite health — DEFERRED (hard case: relocating + regenerating)
Extensive snapshot-diff hunting (tool `find_hp.py`, compounding set-intersection)
**failed to pin a stable address**, and we now understand why:
- **Player health is NOT a fixed global.** The global struct at `0xCF814` (disasm
  sub_17928/17998/17A1C: CF844/848/84C live at CF814+0x30) is **position/camera
  only** — health is not a stable byte anywhere in the BSS globals window
  (0xC0000-0x106000); a 24->27 narrow there gave 0 survivors.
- **Health rides a relocating heap object.** Every candidate pinned in the heap
  (0x284F70, 0x26B8FA, 0x2A5DD3, 0x2725EC, …) matched the seed + ONE change, then
  DIVERGED from the HUD on the next change (e.g. 0x2725EC: 103->33 OK, then read
  112 while HUD=24). Classic signature of a value whose address moves.
- **It also regenerates**, so small-step samples drift between snapshots; only big
  jumps (103->33) gave clean single candidates — which still relocated.
- The heap is full of OTHER entities' health bytes (hundreds of undead/allies), so
  2-3 samples always leave coincidental survivors. The object array at 0x157000
  (+0x24 health) is a **display copy** — freezing it did NOT stop damage (HUD
  dropped 100->84 while we wrote 100).
- Binary is stripped (no "health/damage" symbols).

**Correct next approach (no player walking needed):** set a memory **watchpoint**
on the health value (DOSBox-X debugger `BPM`, or Cheat Engine "find what writes
this address") to catch the writing instruction and the **pointer/base register**
it uses → that base reaches the player object reliably wherever it relocates.
Then per-frame: deref pointer, write max health at the object's HP offset; allies
likely share the object layout. Tools left in place: `find_hp.py`, `health_freeze.py`,
`godmode.py` (the godmode per-frame re-scan skeleton is reusable once the object
signature is known).

## 8. Distribution — shareable mod package (DONE)
Portable, forum-ready packaging in `dist_automap/`:
- `LastRitesAutomap/automap.py` — the renamed automap_rt.py, made portable
  (frozen-aware paths: `sys._MEIPASS` for bundled data, `_HERE` for writable
  markers; JSON search includes `data/`). Self-contained stdlib only (the
  scan_player.py reference is dead code — `_recalibrate_base` is never called).
- `data/` — all 11 levels' `MISSxx_automap.json` + `MISSxx_geo.json`. The mod needs
  NO access to the game's CD ISO (`game/cd/iso/LEVELS`) — geometry is pre-extracted.
- Two builds:
  - **Python build**: `LastRitesAutomap_v1.0.zip` (892 KB) — needs Python 3.
  - **Standalone build**: `LastRitesAutomap_v1.0_standalone.zip` (10.6 MB) — single
    PyInstaller `.exe`, NO Python needed. Built with:
    `pyinstaller --onefile --noconsole --name LastRitesAutomap --add-data "<abs>/data;data" automap.py`
    (the `--add-data` path must be ABSOLUTE; spec-relative fails).
- Launchers (`.bat`): start `..\dosbox.exe` (GOG/Steam layout) + the map; map
  self-attaches. `FORUM_POST.md` = ready-to-paste Steam/GOG post.
- Installed to `C:\games\Last Rites\LastRitesAutomap\` (standalone exe + user's 85
  markers in `markers/`). Windows-only (reads DOSBox memory via WinAPI).

## Deferred / next
1. Second HP snapshot → pin health → freeze loop (player + allies).
2. Sprite-id → item-name legend (user eyeballs `I`-labelled diamonds).
3. Switch/door positions: decode object-ID placement (object array index by id?).
4. Camera-yaw global for realtime 3D/2D rotation (spin-in-place diff probe).
5. Manual map markers (`M` drops a pin at the player) — being added this session.

## New/changed tools (session 84)
```
session_51-automap/automap_rt.py   REWRITTEN: 2D+3D UI, EntityReader, self-heal base, auto-detect
extract_geo.py                     NEW: per-zone world-space mesh → MISSxx_geo.json (all 11 levels)
extract_automap.py                 FIXED: lightmap stride vcnt*e523c (was *1) → MISS07 full
parse_entities.py                  NEW: full post-zone CLF walk + entity type dump
session_51-automap/health_probe.py NEW: damage-diff health hunter
C:\games\Last Rites\Last Rites with Map.bat   NEW: one-click launcher
MISSxx_automap.json (01,04-13)     regenerated (zone bbox + edges)
MISSxx_geo.json (01,04-13)         NEW (render geometry)
```

## Pitfalls discovered this session
- **BDA static scan without the tick gate picks a frozen copy** → wrong base.
  Always require the 18.2 Hz tick to advance.
- **extract_automap lightmap stride was vcnt*1** → silently truncated MISS07.
  Use vcnt*e523c (matches export_obj_transformed/extract_geo).
- **CF6C8 is not health** (oscillates). Don't trust a single decreasing field;
  use the known-value snapshot-diff.
- **Type-3 CLF records are not entity positions** (definitions only).
- **Console UnicodeEncodeError on cp1251** (Russian Windows): reconfigure stdout
  to utf-8 at startup; avoid non-ASCII in print (use `->` not `→`).

---

# SESSION 86 (2026-06-11) — Automap v1.2: fullscreen-overlay fixes from first user feedback

User-reported v1.1 problems and fixes:

1. **Overlay never above the game; B key shrank fullscreen DOSBox.**
   Root causes (CONFIRMED in code + Windows semantics):
   - GOG DOSBox (SDL1) fullscreen = EXCLUSIVE mode -> no window can draw above
     it, topmost or not. Unfixable in software; the game must run windowed.
   - `_bring_to_front()` used Tk `deiconify()`/`lift()`, which ACTIVATE the map
     window -> exclusive-fullscreen SDL loses focus -> minimizes ("shrinks").
   Fixes (automap.py, synced to automap_rt.py):
   - New `_raise_noactivate()`: Win32 `SetWindowPos(HWND_TOPMOST,
     SWP_NOSIZE|NOMOVE|NOACTIVATE|SHOWWINDOW)` + `ShowWindow(SW_SHOWNOACTIVATE)`
     via `GetAncestor(winfo_id(), GA_ROOT)`. Used by B and by the 2-s self-heal
     (which previously also called `lift()`).
   - New `automap_window.conf` ([sdl] fullscreen=false, windowresolution=desktop,
     output=ddraw). Both launcher .bats now pass it as a SECOND `-conf` after the
     game's dosbox.conf (later conf wins) -> game starts in a desktop-sized window
     so the overlay is visible. Delete the conf to restore fullscreen.
   - README: troubleshooting entry explaining the exclusive-fullscreen limitation.

2. **Default overlay placement** moved top-right -> top-middle:
   `380x320+{(sw-380)//2}+16`. User's live ui_state.json re-centered too (saved
   geom overrides the default).

3. **Mislabeled M-pins near items**: user dropped pins as item labels, not
   knowing badges are clickable. Marker rename dialog now accepts `-` to DELETE
   the pin (click pin -> type `-`). README clarifies: click the gray "?" badge
   itself; badges ARE the items.

4. **Item id 64 = Shotgun (CONFIRMED by user click-naming in-game)** — merged
   into ITEM_NAMES_DEFAULT. Remaining unknown ids: 66, 82.

Shipped: dist_automap/LastRitesAutomap_v1.2.zip + _v1.2_standalone.zip
(exe rebuilt via dist_automap/exe_build/LastRitesAutomap.spec, PyInstaller 6.20).
Live install C:\games\Last Rites\LastRitesAutomap updated (exe, bat, conf,
README, ui_state).

Pitfall added: Tk deiconify()/lift() steal focus -> never call them while the
game may be exclusive-fullscreen; raise with SWP_NOACTIVATE instead.

## Session 86 follow-up (same day) — lifecycle fixes

5. **automap_window.conf output=ddraw -> openglnb**: ddraw surface creation FAILS
   on the user's Win11 ("Failed to create ddraw surface, back to normal surface")
   -> fell back to unscaled surface -> blank white desktop-sized window. openglnb
   is what the GOG dosbox.conf itself uses (fullscreen=false + fullresolution=
   desktop + windowresolution=original were ALREADY in the GOG conf — the user
   had toggled fullscreen via Alt+Enter).

6. **Lifecycle (user request)**: (a) overlay panel has a ✕ close button (canvas
   top-right, drawn after v.render each tick) + Esc closes when map focused;
   (b) single instance — automap.pid file, new launch TerminateProcess()es the
   previous instance (only if image name starts with python/lastritesautomap);
   (c) auto-exit ~6 s after the DOSBox process dies (host-side _proc_alive():
   OpenProcess(0x1000)+GetExitCodeProcess==STILL_ACTIVE on reader.get_pid()),
   in BOTH App._tick and the pre-UI auto_detect_level wait loop.
   TESTED: replacement (2 python instances), tick-path exit (fake dosbox.exe =
   renamed ping.exe + explicit MISS01 arg), AUTO-wait-path exit. Note for tests:
   AUTO mode blocks in auto_detect_level BEFORE App exists — tick-path logic
   unreachable until a level is detected; use an explicit level arg.

Pitfall: reader._pid goes STALE after game death (loop only _connect()s when
_handle is None) — game-death detection must check process liveness host-side,
never trust get_pid() freshness.

---

## Session 87 — automap v1.3: declutter, key conflicts, overlay pan (2026-06-12)

User playtest feedback on MISS07 drove four UI fixes + new item ids.

### Item-type ids named by the user in-game (MISS07, item_names.json)
Merged into ITEM_NAMES_DEFAULT (engine-global, apply to all levels):
```
64 = Shotgun            (was already in defaults — user confirmed)
66 = Plasma blaster     (NEW — was on the 64/66/82 unknown list)
67 = Shredder multi-cannon (NEW)
80 = Medkit (25%)       (refined — was generic "Medkit")
81 = Medkit (50%)       (NEW; styled red "+" like 80)
```
Still unidentified: **82** (and any of 65/68/74 if they exist in the wild).

### v1.3 UI changes (all in automap.py; rt + dist + game install synced)
1. **+/- removed from the GLOBAL hotkey map** — the game itself uses +/- to
   resize the game screen (hook never swallows keys, so both fired). Global
   zoom now lives on **[ and ]** (VK 0xDB/0xDD); +/- still work when the MAP
   window has focus.
2. **Labels declutter**: marker-pin labels now obey the same toggle as item
   labels (**I**, default OFF, persisted in ui_state as "labels"). Legend (L)
   identifies symbols without text spam.
3. **Ambient pins hidden by default**: markers whose label matches
   /light|lamp|vending/i (pure scenery, no interaction) are skipped — toggle
   back with **U** (persisted as "ambient"). Hidden pins also skip the
   click-to-rename hit test.
4. **Overview (R) declutter**: at zoom < 0.010 all entity symbols shrink
   (r=6 -> 3, outline 2 -> 1), glyph text + all labels are suppressed, marker
   pins draw as small triangles. Threshold chosen between fit_level zoom
   (~0.007 on MISS07) and follow zoom (0.022).
5. **Overlay pan fix (user request)**: in corner-panel mode a left-drag used to
   ALWAYS move the panel — the map content could never be panned. Now only a
   drag that STARTS on the title strip (y <= 26 px) moves the panel; a drag on
   the map body pans the view (C snaps back to the player). _strip_drag is
   latched in _md.

### Shipping
- exe rebuilt (PyInstaller 6.20, exe_build/LastRitesAutomap.spec).
- Packages: dist_automap/LastRitesAutomap_v1.3.zip + _v1.3_standalone.zip
  (same manifests as v1.2).
- Game install C:\games\Last Rites\LastRitesAutomap updated (exe + README).
  Old exe was file-locked with NO visible process (stale automap.pid, no
  LastRitesAutomap process) — deployed via rename-aside
  (LastRitesAutomap_old.exe left in place; delete once confirmed good).

Pitfall added: a PyInstaller onefile exe can stay file-locked after the process
list is clean — rename-aside works where Copy-Item fails.

### Session 87 addendum — live ambient SCENERY (not just marker pins)
User clarified: the clutter is also LIVE class-1025 statics — ceiling lamps and
vending machines share class 1025 with explosive barrels (all drew the orange
"!" triangle). They differ by sprite id @ +0x86 (already captured as the
triangle's tid). Which sprite ids are lamps vs real barrels is UNKNOWN (needs
live data), so v1.3 makes triangles click-to-name like item badges:
- SCENERY_NAMES {sprite_id: name}, persisted to scenery_names.json next to exe.
- A name matching the ambient regex (now light|lamp|vending|ambien|decor|
  scenery) hides that sprite id everywhere (U shows again). Same check applies
  to click-named ITEM ids and to the legend rows.
- item_hits is now (sx, sy, kind, tid); click dialog branches barrel/item.
- Caveat: sprite id may ANIMATE through several frames per object — one kind
  may need 2-3 namings (documented in README).
Once the user names them, harvest scenery_names.json (game install) into a
SCENERY_NAMES_DEFAULT, like ITEM_NAMES_DEFAULT.

---

## Session 87 part 2 — missing items root cause + CLF switch/door logic DECODED

### CONFIRMED: OBJ_WIN overflow was hiding pickups (MISS05)
The "Uzi clip not on the map" (user standing on it, d=76) lives at flat 0x16FF8C
— PAST the old object window 0x157000+0x16000 (ends 0x16D000). MISS05 has more
objects than MISS07; 24 pickups sat outside the window (wide_scan.py, flat up
to 0x1748xx). FIX: OBJ_WIN size 0x16000 -> 0x38000. All of the user's
"not mentioned on the map" item pins fall in the previously-unscanned tail.
New ids seen live on MISS05: tid 88 (unknown), tid 91 = QUEST CONTAINER
(matches user "Level objective" pin at 165 units; added to defaults, gold Q).
User pin correlation also re-confirmed 81=50% medkit, 84=scanner upgrade, 70/71.

### CONFIRMED: CLF interactive-object logic (extract_logic.py)
All in the sub_50DC4 per-group records + sub_50B30 table:

1. **sub_50DC4 type 8 (33B) = sprite placement**: ASCIIZ filename (10B field),
   u16, then 3x i32 at payload bytes 12/16/20; world=(-x/256, y/256, z/256).
   LOCKx.S16/SERVx.S16 = switch panels — 14/14 of the user's MISS05 switch
   pins matched at d=103..155. LIGHT1.S16 = hanging lights (the live "ambient"
   triangles), DRIPx/STEAMx = sewer effects, *DOR*/SBIGDOOR = door sprites.
2. **sub_50B30 record16 = movable object**: u16 field0, then 3x i32 at bytes
   2/6/10, ALREADY world units, world=(-x, y, z); trailing u16 always 0x100.
   27/27 MISS05 door pins + 20/21 MISS07 door pins matched. The table holds
   ALL movables (proximity doors + switch-driven pieces); no per-record kind
   flag found yet — proximity doors can't be isolated statically (only the
   type-3-referenced subset is exported).
3. **sub_50DC4 type 3 (42B) = action**: i16[0] target id (index into the
   sub_50B30 table), i16[1] sub-part, i32@8 = signed move delta. These are the
   "door opens elsewhere" wirings.
4. **type 22 (13B form) = touch-trigger**: fl byte + 3x i32 world coords
   (y=0). MISS01-style sprite-less switches. z matched user pins to <300
   (one to 1 unit); x reads ~4500 low — likely a volume corner (INFERRED).
5. **group headers = boolean condition over trigger ids**: token a=0/1 ->
   operand id b; a=2 '('; a=3 ')'; a=4 AND. Parses perfectly:
   MISS01 force field grp4 = ( ( T0 AND T1 ) AND ( T2 AND T3 ) );
   MISS07 front door grp23 = ( T22 AND ( T23 AND T25 ) ) — exactly the user's
   description (generator switches 66/67/68 in grp30 light the building, the
   main-door switch only works when its required triggers are set).
6. type 2 = (object id, sub, state code 130/22/131); type 5/6 = signal refs;
   type 14 = sound; type 18 = id list; type 16/7 = small refs (not needed).

### Tools / data shipped
- `extract_logic.py MISSxx [outdir]` -> MISSxx_logic.json (switches with
  positions+conditions+actions, remote-door targets with positions, raw groups).
  Generated for MISS01..13 into dist data; bundled in exe + both zips.
- automap v1.3: blue S squares = switches, brown D squares = remote-operated
  doors; click for wiring popup ("works when T22 AND ...; moves object N at
  (x,z) by d" / "operated by switch at (x,z)"). Legend rows added.
- session_87/: probe_missing_item.py, census_objwin.py, wide_scan.py,
  decode_dc4.py, lock_groups.py, b30_doors.py, match_doors*.py,
  dump_groups_full.py, t22_hex.py, validate_miss05.py.

### Open
- tid 82 and 88 still unnamed.
- Proximity (non-remote) door classification in sub_50B30 — likely possible
  via the live object array (class 33280 n=60 on MISS05 is suspect) or the
  10-byte subrecords; not blocking.
- t22 x-offset (~4500) understanding.
- MISS08 SCLICK/SCLUNK groups: kept as switches (sound-panel sprites); check
  in-game whether sewers switch symbols land correctly.

### Documentation
All session-87 format findings consolidated into **CLF_LOGIC_REFERENCE.md**
(canonical entity/logic reference: post-zone layout, sub_50B30 table, all 23
dc4 record types, sprite catalog incl. LOCK/SERV/LIGHT/DRIP/STEAM/door sprites,
condition grammar, coordinate transforms, runtime windows/classes/item ids,
per-level stats, worked MISS07 front-door example, tooling index).
README.md "What's Left" section replaced (old 18-byte entity record guess was
WRONG — discard).
