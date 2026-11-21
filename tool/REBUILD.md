# Rebuilding the standalone `.exe`

`automap.py` is the canonical source. The standalone `LastRitesAutomap.exe` is
just that file frozen with PyInstaller — it contains a **copy** of `automap.py`,
so any source fix only reaches users of the `.exe` after a rebuild.

## When to rebuild

- After **any** change to `dist_automap/LastRitesAutomap/automap.py`.
- After changing the bundled data files in `.../LastRitesAutomap/data/`.

## How

The PyInstaller specs live in `dist_automap/exe_build/`:

- `LastRitesAutomap.spec`        — release build (`console=False`, windowed).
- `LastRitesAutomap_debug.spec`  — `console=True`, for `--scan`/`--watch` diagnosis.

```bat
cd C:\reverse_engineering\lr\dist_automap\exe_build
pyinstaller LastRitesAutomap.spec          --noconfirm --clean
```

The `.spec` pins the Python 3.13 path under `WindowsApps`; adjust it if you
build with a different interpreter.

Output:
- `exe_build/dist/LastRitesAutomap.exe` — copy this to
  `dist_automap/exe_dist/LastRitesAutomap/LastRitesAutomap.exe` (that is the
  file `make_dist.py` zips).

## Package the release zips

```bat
cd C:\reverse_engineering\lr\dist_automap
python make_dist.py 1.5
```

This writes, next to the script:

- `LastRitesAutomap_v1.5.zip`             — source flavour (needs Python 3).
- `LastRitesAutomap_v1.5_standalone.zip`  — the `.exe` flavour (no Python).

Both include `Install Last Rites Automap.bat` at the top level, and exclude all
machine-specific state (`.membase`, `automap.pid`, `ui_state.json`, logs,
`__pycache__`). Upload **the zips** as the GitHub release — do not point people
at the repo tree (they cannot download a folder from it).

## Checklist before a release

1. `python -m py_compile automap.py` passes.
2. Rebuilt the `.exe` (above) and copied it to `exe_dist/`.
3. Bumped the version in `make_dist.py`, `README.txt`, `README.md`,
   `FORUM_POST.md`.
4. Deleted `.membase`, `automap.pid`, `ui_state.json`, `__pycache__`, `*.log`
   from `LastRitesAutomap/` before zipping (make_dist.py also excludes them,
   but the source folder should stay clean).
5. Ran `python make_dist.py <version>` and attached both zips.
