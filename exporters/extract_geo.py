"""Extract per-zone world-space render geometry (verts + faces) from CLF
for the automap 3D mode. Canonical zone walk from export_obj_transformed.py.

Usage: python extract_geo.py MISS01   →  MISS01_geo.json
"""
import struct, json, sys, os

LEVEL = (sys.argv[1] if len(sys.argv) > 1 else "MISS01").upper()
for d in ('.', '..'):
    p = os.path.join(d, f'{LEVEL}.CLF')
    if os.path.exists(p):
        CLF_PATH = p
        break
else:
    print(f"{LEVEL}.CLF not found"); sys.exit(1)

def u16(d, o): return struct.unpack_from('<H', d, o)[0]
def u32(d, o): return struct.unpack_from('<I', d, o)[0]
def s16(d, o): return struct.unpack_from('<h', d, o)[0]
def s32(d, o): return struct.unpack_from('<i', d, o)[0]

def read_portal(data, ptr):
    iter_start = ptr; ptr += 6
    flag = data[ptr]; ptr += 1
    if flag == 1:
        v5 = u16(data, iter_start + 17)
        ptr = iter_start + 19 + v5 * 2
    return ptr

def read_poly(data, ptr, e523c):
    vcnt = data[ptr]; ptr += 1
    indices = [u16(data, ptr + j*2) for j in range(vcnt)]
    ptr += vcnt * 2
    v2 = u32(data, ptr); ptr += 7
    if v2 & 4: ptr += 6 + vcnt * 4
    ptr += vcnt * e523c
    return ptr, vcnt, indices

def read_poly_nolm(data, ptr):
    vcnt = data[ptr]; ptr += 1
    ptr += vcnt * 2
    v2 = u32(data, ptr); ptr += 7
    if v2 & 4: ptr += 6 + vcnt * 4
    return ptr

def read_sub_50528(data, ptr):
    while True:
        v0 = ptr + 2
        result = u16(data, ptr); ptr += 2
        if result == 0:
            ptr = v0 + 2; break
        ptr += result * 6
        v2 = u16(data, ptr); ptr += 2
        ptr += v2 * 6
        ptr = read_sub_50528(data, ptr)
    return ptr

def read_sub_50790(data, ptr, e523c):
    ptr += 20
    count_a = u16(data, ptr); ptr += 2
    ptr += count_a * 6
    count_b = u16(data, ptr); ptr += 2
    for _ in range(count_b): ptr = read_portal(data, ptr)
    count_c = u16(data, ptr); ptr += 2
    for _ in range(count_c): ptr = read_poly_nolm(data, ptr)
    return read_sub_50528(data, ptr)

def read_zone(data, ptr):
    hx = s32(data, ptr); hy = s32(data, ptr + 4); hz = s32(data, ptr + 8)
    ptr += 18
    lvc = u16(data, ptr); ptr += 4
    pool_start = ptr
    ptr += lvc * 6
    verts = []
    for i in range(lvc):
        lx = s16(data, pool_start + i*6)
        ly = s16(data, pool_start + i*6 + 2)
        lz = s16(data, pool_start + i*6 + 4)
        verts.append((-(hx + lx), hy + ly, hz + lz))
    raw_pc = u16(data, ptr)
    high = (raw_pc >> 8) & 0xFF
    pc = high if high else (raw_pc & 0x01FF)
    ptr += 2
    for _ in range(pc): ptr = read_portal(data, ptr)
    e523c = u16(data, ptr); ptr += 2
    if e523c > 0:
        ptr += 2 + e523c * 2 + e523c * 4
    n_polys = u16(data, ptr); ptr += 2
    faces = []
    for _ in range(n_polys):
        ptr, vcnt, indices = read_poly(data, ptr, e523c)
        faces.append(indices)
    v11 = u16(data, ptr); ptr += 2
    for _ in range(v11):
        v12 = data[ptr]; ptr += 1
        ptr += v12 * 2 + 2 + 1
    ptr = read_sub_50528(data, ptr)
    v14 = u16(data, ptr); ptr += 2
    for _ in range(v14): ptr = read_sub_50790(data, ptr, e523c)
    result = u16(data, ptr); ptr += 2
    ptr += result * 20
    return ptr, verts, faces

data = open(CLF_PATH, 'rb').read()
n_zones = u16(data, 0x20)
ptr = 0x2A
out = []
nf = 0
for zi in range(n_zones):
    try:
        ptr, verts, faces = read_zone(data, ptr)
    except Exception as e:
        print(f"Zone {zi} ERROR at 0x{ptr:X}: {e}")
        break
    # keep faces with valid indices only; winding reversed (X negation flips handedness)
    ok = [list(reversed(f)) for f in faces if all(i < len(verts) for i in f)]
    nf += len(ok)
    out.append({'index': zi, 'verts': [list(v) for v in verts], 'faces': ok})

dest = f'{LEVEL}_geo.json'
with open(dest, 'w') as f:
    json.dump({'level': LEVEL, 'zones': out}, f, separators=(',', ':'))
print(f"Saved {dest}: {len(out)} zones, {nf} faces, {os.path.getsize(dest)//1024} KB")
