import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# The spec lives in build/. PROJECT_ROOT is the repository checkout so that
# templates, static assets and the temporary app_scope profile keep their
# existing locations.
PROJECT_ROOT = Path(SPECPATH).resolve().parent
BUILD_SCOPE = os.environ.get("DOWFLOW_BUILD_SCOPE", "all")
BUILD_NAME = os.environ.get("DOWFLOW_BUILD_NAME", "DowFlow")

if BUILD_SCOPE not in {"all", "video", "music", "film", "anime"}:
    raise ValueError(f"Unsupported DowFlow build scope: {BUILD_SCOPE}")

template_sets = {
    "all": [
        "menu.html", "download.html", "coming_soon.html",
        "stats.html",
    ],
    "video": ["download.html", "stats.html"],
    "music": [],
    "film": ["coming_soon.html"],
    "anime": ["coming_soon.html"],
}
templates = [(str(PROJECT_ROOT / "templates" / name), "templates") for name in template_sets[BUILD_SCOPE]]
static_files = [
    "favicon.svg", "dowflow.ico", "app.css",
    "dependencies-loading.js", "dependencies-loading.css", "update.js",
]
datas = templates + [(str(PROJECT_ROOT / "static" / name), "static") for name in static_files]
profile_file = PROJECT_ROOT / "build" / "app_scope.json"
if profile_file.is_file():
    datas.append((str(profile_file), "portable_data"))
binaries = []
hiddenimports = ["tkinter", "tkinter.filedialog", "folder_picker", "webview"]
if BUILD_SCOPE in {"all", "music"}:
    hiddenimports.append("music")

for package in ("flask", "jinja2", "werkzeug", "waitress", "yt_dlp", "playwright", "requests", "rich", "webview"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    if package == "playwright":
        # The bundled Node runtime is about 120 MB in the build environment.
        # Installed builds use the shared node.exe in <data>/tools; the
        # portable fallback downloads one into <data>/bin.
        def is_playwright_node(item):
            source = str(item[0]).lower()
            return Path(source).name in {"node", "node.exe"} and "playwright" in source and "driver" in source

        package_datas = [item for item in package_datas if not is_playwright_node(item)]
        package_binaries = [
            item for item in package_binaries if not is_playwright_node(item)
        ]
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

# Installer builds must never embed the developer's database, configuration or
# cookie exports. Portable seed data is opt-in so a release stays clean.
portable_files = []
if os.environ.get("DOWFLOW_EMBED_PORTABLE_DATA") == "1":
    portable_files = [
        (PROJECT_ROOT / "dowflow.db", "portable_data"),
        (PROJECT_ROOT / "dowflow.db-wal", "portable_data"),
        (PROJECT_ROOT / "portable_data" / "config.json", "portable_data"),
        (PROJECT_ROOT / "youtube.com_cookies.txt", "portable_data"),
    ]
for source, target in portable_files:
    if source.is_file():
        datas.append((str(source), target))

a = Analysis(
    [str(PROJECT_ROOT / "launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "setuptools",
        "test_download",
        "test_music",
        *( ["music", "music_dataset"] if BUILD_SCOPE == "video" else []),
    ],
    noarchive=False,
    optimize=0,
)
def is_playwright_runtime(item) -> bool:
    # PyInstaller's own Playwright hook can pull driver/node.exe back in after
    # collect_all(); installed builds use the shared tools/node/node.exe.
    for part in item[:2]:
        source = str(part).lower()
        if Path(source).name in {"node", "node.exe"} and "playwright" in source and "driver" in source:
            return True
    return False


a.datas = [item for item in a.datas if not is_playwright_runtime(item)]
a.binaries = [item for item in a.binaries if not is_playwright_runtime(item)]

pyz = PYZ(a.pure)

# One directory install: DowFlow.exe is the bootloader and everything else
# stays in _internal/. Nothing is extracted to %TEMP% at launch.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=BUILD_NAME,
    icon=str(PROJECT_ROOT / "static" / "dowflow.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=BUILD_NAME,
)
