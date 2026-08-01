#!/usr/bin/env python3
"""
export_textured_v25.py — double-height + partial-UV fix for portal textures.

Many textures have wm_v=63 (portal height=64) but the atlas stores 128px of
real content. The polygon UV reaches exactly 128 = 2*(wm_v+1), revealing the
intent. Fix: two-pass CLF walk — pass 1 finds max_uy per descriptor; for any
desc where max_uy == 2*(wm_v+1), use h=128 for both PNG extraction and UV
normalisation, eliminating the unwanted 2x vertical tiling.

v22 changes: + RGBA transparency (index 0 = alpha 0)
v23 changes: + double-height detection for 23 descriptors in MISS01
v24 changes: + DESC_TBL map extended to MISS06/07/08 (reverted partial-UV clamp)

Usage: python session_50/export_textured_v25.py [CLF] [LIF]
"""
import struct, sys, os
from PIL import Image

CLF_PATH = sys.argv[1] if len(sys.argv) > 1 else "MISS04.CLF"
LIF_PATH = sys.argv[2] if len(sys.argv) > 2 else "MISS04.LIF"
LEVEL = CLF_PATH.rsplit(".", 1)[0]
OUT_DIR = "session_50"
TEX_DIR = os.path.join(OUT_DIR, f"{LEVEL}_v25_textures")
os.makedirs(TEX_DIR, exist_ok=True)

def u16(d,o): return struct.unpack_from("<H",d,o)[0]
def u32(d,o): return struct.unpack_from("<I",d,o)[0]
def s16(d,o): return struct.unpack_from("<h",d,o)[0]
def s32(d,o): return struct.unpack_from("<i",d,o)[0]

# ── LIF ─────────────────────────────────────────────────────────────────────────

with open(LIF_PATH, "rb") as f: lif = bytearray(f.read())

E50CC   = 62
ATLAS_B = 0x5070C
ATLAS_W = 256
PAL_OFF = 0x50000

_DESC_TBL_MAP = {
    "MISS01": 0x39A20C,
    "MISS04": 0x33C00C,
    "MISS06": 0x34C70C,
    "MISS07": 0x3F980C,
    "MISS08": 0x3ABC0C,
}
_key = next((k for k in _DESC_TBL_MAP if k in LIF_PATH.upper()), None)
if _key:
    DESC_TBL = _DESC_TBL_MAP[_key]
else:
    for cand in sorted(_DESC_TBL_MAP.values()):
        try:
            cnt = u32(lif, cand)
            if 10 < cnt < 2000:
                DESC_TBL = cand; break
        except Exception: pass
    else:
        raise RuntimeError("Cannot determine DESC_TBL for this LIF")

pal = []
for i in range(256):
    r = (lif[PAL_OFF + i*3    ] & 0x3F) << 2
    g = (lif[PAL_OFF + i*3 + 1] & 0x3F) << 2
    b = (lif[PAL_OFF + i*3 + 2] & 0x3F) << 2
    a = 0 if i == 0 else 255
    pal.append((r, g, b, a))

desc_count = u32(lif, DESC_TBL)
print(f"{LIF_PATH}: {len(lif)} bytes, {desc_count} descriptors")

atlas_total_rows = (len(lif) - ATLAS_B) // ATLAS_W

def get_desc_atlas(desc_id):
    if desc_id >= desc_count: return None
    ptr2 = u32(lif, DESC_TBL + 4 + desc_id * 4)
    if ptr2 < 0x100 or ptr2 + 8 > len(lif): return None
    atlas_off = u32(lif, ptr2 + 4)
    if atlas_off < ATLAS_B: return None
    d = atlas_off - ATLAS_B
    return d // ATLAS_W, d % ATLAS_W

def extract_desc_png(desc_id, wm_u, actual_h):
    """Extract tile as RGBA PNG using actual_h (may be 2*(wm_v+1)). Returns (fname, has_alpha)."""
    rc = get_desc_atlas(desc_id)
    if not rc: return None, False
    row, col = rc
    w = wm_u + 1
    h = min(actual_h, atlas_total_rows - row)
    if h <= 0 or w <= 0: return None, False
    img = Image.new("RGBA", (w, h))
    px = img.load()
    has_alpha = False
    for y in range(h):
        for x in range(w):
            atlas_col = (col + x) % ATLAS_W
            off = ATLAS_B + (row + y) * ATLAS_W + atlas_col
            if off < len(lif):
                idx = lif[off]
                px[x, y] = pal[idx]
                if idx == 0:
                    has_alpha = True
    fname = f"desc_{desc_id:03d}.png"
    img.save(os.path.join(TEX_DIR, fname))
    return fname, has_alpha

# ── CLF helpers ─────────────────────────────────────────────────────────────────

def read_portal_data(data, ptr):
    s = ptr
    raw_tex = u16(data, s)
    wm_v    = u16(data, s + 2) & 0xFF
    wm_u    = u16(data, s + 4) & 0xFF
    fl = data[s + 6]; ptr = s + 7
    if fl == 1:
        v5 = u16(data, s + 17); ptr = s + 19 + v5 * 2
    return ptr, raw_tex, wm_u, wm_v

def skip_portal(data, ptr):
    s = ptr; fl = data[ptr+6]; ptr += 7
    if fl == 1:
        v5 = u16(data, s + 17); ptr = s + 19 + v5 * 2
    return ptr

def skip_bsp(data, ptr):
    while True:
        result = u16(data, ptr); ptr += 2
        if result == 0: return ptr + 2
        ptr += result * 6
        v2b = u16(data, ptr); ptr += 2; ptr += v2b * 6
        ptr = skip_bsp(data, ptr)

def read_poly_nolm(data, ptr):
    vcnt = data[ptr]; ptr += 1; ptr += vcnt * 2
    v2 = u32(data, ptr); ptr += 7
    if v2 & 4: ptr += 6 + vcnt * 4
    return ptr

def clf_walk(data, n_zones, on_portal, on_face):
    """Generic CLF zone walk. Calls on_portal(raw_tex, wm_u, wm_v, zone_k)
    and on_face(zone_i, portal_map, vcnt, idxs, v2, tid, face_uvs, hx,hy,hz, pool)."""
    ptr = 0x2A
    for zi in range(n_zones):
        hx = s32(data, ptr); hy = s32(data, ptr+4); hz = s32(data, ptr+8)
        ptr += 18
        lvc = u16(data, ptr); ptr += 4
        pool = []
        for i in range(lvc):
            lx = s16(data, ptr + i*6)
            ly = s16(data, ptr + i*6 + 2)
            lz = s16(data, ptr + i*6 + 4)
            pool.append((-(hx + lx), hy + ly, hz + lz))
        ptr += lvc * 6
        raw_pc = u16(data, ptr)
        high = (raw_pc >> 8) & 0xFF
        pc = high if high else (raw_pc & 0x01FF)
        ptr += 2
        portal_map = {}
        for k in range(pc):
            ptr, raw_tex, wm_u, wm_v = read_portal_data(data, ptr)
            did = raw_tex + E50CC
            on_portal(did, wm_u, wm_v)
            portal_map[k] = (did, wm_u, wm_v)
        e523c = u16(data, ptr); ptr += 2
        if e523c > 0:
            ptr += 2 + e523c * 2 + e523c * 4
        n_polys = u16(data, ptr); ptr += 2
        for _ in range(n_polys):
            vcnt = data[ptr]; ptr += 1
            idxs = [u16(data, ptr + j*2) for j in range(vcnt)]
            ptr += vcnt * 2
            v2 = u32(data, ptr); ptr += 7
            if v2 & 4:
                tid = u16(data, ptr)
                face_uvs = [(u16(data, ptr+6+j*4), u16(data, ptr+6+j*4+2)) for j in range(vcnt)]
                ptr += 6 + vcnt * 4
                on_face(zi, portal_map, vcnt, idxs, v2, tid, face_uvs, hx, hy, hz, pool, e523c)
            else:
                on_face(zi, portal_map, vcnt, idxs, v2, None, None, hx, hy, hz, pool, e523c)
            ptr += vcnt * e523c
        v11 = u16(data, ptr); ptr += 2
        for _ in range(v11):
            v12 = data[ptr]; ptr += 1; ptr += v12 * 2 + 3
        ptr = skip_bsp(data, ptr)
        v14 = u16(data, ptr); ptr += 2
        for _ in range(v14):
            ptr += 20
            ca = u16(data, ptr); ptr += 2; ptr += ca * 6
            cb = u16(data, ptr); ptr += 2
            for _ in range(cb): ptr = skip_portal(data, ptr)
            cc = u16(data, ptr); ptr += 2
            for _ in range(cc): ptr = read_poly_nolm(data, ptr)
            ptr = skip_bsp(data, ptr)
        result = u16(data, ptr); ptr += 2
        ptr += result * 20
    return ptr

# ── Load CLF ────────────────────────────────────────────────────────────────────

with open(CLF_PATH, "rb") as f: clf = bytearray(f.read())
n_zones = u16(clf, 0x20)
print(f"{CLF_PATH}: {len(clf)} bytes, {n_zones} zones")

# ── Pass 1: collect wm values and max uy per descriptor ─────────────────────────

desc_wm    = {}   # desc_id → (wm_u, wm_v)
desc_max_uy = {}  # desc_id → max raw uy seen in any face

def p1_portal(did, wm_u, wm_v):
    desc_wm[did] = (wm_u, wm_v)

def p1_face(zi, portal_map, vcnt, idxs, v2, tid, face_uvs, hx, hy, hz, pool, e523c):
    if tid is None or face_uvs is None: return
    if tid not in portal_map: return
    did = portal_map[tid][0]
    max_uy = max(uv[1] for uv in face_uvs)
    if max_uy > desc_max_uy.get(did, 0):
        desc_max_uy[did] = max_uy

clf_walk(clf, n_zones, p1_portal, p1_face)

# ── Determine actual height for each descriptor ─────────────────────────────────

desc_actual_h = {}
n_doubled = 0
n_partial  = 0
for did, (wm_u, wm_v) in desc_wm.items():
    h = wm_v + 1
    max_uy = desc_max_uy.get(did, 0)
    rc = get_desc_atlas(did)
    if rc and max_uy == 2 * h and (atlas_total_rows - rc[0]) >= 2 * h:
        h = 2 * h
        n_doubled += 1
    elif 0 < max_uy < h:
        h = max_uy
        n_partial += 1
    desc_actual_h[did] = h

print(f"Double-height fix applied to {n_doubled} descriptors, partial-UV clamp to {n_partial}")

# ── Pass 2: collect geometry + normalised UVs ────────────────────────────────────

world_verts = []
vert_map    = {}
uv_list     = []
desc_faces  = {}   # desc_id → [(vi_list, uvi_list), ...]
plain_faces = []
missing_warn = []

def get_vidx(v):
    if v not in vert_map:
        vert_map[v] = len(world_verts) + 1
        world_verts.append(v)
    return vert_map[v]

def p2_face(zi, portal_map, vcnt, idxs, v2, tid, face_uvs, hx, hy, hz, pool, e523c):
    if v2 & 4:
        if tid not in portal_map:
            missing_warn.append((zi, tid))
            vis = [get_vidx(pool[i]) for i in idxs]
            plain_faces.append(list(reversed(vis)))
            return
        did, wm_u, wm_v = portal_map[tid]
        tw = wm_u + 1
        th = desc_actual_h[did]
        vis  = [get_vidx(pool[i]) for i in idxs]
        uvis = []
        for ux, uy in face_uvs:
            u_n = ux / tw
            v_n = 1.0 - uy / th
            uv_list.append((u_n, v_n))
            uvis.append(len(uv_list))
        if did not in desc_faces:
            desc_faces[did] = []
        desc_faces[did].append((list(reversed(vis)), list(reversed(uvis))))
    else:
        vis = [get_vidx(pool[i]) for i in idxs]
        plain_faces.append(list(reversed(vis)))

final_ptr = clf_walk(clf, n_zones, p1_portal, p2_face)

total_tex = sum(len(v) for v in desc_faces.values())
print(f"Final ptr: 0x{final_ptr:X}  remaining: {len(clf)-final_ptr}")
print(f"Verts: {len(world_verts)}, textured: {total_tex}, plain: {len(plain_faces)}")
print(f"Unique descriptors: {len(desc_faces)}")
if missing_warn:
    from collections import Counter
    c = Counter(zi for zi,_ in missing_warn)
    print(f"WARNING: {len(missing_warn)} faces missing portal (zones: {dict(c)})")

# ── Extract per-descriptor textures ─────────────────────────────────────────────

print(f"Extracting {len(desc_wm)} descriptor images to {TEX_DIR}/ ...")
tex_files  = {}
desc_alpha = {}
for did in sorted(desc_wm):
    if did not in desc_faces and did not in desc_actual_h:
        continue
    wm_u, wm_v = desc_wm[did]
    actual_h   = desc_actual_h.get(did, wm_v + 1)
    fname, has_alpha = extract_desc_png(did, wm_u, actual_h)
    if fname:
        tex_files[did]  = fname
        desc_alpha[did] = has_alpha
        tag = f"[{wm_u+1}x{actual_h}" + (" doubled" if actual_h == 2*(wm_v+1) else "") + "]"
        if has_alpha:
            print(f"  desc_{did:03d} {tag} [alpha]")
    else:
        print(f"  WARNING: desc_{did:03d} has no valid atlas position")

# ── Write MTL ────────────────────────────────────────────────────────────────────

tex_subdir = os.path.basename(TEX_DIR)
mtl_name   = f"{LEVEL}_v25.mtl"
mtl_path   = os.path.join(OUT_DIR, mtl_name)
with open(mtl_path, "w") as f:
    for did in sorted(desc_faces.keys()):
        fname     = tex_files.get(did)
        has_alpha = desc_alpha.get(did, False)
        f.write(f"newmtl desc_{did:03d}\n")
        f.write(f"Kd 1 1 1\n")
        if fname:
            f.write(f"map_Kd {tex_subdir}/{fname}\n")
            if has_alpha:
                f.write(f"map_d  {tex_subdir}/{fname}\n")
                f.write(f"d 1.0\n")
        f.write("\n")
    f.write("newmtl nomat\nKd 0.5 0.5 0.5\n")
print(f"Written: {mtl_path}")

# ── Write OBJ ────────────────────────────────────────────────────────────────────

obj_path = os.path.join(OUT_DIR, f"{LEVEL}_v25.obj")
with open(obj_path, "w") as f:
    f.write(f"# {CLF_PATH} textured v25 — double-height + partial-UV fix\n")
    f.write(f"# {len(world_verts)}v  {len(uv_list)}vt\n")
    f.write(f"mtllib {mtl_name}\n")
    f.write(f"o {LEVEL}_v24\n")
    for x, y, z in world_verts:
        f.write(f"v {x*0.01:.4f} {y*0.01:.4f} {z*0.01:.4f}\n")
    for u_n, v_n in uv_list:
        f.write(f"vt {u_n:.6f} {v_n:.6f}\n")
    for did in sorted(desc_faces.keys()):
        f.write(f"usemtl desc_{did:03d}\n")
        for vis, uvis in desc_faces[did]:
            terms = " ".join(f"{vi}/{ui}" for vi, ui in zip(vis, uvis))
            f.write(f"f {terms}\n")
    f.write("usemtl nomat\n")
    for vis in plain_faces:
        f.write("f " + " ".join(str(v) for v in vis) + "\n")

print(f"Written: {obj_path}")
print("Import in Blender: Up=Y, scale=0.01")
print("For alpha materials: Material > Blend Mode = Alpha Clip")
