import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

PROJECT_ROOT = Path(SPECPATH).resolve()
BUILD_SCOPE = os.environ.get("DOWFLOW_BUILD_SCOPE", "all")
BUILD_NAME = os.environ.get("DOWFLOW_BUILD_NAME", "DowFlow")

if BUILD_SCOPE not in {"all", "video", "music", "film", "anime", "image"}:
    raise ValueError(f"Unsupported DowFlow build scope: {BUILD_SCOPE}")

template_sets = {
    "all": [
        "menu.html", "download.html", "music.html", "music_explore.html",
        "music_liked.html", "coming_soon.html", "export_controls.html",
    ],
    "video": ["download.html", "export_controls.html"],
    "music": [
        "music.html", "music_explore.html", "music_liked.html",
        "export_controls.html",
    ],
    "film": ["coming_soon.html", "export_controls.html"],
    "anime": ["coming_soon.html", "export_controls.html"],
    "image": ["coming_soon.html", "export_controls.html"],
}
templates = [(str(PROJECT_ROOT / "templates" / name), "templates") for name in template_sets[BUILD_SCOPE]]
static_files = [
    "favicon.svg", "dowflow.ico", "export.js", "export.css",
    "dependencies-loading.js", "dependencies-loading.css",
]
if BUILD_SCOPE in {"all", "music"}:
    static_files += ["music.css", "music.js"]

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
        # DowFlow installs a verified portable node.exe in the selected root/bin
        # on first launch and points Playwright to it at runtime.
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

# Initial mutable data is extracted into the user-selected portable root.
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
    [str(PROJECT_ROOT / "startup.py")],
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
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
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
