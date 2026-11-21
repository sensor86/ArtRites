"""
Last Rites (1997) — Real-Time Automap
Reads player zone/position from DOSBox flat physical memory (MemBase + CF offsets).

From disassembly (confirmed):
  CF840 = zone index  — updated on every portal crossing
  CF844 = x ×256      — updated on every portal crossing
  CF848 = y ×256      — updated on every portal crossing
  CF84C = z ×256      — updated on every portal crossing
  These are copies of E5278/E5284/E5288/E528C made in the portal-crossing handler.

MemBase (DOSBox flat physical start) is found dynamically each session by scanning
for the largest committed block where offset CF840 holds a valid zone (1-600).

UI (session 84): clean light-theme 2D top-down map by default; Tab switches to a
3D floor-slab view for multi-storey levels. Auto-detects the loaded level when
launched without arguments. Per-floor visibility follows the player's live y.
"""
import json, sys, os, math, struct, glob, gzip, time, threading, queue, ctypes, ctypes.wintypes as wt
import tkinter as tk
try:
    sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
import argparse
_ap = argparse.ArgumentParser(add_help=False)
_ap.add_argument('level', nargs='?', default='AUTO')
_ap.add_argument('--base', default=None, help='Force MemBase (hex), e.g. --base 0x28C0000')
_ap.add_argument('--scan', action='store_true', help='Dump raw memory regions and exit')
_ap.add_argument('--search', action='store_true', help='Byte-pattern search for real MemBase and exit')
_ap.add_argument('--watch', action='store_true', help='Live console monitor: prints CF840/E5278 every 0.5s')
_ap.add_argument('--self-test', action='store_true', help='Dry-run detection without a running game; print findings and exit 0')
_args, _ = _ap.parse_known_args()

LEVEL     = _args.level.upper()

if getattr(sys, 'frozen', False):
    # PyInstaller .exe: bundled read-only data lives in sys._MEIPASS; user-writable
    # files (markers, .membase, ui state) go next to the .exe itself.
    _HERE     = os.path.dirname(sys.executable)
    _BUNDLED  = getattr(sys, '_MEIPASS', _HERE)
else:
    _HERE     = os.path.dirname(os.path.abspath(__file__))
    _BUNDLED  = _HERE

_BASE_FILE = os.path.join(_HERE, '.membase')

# ---------------------------------------------------------------------------
# Logging: the release .exe is a windowed (no-console) build, so every print()
# is invisible — and PyInstaller sets sys.stdout to None, where print() would
# even raise. Tee stdout/stderr into automap.log next to this file so a stuck
# install is diagnosable ("attach automap.log").
# ---------------------------------------------------------------------------
_LOG_FILE = None

def _setup_log():
    global _LOG_FILE
    try:
        _LOG_FILE = open(os.path.join(_HERE, 'automap.log'), 'w', encoding='utf-8')
    except Exception:
        _LOG_FILE = None
    if _LOG_FILE is None:
        return
    _LOG_FILE.write(f"--- Last Rites Automap {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    _LOG_FILE.flush()
    class _Tee:
        def __init__(self, *streams):
            self._streams = [s for s in streams if s is not None]
        def write(self, s):
            for st in self._streams:
                try:
                    st.write(s)
                    st.flush()
                except Exception:
                    pass
            return len(s)
        def flush(self):
            for st in self._streams:
                try:
                    st.flush()
                except Exception:
                    pass
        def isatty(self):
            return False
    sys.stdout = _Tee(sys.stdout, _LOG_FILE)
    sys.stderr = _Tee(sys.stderr, _LOG_FILE)

_setup_log()

def _load_saved_base():
    try:
        return int(open(_BASE_FILE).read().strip(), 16)
    except Exception:
        return None

def _save_base(val):
    try:
        open(_BASE_FILE, 'w').write(hex(val))
    except Exception:
        pass

USER_FORCED = bool(_args.base)   # explicit --base: never auto-rediscover over it
if _args.base:
    FORCED_BASE = int(_args.base, 16)
    _save_base(FORCED_BASE)
else:
    FORCED_BASE = _load_saved_base()   # auto-load last confirmed base

POLL_MS   = 80   # memory read interval (ms)
SCAN_INTERVAL = 5.0  # re-scan for DOSBox process every N seconds if not found

# Portal-crossing copies (updated only on zone boundary crossing)
OFF_CF840 = 0xCF840   # zone index
OFF_CF844 = 0xCF844   # x ×256
OFF_CF848 = 0xCF848   # y ×256
OFF_CF84C = 0xCF84C   # z ×256

# Live player state (updated every frame — preferred for smooth tracking)
OFF_E5278 = 0xE5278   # zone index (live)
OFF_E5284 = 0xE5284   # x ×256   (live — CONFIRMED snapshot only, not per-frame)
OFF_E5288 = 0xE5288   # y ×256   (live)
OFF_E528C = 0xE528C   # z ×256   (live)

# Player state backup saved at start of each sub_3E278 (entity processing) call.
OFF_DB309 = 0xDB309   # player x backup (DB2C5 + 0x44)
OFF_DB30D = 0xDB30D   # player y backup (DB2C5 + 0x48)
OFF_DB311 = 0xDB311   # player z backup (DB2C5 + 0x4C)

# Valid zone range for any LR level (MISS07 has 542 zones)
ZONE_MIN, ZONE_MAX = 1, 600

# Current-mission asset-path table (session 85, CONFIRMED live): fixed buffers at
#   flat+0xCE050 music, +0xCE090 mission text, +0xCE0D0 "levels\missNN", +0xCE110 briefing.
# Reading the missNN string is the authoritative "which level is loaded" signal —
# it also tells MISS01 and MISS06 (identical maps) apart, which positions never can.
OFF_LEVELNAME = 0xCE0D0
import re as _re
_LEVELNAME_RE = _re.compile(rb'levels\\miss(\d\d)')

# ---------------------------------------------------------------------------
# Level data
# ---------------------------------------------------------------------------
_JSON_DIRS = [os.path.join(_BUNDLED, 'data'), os.path.join(_HERE, 'data'),
              _HERE, os.path.join(_HERE, '..'), '.']

def find_json(level):
    for d in _JSON_DIRS:
        p = os.path.join(d, f'{level}_automap.json')
        if os.path.exists(p):
            return p
    return None

# Globals populated by load_level()
zones = []
blocks = []
block_by_idx = {}
LVL_XMIN = LVL_XMAX = LVL_ZMIN = LVL_ZMAX = 0

def load_level(level):
    global LEVEL, zones, blocks, block_by_idx
    global LVL_XMIN, LVL_XMAX, LVL_ZMIN, LVL_ZMAX
    path = find_json(level)
    if not path:
        print(f"Cannot find {level}_automap.json — run from lr/ directory.")
        sys.exit(1)
    with open(path) as f:
        level_data = json.load(f)
    LEVEL  = level
    zones  = level_data['zones']
    blocks = []
    for z in zones:
        b   = z['bounds']
        mn, mx = b['min'], b['max']
        blocks.append({
            'idx':  z['index'],
            'cx':  (mn[0]+mx[0])/2, 'cy': (mn[1]+mx[1])/2, 'cz': (mn[2]+mx[2])/2,
            'npoly': z['n_polys'],
            'bounds': (mn, mx),
        })
    block_by_idx = {b['idx']: b for b in blocks}
    LVL_XMIN = min(z['bounds']['min'][0] for z in zones)
    LVL_XMAX = max(z['bounds']['max'][0] for z in zones)
    LVL_ZMIN = min(z['bounds']['min'][2] for z in zones)
    LVL_ZMAX = max(z['bounds']['max'][2] for z in zones)
    load_logic(level)
    print(f"Level: {LEVEL} — {len(blocks)} zones loaded, "
          f"{len(LOGIC_SW)} switches, {len(LOGIC_DOORS)} remote doors")

# --- user markers (persisted per level) ---------------------------------------
def markers_path(level):
    # markers are user-generated -> save to a writable folder next to the exe/script
    mdir = os.path.join(_HERE, 'markers')
    try:
        os.makedirs(mdir, exist_ok=True)
    except Exception:
        mdir = _HERE
    return os.path.join(mdir, f'{level}_markers.json')

def load_markers(level):
    # primary writable location, then legacy spots (data/, package root)
    for p in (markers_path(level),
              os.path.join(_HERE, 'data', f'{level}_markers.json'),
              os.path.join(_BUNDLED, 'data', f'{level}_markers.json')):
        try:
            with open(p) as f:
                return [tuple(m) for m in json.load(f)]
        except Exception:
            continue
    return []

def save_markers(level, markers):
    try:
        with open(markers_path(level), 'w') as f:
            json.dump([list(m) for m in markers], f)
    except Exception:
        pass

# --- switch/door logic layer (session 87, extracted from CLF by extract_logic.py)
# switches: type-8 LOCK/SERV sprites + type-22 touch triggers (validated 14/14
# vs hand pins on MISS05). doors: sub_50B30 records moved by type-3 actions =
# remote-operated doors/objects ("opens elsewhere").
LOGIC_SW = []      # [{x,y,z,file,cond,ids,actions,group}]
LOGIC_DOORS = []   # [{x,y,z,id}]
LOGIC_BY_DOOR = {} # door id -> [switch dict]

def load_logic(level):
    global LOGIC_SW, LOGIC_DOORS, LOGIC_BY_DOOR
    LOGIC_SW, LOGIC_DOORS, LOGIC_BY_DOOR = [], [], {}
    for d in _JSON_DIRS:
        p = os.path.join(d, f'{level}_logic.json')
        if not os.path.exists(p):
            continue
        try:
            with open(p) as f:
                lg = json.load(f)
            LOGIC_SW = lg.get('switches', [])
            LOGIC_DOORS = lg.get('doors', [])
            for s in LOGIC_SW:
                for a in s.get('actions', []):
                    LOGIC_BY_DOOR.setdefault(a.get('target'), []).append(s)
        except Exception:
            pass
        break

# --- item legend (session 85) --------------------------------------------------
# Live pickup structs carry the item-type id at +0x52 (CONFIRMED by correlating
# the user's hand-placed markers with the live object array on MISS07).
# Type ids are engine-global; unknown ids can be named in-app (click the symbol)
# and are saved to item_names.json next to the exe.
ITEM_NAMES_DEFAULT = {
    63: 'Uzi', 64: 'Shotgun', 66: 'Plasma blaster', 67: 'Shredder multi-cannon',
    70: 'Shotgun shells', 71: 'Uzi clip',
    72: 'Shredder pack', 73: 'Scavenger rockets', 75: 'Inferno canister',
    78: 'Battery', 80: 'Medkit (25%)', 81: 'Medkit (50%)', 84: 'Scanner',
    91: 'Quest container',   # MISS05: matches the user's "Level objective" pin
}
_ITEM_NAMES_FILE = os.path.join(_HERE, 'item_names.json')

def load_item_names():
    names = dict(ITEM_NAMES_DEFAULT)
    try:
        with open(_ITEM_NAMES_FILE) as f:
            names.update({int(k): v for k, v in json.load(f).items()})
    except Exception:
        pass
    return names

def save_item_name(tid, name):
    try:
        cur = {}
        try:
            with open(_ITEM_NAMES_FILE) as f:
                cur = json.load(f)
        except Exception:
            pass
        cur[str(tid)] = name
        with open(_ITEM_NAMES_FILE, 'w') as f:
            json.dump(cur, f, indent=1)
    except Exception:
        pass

ITEM_NAMES = load_item_names()

# Class-1025 statics (orange triangles) are not all explosive barrels — ceiling
# lamps, vending machines etc. share the class, distinguished by the sprite id
# @ +0x86. User names them by clicking the triangle; ambient-sounding names
# (lights, vending…) hide that sprite id from the map.
_SCENERY_NAMES_FILE = os.path.join(_HERE, 'scenery_names.json')

def load_scenery_names():
    try:
        with open(_SCENERY_NAMES_FILE) as f:
            raw = json.load(f)
        out = {}
        for k, v in raw.items():
            # keys are either numeric spr ids or '@x,z' position strings
            try:
                out[int(k)] = v
            except ValueError:
                out[k] = v
        return out
    except Exception:
        return {}

def scenery_key(spr, wx, wz):
    """Name key for class-1025 static objects.
    spr>0: type-wide key (int) — one name for all instances of that sprite id.
    spr==0: position-based key (str) — each spatially distinct object gets its own name,
    because many unrelated types share spr==0 (tombstones, fences, etc.)."""
    if spr != 0:
        return spr
    return f'@{round(wx / 100)},{round(wz / 100)}'

def save_scenery_name(key, name):
    try:
        cur = {}
        try:
            with open(_SCENERY_NAMES_FILE) as f:
                cur = json.load(f)
        except Exception:
            pass
        cur[str(key)] = name
        with open(_SCENERY_NAMES_FILE, 'w') as f:
            json.dump(cur, f, indent=1)
    except Exception:
        pass

SCENERY_NAMES = load_scenery_names()

# stable per-item-kind colours: health red, energy yellow, weapons purple,
# ammo shades of green/teal, unknown gray
_ITEM_STYLE = {
    80: ('#e23c1e', '+'),    # medkit 25%
    81: ('#e23c1e', '+'),    # medkit 50%
    78: ('#e0a800', 'E'),    # battery
    84: ('#2a87c9', 'S'),    # scanner
    63: ('#9651c9', 'W'),    # weapon: Uzi
    64: ('#9651c9', 'W'), 65: ('#9651c9', 'W'), 66: ('#9651c9', 'W'),
    67: ('#9651c9', 'W'), 68: ('#9651c9', 'W'),
    70: ('#2e9e4f', 'a'), 71: ('#11a3a3', 'a'), 72: ('#7a8c1e', 'a'),
    73: ('#1e7a5e', 'a'), 74: ('#4f9e2e', 'a'), 75: ('#c95a23', 'a'),
    91: ('#c9a23c', 'Q'),    # quest/objective container
}
def item_style(tid):
    return _ITEM_STYLE.get(tid, ('#8a8a8a', '?'))

# Names that mean pure scenery (lights, vending machines…) — nothing to
# interact with, so they only add clutter. Applies to user marker pins AND to
# live entities the user has click-named. Hidden unless toggled back on with U.
_AMBIENT_MARKER = _re.compile(r'light|lamp|vending|ambien|decor|scenery', _re.I)

def _is_ambient(name):
    return bool(name) and _AMBIENT_MARKER.search(name) is not None

# --- persisted UI state (overlay mode, geometry, opacity) ----------------------
_UI_STATE_FILE = os.path.join(_HERE, 'ui_state.json')

def load_ui_state():
    try:
        with open(_UI_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def save_ui_state(st):
    try:
        with open(_UI_STATE_FILE, 'w') as f:
            json.dump(st, f, indent=1)
    except Exception:
        pass

def sane_geom(g, min_w=160, min_h=120):
    """Validate a Tk 'WxH+X+Y' string. Tk reports degenerate sizes (1x1, 120x1)
    before the window is mapped; persisting one bricks every later launch.
    Returns g if usable, else None."""
    try:
        w, h = g.split('+')[0].split('x')
        if int(w) >= min_w and int(h) >= min_h:
            return g
    except Exception:
        pass
    return None

# --- 3D render geometry (extract_geo.py output) -------------------------------
GEO = {}           # zone idx -> list of face dicts (loaded in background)
GEO_LEVEL = None   # level the GEO dict belongs to
_GEO_LOCK = threading.Lock()

def _luminance_hex(r, g, b, k):
    return '#%02x%02x%02x' % (min(255, int(r*k)), min(255, int(g*k)), min(255, int(b*k)))

# base tints (r,g,b 0-255) per zone state: 0 unvisited, 1 visited, 2 current
_TINTS = [(226, 223, 215), (203, 222, 242), (255, 216, 150)]

def load_geo_async(level):
    """Load {level}_geo.json in a worker thread and precompute per-face shading."""
    def work():
        global GEO, GEO_LEVEL
        path = None
        for d in _JSON_DIRS:
            p = os.path.join(d, f'{level}_geo.json')
            if os.path.exists(p):
                path = p
                break
        if not path:
            print(f"[automap] no {level}_geo.json — 3D mode will use flat slabs "
                  f"(run extract_geo.py {level})")
            with _GEO_LOCK:
                GEO, GEO_LEVEL = {}, level
            return
        with open(path) as f:
            gd = json.load(f)
        # fixed light from upper-left; faces shaded by normal once at load
        lx, ly, lz = 0.35, 0.80, 0.45
        ln = math.sqrt(lx*lx + ly*ly + lz*lz)
        lx, ly, lz = lx/ln, ly/ln, lz/ln
        geo = {}
        for z in gd['zones']:
            verts = z['verts']
            faces = []
            for f in z['faces']:
                pts = [verts[i] for i in f]
                n = len(pts)
                cx = sum(p[0] for p in pts)/n
                cy = sum(p[1] for p in pts)/n
                cz = sum(p[2] for p in pts)/n
                # Newell normal
                nx = ny = nz = 0.0
                for i in range(n):
                    x0, y0, z0 = pts[i]
                    x1, y1, z1 = pts[(i+1) % n]
                    nx += (y0-y1)*(z0+z1)
                    ny += (z0-z1)*(x0+x1)
                    nz += (x0-x1)*(y0+y1)
                m = math.sqrt(nx*nx + ny*ny + nz*nz) or 1.0
                dot = (nx*lx + ny*ly + nz*lz) / m
                shade = 0.66 + 0.34*max(0.0, dot)
                fills = tuple(_luminance_hex(r, g, b, shade) for r, g, b in _TINTS)
                outs  = tuple(_luminance_hex(r, g, b, shade*0.82) for r, g, b in _TINTS)
                span = max(max(p[0] for p in pts) - min(p[0] for p in pts),
                           max(p[1] for p in pts) - min(p[1] for p in pts),
                           max(p[2] for p in pts) - min(p[2] for p in pts))
                faces.append({'pts': pts, 'miny': min(p[1] for p in pts),
                              'c': (cx, cy, cz), 'span': span,
                              'fill': fills, 'out': outs})
            geo[z['index']] = faces
        with _GEO_LOCK:
            GEO, GEO_LEVEL = geo, level
        print(f"[automap] 3D geometry ready: {level} "
              f"({sum(len(v) for v in geo.values())} faces)")
    threading.Thread(target=work, daemon=True).start()

# --- Level auto-detection -----------------------------------------------------
_ALL_META = None   # {level: [(mn,mx), ...]}

def _all_level_meta():
    global _ALL_META
    if _ALL_META is None:
        _ALL_META = {}
        seen = set()
        for d in _JSON_DIRS:
            for p in glob.glob(os.path.join(d, 'MISS*_automap.json')):
                name = os.path.basename(p)[:-len('_automap.json')]
                if name in seen:
                    continue
                seen.add(name)
                try:
                    with open(p) as f:
                        dd = json.load(f)
                    _ALL_META[name] = [(z['bounds']['min'], z['bounds']['max'])
                                       for z in dd['zones']]
                except Exception:
                    pass
    return _ALL_META

def detect_level_from_pos(ox, oz, zone_raw):
    """Which level contains world (ox, oz)? Tiebreak with the CF840 zone index
    (its bbox must also contain the position). Returns level name or None."""
    meta = _all_level_meta()
    matches = []
    for name, bnds in meta.items():
        contain = [i for i, (mn, mx) in enumerate(bnds)
                   if mn[0] <= ox <= mx[0] and mn[2] <= oz <= mx[2]]
        if not contain:
            continue
        zone_ok = False
        for zi in (zone_raw, zone_raw & 0xFF):
            if 0 <= zi < len(bnds):
                mn, mx = bnds[zi]
                if mn[0] <= ox <= mx[0] and mn[2] <= oz <= mx[2]:
                    zone_ok = True
                    break
        matches.append((zone_ok, name))
    if not matches:
        return None
    zone_hits = [n for ok, n in matches if ok]
    if zone_hits:
        return zone_hits[0]
    if len(matches) == 1:
        return matches[0][1]
    return None   # ambiguous without a zone-index confirmation

import subprocess

def _dist_to_nearest_zone(ox, oz):
    best = 1e9
    for z in zones:
        mn, mx = z['bounds']['min'], z['bounds']['max']
        dx = max(mn[0]-ox, 0, ox-mx[0]); dz = max(mn[2]-oz, 0, oz-mx[2])
        d = (dx*dx + dz*dz) ** 0.5
        if d < best: best = d
    return best

def _base_is_live(handle, base):
    """Valid base = player's x & z map to a position on/near an actual
    zone (<=1000 OBJ units). Retries over ~1s so a player transiently in a portal
    gap isn't falsely flagged stale. Rejects false bases (dead gaps >1500 away)."""
    for _ in range(8):
        d = _read_mem(handle, base + OFF_CF844, 4)
        e = _read_mem(handle, base + OFF_CF84C, 4)
        if d and e and len(d) == 4 and len(e) == 4:
            ox = -struct.unpack('<i', d)[0] / 256.0
            oz =  struct.unpack('<i', e)[0] / 256.0
            if _dist_to_nearest_zone(ox, oz) <= 1000:
                return True
        time.sleep(0.12)
    return False

def _recalibrate_base():
    """Find the live MemBase by driving the player (scan_player.py moves W/turns,
    detects the struct whose x AND z track movement) and reload the saved value."""
    try:
        script = os.path.join(os.path.dirname(__file__), 'scan_player.py')
        print("[automap] recalibrating — the player will move briefly, please wait…", flush=True)
        subprocess.run([sys.executable, script, LEVEL], timeout=120)
    except Exception as ex:
        print(f"[automap] recalibration failed: {ex}")
    return _load_saved_base()

# ---------------------------------------------------------------------------
# Windows memory reader
# ---------------------------------------------------------------------------
K32  = ctypes.windll.kernel32
PSAPI = ctypes.windll.psapi if hasattr(ctypes.windll, 'psapi') else None

PROCESS_VM_READ           = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400

class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress",       ctypes.c_size_t),
        ("AllocationBase",    ctypes.c_size_t),
        ("AllocationProtect", wt.DWORD),
        ("RegionSize",        ctypes.c_size_t),
        ("State",             wt.DWORD),
        ("Protect",           wt.DWORD),
        ("Type",              wt.DWORD),
    ]

MEM_COMMIT = 0x1000

def _read_mem(handle, address, size):
    buf  = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t(0)
    ok   = K32.ReadProcessMemory(handle, ctypes.c_void_p(address), buf, size, ctypes.byref(read))
    return buf.raw[:read.value] if ok else None

def find_dosbox_pid():
    TH32CS_SNAPPROCESS = 0x00000002
    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ('dwSize',              wt.DWORD),
            ('cntUsage',            wt.DWORD),
            ('th32ProcessID',       wt.DWORD),
            ('th32DefaultHeapID',   ctypes.POINTER(ctypes.c_ulong)),
            ('th32ModuleID',        wt.DWORD),
            ('cntThreads',          wt.DWORD),
            ('th32ParentProcessID', wt.DWORD),
            ('pcPriClassBase',      ctypes.c_long),
            ('dwFlags',             wt.DWORD),
            ('szExeFile',           ctypes.c_char * 260),
        ]
    snap = K32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == wt.HANDLE(-1).value:
        return None
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    pids = []
    if K32.Process32First(snap, ctypes.byref(entry)):
        while True:
            name = entry.szExeFile.decode('ascii', errors='ignore').lower()
            if 'dosbox' in name:
                pids.append(entry.th32ProcessID)
            if not K32.Process32Next(snap, ctypes.byref(entry)):
                break
    K32.CloseHandle(snap)
    return pids[0] if pids else None


def _committed_regions(handle, min_size):
    """All committed memory regions of at least min_size bytes."""
    _PTR = ctypes.sizeof(ctypes.c_void_p)
    MAX_ADDR = 0x800_0000_0000 if _PTR == 8 else 0x1_0000_0000
    mbi = MEMORY_BASIC_INFORMATION()
    out = []
    addr = 0
    while addr < MAX_ADDR:
        sz = K32.VirtualQueryEx(handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if sz == 0:
            break
        if mbi.State == MEM_COMMIT and mbi.RegionSize >= min_size:
            out.append((mbi.BaseAddress, mbi.RegionSize))
        addr = mbi.BaseAddress + max(mbi.RegionSize, 1)
    return out


def find_base_static(handle):
    """Self-healing MemBase discovery (session 83/84 technique, no player movement):
    locate the live BIOS Data Area inside DOSBox's emulated RAM —
      u16 @ phys 0x413 == 640 (conventional KB), text cols 40/80, video mode < 0x20,
      and DECISIVELY: the BIOS tick dword @ 0x46C advancing at ~18.2 Hz.
    Flat (CauseWay DS) base = phys0 + 0x18C000.  Returns flat base or None."""
    cands = []
    for rbase, rsize in _committed_regions(handle, 4 * 1024 * 1024):
        raw = _read_mem(handle, rbase, rsize)
        if not raw:
            continue
        idx = raw.find(b'\x80\x02')          # u16 640 LE
        while idx != -1 and len(cands) < 512:
            off = idx - 0x413
            if off >= 0 and off + 0x470 <= len(raw):
                mode = raw[off + 0x449]
                cols = struct.unpack_from('<H', raw, off + 0x44A)[0]
                if mode < 0x20 and cols in (40, 80):
                    cands.append(rbase + off)
            idx = raw.find(b'\x80\x02', idx + 1)
    if not cands:
        return None
    ticks0 = {}
    for c in cands:
        d = _read_mem(handle, c + 0x46C, 4)
        if d and len(d) == 4:
            ticks0[c] = struct.unpack('<I', d)[0]
    time.sleep(1.15)
    live = []
    for c, t0 in ticks0.items():
        d = _read_mem(handle, c + 0x46C, 4)
        if d and len(d) == 4:
            dt = (struct.unpack('<I', d)[0] - t0) & 0xFFFFFFFF
            if 10 <= dt <= 40:               # ~18.2 ticks/s over 1.15s
                live.append(c)
    if len(live) != 1:
        return None                          # ambiguous or none — try again later
    flat = live[0] + 0x18C000
    print(f"[automap] MemBase self-discovered: BDA at 0x{live[0]:X} -> flat base 0x{flat:X}")
    return flat


# --- DOSBox-version-independent flat-base discovery --------------------------
# find_base_static() assumes the CauseWay flat-DS sits at a FIXED offset from the
# BDA. That offset is a property of the game's DOS-extender layout, but pinning
# it is fragile across DOSBox builds / memory sizes. This is the robust anchor:
# the game itself writes its current level as "levels\missNN" at flat+0xCE0D0.
# Find that string in DOSBox memory and derive flat = hit - 0xCE0D0 — no
# emulator-layout assumption at all, so it works on DOSBox, DOSBox-X, Staging,
# etc. The candidate is validated by the live player position landing in a real
# level (so a static level-name TABLE in the exe can't fake it).
def find_flat_by_levelname(handle):
    """Scan committed DOSBox memory for the game's runtime level-name buffer.
    Returns (flat_base, 'MISSNN') or (None, None)."""
    for rbase, rsize in _committed_regions(handle, 4 * 1024 * 1024):
        raw = _read_mem(handle, rbase, rsize)
        if not raw:
            continue
        start = 0
        while True:
            i = raw.find(b'levels\\miss', start)
            if i < 0:
                break
            start = i + 1
            cand = rbase + i - OFF_LEVELNAME
            if cand < 0x100000:            # flat DS lives in extended memory
                continue
            d = _read_mem(handle, cand + OFF_LEVELNAME, 16)
            if not d:
                continue
            m = _LEVELNAME_RE.match(d)
            if not m:
                continue
            # a level must actually be RUNNING here: the live player position
            # (flat+0xCF840) has to land inside a real level
            pd = _read_mem(handle, cand + OFF_CF840, 16)
            if pd and len(pd) == 16:
                zone_raw, x, y, z = struct.unpack_from('<4i', pd)
                if detect_level_from_pos(-x/256.0, z/256.0, zone_raw):
                    return cand, 'MISS' + m.group(1).decode()
    return None, None


def _proc_alive(pid):
    """Is the process still running? (host-side check, no game memory involved)"""
    h = K32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = wt.DWORD(0)
    ok = K32.GetExitCodeProcess(h, ctypes.byref(code))
    K32.CloseHandle(h)
    return bool(ok) and code.value == 259     # STILL_ACTIVE


_PID_FILE = os.path.join(_HERE, 'automap.pid')

def replace_previous_instance():
    """One automap at a time: launching a new one replaces a running one
    (the launcher .bat starts a map every time, so re-running it must not
    pile up duplicate map windows)."""
    try:
        old = int(open(_PID_FILE).read().strip())
    except Exception:
        old = None
    if old and old != os.getpid():
        h = K32.OpenProcess(0x1001, False, old)   # TERMINATE | QUERY_LIMITED_INFO
        if h:
            # only kill it if it really is a python/automap process — the pid
            # could have been reused by something else since the file was written
            buf = ctypes.create_unicode_buffer(512)
            sz = wt.DWORD(512)
            name = ''
            try:
                if K32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(sz)):
                    name = os.path.basename(buf.value).lower()
            except Exception:
                pass
            if name.startswith(('python', 'lastritesautomap')):
                K32.TerminateProcess(h, 0)
                print(f"[automap] replaced previous map instance (pid {old})")
            K32.CloseHandle(h)
    try:
        open(_PID_FILE, 'w').write(str(os.getpid()))
    except Exception:
        pass


class MemReader:
    """Thread-safe player position reader."""
    def __init__(self):
        self._lock       = threading.Lock()
        self._pos        = None   # (zone, x, z) or None
        self._handle     = None
        self._flat_base  = None   # DOSBox flat physical memory base (MemBase)
        self._pid        = None
        self._last_scan  = 0.0
        self._warned_stale = False
        self._mem_level  = None   # "MISSNN" parsed from the asset-path table
        self._thread     = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def get_pos(self):
        with self._lock:
            return self._pos

    def get_level(self):
        """Level name the GAME says is loaded (flat+0xCE0D0), or None."""
        with self._lock:
            return self._mem_level

    def get_pid(self):
        with self._lock:
            return self._pid

    def _read_level_name(self):
        d = _read_mem(self._handle, self._flat_base + OFF_LEVELNAME, 16)
        if d:
            m = _LEVELNAME_RE.match(d)
            if m:
                return 'MISS' + m.group(1).decode()
        return None

    def get_status(self):
        with self._lock:
            if self._handle and self._flat_base is not None:
                return f"pid={self._pid} base=0x{self._flat_base:X}"
            elif self._pid:
                return f"DOSBox found — scanning memory (walk around if needed)"
            return "Waiting for DOSBox…"

    def _connect(self):
        global FORCED_BASE
        now = time.monotonic()
        if now - self._last_scan < SCAN_INTERVAL:
            return
        self._last_scan = now
        if self._handle:
            K32.CloseHandle(self._handle)
            self._handle = None
        self._flat_base = None
        pid = find_dosbox_pid()
        if not pid:
            self._pid = None
            return
        self._pid = pid
        handle = K32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not handle:
            return
        flat = FORCED_BASE if FORCED_BASE is not None else _load_saved_base()
        # Validate the saved base WITHOUT moving the player. If stale (e.g. after a
        # DOSBox restart), tell the user to recalibrate manually — do NOT auto-move
        # the player (that caused a feedback loop dragging the player into gaps).
        if flat is not None and not _base_is_live(handle, flat):
            if not self._warned_stale:
                self._warned_stale = True
                print(f"[automap] saved base 0x{flat:X} looks stale — self-discovering…")
            flat = None
        # Self-healing: re-find the base from the BIOS Data Area fingerprint
        # (validated by _base_is_live before use, so a wrong hit cannot stick).
        if flat is None and not USER_FORCED:
            found = find_base_static(handle)
            if found and _base_is_live(handle, found):
                _save_base(found)
                FORCED_BASE = found
                self._warned_stale = False
                flat = found
        # DOSBox-version-independent recovery: if the BDA offset assumption did
        # not pan out (different emulator build), anchor on the game's own level
        # string instead.
        if flat is None and not USER_FORCED:
            flat2, _lv = find_flat_by_levelname(handle)
            if flat2 and _base_is_live(handle, flat2):
                _save_base(flat2)
                FORCED_BASE = flat2
                self._warned_stale = False
                flat = flat2
                print(f"[automap] MemBase recovered from level-name scan: 0x{flat2:X}")
        if flat is not None:
            self._handle    = handle
            self._flat_base = flat
        else:
            K32.CloseHandle(handle)

    def _read(self):
        if self._flat_base is None:
            return None
        # CF840 block: zone, x, y, z — live player state at the true flat base
        # (phys0 + 0x18C000, session 83). The entity loop can transiently write an
        # NPC's coords here, so take 3 samples ~1 frame apart and use the median:
        # a single contaminated frame cannot poison the reading.
        samples = []
        for i in range(3):
            rd = _read_mem(self._handle, self._flat_base + OFF_CF840, 16)
            if rd and len(rd) == 16:
                samples.append(struct.unpack_from('<4i', rd))
            if i < 2:
                time.sleep(0.015)
        if not samples:
            return None
        med = lambda vals: sorted(vals)[len(vals)//2]
        zone_raw = med([s[0] for s in samples])
        gx = med([s[1] for s in samples])
        gy = med([s[2] for s in samples])
        gz = med([s[3] for s in samples])
        zone = zone_raw & 0xFF
        return (zone, gx, gy, gz, zone_raw, gx, gy, gz)

    def _loop(self):
        prev_zone = None
        while True:
            try:
                if self._handle is None or self._flat_base is None:
                    self._connect()
                if self._handle and self._flat_base is not None:
                    pos = self._read()
                    lvl = self._read_level_name()
                    with self._lock:
                        self._mem_level = lvl
                    if pos is not None:
                        with self._lock:
                            self._pos = pos
                        z = pos[0]
                        if z != prev_zone:
                            ox = -pos[1]/256.0
                            oz =  pos[3]/256.0
                            print(f"x={ox:.0f}  z={oz:.0f}  zone={z}")
                            prev_zone = z
                    # Only force reconnect on read_mem failure, not on invalid zone
            except Exception as e:
                print(f"[automap] exception: {e}")
                with self._lock:
                    self._handle = None
            time.sleep(POLL_MS / 1000.0)

class EntityReader:
    """Live NPC + object positions from the game's runtime entity arrays
    (session 84 discovery, MISS07): NPC structs stride 0x234 near flat+0xD0000,
    object structs stride 0xA0 near flat+0x158000. Instead of trusting struct
    bases, every 4-byte offset in each window is tested with a hard validity
    rule: zone index valid AND the position lies inside that zone's bbox AND
    raw magnitude says ×256 scale. Runs in its own thread with its own handle —
    the position reader (MemReader) is untouched."""
    NPC_WIN = (0xCF000, 0x4000)    # window start (flat offset), size
    # 0x16000 was too small: on MISS05 the object array runs past 0x16D000 and
    # two dozen pickups (incl. an Uzi clip the user stood on) were never seen
    # (session 87 wide_scan.py — pickups confirmed up to flat 0x1748xx).
    OBJ_WIN = (0x157000, 0x38000)

    def __init__(self):
        self._lock = threading.Lock()
        self._npcs = []   # [(x, y, z), ...] world coords
        self._objs = []   # [(x, y, z, sprite_id), ...]
        self.show_all_ents = False  # set by App when X is pressed
        threading.Thread(target=self._loop, daemon=True).start()

    def get(self):
        with self._lock:
            return self._npcs, self._objs

    @staticmethod
    def _scan(buf, zb, want_id, debug=False):
        """want_id=False: NPC window — positions only.
        want_id=True: object window — classify each struct (session 85):
          u16 @ off-0x10 (class) == 39 and sprite-frame @ +0x86 in (87, 88)
            -> pickup; real item-type id @ +0x52 (63 Uzi … 80 Medkit, see ITEM_NAMES)
          class == 1025 -> explosive barrel/crate
          everything else (class 2087 decals, sprite-0 decorations) is skipped.
        debug=True: also emit (wx,wy,wz,'unknown',cls) for unclassified non-zero classes."""
        _SKIP_CLS = {0, 39, 1025, 2087}
        out = []
        seen = set()
        nz = len(zb)
        n = len(buf)
        for off in range(0x10 if want_id else 0, n - 0x90 if want_id else n - 16, 4):
            zone, x, y, z = struct.unpack_from('<4i', buf, off)
            if not (0 < zone < nz):
                continue
            if abs(x) < 80000 and abs(z) < 80000:
                continue
            wx, wy, wz = -x/256.0, y/256.0, z/256.0
            mn, mx = zb[zone]
            if not (mn[0]-100 <= wx <= mx[0]+100 and mn[1]-300 <= wy <= mx[1]+300
                    and mn[2]-100 <= wz <= mx[2]+100):
                continue
            key = (round(wx/60), round(wy/120), round(wz/60))
            if key in seen:
                continue
            seen.add(key)
            if want_id:
                cls = struct.unpack_from('<H', buf, off - 0x10)[0]
                spr = struct.unpack_from('<H', buf, off + 0x86)[0]
                if cls == 39 and spr in (87, 88):
                    tid = struct.unpack_from('<H', buf, off + 0x52)[0]
                    out.append((wx, wy, wz, 'item', tid))
                elif cls == 1025:
                    out.append((wx, wy, wz, 'barrel', spr))
                elif debug and cls not in _SKIP_CLS:
                    out.append((wx, wy, wz, 'unknown', cls))
            else:
                out.append((wx, wy, wz))
        return out

    def _loop(self):
        handle = None
        t_obj = 0.0
        while True:
            try:
                if handle is None:
                    pid = find_dosbox_pid()
                    if pid:
                        handle = K32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION,
                                                 False, pid)
                base = FORCED_BASE if FORCED_BASE is not None else _load_saved_base()
                if handle and base and zones:
                    zb = [(zz['bounds']['min'], zz['bounds']['max']) for zz in zones]
                    buf = _read_mem(handle, base + self.NPC_WIN[0], self.NPC_WIN[1])
                    if buf:
                        npcs = self._scan(buf, zb, False)
                        with self._lock:
                            self._npcs = npcs
                    else:
                        K32.CloseHandle(handle)
                        handle = None
                    now = time.monotonic()
                    if handle and now - t_obj > 2.0:
                        t_obj = now
                        buf = _read_mem(handle, base + self.OBJ_WIN[0], self.OBJ_WIN[1])
                        if buf:
                            objs = self._scan(buf, zb, True, self.show_all_ents)
                            with self._lock:
                                self._objs = objs
            except Exception:
                handle = None
            time.sleep(0.5)

# ---------------------------------------------------------------------------
# Save-state fallback (DOSBox-X Ctrl+Shift+F5)
# ---------------------------------------------------------------------------
def read_sav_pos(filepath):
    try:
        with open(filepath, 'rb') as f:
            raw = f.read()
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
        for i in range(0, len(raw)-12, 4):
            x = struct.unpack_from('<i', raw, i)[0]
            if -500_000 <= x <= 500_000:
                y = struct.unpack_from('<i', raw, i+4)[0]
                z = struct.unpack_from('<i', raw, i+8)[0]
                if 0 <= y <= 500_000 and -500_000 <= z <= 500_000:
                    return x, y, z
    except Exception:
        pass
    return None

# ---------------------------------------------------------------------------
# Map view — light theme, 2D top-down default + 3D floor-slab mode
# ---------------------------------------------------------------------------
COL_BG        = '#f5f3ee'
COL_GRID      = '#ebe8e0'
COL_UNVISITED = '#e6e3db'
COL_UNVIS_OUT = '#cdc9be'
COL_VISITED   = '#cfe0f2'
COL_VIS_OUT   = '#a8c1d9'
COL_CURRENT   = '#ffd98a'
COL_CUR_OUT   = '#d9a440'
COL_GHOST_OUT = '#dedacf'
COL_TRAIL     = '#e8956d'
COL_PLAYER    = '#e23c1e'
COL_PLAYER_OUT= '#ffffff'
COL_TEXT      = '#5a564c'
COL_TEXT_DARK = '#36332b'

Y_SOLID_MARGIN = 350     # zone is "on the player's floor" if its y-extent overlaps player_y ± this
Y_TRAIL_WINDOW = 1600    # trail segments further than this from the floor window are hidden
FLOOR_STEP     = 1200    # PgUp/PgDn manual floor shift (world units)
CUT_ABOVE      = 900     # 3D cutaway: hide/truncate geometry above player_y + this


class MapView:
    """Renders the level. mode '2d' (default): clean top-down plan.
    mode '3d': floor slabs (top faces only — no side walls, no connector lines)."""

    def __init__(self, canvas, w, h):
        self.c  = canvas
        self.cw, self.ch = w, h
        self.mode      = '2d'
        self.follow    = True
        self.autorot   = False    # velocity-based heading lags → queasy; opt-in via N
        self.rot       = 0.0      # current view rotation (rad), smoothed
        self.zoom      = 0.022    # px per world unit (2D)
        self.angle     = 0.7      # 3D yaw (when not auto-rotating)
        self.tilt      = 0.95     # 3D tilt
        self.camx = self.camz = 0.0
        self.panx = self.pany = 0.0    # extra pan when follow is off
        self.topmost   = False
        # state fed by App each tick
        self.player    = [0.0, 0.0, 0.0]
        self.heading   = None     # rad, None until the player moves
        self.cur_zone  = -1
        self.visited   = set()
        self.trail     = []       # [(x, y, z), ...]
        self.npcs      = []       # live [(x, y, z)]
        self.objs      = []       # live [(x, y, z, kind, type_id)]
        self.show_ids  = False    # I — text labels (item names + marker labels)
        self.show_legend = True   # L — legend panel for item symbols
        self.show_ambient = False # U — scenery-only markers (lights, vending…)
        self.show_wiring = False  # W — switch→door relationship lines on map
        self.show_all_ents = False  # X — surface all live object classes (for identification)
        self.logic_hits = []      # screen positions of switch/door symbols
        self.item_hits = []       # screen positions of item symbols (click-to-name)
        self.overlay   = False    # compact HUD when running as the corner panel
        self.markers   = []       # user pins [(x, y, z, label)]
        self.y_override = None    # manual floor shift (PgUp/PgDn)
        self.lod_bias  = 1.0      # 3D feedback LOD (grows when too many faces drawn)
        # drag state
        self.drag = False
        self.btn  = 0
        self.dx = self.dy = 0.0

    # --- view transform ----------------------------------------------------
    def _eff_rot(self):
        if self.mode == '2d':
            return self.rot
        return self.angle

    def proj(self, wx, wy, wz):
        a  = self._eff_rot()
        ca, sa = math.cos(a), math.sin(a)
        dx = wx - self.camx
        dz = wz - self.camz
        rx = dx*ca - dz*sa
        rz = dx*sa + dz*ca
        s  = self.zoom
        cx = self.cw/2 + self.panx
        cy = self.ch/2 + self.pany
        if self.mode == '2d':
            return (cx + rx*s, cy - rz*s)
        ct, st = math.cos(self.tilt), math.sin(self.tilt)
        dy = wy - self.player[1]
        return (cx + rx*s, cy - (rz*st + dy*ct*0.9)*s)

    def fit_level(self):
        """Zoom so the whole level fits (used when follow is off / R pressed)."""
        spanx = max(1, LVL_XMAX - LVL_XMIN)
        spanz = max(1, LVL_ZMAX - LVL_ZMIN)
        self.zoom = min(self.cw/spanx, self.ch/spanz) * 0.92
        self.camx = (LVL_XMIN + LVL_XMAX) / 2
        self.camz = (LVL_ZMIN + LVL_ZMAX) / 2
        self.panx = self.pany = 0.0

    # --- floor logic ---------------------------------------------------------
    def floor_y(self):
        return self.y_override if self.y_override is not None else self.player[1]

    def on_floor(self, b):
        mn, mx = b['bounds']
        fy = self.floor_y()
        return mn[1] - Y_SOLID_MARGIN <= fy <= mx[1] + Y_SOLID_MARGIN

    # --- drawing helpers -----------------------------------------------------
    def _rquad(self, pts, fill, outline, width=1, rfrac=0.18):
        """Quad with rounded corners: cut each corner toward its neighbours and
        let tkinter smooth the polygon."""
        out = []
        n = len(pts)
        for i in range(n):
            x0, y0 = pts[i]
            xp, yp = pts[(i-1) % n]
            xn, yn = pts[(i+1) % n]
            out += [x0 + (xp-x0)*rfrac, y0 + (yp-y0)*rfrac,
                    x0, y0,
                    x0 + (xn-x0)*rfrac, y0 + (yn-y0)*rfrac]
        self.c.create_polygon(out, smooth=True, fill=fill,
                              outline=outline, width=width)

    def _zone_corners(self, b, y=None):
        mn, mx = b['bounds']
        yy = mn[1] if y is None else y
        return [self.proj(mn[0], yy, mn[2]), self.proj(mx[0], yy, mn[2]),
                self.proj(mx[0], yy, mx[2]), self.proj(mn[0], yy, mx[2])]

    def _zone_style(self, b, solid):
        if not solid:
            return '', COL_GHOST_OUT, 1
        idx = b['idx']
        if idx == self.cur_zone:
            return COL_CURRENT, COL_CUR_OUT, 2
        if idx in self.visited:
            return COL_VISITED, COL_VIS_OUT, 1
        return COL_UNVISITED, COL_UNVIS_OUT, 1

    def _draw_grid(self):
        """Subtle world-aligned 8000-unit grid (the engine's tile spacing)."""
        if self.mode != '2d' or self.zoom < 0.004:
            return
        step = 8000
        x0 = int(LVL_XMIN // step) * step
        z0 = int(LVL_ZMIN // step) * step
        x = x0
        while x <= LVL_XMAX + step:
            p1 = self.proj(x, 0, LVL_ZMIN - step)
            p2 = self.proj(x, 0, LVL_ZMAX + step)
            self.c.create_line(p1, p2, fill=COL_GRID)
            x += step
        z = z0
        while z <= LVL_ZMAX + step:
            p1 = self.proj(LVL_XMIN - step, 0, z)
            p2 = self.proj(LVL_XMAX + step, 0, z)
            self.c.create_line(p1, p2, fill=COL_GRID)
            z += step

    def _draw_trail(self):
        if len(self.trail) < 2:
            return
        fy = self.floor_y()
        run = []
        for (tx, ty, tz) in self.trail:
            if abs(ty - fy) <= Y_TRAIL_WINDOW:
                run.append(self.proj(tx, ty, tz))
            else:
                if len(run) >= 2:
                    self.c.create_line(run, fill=COL_TRAIL, width=2,
                                       capstyle='round', joinstyle='round')
                run = []
        if len(run) >= 2:
            self.c.create_line(run, fill=COL_TRAIL, width=2,
                               capstyle='round', joinstyle='round')

    def _draw_player(self):
        px, py, pz = self.player
        sx, sy = self.proj(px, py, pz)
        if self.heading is None:
            self.c.create_oval(sx-8, sy-8, sx+8, sy+8,
                               fill=COL_PLAYER, outline=COL_PLAYER_OUT, width=3)
            return
        # arrow rotated by heading relative to current view rotation
        a = self.heading - self._eff_rot() if self.mode == '2d' else self.heading - self.angle
        # screen angle: heading==view rotation → arrow points up
        ca, sa = math.cos(a), math.sin(a)
        def rp(ux, uy):   # unit arrow shape, up = forward
            return (sx + (ux*ca - uy*sa), sy + (ux*sa + uy*ca))
        pts = [rp(0, -13), rp(9, 10), rp(0, 4), rp(-9, 10)]
        self.c.create_polygon(pts, fill=COL_PLAYER, outline=COL_PLAYER_OUT, width=2)

    # --- main render ---------------------------------------------------------
    def render(self):
        self.c.delete('all')
        self._draw_grid()

        if self.mode == '2d':
            ghosts = [b for b in blocks if not self.on_floor(b)]
            solids = [b for b in blocks if self.on_floor(b)]
            for b in ghosts:
                f, o, w = self._zone_style(b, False)
                self._rquad(self._zone_corners(b), f, o, w)
            cur = None
            for b in solids:
                if b['idx'] == self.cur_zone:
                    cur = b
                    continue
                f, o, w = self._zone_style(b, True)
                self._rquad(self._zone_corners(b), f, o, w)
            if cur:
                f, o, w = self._zone_style(cur, True)
                self._rquad(self._zone_corners(cur), f, o, w)
        else:
            with _GEO_LOCK:
                geo, geo_lvl = GEO, GEO_LEVEL
            if geo and geo_lvl == LEVEL:
                self._render_mesh(geo)
            else:
                # fallback: floor slabs while geometry loads
                a = self.angle
                sa, ca = math.sin(a), math.cos(a)
                def depth(b):
                    return b['cx']*sa + b['cz']*ca
                order = sorted(blocks, key=lambda b: (-depth(b), b['bounds'][0][1]))
                for b in order:
                    solid = self.on_floor(b)
                    f, o, w = self._zone_style(b, solid)
                    pts = self._zone_corners(b, y=b['bounds'][0][1])
                    flat = [c for p in pts for c in p]
                    self.c.create_polygon(flat, fill=f, outline=o, width=w)

        self._draw_trail()
        self._draw_entities()
        self._draw_player()
        self._draw_hud()

    def _draw_entities(self):
        fy = self.floor_y()
        px, py, pz = self.player
        self.item_hits = []     # [(sx, sy, tid)] for click-to-name
        # At overview zoom (R) full-size symbols bury the level: shrink them and
        # drop all glyphs/labels — colour + legend still identify the kind.
        small = self.zoom < 0.010
        r = 3 if small else 6
        ow = 1 if small else 2
        labels = self.show_ids and not small
        # static CLF logic layer: switches (S) + remote-operated doors (D).
        # Drawn first so live symbols stay on top. Click a symbol for wiring.
        self.logic_hits = []
        # optional wiring lines: thin dashed lines switch→target door
        # No Y filter — cross-floor connections must still be visible.
        if self.show_wiring and LOGIC_SW:
            door_scr = {dd['id']: self.proj(dd['x'], dd['y'], dd['z'])
                        for dd in LOGIC_DOORS}
            for sw in LOGIC_SW:
                sx, sy = self.proj(sw['x'], sw['y'], sw['z'])
                for a in sw.get('actions', []):
                    ds = door_scr.get(a.get('target'))
                    if ds:
                        self.c.create_line(sx, sy, ds[0], ds[1],
                                           fill='#5588ff', dash=(4, 3), width=1)
        for dd in LOGIC_DOORS:
            # Remote-operated doors always show regardless of floor — they are
            # navigation landmarks and may be operated from a different floor.
            if dd['id'] not in LOGIC_BY_DOOR:
                continue
            sx, sy = self.proj(dd['x'], dd['y'], dd['z'])
            self.c.create_rectangle(sx-r, sy-r+2, sx+r, sy+r-2,
                                    fill='#8a5a2c', outline='#ffffff', width=ow)
            if not small:
                self.c.create_text(sx, sy, text='D',
                                   font=('Segoe UI', 7, 'bold'), fill='#ffffff')
            self.logic_hits.append((sx, sy, 'door', dd))
        for sw in LOGIC_SW:
            if abs(sw['y'] - fy) > Y_TRAIL_WINDOW:
                continue
            sx, sy = self.proj(sw['x'], sw['y'], sw['z'])
            self.c.create_rectangle(sx-r, sy-r, sx+r, sy+r,
                                    fill='#1f5fd6', outline='#ffffff', width=ow)
            if not small:
                self.c.create_text(sx, sy, text='S',
                                   font=('Segoe UI', 7, 'bold'), fill='#ffffff')
            self.logic_hits.append((sx, sy, 'switch', sw))
            if labels:
                self.c.create_text(sx+8, sy-8, anchor='sw', text='switch',
                                   font=('Segoe UI', 7), fill=COL_TEXT_DARK)
        for (ox, oy, oz, kind, tid) in self.objs:
            if abs(oy - fy) > Y_TRAIL_WINDOW:
                continue
            # live scenery the user has named (lamps, vending machines…) is
            # hidden like ambient marker pins — U brings it back
            skey = scenery_key(tid, ox, oz) if kind == 'barrel' else None
            name = (SCENERY_NAMES.get(skey) if kind == 'barrel'
                    else ITEM_NAMES.get(tid))
            if not self.show_ambient and _is_ambient(name):
                continue
            sx, sy = self.proj(ox, oy, oz)
            if kind == 'barrel':
                # orange warning triangle (click to name — not all are barrels)
                self.c.create_polygon(sx, sy-r, sx+r, sy+r-1, sx-r, sy+r-1,
                                      fill='#e07820', outline='#7a3c00', width=1)
                if not small:
                    self.c.create_text(sx, sy+1, text='!',
                                       font=('Segoe UI', 7, 'bold'), fill='#ffffff')
                self.item_hits.append((sx, sy, kind, tid, ox, oz))
            elif kind == 'unknown':
                # debug mode: grey dot labelled with class id
                self.c.create_oval(sx-r, sy-r, sx+r, sy+r,
                                   fill='#888888', outline='#ffffff', width=1)
                if not small:
                    self.c.create_text(sx, sy, text='?',
                                       font=('Segoe UI', 6, 'bold'), fill='#ffffff')
                if labels or not small:
                    self.c.create_text(sx+8, sy-8, anchor='sw', text=f'cls {tid}',
                                       font=('Segoe UI', 6), fill=COL_TEXT_DARK)
            else:
                col, glyph = item_style(tid)
                self.c.create_oval(sx-r, sy-r, sx+r, sy+r,
                                   fill=col, outline='#ffffff', width=ow)
                if not small:
                    self.c.create_text(sx, sy, text=glyph,
                                       font=('Segoe UI', 8, 'bold'), fill='#ffffff')
                self.item_hits.append((sx, sy, kind, tid, ox, oz))
                if labels:
                    self.c.create_text(sx+8, sy-8, anchor='sw',
                                       text=name or f'id {tid}',
                                       font=('Segoe UI', 7), fill=COL_TEXT_DARK)
        for (nx, ny, nz) in self.npcs:
            if abs(ny - fy) > Y_TRAIL_WINDOW:
                continue
            if abs(nx - px) < 150 and abs(nz - pz) < 150:
                continue   # that's the player echo
            sx, sy = self.proj(nx, ny, nz)
            self.c.create_oval(sx-r, sy-r, sx+r, sy+r,
                               fill='#d61f1f', outline='#ffffff', width=ow)
        # user markers (gold pins) — drawn on every floor but dimmed when off-floor
        for (mx, my, mz, label) in self.markers:
            if not self.show_ambient and _AMBIENT_MARKER.search(label):
                continue
            sx, sy = self.proj(mx, my, mz)
            on = abs(my - fy) <= Y_TRAIL_WINDOW
            fill = '#f4b400' if on else '#e8dca8'
            if small:
                self.c.create_polygon(sx, sy-5, sx+3, sy, sx-3, sy,
                                      fill=fill, outline='#7a5a00', width=1)
            else:
                self.c.create_polygon(sx, sy-10, sx+6, sy-1, sx, sy, sx-6, sy-1,
                                      fill=fill, outline='#7a5a00', width=1)
                self.c.create_oval(sx-2, sy-7, sx+2, sy-3, fill='#7a5a00', outline='')
            if label and on and labels:
                self.c.create_text(sx, sy-12, anchor='s', text=label,
                                   font=('Segoe UI', 8, 'bold'), fill=COL_TEXT_DARK)

    def _render_mesh(self, geo):
        """Real level geometry: flat-shaded, backface-culled (near walls vanish so
        you see into rooms — dollhouse view), cut away above head height so upper
        floors and roofs don't bury the player. Painter-sorted."""
        a = self.angle
        ca, sa = math.cos(a), math.sin(a)
        ct, st = math.cos(self.tilt), math.sin(self.tilt)
        s  = self.zoom
        scx = self.cw/2 + self.panx
        scy = self.ch/2 + self.pany
        camx, camz = self.camx, self.camz
        camy = self.player[1]
        # Cutaway plane: just below the CURRENT zone's ceiling, so the storey
        # above never covers the player (mall storeys can be <900 units), but a
        # tall atrium still shows its balconies. Clamped to py+500..py+2500.
        fy  = self.floor_y()
        cut = fy + CUT_ABOVE
        bcur = block_by_idx.get(self.cur_zone)
        if bcur is not None and self.y_override is None:
            zone_ceil = bcur['bounds'][1][1]
            cut = min(fy + 2500, max(fy + 500, zone_ceil - 60))
        # only zones within the visible radius are transformed at all
        r_vis = math.hypot(self.cw, self.ch) / (2*s) + 4000

        # feedback LOD (uses last frame's bias): skip small faces BEFORE the
        # transform/sort — tkinter chokes above ~2000 items, and at far zoom the
        # candidate set is the whole level
        min_px = 2.5 * self.lod_bias
        min_world = min_px / s   # face bbox below this can't pass the screen test

        items = []
        for b in blocks:
            if abs(b['cx'] - camx) > r_vis or abs(b['cz'] - camz) > r_vis:
                continue
            faces = geo.get(b['idx'])
            if not faces:
                continue
            if b['bounds'][0][1] > cut:
                continue   # whole zone above the cutaway plane
            idx = b['idx']
            state = 2 if idx == self.cur_zone else (1 if idx in self.visited else 0)
            for f in faces:
                if f['miny'] > cut:
                    continue
                fcx, fcy, fcz = f['c']
                dx = fcx - camx; dz = fcz - camz
                # distance-weighted LOD: detail near the player always survives,
                # far small faces are dropped first
                if f['span'] < min_world * (0.25 + (abs(dx) + abs(dz)) / r_vis):
                    continue
                rz = dx*sa + dz*ca
                depth = rz*ct - (fcy - camy)*st
                items.append((depth, f, state))
        items.sort(key=lambda t: -t[0])   # far first

        ycl = 0.9   # vertical foreshortening factor (matches proj())
        drawn = 0
        create_poly = self.c.create_polygon
        for depth, f, state in items:
            pts = f['pts']
            scr = []
            for (wx, wy, wz) in pts:
                if wy > cut:
                    wy = cut   # truncate walls at the cutaway plane
                dx = wx - camx; dz = wz - camz
                rx = dx*ca - dz*sa
                rz = dx*sa + dz*ca
                scr.append(scx + rx*s)
                scr.append(scy - (rz*st + (wy - camy)*ct*ycl)*s)
            # backface cull (shoelace sign; screen y is inverted → keep negatives)
            area = 0.0
            n2 = len(scr)
            for i in range(0, n2, 2):
                j = (i+2) % n2
                area += scr[i]*scr[j+1] - scr[j]*scr[i+1]
            if area < 0:
                continue   # backface (floors viewed from above have positive area)
            # skip sub-pixel faces
            xs = scr[0::2]; ys = scr[1::2]
            if max(xs)-min(xs) < min_px and max(ys)-min(ys) < min_px:
                continue
            create_poly(scr, fill=f['fill'][state], outline=f['out'][state], width=1)
            drawn += 1
        if drawn > 1300:
            self.lod_bias = min(8.0, self.lod_bias * 1.3)
        elif drawn < 700 and self.lod_bias > 1.0:
            self.lod_bias = max(1.0, self.lod_bias / 1.15)

    def _draw_legend(self):
        """Item-symbol legend for the kinds present in the live object list."""
        amb = (lambda n: False) if self.show_ambient else _is_ambient
        tids = sorted({tid for (_, _, _, kind, tid) in self.objs if kind == 'item'
                       and not amb(ITEM_NAMES.get(tid))})
        rows = [(item_style(t), ITEM_NAMES.get(t, f'unknown (click to name)'))
                for t in tids]
        if any(kind == 'barrel' and not amb(SCENERY_NAMES.get(scenery_key(tid, ox, oz)))
               for (ox, _, oz, kind, tid) in self.objs):
            rows.append((('#e07820', '!'), 'Barrel / object (click to name)'))
        if LOGIC_SW:
            rows.append((('#1f5fd6', 'S'), 'Switch (click for wiring)'))
        if LOGIC_DOORS:
            rows.append((('#8a5a2c', 'D'), 'Remote-operated door'))
        if self.show_wiring and LOGIC_SW:
            rows.append((('#5588ff', '-'), 'Wiring: switch->door [Z]'))
        if self.show_all_ents:
            rows.append((('#888888', '?'), 'Unknown class [X] (cls NNN)'))
        if not rows:
            return
        x0 = self.cw - 150
        y  = 34 if self.overlay else 100   # below the north indicator in window mode
        self.c.create_rectangle(x0 - 10, y - 8, self.cw - 6, y + len(rows)*16 + 4,
                                fill='#ffffff', outline=COL_UNVIS_OUT)
        for (col, glyph), name in rows:
            self.c.create_oval(x0-5, y-5, x0+5, y+5, fill=col,
                               outline='#ffffff', width=1)
            self.c.create_text(x0, y, text=glyph, font=('Segoe UI', 7, 'bold'),
                               fill='#ffffff')
            self.c.create_text(x0+10, y, anchor='w', text=name,
                               font=('Segoe UI', 8), fill=COL_TEXT_DARK)
            y += 16

    def _draw_hud(self):
        if self.overlay:
            # compact: level name + floor only, legend if toggled
            self.c.create_text(10, 8, anchor='nw', text=LEVEL,
                               font=('Segoe UI', 11, 'bold'), fill=COL_TEXT_DARK)
            if self.y_override is not None:
                self.c.create_text(10, 26, anchor='nw', text='manual floor',
                                   font=('Segoe UI', 8), fill=COL_TEXT)
            if self.show_legend:
                self._draw_legend()
            return
        # level name + floor info, top-left
        self.c.create_text(14, 12, anchor='nw', text=LEVEL,
                           font=('Segoe UI', 16, 'bold'), fill=COL_TEXT_DARK)
        fy = self.floor_y()
        info = f"floor y {fy:.0f}"
        if self.y_override is not None:
            info += "  (manual — PgUp/PgDn, C to reset)"
        self.c.create_text(14, 38, anchor='nw', text=info,
                           font=('Segoe UI', 10), fill=COL_TEXT)
        n_vis = len(self.visited)
        self.c.create_text(14, 56, anchor='nw',
                           text=f"explored {n_vis}/{len(blocks)} zones",
                           font=('Segoe UI', 10), fill=COL_TEXT)
        mode_bits = [('3D' if self.mode == '3d' else '2D') + ' [Tab]',
                     ('follow ON' if self.follow else 'follow OFF') + ' [C]',
                     ('rotate ON' if self.autorot else 'north-up') + ' [N]']
        self.c.create_text(self.cw - 14, 12, anchor='ne',
                           text='   '.join(mode_bits),
                           font=('Segoe UI', 9), fill=COL_TEXT)
        if self.show_legend:
            self._draw_legend()
        hint = ('wheel/[ ]: zoom  drag: pan  right-drag: orbit  M: mark  R: overview  O: overlay'
                if self.mode == '3d' else
                'wheel/[ ]: zoom  drag: pan  M: mark  Del: unmark  L: legend  I: labels  U: ambient  Z: wiring  X: ent-debug  R: overview  O: overlay')
        self.c.create_text(self.cw - 14, self.ch - 10, anchor='se',
                           text=hint, font=('Segoe UI', 9), fill=COL_TEXT)
        # north indicator (2D only)
        if self.mode == '2d':
            nx, ny = self.cw - 30, 64
            a = self._eff_rot()
            ca, sa = math.cos(a), math.sin(a)
            # world +z (north) on screen
            vx, vy = -sa*16, -ca*16
            self.c.create_oval(nx-18, ny-18, nx+18, ny+18,
                               fill='#ffffff', outline=COL_UNVIS_OUT)
            self.c.create_line(nx, ny, nx+vx, ny+vy, fill=COL_PLAYER, width=2,
                               arrow='last')
            self.c.create_text(nx, ny+24, text='N', font=('Segoe UI', 8),
                               fill=COL_TEXT)

# ---------------------------------------------------------------------------
# Global hotkeys — map keys keep working while the GAME window has focus
# ---------------------------------------------------------------------------
class GlobalHotkeys:
    """WH_KEYBOARD_LL hook: when the foreground window belongs to the DOSBox
    process, map hotkeys are forwarded to the app (queued — Tk is not
    thread-safe). Keys are never swallowed; the game still receives them."""
    # NOTE: the game itself uses F1-F8 AND +/- (screen size), so map hotkeys
    # must stay off those; global zoom lives on [ and ] instead.
    VKMAP = {0x4D: 'm', 0x43: 'c', 0x09: 'Tab', 0x4E: 'n', 0x52: 'r', 0x54: 't',
             0x49: 'i', 0x4C: 'l', 0x55: 'u', 0x21: 'Prior', 0x22: 'Next',
             0xDB: 'bracketleft', 0xDD: 'bracketright',
             0x2E: 'Delete', 0x4F: 'o', 0x56: 'v', 0x42: 'b',
             0x5A: 'z', 0x58: 'x'}
    REPEAT_GUARD = 0.25   # s — key auto-repeat must not spam pins/toggles

    def __init__(self, app):
        self.app = app
        self._user32 = ctypes.windll.user32
        self._last = {}
        threading.Thread(target=self._run, daemon=True).start()

    def _game_foreground(self):
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = wt.DWORD(0)
        self._user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
        game_pid = self.app.reader.get_pid()
        return game_pid is not None and pid.value == game_pid

    def _run(self):
        user32 = self._user32
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p,
                                             ctypes.c_void_p, wt.DWORD]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                          wt.WPARAM, ctypes.c_void_p]
        user32.GetForegroundWindow.restype = ctypes.c_void_p

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [('vkCode', wt.DWORD), ('scanCode', wt.DWORD),
                        ('flags', wt.DWORD), ('time', wt.DWORD),
                        ('dwExtraInfo', ctypes.c_size_t)]
        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                      wt.WPARAM, ctypes.POINTER(KBDLLHOOKSTRUCT))

        def cb(nCode, wParam, lParam):
            if nCode >= 0 and wParam in (0x0100, 0x0104):   # KEYDOWN / SYSKEYDOWN
                k = self.VKMAP.get(lParam.contents.vkCode)
                if k:
                    now = time.monotonic()
                    if now - self._last.get(k, 0.0) >= self.REPEAT_GUARD \
                            and self._game_foreground():
                        self._last[k] = now
                        self.app.hotkey_q.put(k)
            return user32.CallNextHookEx(None, nCode, wParam,
                                         ctypes.cast(lParam, ctypes.c_void_p))

        self._proc = HOOKPROC(cb)   # keep a reference or the hook dies
        hook = user32.SetWindowsHookExW(13, ctypes.cast(self._proc, ctypes.c_void_p),
                                        None, 0)
        if not hook:
            print("[automap] global hotkeys unavailable (hook failed)")
            return
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0):
            pass

# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------
class App:
    def __init__(self):
        self.ui = load_ui_state()
        self.root   = tk.Tk()
        self.root.title("Last Rites Automap — waiting for a level" if LEVEL == 'AUTO'
                        else f"Last Rites Automap — {LEVEL}")
        self.root.configure(bg=COL_BG)
        self.root.geometry(sane_geom(self.ui.get('window_geom', '')) or '1000x760')

        self.canvas = tk.Canvas(self.root, bg=COL_BG, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)

        self.view   = MapView(self.canvas, 1000, 760)
        self.view.markers = load_markers(LEVEL)
        self.reader = MemReader()
        self.ents   = EntityReader()

        self.px = self.py = self.pz = 0.0
        self._pos_established = False   # first live reading is accepted without jump-clamp
        self._rej = []                  # recent rejected readings (re-acquire consensus)
        self._oob = 0                   # consecutive out-of-level-bounds readings
        self._last_redetect = 0.0
        self._lvl_pending = 0           # consecutive ticks the game reports another level

        # heading from velocity (smoothed); replaced by a real yaw global if found
        self._hvx = self._hvy = 0.0     # smoothed heading unit vector

        # Save-state fallback
        self.last_sav   = ''
        self.sav_tick   = 0
        self._first_pos = True   # auto-center on first reading

        self.status = tk.Label(self.root, text="Waiting for a running level…",
                               fg=COL_TEXT, bg=COL_BG, font=('Consolas', 9))
        self.status.pack(pady=2)

        # Bindings
        self.canvas.bind('<Button-1>',        lambda e: self._md(e, 1))
        self.canvas.bind('<Button-3>',        lambda e: self._md(e, 3))
        self.canvas.bind('<ButtonRelease-1>', lambda e: self._mu(e))
        self.canvas.bind('<ButtonRelease-3>', lambda e: self._mu(e))
        self.canvas.bind('<B1-Motion>',       self._mm)
        self.canvas.bind('<B3-Motion>',       self._mm)
        self.canvas.bind('<MouseWheel>',      self._mw)
        self.canvas.bind('<Configure>',       self._resize)
        self.root.bind('<KeyPress>',          self._key)
        self.root.bind('<Escape>',            lambda e: self._on_close())
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

        # overlay (corner panel) mode — default ON so launching the game gives a
        # small semi-transparent always-on-top map out of the box
        self.overlay = self.ui.get('overlay', True)
        self.alpha   = self.ui.get('alpha', 0.85)
        self.view.show_legend = self.ui.get('legend', True)
        self.view.show_ids = self.ui.get('labels', False)
        self.view.show_ambient = self.ui.get('ambient', False)
        self._click_xy = None
        self._strip_drag = False
        if self.overlay and LEVEL != 'AUTO':
            self.root.after(50, lambda: self._apply_window_mode())

        self.hotkey_q = queue.Queue()
        GlobalHotkeys(self)
        self._tick()

    # --- overlay / window mode ------------------------------------------------
    def _apply_window_mode(self):
        v = self.view
        if self.overlay:
            try:
                g = sane_geom(self.root.winfo_geometry())
                if g:
                    self.ui['window_geom'] = g
            except Exception:
                pass
            self.status.pack_forget()
            self.root.overrideredirect(True)
            self.root.attributes('-topmost', True)
            self.root.attributes('-alpha', self.alpha)
            sw = self.root.winfo_screenwidth()
            geom = sane_geom(self.ui.get('overlay_geom') or '') or f"380x320+{(sw-380)//2}+16"
            self.root.geometry(geom)
            v.overlay = True
            v.topmost = True
            v.follow  = True
            if v.zoom < 0.01:
                v.zoom = 0.022
        else:
            try:
                g = sane_geom(self.root.winfo_geometry())
                if g:
                    self.ui['overlay_geom'] = g
            except Exception:
                pass
            self.root.overrideredirect(False)
            self.root.attributes('-topmost', False)
            self.root.attributes('-alpha', 1.0)
            self.root.geometry(sane_geom(self.ui.get('window_geom', '')) or '1000x760')
            self.status.pack(pady=2)
            v.overlay = False
            v.topmost = False
        # process the geometry request NOW — otherwise _save_ui captures the
        # previous mode's size (e.g. 1000x760 window saved as overlay_geom)
        self.root.update_idletasks()
        self._save_ui()

    def _save_ui(self):
        self.ui['overlay'] = self.overlay
        self.ui['alpha']   = self.alpha
        self.ui['legend']  = self.view.show_legend
        self.ui['labels']  = self.view.show_ids
        self.ui['ambient'] = self.view.show_ambient
        try:
            key = 'overlay_geom' if self.overlay else 'window_geom'
            g = sane_geom(self.root.winfo_geometry())
            if g:
                self.ui[key] = g
        except Exception:
            pass
        save_ui_state(self.ui)

    def _on_close(self):
        self._save_ui()
        self.root.destroy()

    def _raise_noactivate(self):
        """Put the map above other windows WITHOUT taking keyboard focus.
        Tk's deiconify()/lift() activate the window — stealing focus from
        fullscreen DOSBox makes SDL minimize the game (the 'B shrinks the
        game' bug). SetWindowPos with SWP_NOACTIVATE raises silently."""
        try:
            u = ctypes.windll.user32
            u.GetAncestor.restype = ctypes.c_void_p
            u.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            hwnd = u.GetAncestor(self.root.winfo_id(), 2)        # GA_ROOT
            if hwnd:
                u.ShowWindow(ctypes.c_void_p(hwnd), 4)           # SW_SHOWNOACTIVATE
                # HWND_TOPMOST; NOSIZE|NOMOVE|NOACTIVATE|SHOWWINDOW
                u.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(-1),
                               0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)
        except Exception:
            pass

    def _bring_to_front(self):
        """B — pop the map above everything without touching the game's focus.
        In window mode the topmost flag is flashed briefly."""
        self._raise_noactivate()
        if not self.overlay and not self.view.topmost:
            self.root.after(300, lambda: self.root.attributes('-topmost', False))

    # --- input ---------------------------------------------------------------
    def _resize(self, e):
        self.view.cw, self.view.ch = e.width, e.height

    def _md(self, e, btn):
        self.view.drag = True
        self.view.btn  = btn
        self.view.dx, self.view.dy = e.x, e.y
        self._click_xy = (e.x, e.y)
        self._win_drag = (e.x_root, e.y_root,
                          self.root.winfo_x(), self.root.winfo_y())
        # overlay: only a drag that STARTS on the title strip moves the panel;
        # a drag on the map body pans the view (C snaps back to the player)
        self._strip_drag = e.y <= 26

    def _mu(self, e):
        self.view.drag = False
        if self._click_xy is None:
            return
        cx, cy = self._click_xy
        self._click_xy = None
        if abs(e.x - cx) > 5 or abs(e.y - cy) > 5:
            return
        self._handle_click(e.x, e.y)

    def _handle_click(self, x, y):
        """Click (no drag): name the item symbol under the cursor, or rename the
        marker pin under it."""
        v = self.view
        if self.overlay and x >= v.cw - 22 and y <= 20:   # ✕ close button
            self._on_close()
            return
        for (sx, sy, kind, tid, hit_ox, hit_oz) in v.item_hits:
            if abs(sx - x) <= 9 and abs(sy - y) <= 9:
                import tkinter.simpledialog as sd
                if kind == 'barrel':
                    skey = scenery_key(tid, hit_ox, hit_oz)
                    cur = SCENERY_NAMES.get(skey, '')
                    if tid == 0:
                        scope = 'this object only (sprite 0 is shared by many types)'
                    else:
                        scope = f'all sprite-{tid} objects on this level'
                    name = sd.askstring(
                        "Object name",
                        f"Static object, sprite {tid} — what is it?\n"
                        f"Name applies to: {scope}\n"
                        "(a name containing light / lamp / vending hides this "
                        "kind from the map; U shows them again)",
                        initialvalue=cur, parent=self.root)
                    if name and name.strip():
                        SCENERY_NAMES[skey] = name.strip()
                        save_scenery_name(skey, name.strip())
                else:
                    cur = ITEM_NAMES.get(tid, '')
                    name = sd.askstring("Item name",
                                        f"Item type {tid} — what is it?",
                                        initialvalue=cur, parent=self.root)
                    if name and name.strip():
                        ITEM_NAMES[tid] = name.strip()
                        save_item_name(tid, name.strip())
                return
        for (sx, sy, kind, obj) in v.logic_hits:
            if abs(sx - x) <= 9 and abs(sy - y) <= 9:
                import tkinter.messagebox as mb
                if kind == 'switch':
                    lines = [f"Switch ({obj.get('file', '?')}) "
                             f"at ({obj['x']:.0f}, {obj['z']:.0f})"]
                    if obj.get('cond'):
                        lines.append(f"works when: {obj['cond']}")
                    for a in obj.get('actions', []):
                        if 'tx' in a:
                            lines.append(f"moves door/object {a['target']} at "
                                         f"({a['tx']:.0f}, {a['tz']:.0f}) "
                                         f"by {a['delta']}")
                        else:
                            lines.append(f"moves object {a['target']}")
                    if not obj.get('actions'):
                        lines.append(f"feeds trigger(s) {obj.get('ids')} "
                                     "(used by another switch/door's condition)")
                else:
                    lines = [f"Remote-operated door/object {obj.get('id')} "
                             f"at ({obj['x']:.0f}, {obj['z']:.0f})"]
                    for s in LOGIC_BY_DOOR.get(obj.get('id'), []):
                        lines.append(f"operated by switch at "
                                     f"({s['x']:.0f}, {s['z']:.0f})"
                                     + (f" when {s['cond']}" if s.get('cond') else ''))
                mb.showinfo("Level logic", "\n".join(lines), parent=self.root)
                return
        for i, (mx_, my_, mz_, label) in enumerate(v.markers):
            if not v.show_ambient and _AMBIENT_MARKER.search(label):
                continue   # hidden pins must not swallow clicks
            sx, sy = v.proj(mx_, my_, mz_)
            if abs(sx - x) <= 9 and abs(sy - y) <= 12:
                import tkinter.simpledialog as sd
                name = sd.askstring("Marker", "Label (empty = keep, '-' = delete):",
                                    initialvalue=label, parent=self.root)
                if name is not None and name.strip():
                    if name.strip() == '-':
                        del v.markers[i]
                    else:
                        v.markers[i] = (mx_, my_, mz_, name.strip())
                    save_markers(LEVEL, v.markers)
                return

    def _mm(self, e):
        v = self.view
        if not v.drag:
            return
        if self._click_xy and (abs(e.x - self._click_xy[0]) > 5 or
                               abs(e.y - self._click_xy[1]) > 5):
            self._click_xy = None   # it's a drag, not a click
        if self.overlay and v.btn == 1 and self._strip_drag:
            # drag that began on the title strip moves the whole panel
            x0r, y0r, wx, wy = self._win_drag
            self.root.geometry(f"+{wx + e.x_root - x0r}+{wy + e.y_root - y0r}")
            return
        dx = e.x - v.dx; dy = e.y - v.dy
        v.dx, v.dy = e.x, e.y
        if v.btn == 1:
            if v.follow:
                v.follow = False    # dragging detaches the camera
            v.panx += dx; v.pany += dy
        elif v.mode == '3d':
            v.autorot = False
            v.angle += dx * 0.01
            v.tilt   = max(0.2, min(1.5, v.tilt + dy * 0.01))

    def _mw(self, e):
        v = self.view
        f = 1.15 if e.delta > 0 else 1/1.15
        v.zoom = max(0.0015, min(0.4, v.zoom * f))

    def _key(self, e):
        self._key_action(e.keysym)

    def _key_action(self, k):
        v = self.view
        if k in ('o', 'O'):
            self.overlay = not self.overlay
            self._apply_window_mode()
        elif k in ('v', 'V'):
            steps = [0.5, 0.65, 0.8, 0.95]
            cur = min(range(len(steps)), key=lambda i: abs(steps[i] - self.alpha))
            self.alpha = steps[(cur + 1) % len(steps)]
            if self.overlay:
                self.root.attributes('-alpha', self.alpha)
            self._save_ui()
        elif k in ('b', 'B'):
            self._bring_to_front()
        elif k in ('l', 'L'):
            v.show_legend = not v.show_legend
        elif k == 'Tab':
            v.mode = '3d' if v.mode == '2d' else '2d'
        elif k in ('c', 'C'):
            v.follow = True
            v.panx = v.pany = 0.0
            v.y_override = None
            if v.zoom < 0.008:
                v.zoom = 0.022
        elif k in ('n', 'N'):
            v.autorot = not v.autorot
            if not v.autorot:
                v.rot = 0.0
        elif k in ('r', 'R'):
            v.follow = False
            v.autorot = False
            v.rot = 0.0
            v.fit_level()
        elif k in ('t', 'T'):
            if not self.overlay:   # overlay is always on top
                v.topmost = not v.topmost
                self.root.attributes('-topmost', v.topmost)
        elif k in ('Prior',):    # PgUp — one floor up
            v.y_override = (v.y_override if v.y_override is not None
                            else self.py) + FLOOR_STEP
        elif k in ('Next',):     # PgDn — one floor down
            v.y_override = (v.y_override if v.y_override is not None
                            else self.py) - FLOOR_STEP
        elif k in ('plus', 'equal', 'bracketright'):
            v.zoom = min(0.4, v.zoom * 1.15)
        elif k in ('minus', 'bracketleft'):
            v.zoom = max(0.0015, v.zoom / 1.15)
        elif k in ('i', 'I'):
            v.show_ids = not v.show_ids
            self._save_ui()
        elif k in ('u', 'U'):
            v.show_ambient = not v.show_ambient
            self._save_ui()
        elif k in ('z', 'Z'):
            v.show_wiring = not v.show_wiring
        elif k in ('x', 'X'):
            v.show_all_ents = not v.show_all_ents
            self.ents.show_all_ents = v.show_all_ents
        elif k in ('m', 'M'):
            self._drop_marker()
        elif k in ('Delete', 'BackSpace'):
            self._delete_nearest_marker()

    # --- markers -------------------------------------------------------------
    def _drop_marker(self):
        """Instant numbered pin at the player position — no dialog, the game
        keeps focus. Rename later by clicking the pin."""
        if not self._pos_established:
            return
        n = sum(1 for m in self.view.markers if m[3].startswith('#')) + 1
        self.view.markers.append((self.px, self.py, self.pz, f'#{n}'))
        save_markers(LEVEL, self.view.markers)

    def _delete_nearest_marker(self):
        if not self.view.markers or not self._pos_established:
            return
        best = min(range(len(self.view.markers)),
                   key=lambda i: (self.view.markers[i][0]-self.px)**2 +
                                 (self.view.markers[i][2]-self.pz)**2)
        # only delete if reasonably close (within 4000 units)
        mx, _, mz, _ = self.view.markers[best]
        if (mx-self.px)**2 + (mz-self.pz)**2 <= 4000**2:
            del self.view.markers[best]
            save_markers(LEVEL, self.view.markers)

    # --- helpers -------------------------------------------------------------
    def _check_savstate(self):
        self.sav_tick += 1
        if self.sav_tick % 5 != 0:
            return None
        savs = glob.glob('*.sav')
        if not savs:
            return None
        latest = max(savs, key=os.path.getmtime)
        if latest == self.last_sav:
            return None
        self.last_sav = latest
        pos = read_sav_pos(latest)
        if pos:
            self.px, self.py, self.pz = pos
            return f"SAV: X={pos[0]} Y={pos[1]} Z={pos[2]}"
        return None

    def _zone_for_pos(self, x, z, y):
        """Containing zone; with stacked floors prefer the one whose y-extent
        holds the player, then the vertically nearest."""
        cands = []
        for b in blocks:
            mn, mx = b['bounds']
            if mn[0] <= x <= mx[0] and mn[2] <= z <= mx[2]:
                cands.append(b)
        if not cands:
            return -1
        def ydist(b):
            mn, mx = b['bounds']
            if mn[1] - Y_SOLID_MARGIN <= y <= mx[1] + Y_SOLID_MARGIN:
                return (0, mx[1] - mn[1])
            return (1, min(abs(y - mn[1]), abs(y - mx[1])))
        return min(cands, key=ydist)['idx']

    def _update_heading(self, nx, nz, moved):
        """Velocity-based heading: direction of travel, exponentially smoothed.
        Only updates while actually moving so standing still keeps the last bearing."""
        if moved < 35:
            return
        h = math.atan2(nx - self._prev_x, nz - self._prev_z)
        # smooth on the unit circle to avoid ±pi wrap glitches
        k = min(1.0, moved / 600.0) * 0.45 + 0.15
        self._hvx = (1-k)*self._hvx + k*math.sin(h)
        self._hvy = (1-k)*self._hvy + k*math.cos(h)
        if self._hvx*self._hvx + self._hvy*self._hvy > 0.01:
            self.view.heading = math.atan2(self._hvx, self._hvy)

    def _load_first_level(self, newL):
        """AUTO detection resolved: hot-load the detected level and drop into
        the user's preferred overlay/window mode."""
        global LEVEL
        load_level(newL)
        load_geo_async(newL)
        self.view.markers = load_markers(LEVEL)
        self.view.follow = True
        self._first_pos = True
        self._pos_established = False
        self.root.title(f"Last Rites Automap — {LEVEL}")
        if self.overlay:
            self._apply_window_mode()

    def _draw_waiting(self):
        """Placeholder screen while AUTO detection is still resolving."""
        self.canvas.delete('all')
        w, h = self.view.cw, self.view.ch
        self.canvas.create_text(w/2, h/2 - 14,
            text="Waiting for a running level…",
            fill=COL_TEXT, font=('Segoe UI', 16, 'bold'), justify='center')
        self.canvas.create_text(w/2, h/2 + 24,
            text="Start Last Rites and load a mission — the map attaches by itself.\n"
                 "If it never attaches, close the map and attach automap.log\n"
                 "(it is written next to this file).",
            fill=COL_TEXT, font=('Segoe UI', 11), justify='center')
        self.status.config(text=self.reader.get_status())

    def _switch_level(self, newL):
        """Hot-swap the loaded map to newL (resets trail/visited/markers)."""
        if not find_json(newL):
            now = time.monotonic()
            if now - self._last_redetect > 30.0:
                self._last_redetect = now
                print(f"[automap] game is on {newL} but no {newL}_automap.json is bundled")
            return
        print(f"[automap] level change detected: {LEVEL} → {newL}")
        load_level(newL)
        load_geo_async(newL)
        v = self.view
        v.visited = set()
        v.trail = []
        v.cur_zone = -1
        v.y_override = None
        v.heading = None
        v.markers = load_markers(LEVEL)
        self._pos_established = False
        self._rej = []
        self._oob = 0
        self._first_pos = True
        self.root.title(f"Last Rites Automap — {LEVEL}")

    def _maybe_switch_level(self, ox, oz, zone_raw):
        """Fallback (no level-name string readable): player persistently outside
        this level's bounds → re-detect from position and hot-swap."""
        now = time.monotonic()
        if now - self._last_redetect < 3.0:
            return
        self._last_redetect = now
        newL = detect_level_from_pos(ox, oz, zone_raw)
        if newL and newL != LEVEL:
            self._switch_level(newL)

    # --- main loop -----------------------------------------------------------
    def _tick(self):
        # hotkeys arriving from the global hook thread
        try:
            while True:
                self._key_action(self.hotkey_q.get_nowait())
        except queue.Empty:
            pass

        # window-first startup: while AUTO detection is still resolving, show a
        # clear waiting screen instead of an empty map
        if LEVEL == 'AUTO' and not zones:
            with _DETECT_LOCK:
                dl = _DETECTED_LEVEL
            if dl:
                self._load_first_level(dl)
            else:
                self._draw_waiting()
                self.root.after(200, self._tick)
                return

        pos     = self.reader.get_pos()
        status  = self.reader.get_status()
        v       = self.view

        # close with the game: once attached, if the DOSBox process dies and no
        # new one shows up within a short grace period, exit the map too
        pid = self.reader.get_pid()
        if pid is not None and _proc_alive(pid):
            self._game_seen = True
            self._game_gone = None
        elif getattr(self, '_game_seen', False):
            if getattr(self, '_game_gone', None) is None:
                self._game_gone = time.monotonic()
            elif time.monotonic() - self._game_gone > 6.0:
                print("[automap] game closed -- exiting")
                self._on_close()
                return

        # overlay self-heals its on-top status (~2 s): fullscreen toggles and
        # focus changes can bury even a topmost window
        self._top_tick = getattr(self, '_top_tick', 0) + 1
        if self.overlay and self._top_tick % 25 == 0:
            self._raise_noactivate()

        # authoritative level identity: the game's own "levels\missNN" string.
        # Require 3 consecutive agreeing ticks so a mid-load transient can't flip the map.
        memL = self.reader.get_level()
        if memL and memL != LEVEL:
            self._lvl_pending += 1
            if self._lvl_pending >= 3:
                self._lvl_pending = 0
                self._switch_level(memL)
        else:
            self._lvl_pending = 0

        if pos:
            zone_raw, gx, gy, gz = pos[4], pos[1], pos[2], pos[3]
            # Session 83 calibration: world = raw/256 (sign_x = -1), verified 6/6
            ox_raw = -gx / 256.0
            oz_raw =  gz / 256.0
            oy_raw =  gy / 256.0

            in_bounds = (LVL_XMIN - 15000 <= ox_raw <= LVL_XMAX + 15000 and
                         LVL_ZMIN - 15000 <= oz_raw <= LVL_ZMAX + 15000)
            if not in_bounds:
                self._oob += 1
                # position fallback only when the level-name string is unreadable
                if self._oob >= 25 and not memL:
                    self._maybe_switch_level(ox_raw, oz_raw, zone_raw)
            else:
                self._oob = 0
                self._prev_x, self._prev_z = self.px, self.pz
                if not self._pos_established:
                    # First live reading: accept directly (px/pz start at 0).
                    self.px, self.pz = ox_raw, oz_raw
                    self._prev_x, self._prev_z = ox_raw, oz_raw
                    self._pos_established = True
                else:
                    # Accept/reject the position as a WHOLE — updating one axis from
                    # a contaminated reading drags the dot sideways off the track.
                    MAX_JUMP = 3000.0   # world units per 80ms tick (walking ≈ 200)
                    if abs(ox_raw - self.px) <= MAX_JUMP and abs(oz_raw - self.pz) <= MAX_JUMP:
                        self.px, self.pz = ox_raw, oz_raw
                        self._rej = []
                    else:
                        # Rejected: either an NPC spike, or the dot is stuck far from
                        # the real player. If 4 consecutive rejects agree with each
                        # other, they ARE the player — re-acquire there.
                        self._rej.append((ox_raw, oz_raw))
                        if len(self._rej) >= 4:
                            xs = [p[0] for p in self._rej[-4:]]
                            zs = [p[1] for p in self._rej[-4:]]
                            if max(xs)-min(xs) <= 2500 and max(zs)-min(zs) <= 2500:
                                self.px, self.pz = ox_raw, oz_raw
                                self._rej = []
                            else:
                                self._rej = self._rej[-6:]
                self.py = oy_raw

                moved = math.hypot(self.px - self._prev_x, self.pz - self._prev_z)
                self._update_heading(self.px, self.pz, moved)

                # breadcrumb trail
                if not v.trail or (math.hypot(self.px - v.trail[-1][0],
                                              self.pz - v.trail[-1][2]) > 120):
                    v.trail.append((self.px, self.py, self.pz))
                    if len(v.trail) > 4000:
                        del v.trail[:500]

                zone = self._zone_for_pos(self.px, self.pz, self.py)
                if zone >= 0:
                    v.cur_zone = zone
                    v.visited.add(zone)

                if self._first_pos:
                    self._first_pos = False
                    v.follow = True

                status = (f"Zone {v.cur_zone} | x={self.px:.0f} y={self.py:.0f} "
                          f"z={self.pz:.0f} | {status}")
        else:
            sav_msg = self._check_savstate()
            if sav_msg:
                status = sav_msg

        # live entities (NPC radar + objects)
        v.npcs, v.objs = self.ents.get()

        # camera follow + smooth auto-rotation
        v.player = [self.px, self.py, self.pz]
        if v.follow:
            v.camx, v.camz = self.px, self.pz
            v.panx = v.pany = 0.0
        if v.autorot and v.heading is not None:
            target = v.heading
            d = (target - v.rot + math.pi) % (2*math.pi) - math.pi
            v.rot += d * 0.18
            if v.mode == '3d':
                v.angle = v.rot
        t0 = time.perf_counter()
        v.render()
        if self.overlay:
            # close button — the borderless panel has no title bar
            self.canvas.create_text(v.cw - 11, 10, text='✕',
                                    font=('Segoe UI', 9), fill='#999999')
        self.status.config(text=status or "")
        # adaptive schedule: leave the Tk thread breathing room after slow 3D frames
        render_ms = (time.perf_counter() - t0) * 1000
        self.root.after(max(POLL_MS, int(render_ms * 0.6)), self._tick)

    def run(self):
        self.root.mainloop()

# ---------------------------------------------------------------------------
# Diagnostics entry points (--scan/--search/--watch) and startup
# ---------------------------------------------------------------------------
def raw_scan(handle):
    """Dump all committed allocations ≥512KB with key game offsets."""
    _PTR = ctypes.sizeof(ctypes.c_void_p)
    MAX_ADDR = 0x800_0000_0000 if _PTR == 8 else 0x1_0000_0000
    mbi = MEMORY_BASIC_INFORMATION()
    seen = set()
    addr = 0
    print(f"{'Base':>14}  {'Size':>8}  {'CF840_z':>8}  {'CF848_y/256':>12}")
    while addr < MAX_ADDR:
        sz = K32.VirtualQueryEx(handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if sz == 0:
            break
        if mbi.State == MEM_COMMIT:
            abase = mbi.AllocationBase or mbi.BaseAddress
            if abase not in seen:
                seen.add(abase)
                total_kb = mbi.RegionSize // 1024
                if total_kb >= 512:
                    def rdi(off):
                        d = _read_mem(handle, abase + off, 4)
                        return struct.unpack_from('<i', d)[0] if (d and len(d) == 4) else None
                    cf840 = rdi(0xCF840)
                    cf848 = rdi(0xCF848)
                    print(f"  0x{abase:08X}  {total_kb:>6}KB  "
                          f"{str(cf840) if cf840 is not None else 'rf':>8}  "
                          f"{str(cf848//256) if cf848 is not None else 'rf':>12}")
        addr = mbi.BaseAddress + max(mbi.RegionSize, 1)


# --- Background level detection (window-first startup) -----------------------
# The original auto_detect_level() blocked BEFORE the Tk window existed, so on a
# fresh machine (no DOSBox running yet, or a stale .membase copied from another
# PC) the exe sat silently in the background forever — the reported "click →
# nothing". Detection now runs in a daemon thread; the window shows "waiting for
# a running level" until it resolves, then hot-loads the detected level.
_DETECT_LOCK = threading.Lock()
_DETECTED_LEVEL = None

def detect_loop():
    """Resolve the live MemBase + loaded level WITHOUT a level already being
    loaded (find_base_static's BDA fingerprint needs no level data). Sets
    _DETECTED_LEVEL; the App polls it and hot-loads the level."""
    global FORCED_BASE, _DETECTED_LEVEL
    print("[automap] AUTO mode: waiting for a running level…")
    last_discovery = 0.0
    while True:
        with _DETECT_LOCK:
            if _DETECTED_LEVEL:
                return
        pid = find_dosbox_pid()
        base = FORCED_BASE if FORCED_BASE is not None else _load_saved_base()
        if pid:
            h = K32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
            if h:
                detected = None
                if base:
                    # primary: the game's own current-level string
                    d = _read_mem(h, base + OFF_LEVELNAME, 16)
                    if d:
                        m = _LEVELNAME_RE.match(d)
                        if m:
                            cand = 'MISS' + m.group(1).decode()
                            if find_json(cand):
                                detected = cand
                if base and not detected:
                    d = _read_mem(h, base + OFF_CF840, 16)
                    if d and len(d) == 16:
                        zone_raw, x, y, z = struct.unpack_from('<4i', d)
                        detected = detect_level_from_pos(-x/256.0, z/256.0, zone_raw)
                # DOSBox-version-independent: locate the game's own level-name
                # buffer ("levels\missNN" @ flat+0xCE0D0) — works whatever the
                # emulator's memory layout / CauseWay flat-DS placement is.
                if not detected:
                    flat2, lvl2 = find_flat_by_levelname(h)
                    if flat2 and lvl2 and find_json(lvl2):
                        _save_base(flat2)
                        FORCED_BASE = flat2
                        detected = lvl2
                if detected:
                    with _DETECT_LOCK:
                        _DETECTED_LEVEL = detected
                    K32.CloseHandle(h)
                    print(f"[automap] detected level: {detected}")
                    return
                # base missing or not reading the game — (re)discover it from the
                # BIOS Data Area fingerprint (throttled; it sleeps ~1.2s inside)
                now = time.monotonic()
                if not USER_FORCED and now - last_discovery > 3.0:
                    last_discovery = now
                    found = find_base_static(h)
                    if found:
                        _save_base(found)
                        FORCED_BASE = found
                K32.CloseHandle(h)
        time.sleep(2.0)


if __name__ == '__main__':
    if _args.scan:
        pid = find_dosbox_pid()
        if not pid:
            print("DOSBox not found.")
            sys.exit(1)
        handle = K32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not handle:
            print("OpenProcess failed.")
            sys.exit(1)
        raw_scan(handle)
        K32.CloseHandle(handle)
        sys.exit(0)

    if _args.watch:
        pid = find_dosbox_pid()
        if not pid:
            print("DOSBox not found."); sys.exit(1)
        handle = K32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        base = FORCED_BASE if FORCED_BASE is not None else _load_saved_base()
        if base is None:
            print("MemBase not found — run membase_static2.py first."); sys.exit(1)
        print(f"Watching 0x{base:X}.")
        def _ri(off, size=4):
            d = _read_mem(handle, base + off, size)
            if not d or len(d) != size: return None
            return struct.unpack_from('<H' if size==2 else '<i', d)[0]
        t0 = time.time()
        while True:
            zone = _ri(OFF_CF840); x = _ri(OFF_CF844); y = _ri(OFF_CF848); z = _ri(OFF_CF84C)
            def fv(v): return f"{v/256:9.0f}" if v is not None else "        ?"
            print(f"{int(time.time()-t0):5d}  zone={zone}  x={fv(x)} y={fv(y)} z={fv(z)}")
            time.sleep(0.25)

    if _args.self_test:
        # Dry-run of the detection chain, no window, safe with no game running.
        print("[self-test] looking for a DOSBox process...")
        pid = find_dosbox_pid()
        if not pid:
            print("[self-test] no DOSBox process found (this is fine if the game isn't running).")
            sys.exit(0)
        print(f"[self-test] DOSBox pid={pid}")
        handle = K32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not handle:
            print("[self-test] OpenProcess failed (insufficient rights?).")
            sys.exit(0)
        regions = _committed_regions(handle, 4 * 1024 * 1024)
        print(f"[self-test] {len(regions)} committed region(s) >= 4MB")
        flat, lvl = find_flat_by_levelname(handle)
        if flat is not None:
            print(f"[self-test] level-name scan: flat base 0x{flat:X}, level {lvl}")
        else:
            print("[self-test] level-name scan: no match (no mission loaded yet, or scan needs a retry).")
        K32.CloseHandle(handle)
        sys.exit(0)

    replace_previous_instance()
    if LEVEL == 'AUTO':
        # window-first: create the UI immediately and detect the level in the
        # background instead of blocking before the window exists
        threading.Thread(target=detect_loop, daemon=True).start()
    else:
        load_level(LEVEL)
        load_geo_async(LEVEL)
    App().run()
