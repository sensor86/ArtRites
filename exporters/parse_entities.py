"""Parse CLF post-zone data: sub_50B30 / sub_50C00 / sub_50DC4 (entities) / sub_511DC.
Skip logic transcribed 1:1 from LR_Exe_disassembly.txt (Hex-Rays, trusted).

Usage: python parse_entities.py MISS01 [--dump N]
"""
import struct, sys, os, json, collections

LEVEL = (sys.argv[1] if len(sys.argv) > 1 else "MISS01").upper()
DUMP = int(sys.argv[sys.argv.index('--dump')+1]) if '--dump' in sys.argv else 3

def u16(d, o): return struct.unpack_from('<H', d, o)[0]
def u32(d, o): return struct.unpack_from('<I', d, o)[0]
def s16(d, o): return struct.unpack_from('<h', d, o)[0]
def s32(d, o): return struct.unpack_from('<i', d, o)[0]

# --- canonical zone walk (same as extract_geo.py) ---------------------------
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
print(f"{LEVEL}: zones end at 0x{p:X}  (file {len(data)} bytes, {len(data)-p} left)")

# --- sub_50B30 ---------------------------------------------------------------
b30_start = p
n1 = u16(data, p); p += 2
b30 = []
for i in range(n1):
    rec16 = data[p:p+16]; p += 16
    n2 = u16(data, p); p += 2
    subs = []
    for j in range(n2):
        sub10 = data[p:p+10]; p += 10
        flags = u32(data, p); p += 4
        extra = None
        if flags & 0x1000:
            extra = u16(data, p); p += 2
        subs.append((sub10, flags, extra))
    b30.append((rec16, subs))
print(f"sub_50B30 @0x{b30_start:X}: {n1} records, {sum(len(s) for _, s in b30)} subrecords -> ends 0x{p:X}")

# --- sub_50C00 ---------------------------------------------------------------
c00_start = p
cnt = u16(data, p); p += 2
SKIP_C00 = {1:4, 4:4, 5:4, 6:4, 2:8, 3:8, 7:4, 8:4, 12:4, 9:6, 11:6, 10:2, 13:4, 14:6}
c00 = []
c00_types = collections.Counter()
for i in range(cnt):
    typ = u32(data, p)
    hdr4 = data[p+4:p+8]
    p += 8
    if typ not in SKIP_C00:
        print(f"  !! sub_50C00 unknown type {typ} at 0x{p-8:X}"); sys.exit(1)
    pay = data[p:p+SKIP_C00[typ]]; p += SKIP_C00[typ]
    c00.append((typ, hdr4, pay))
    c00_types[typ] += 1
print(f"sub_50C00 @0x{c00_start:X}: {cnt} records {dict(sorted(c00_types.items()))} -> ends 0x{p:X}")

# --- sub_50DC4 (entities) ------------------------------------------------------
dc4_start = p
v17 = u16(data, p); p += 2
ent_types = collections.Counter()
entities = []   # (group, type, payload_bytes, offset)
for gi in range(v17):
    m = u16(data, p); p += 2
    for _ in range(m):
        a = u32(data, p); p += 4
        if a < 2: p += 2
    ec = u16(data, p); p += 2
    for ei in range(ec):
        off = p
        typ = u32(data, p)
        hdr2 = u16(data, p+4)
        p += 6
        if typ in (0, 1):
            pay = b''
        elif typ == 2:   pay = data[p:p+6];  p += 6
        elif typ == 3:   pay = data[p:p+42]; p += 42
        elif typ == 4:   pay = data[p:p+16]; p += 16
        elif typ == 5:   pay = data[p:p+3];  p += 3
        elif typ == 6:   pay = data[p:p+3];  p += 3
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
            fl = data[p]
            ln = 13 if fl == 1 else 1
            pay = data[p:p+ln]; p += ln
        elif typ == 23:  pay = data[p:p+25]; p += 25
        else:
            print(f"  !! sub_50DC4 unknown type {typ} at 0x{off:X} group {gi}"); sys.exit(1)
        entities.append((gi, typ, hdr2, pay, off))
        ent_types[typ] += 1
print(f"sub_50DC4 @0x{dc4_start:X}: {v17} groups (n_zones={n_zones}), "
      f"{len(entities)} entities -> ends 0x{p:X}")
print(f"  type histogram: {dict(sorted(ent_types.items()))}")

# --- sub_511DC ----------------------------------------------------------------
dc_start = p
for _ in range(cnt):
    k = u16(data, p); p += 2 + k*2
print(f"sub_511DC @0x{dc_start:X} -> ends 0x{p:X}  (file size {len(data)}, leftover {len(data)-p})")

# --- payload peek ---------------------------------------------------------------
print(f"\n--- payload samples (first {DUMP} per type, as i16 / i32 views) ---")
by_type = collections.defaultdict(list)
for gi, typ, hdr2, pay, off in entities:
    by_type[typ].append((gi, hdr2, pay, off))
for typ in sorted(by_type):
    lst = by_type[typ]
    print(f"type {typ:2d}  x{len(lst)}")
    for gi, hdr2, pay, off in lst[:DUMP]:
        i16s = [s16(pay, k) for k in range(0, len(pay)-1, 2)]
        i32s = [s32(pay, k) for k in range(0, len(pay)-3, 4)]
        print(f"   grp={gi:3d} hdr2={hdr2:5d} @0x{off:X}  i16={i16s[:12]}  i32={i32s[:6]}")
