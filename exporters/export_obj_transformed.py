#!/usr/bin/env python3
"""Export CLF with zone header as world-space tile origin + pool verts as local offset.
Import in Blender: Up=Y, scale=0.01 (or 1.0 if using baked scale below).
"""
import struct, sys

CLF_PATH = sys.argv[1] if len(sys.argv) > 1 else "MISS04.CLF"
OBJ_PATH = CLF_PATH.replace(".CLF", "_world.obj")

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
    zone_start = ptr

    # decode 18-byte zone header for world position
    hx = s32(data, ptr)
    hy = s32(data, ptr + 4)
    hz = s32(data, ptr + 8)
    ptr += 18

    lvc = u16(data, ptr); ptr += 4
    pool_start = ptr
    ptr += lvc * 6

    # pool verts as local coords; world = header + local; negate X to match game orientation
    verts = []
    for i in range(lvc):
        lx = s16(data, pool_start + i*6)
        ly = s16(data, pool_start + i*6 + 2)
        lz = s16(data, pool_start + i*6 + 4)
        wx = -(hx + lx)
        wy = hy + ly
        wz = hz + lz
        verts.append((wx, wy, wz))

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

    return ptr, verts, faces, (hx, hy, hz)

with open(CLF_PATH, 'rb') as f:
    data = bytearray(f.read())

fsize = len(data)
n_zones = u16(data, 0x20)
print(f"{CLF_PATH}: {fsize} bytes, {n_zones} zones")

vert_map = {}
vert_list = []
all_faces = []

def get_vidx(v):
    if v not in vert_map:
        vert_map[v] = len(vert_list) + 1
        vert_list.append(v)
    return vert_map[v]

ptr = 0x2A
for zi in range(n_zones):
    try:
        ptr, verts, faces, origin = read_zone(data, ptr)
    except Exception as e:
        print(f"Zone {zi} ERROR at 0x{ptr:X}: {e}")
        break
    for face in faces:
        obj_face = [get_vidx(verts[i]) for i in reversed(face)]
        all_faces.append(obj_face)

print(f"Final ptr: 0x{ptr:X}  remaining: {fsize-ptr} bytes")
print(f"Vertices: {len(vert_list)}  Faces: {len(all_faces)}")

if vert_list:
    xs = [v[0] for v in vert_list]
    ys = [v[1] for v in vert_list]
    zs = [v[2] for v in vert_list]
    print(f"World X: [{min(xs)}, {max(xs)}] = [{min(xs)*0.01:.1f}, {max(xs)*0.01:.1f}]m")
    print(f"World Y: [{min(ys)}, {max(ys)}] = [{min(ys)*0.01:.1f}, {max(ys)*0.01:.1f}]m")
    print(f"World Z: [{min(zs)}, {max(zs)}] = [{min(zs)*0.01:.1f}, {max(zs)*0.01:.1f}]m")

with open(OBJ_PATH, 'w') as f:
    f.write(f"# {CLF_PATH} geometry with zone header transform  zones={n_zones}\n")
    f.write(f"# {len(vert_list)} verts  {len(all_faces)} faces\n")
    f.write(f"o {CLF_PATH.split('.')[0]}_world\n")
    for x, y, z in vert_list:
        f.write(f"v {x*0.01:.4f} {y*0.01:.4f} {z*0.01:.4f}\n")
    for face in all_faces:
        f.write("f " + " ".join(str(i) for i in face) + "\n")
print(f"Written {OBJ_PATH}")
