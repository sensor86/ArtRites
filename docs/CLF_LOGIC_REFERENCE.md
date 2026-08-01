# Last Rites CLF — Entity & Logic Format Reference

Complete reference for the **post-zone data** of `MISSxx.CLF` files: movable
objects, sprite placements (switches, lights, doors), trigger logic, and the
runtime memory layout used by the live automap. Established sessions 84–87.

Evidence levels: **CONFIRMED** = byte-level match against in-game ground truth
(user-placed pins at known objects, live memory correlation); **INFERRED** =
consistent decode, not yet verified in-game.

Geometry/texture format (zones, polygons, LIF atlases) is documented in
`README.md`. The canonical parser for everything below is `extract_logic.py`
(walk transcribed 1:1 from the Hex-Rays disassembly, `LR_Exe_disassembly.txt`).

---

## 1. Post-zone file layout

After the last zone (see README for the zone walk), four sections follow
back-to-back, read by these engine functions:

| # | Function   | Content                                            |
|---|------------|----------------------------------------------------|
| 1 | sub_50B30  | Movable-object table (doors, lifts, pieces)        |
| 2 | sub_50C00  | Typed records, semantics unknown                   |
| 3 | sub_50DC4  | **Logic groups** (switches, triggers, actions)     |
| 4 | sub_511DC  | Per-50C00-record u16 lists, semantics unknown      |

The file ends exactly at the end of section 4 (verified: 0 leftover bytes on
MISS07).

---

## 2. sub_50B30 — movable-object table  (CONFIRMED)

```
u16 count                      (MISS07: 722, MISS05: 575)
count × {
  rec16:
    u16  field0        monotonically increasing, ≈ index − 75…95 (mesh ref?)
    i32  x  @ byte 2   ┐ ALREADY world units (no /256)
    i32  y  @ byte 6   │ world = (−x, y, z)
    i32  z  @ byte 10  ┘
    u16  @ byte 14     always 0x0100 (no kind flag here)
  u16 n_subs
  n_subs × {
    10 bytes:  i16[0] = linked record id, i16[1] = param (length/extent?),
               then 0, 1, 0
    u32 flags          0x7 typical; if flags & 0x1000, one extra u16 follows
  }
}
```

**Validation:** nearest-record match against user door pins:
MISS05 **27/27** pins matched (d = 100–365 units), MISS07 **20/21**
(the miss was a switch pin, not a door). Record indices are the id space used
by type-3 actions (below).

The table holds **all** movables — proximity doors, switch-driven pieces,
lift platforms. No per-record kind flag was found, so plain proximity doors
cannot yet be isolated statically; only the switch-driven subset (referenced
by type-3 actions) is classified. Suspected future discriminator: the runtime
object array (class 33280, see §7) or the subrecord params.

---

## 3. sub_50C00 — typed records  (structure CONFIRMED, semantics unknown)

`u16 count`, then per record: `u32 type` + 4 header bytes + payload of fixed
size by type: types 1/4/5/6/7/8/12/13 → 4 bytes, 2/3 → 8, 9/11/14 → 6,
10 → 2. MISS07 census: `{1:12, 2:16, 5:22, 6:1, 7:12, 8:68, 10:2, 11:2}`.
Section 4 (sub_511DC) holds one u16-list per 50C00 record.

---

## 4. sub_50DC4 — logic groups  (the heart of level scripting)

```
u16 n_groups                   (MISS07: 133, MISS05: 74, MISS01: 7)
n_groups × {
  u16 m                        header token count
  m × token {
    u32 a
    if a < 2: u16 b            operand
  }
  u16 n_entities
  n_entities × { u32 type; u16 hdr2; payload (size by type, §4.2) }
}
```

### 4.1 Group headers = boolean trigger conditions  (CONFIRMED)

Tokens form an infix boolean expression over **trigger ids**:

| token a | meaning            |
|---------|--------------------|
| 0, 1    | operand: trigger id `b` (a=0/1 distinction unknown) |
| 2       | `(`                |
| 3       | `)`                |
| 4       | `AND`              |

A *switch* group's header is its own trigger id; a *door/effect* group's
header is the condition that arms it. Verified word-for-word against
gameplay:

- **MISS01 force field** (group 4): `( ( T0 AND T1 ) AND ( T2 AND T3 ) )` —
  the four city switches.
- **MISS07 front door** (group 23): `( T22 AND ( T23 AND T25 ) )` — the main
  switch only works after the others; the three stacked generator switches
  are groups 27/28/29 (ids 66/67/68) combined by group 30 `[66, 67, 68]`
  ("two switches on the generator light up the building and allow the
  front-door switch to function" — user's description, found verbatim in
  the file).

No OR operator observed yet.

### 4.2 Entity record types (payload sizes after the 6-byte type+hdr2)

| type | size | meaning                                                | status    |
|------|------|--------------------------------------------------------|-----------|
| 0, 1 | 0    | markers/separators                                     | unknown   |
| 2    | 6    | `[object id, sub, state code]` (codes 22/78/130/131)   | INFERRED  |
| 3    | 42   | **action: move movable** — §4.4                        | CONFIRMED |
| 4    | 16   | —                                                      | unknown   |
| 5, 6 | 3    | `[trigger id]` + 1 byte — signal/enable link           | INFERRED  |
| 7    | 4    | `[id, 0]` small ref (790× on MISS07)                   | unknown   |
| 8    | 33   | **sprite placement with position** — §4.3              | CONFIRMED |
| 9    | 4    | —                                                      | unknown   |
| 10   | 16   | `[id, x_lo, x_hi, z_lo, z_hi, y_lo, y_hi, 51]` posed   | INFERRED  |
| 11,13| 8    | —                                                      | unknown   |
| 12   | 6    | —                                                      | unknown   |
| 14   | 8    | `[569, 0, 4096|4102, 0]` — sound ref?                  | INFERRED  |
| 15   | 14   | —                                                      | unknown   |
| 16   | 2    | small ref (128× on MISS07)                             | unknown   |
| 17   | 5    | —                                                      | unknown   |
| 18   | 2+2n | u16 count + n×u16 id list (MISS01: ids 135–141)        | INFERRED  |
| 19   | 8    | —                                                      | unknown   |
| 20,21| 10   | —                                                      | unknown   |
| 22   | 1/13 | **touch trigger** — §4.5 (13B form when first byte=1)  | CONFIRMED |
| 23   | 25   | **sprite state/animation frame** (no position) — §4.3  | INFERRED  |

### 4.3 Type 8 — sprite placement  (CONFIRMED, 14/14 switch pins)

33-byte payload:

```
bytes 0–9    ASCIIZ sprite filename (10-byte field), e.g. "LOCK2.S16"
bytes 10–11  u16 param (varies per sprite kind: LIGHT1=5952, LOCK2=16402,
             LOCK4=4672, LOCK6=10049 — scale/animation?)
bytes 12–23  3 × i32 raw coords;  world = (−x/256, y/256, z/256)
bytes 24–32  u16 ≈4096|16, u16 0, u16 ≈32512|127, u16 0, 1 byte
             (16/127 on lights — radius/intensity?; 4096/32512 on locks)
```

**Sprite catalog** (all `.S16` files, observed MISS01–13):

| sprite              | meaning                              | map class |
|---------------------|--------------------------------------|-----------|
| LOCK2 / LOCK4 / LOCK6 | wall switch panels (mall, complex) | switch    |
| SERV1 / SERV2       | server/console switches (MISS05)     | switch    |
| BIGLOCK             | big lock panel                       | switch    |
| SCLICK / SCLUNK     | click/clunk panels (sewers MISS08)   | switch    |
| LIGHT1              | hanging ceiling light                | ambient   |
| DRIP1–DRIP5         | water drips (sewers)                 | ambient   |
| STEAM1–STEAM6       | steam jets                           | ambient   |
| SENGINE             | engine (sound emitter?)              | ambient   |
| TELEPRT2            | teleporter effect                    | ambient   |
| STONEDOR / SBIGDOOR / SDOORCLS / BIGDORR | door sprites    | door      |

Validation: every LOCK position matched a user-placed "Switch" pin at
d = 103–155 units (MISS05 14/14; MISS07 LOCK2/LOCK4/LOCK6 groups matched the
switch pins including the three stacked generator switches at y 225/1775/3315).

Type 23 (25 bytes) is the same filename header + params but **without**
coordinates — animation/state frames attached to the parent group (e.g. the
MISS07 front-door group holds BIGDORR.S16/BIGLOCK.S16 frames with hdr2
0/10/60/140/180 — timing offsets?).

### 4.4 Type 3 — move action  (CONFIRMED)

42-byte payload:

```
i16 @0   target id  = index into the sub_50B30 movable table (§2)
i16 @2   sub-part   (front door uses subs 0–4 = five panels)
i32 @4   secondary param (axis/speed? −62 on MISS01, 0 on MISS07)
i32 @8   signed move delta (e.g. ±700, ±840, −693, +1823, +2603)
rest     constant-looking [1,0,1,0,1,0...]
```

When the group's condition becomes true, each type-3 moves its target by
delta — this is the entire "switch opens door" mechanism. Doors that
"open elsewhere" are exactly the type-3 targets (user pin "Gates (opens
elsewhere)" = target rec 239, MISS05).

### 4.5 Type 22 — touch trigger  (CONFIRMED, with caveat)

1 byte (flag=0 form) or 13 bytes (flag=1): `u8 flag` + 3 × i32 **direct**
world coords (y always 0 — an XZ trigger column). Used for sprite-less
switches (MISS01 city switches are bare wall textures + touch triggers).

Caveat: z matched user switch pins to 1–300 units, but **x reads ~4500–4800
low** on all three verified MISS01 triggers — the stored point is likely a
corner of a trigger *volume*, not its center. Treat x as approximate.

---

## 5. Coordinate transforms (summary)

| source                        | world transform                  |
|-------------------------------|----------------------------------|
| zone pool verts               | world = header_origin + local, x negated (README) |
| type-8 sprite placement       | (−x/256, y/256, z/256)           |
| sub_50B30 movable record      | (−x, y, z) — already world units |
| type-22 touch trigger         | (−x, y, z) — x ~4500 low (volume corner?) |
| live memory structs (runtime) | (−x/256, y/256, z/256)           |
| automap marker pins           | player position when dropped (≈100–600 units from the object) |

---

## 6. Per-level extraction results (extract_logic.py)

| level  | switches | remote doors | logic groups | notes                     |
|--------|----------|--------------|--------------|---------------------------|
| MISS01 | 5        | 4            | 6            | 4 switches + force field  |
| MISS04 | 0        | 0            | 0            | no scripted objects       |
| MISS05 | 20       | 53           | 74           | LOCK2 ×18 + SERV ×8 (grouped) |
| MISS06 | 4        | 2            | 5            |                           |
| MISS07 | 8        | 24           | 107          | mall: front door + generator |
| MISS08 | 26       | 41           | 60           | sewers: SCLICK/SCLUNK panels |
| MISS09 | 7        | 60           | 63           |                           |
| MISS10 | 11       | 63           | 74           |                           |
| MISS11 | 2        | 6            | 51           |                           |
| MISS12 | 0        | 7            | 29           | doors but no switch sprites |
| MISS13 | 0        | 0            | 0            | boss arena                |

Output: `data/MISSxx_logic.json` — `switches` (position, sprite, condition
string, actions), `doors` (type-3 targets + positioned door sprites),
`groups` (raw tokens + records for further RE).

---

## 7. Runtime memory (live automap layer)

All offsets are CauseWay flat-DS; host = phys0 + 0x18C000 + offset
(see notes v83/v85 for base discovery).

### Scan windows

| window  | flat offset | size     | content                          |
|---------|-------------|----------|----------------------------------|
| NPC_WIN | 0xCF000     | 0x4000   | NPC/creature structs, stride 0x234 |
| OBJ_WIN | 0x157000    | **0x38000** | object array, stride 0xA0     |

**Pitfall (session 87):** OBJ_WIN was 0x16000 and MISS05's object array runs
past 0x16D000 — 24 pickups (incl. a quest container) were invisible on the
map. Pickups confirmed up to flat 0x1748xx; window now ends 0x18F000.

### Object struct (fields relative to the zone/x/y/z block at +0)

```
−0x10  u16  class
+0x00  i32  zone index
+0x04  i32  x raw (world = −x/256)
+0x08  i32  y raw (/256)
+0x0C  i32  z raw (/256)
+0x52  u16  item-type id (pickups)
+0x86  u16  sprite frame
```

### Classes observed (MISS05/MISS07 live)

| class | meaning                                             | status    |
|-------|-----------------------------------------------------|-----------|
| 39    | pickup (sprite frame 87/88)                         | CONFIRMED |
| 1025  | static scenery: explosive barrels (frames 120–128, animating), ceiling lamps, vending machines | CONFIRMED |
| 2087  | decal (skip)                                        | CONFIRMED |
| 33280 | n=60 on MISS05 — suspected door/movable instances   | suspect   |
| 35, 34, 47, 166/167 (oscillates), 175, 4135, 4143, 6183 | unknown | —    |

### Item-type ids (engine-global, at +0x52)

| id | item                | source                          |
|----|---------------------|---------------------------------|
| 63 | Uzi                 | session 85                      |
| 64 | Shotgun             | user-named, confirmed           |
| 66 | Plasma blaster      | user-named (s87)                |
| 67 | Shredder multi-cannon | user-named (s87)              |
| 70 | Shotgun shells      | session 85, pin-confirmed s87   |
| 71 | Uzi clip            | session 85, pin-confirmed s87   |
| 72 | Shredder pack       | session 85                      |
| 73 | Scavenger rockets   | session 85                      |
| 75 | Inferno canister    | session 85                      |
| 78 | Battery             | session 85                      |
| 80 | Medkit 25%          | user-named (s87)                |
| 81 | Medkit 50%          | user-named, pin-confirmed s87   |
| 84 | Scanner (upgrade)   | session 85, pin-confirmed s87   |
| 91 | Quest container     | pin-correlated s87 (165 units)  |
| **82, 88** | **unknown**  | seen live, not yet identified   |

---

## 8. Worked example — MISS07 mall front door

From `MISS07_logic.json` / `session_87/lock_groups.py`:

```
grp 31  id 22:  LOCK4.S16 switch at (−10080, −1679, 41581)
grp 32  id 23:  LOCK4.S16 switch at (−10080, −1680, 42560)
grp 20  ids [25, 24]                       (third required trigger pair)
grp 27  id 66:  LOCK6.S16 at (−1420, 3315, 655)  ┐ generator
grp 28  id 67:  LOCK6.S16 at (−1420, 1775, 655)  │ switches
grp 29  id 68:  LOCK6.S16 at (−1420,  225, 665)  ┘ (stacked vertically)
grp 30  condition [66, 67, 68]             (building lights / enable)
grp 23  condition ( T22 AND ( T23 AND T25 ) ):
        LOCK4.S16 switch at (−8260, 140, −1399)   <- main entrance
        5 × type-3: move object 237 sub 0–4 by −693 (five door panels)
        BIGDORR.S16 / BIGLOCK.S16 type-23 animation frames
```

## 9. Tooling index

| tool                                | purpose                                  |
|-------------------------------------|------------------------------------------|
| `extract_logic.py MISSxx [outdir]`  | canonical logic extractor → `_logic.json` |
| `parse_entities.py MISSxx`          | raw post-zone walk + type histogram      |
| `session_87/lock_groups.py`         | full dump of sprite-bearing groups       |
| `session_87/dump_groups_full.py`    | every record of every group              |
| `session_87/match_doors*.py`        | pin-vs-record validation                 |
| `session_87/wide_scan.py`           | live wide-memory pickup scan             |
| `session_87/census_objwin.py`       | live object-window class census          |
| `session_87/probe_missing_item.py`  | "why is this item not on the map" probe  |
