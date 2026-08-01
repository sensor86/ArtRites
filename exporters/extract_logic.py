"""Extract interactive-object logic from a CLF: switches (type-8 LOCK sprites,
world positions), movable objects/doors (sub_50B30 records referenced by type-3
move actions), and the trigger wiring between them (group header conditions).

Confirmed facts (session 87, MISS07 vs user's hand-placed pins):
  - sub_50DC4 type 8 payload (33B) = sprite placement: ASCIIZ filename in the
    first 10 bytes, then u16 param, then 3x i32 raw coords at bytes 12/16/20;
    world = (-x/256, y/256, z/256). LOCKx.S16 = wall switches (3/3 matched),
    LIGHT1.S16 = hanging lights.
  - sub_50B30 record16 = movable object: u16 field, then 3x i32 at bytes 2/6/10
    ALREADY in world units, world = (-x, y, z) (20/21 door pins matched).
  - sub_50DC4 type 3 payload (42B) = action: i16[0] target id (index into
    sub_50B30 table), i16[1] sub-part, i32 @8 = signed move delta.
  - group headers: list of (a, b) tokens; a==0/1 -> operand trigger id b,
    a>=2 -> operator token (boolean wiring, e.g. MISS07 front door = three
    LOCK4 switch ids AND-ed). Raw tokens are preserved in the JSON.

Usage: python extract_logic.py MISS07 [outdir]
"""
import struct, sys, os, json
sys.stdout.reconfigure(encoding='utf-8')

LEVEL = (sys.argv[1] if len(sys.argv) > 1 else "MISS07").upper()
OUTDIR = sys.argv[2] if len(sys.argv) > 2 else '.'

def u16(d, o): return struct.unpack_from('<H', d, o)[0]
def u32(d, o): return struct.unpack_from('<I', d, o)[0]
def s16(d, o): return struct.unpack_from('<h', d, o)[0]
def s32(d, o): return struct.unpack_from('<i', d, o)[0]

# --- canonical zone walk (sub_508D4 family — see parse_entities.py) ----------
def read_portal(d, p):
    st = p; p += 6
    fl = d[p]; p += 1
    if fl == 1:
        p = st + 19 + u16(d, st+17) * 2
    return p

def read_poly(d, p, e):
    vc = d[p]; p += 1 + vc*2
    v2 = u32(d, p); p += 7
    if v2 & 4: p += 6 + vc*4
    return p + vc*e

def read_poly_nolm(d, p):
    vc = d[p]; p += 1 + vc*2
    v2 = u32(d, p); p += 7
    if v2 & 4: p += 6 + vc*4
    return p

def read_50528(d, p):
    while True:
        v0 = p + 2
        r = u16(d, p); p += 2
        if r == 0:
            return v0 + 2
        p += r*6
        v2 = u16(d, p); p += 2
        p += v2*6
        p = read_50528(d, p)

def read_50790(d, p, e):
    p += 20
    ca = u16(d, p); p += 2 + ca*6
    cb = u16(d, p); p += 2
    for _ in range(cb): p = read_portal(d, p)
    cc = u16(d, p); p += 2
    for _ in range(cc): p = read_poly_nolm(d, p)
    return read_50528(d, p)

def read_zone(d, p):
    p += 18
    lvc = u16(d, p); p += 4 + lvc*6
    raw = u16(d, p); p += 2
    hi = (raw >> 8) & 0xFF
    pc = hi if hi else (raw & 0x1FF)
    for _ in range(pc): p = read_portal(d, p)
    e = u16(d, p); p += 2
    if e > 0: p += 2 + e*2 + e*4
    npo = u16(d, p); p += 2
    for _ in range(npo): p = read_poly(d, p, e)
    v11 = u16(d, p); p += 2
    for _ in range(v11):
        v12 = d[p]; p += 1 + v12*2 + 3
    p = read_50528(d, p)
    v14 = u16(d, p); p += 2
    for _ in range(v14): p = read_50790(d, p, e)
    res = u16(d, p); p += 2 + res*20
    return p

data = open(f'{LEVEL}.CLF', 'rb').read()
n_zones = u16(data, 0x20)
p = 0x2A
for zi in range(n_zones):
    p = read_zone(data, p)

# --- sub_50B30: movable-object table -----------------------------------------
n1 = u16(data, p); p += 2
b30 = []
for i in range(n1):
    rec16 = data[p:p+16]; p += 16
    n2 = u16(data, p); p += 2
    for j in range(n2):
        p += 10
        flags = u32(data, p); p += 4
        if flags & 0x1000: p += 2
    b30.append(rec16)

def b30_pos(rid):
    r = b30[rid]
    x = struct.unpack_from('<i', r, 2)[0]
    y = struct.unpack_from('<i', r, 6)[0]
    z = struct.unpack_from('<i', r, 10)[0]
    return (-x, y, z)

# --- sub_50C00 ----------------------------------------------------------------
cnt = u16(data, p); p += 2
SKIP_C00 = {1:4, 4:4, 5:4, 6:4, 2:8, 3:8, 7:4, 8:4, 12:4, 9:6, 11:6, 10:2, 13:4, 14:6}
for i in range(cnt):
    typ = u32(data, p); p += 8 + SKIP_C00[typ]

# --- sub_50DC4 groups ----------------------------------------------------------
v17 = u16(data, p); p += 2
groups = []
for gi in range(v17):
    m = u16(data, p); p += 2
    hdrs = []
    for _ in range(m):
        a = u32(data, p); p += 4
        b = None
        if a < 2:
            b = u16(data, p); p += 2
        hdrs.append((a, b))
    ec = u16(data, p); p += 2
    ents = []
    for ei in range(ec):
        typ = u32(data, p); hdr2 = u16(data, p+4); p += 6
        if typ in (0, 1): pay = b''
        elif typ == 2:   pay = data[p:p+6];  p += 6
        elif typ == 3:   pay = data[p:p+42]; p += 42
        elif typ == 4:   pay = data[p:p+16]; p += 16
        elif typ in (5, 6): pay = data[p:p+3]; p += 3
        elif typ == 7:   pay = data[p:p+4];  p += 4
        elif typ == 8:   pay = data[p:p+33]; p += 33
        elif typ == 9:   pay = data[p:p+4];  p += 4
        elif typ == 10:  pay = data[p:p+16]; p += 16
        elif typ in (11, 13): pay = data[p:p+8]; p += 8
        elif typ == 12:  pay = data[p:p+6];  p += 6
        elif typ == 14:  pay = data[p:p+8];  p += 8
        elif typ == 15:  pay = data[p:p+14]; p += 14
        elif typ == 16:  pay = data[p:p+2];  p += 2
        elif typ == 17:  pay = data[p:p+5];  p += 5
        elif typ == 18:
            n = u16(data, p); pay = data[p:p+2+n*2]; p += 2 + n*2
        elif typ == 19:  pay = data[p:p+8];  p += 8
        elif typ in (20, 21): pay = data[p:p+10]; p += 10
        elif typ == 22:
            fl = data[p]; ln = 13 if fl == 1 else 1
            pay = data[p:p+ln]; p += ln
        elif typ == 23:  pay = data[p:p+25]; p += 25
        else:
            raise SystemExit(f"unknown dc4 type {typ}")
        ents.append((typ, hdr2, pay))
    groups.append((hdrs, ents))

# --- build logic model ----------------------------------------------------------
def fname(pay):
    e = pay.find(b'\0')
    return pay[:e if e >= 0 else len(pay)].decode('ascii', 'replace')

def cond_str(tokens):
    """Header tokens -> readable boolean expr. a: 0/1 operand, 2 '(', 3 ')',
    4 AND (parses to balanced exprs on MISS01 grp4 + MISS07 grp23)."""
    out = []
    for a, b in tokens:
        if b is not None:
            out.append(f"T{b}")
        else:
            out.append({2: '(', 3: ')', 4: 'AND'}.get(a, f'op{a}'))
    return ' '.join(out)

switches = []
sprite_doors = []
door_ids = set()
glog = []
for gi, (hdrs, ents) in enumerate(groups):
    own_ids = [b for (a, b) in hdrs if b is not None]
    tokens = [[a, b] for (a, b) in hdrs]
    sprites, actions, refs, trigpts = [], [], [], []
    for typ, hdr2, pay in ents:
        if typ == 8:
            f = fname(pay)
            x, y, z = struct.unpack_from('<3i', pay, 12)
            sprites.append({'file': f, 'x': -x/256.0, 'y': y/256.0, 'z': z/256.0})
        elif typ == 22 and len(pay) == 13:
            # touch-trigger column: fl + x,y,z i32, already world units
            # (z matched MISS01 switch pins to <300 units; x reads ~4500 low —
            # likely a volume corner, close enough for map display)
            x, y, z = struct.unpack_from('<3i', pay, 1)
            trigpts.append({'x': -x, 'y': y, 'z': z})
        elif typ == 3:
            tgt, sub = s16(pay, 0), s16(pay, 2)
            delta = s32(pay, 8)
            a = {'target': tgt, 'sub': sub, 'delta': delta}
            if 0 <= tgt < len(b30):
                wx, wy, wz = b30_pos(tgt)
                a.update({'tx': wx, 'ty': wy, 'tz': wz})
                door_ids.add(tgt)
            actions.append(a)
        elif typ in (5, 6):
            refs.append(s16(pay, 0))
    # sprite classification: ambient effects are not interactive; *DOR*/DOOR
    # sprites are the doors themselves (positioned); LOCK/SERV/SCLICK/… panels
    # are switches. One switch entry per group (a group may carry the panel
    # sprite plus its click/clunk sound sprites at the same spot).
    AMBIENT = ('LIGHT', 'DRIP', 'STEAM', 'SENGINE', 'TELEPRT', 'FLAME', 'SMOKE')
    sw_sprite = None
    for s in sprites:
        up = s['file'].upper()
        if up.startswith(AMBIENT):
            continue
        if 'DOR' in up or 'DOOR' in up:
            sprite_doors.append({'id': None, 'file': s['file'],
                                 'x': s['x'], 'y': s['y'], 'z': s['z'],
                                 'group': gi})
            continue
        if sw_sprite is None or up.startswith(('LOCK', 'SERV', 'BIGLOCK')):
            if not (sw_sprite and sw_sprite['file'].upper()
                    .startswith(('LOCK', 'SERV', 'BIGLOCK'))):
                sw_sprite = s
    if sw_sprite is not None:
        switches.append({'group': gi, 'ids': own_ids, 'file': sw_sprite['file'],
                         'x': sw_sprite['x'], 'y': sw_sprite['y'],
                         'z': sw_sprite['z'],
                         'actions': actions, 'cond': cond_str(tokens)})
    elif trigpts and (actions or own_ids):
        # sprite-less switch (MISS01 style): use the touch-trigger point
        t = trigpts[0]
        switches.append({'group': gi, 'ids': own_ids, 'file': 'trigger',
                         'x': t['x'], 'y': t['y'], 'z': t['z'],
                         'actions': actions, 'cond': cond_str(tokens)})
    if sprites or actions or trigpts or len(hdrs) > 1:
        glog.append({'group': gi, 'tokens': tokens, 'cond': cond_str(tokens),
                     'sprites': sprites, 'trigpts': trigpts,
                     'actions': actions, 'refs': refs})

# --- resolve indirect trigger chains (LOCK2-style: switch sets T(N) via
# type-5/6 refs; a separate automated group fires on T(N) and moves doors).
# Build: trigger_id -> list of groups that have it as a condition.
# Each group is stored as (own_ids, ents) from the original parse.
_trig_to_groups = {}
for gi2, (hdrs2, ents2) in enumerate(groups):
    cond_ids = {b for (a, b) in hdrs2 if b is not None}
    own_ids2 = [b for (a, b) in hdrs2 if b is not None and a == 0]
    # Collect this group's type-3 moves
    g_moves = []
    for typ2, hdr2_2, pay2 in ents2:
        if typ2 == 3:
            tgt2 = s16(pay2, 0); delta2 = s32(pay2, 8)
            a2 = {'target': tgt2, 'sub': s16(pay2, 2), 'delta': delta2}
            if 0 <= tgt2 < len(b30):
                wx2, wy2, wz2 = b30_pos(tgt2)
                a2.update({'tx': wx2, 'ty': wy2, 'tz': wz2})
            g_moves.append(a2)
    for tid in cond_ids:
        _trig_to_groups.setdefault(tid, []).append({
            'gi': gi2, 'own_ids': own_ids2, 'cond_ids': cond_ids, 'moves': g_moves
        })

# For switches that have no direct type-3 actions (LOCK2 indirect style),
# follow their refs to find the actuated door groups.
for sw in switches:
    if sw['actions']:
        continue  # already has direct moves
    # Find refs for this switch's group from glog
    gl = next((g for g in glog if g['group'] == sw['group']), None)
    if gl is None:
        continue
    sw_own = set(sw['ids'])
    indirect = []
    for ref_tid in gl.get('refs', []):
        if ref_tid in sw_own:
            continue  # skip self-arming refs
        for actor in _trig_to_groups.get(ref_tid, []):
            if actor['gi'] == sw['group']:
                continue
            for mv in actor['moves']:
                indirect.append(dict(mv, via_trigger=ref_tid))
                if 'target' in mv:
                    door_ids.add(mv['target'])
    if indirect:
        sw['actions'] = indirect

doors = []
for rid in sorted(door_ids):
    wx, wy, wz = b30_pos(rid)
    doors.append({'id': rid, 'x': wx, 'y': wy, 'z': wz})
doors += sprite_doors

out = {'level': LEVEL, 'switches': switches, 'doors': doors, 'groups': glog}
path = os.path.join(OUTDIR, f'{LEVEL}_logic.json')
with open(path, 'w') as f:
    json.dump(out, f, indent=1)

print(f"{LEVEL}: {len(switches)} switches, {len(doors)} movable targets, "
      f"{len(glog)} logic groups -> {path}")
for s in switches:
    acts = ', '.join(f"obj{a['target']}{'' if 'tx' not in a else ' @(%d,%d,%d)' % (a['tx'], a['ty'], a['tz'])} d={a['delta']}"
                     for a in s['actions']) or '(via trigger ids %s)' % s['ids']
    print(f"  [{s['file']:11s}] grp{s['group']:3d} ids={s['ids']} "
          f"({s['x']:7.0f},{s['y']:6.0f},{s['z']:7.0f})  -> {acts}")
