#!/usr/bin/env python3
"""Build (and optionally sign + notarize) a standalone Stitcher app.

Plain local build — produces a double-clickable app under dist/:

    pip install -r requirements-dev.txt
    python build.py

macOS signed + notarized build (needs a paid Apple Developer account):

    python build.py \
        --sign "Developer ID Application: Your Name (TEAMID)" \
        --notary-profile stitcher-notary

Output:
    macOS   -> dist/Stitcher.app        (double-click to launch)
    Windows -> dist/Stitcher/Stitcher.exe
    Linux   -> dist/Stitcher/Stitcher

pyembroidery loads its per-format reader/writer modules dynamically, so we
pull them all in explicitly with --collect-submodules.

--- macOS signing / notarization setup (one time) ---

1. In Xcode / developer.apple.com create a "Developer ID Application"
   certificate and install it in your login keychain. Confirm it with:

       security find-identity -v -p codesigning

2. Store notary credentials in the keychain once (uses an app-specific
   password from appleid.apple.com, NOT your Apple ID password):

       xcrun notarytool store-credentials stitcher-notary \
           --apple-id you@example.com --team-id TEAMID \
           --password xxxx-xxxx-xxxx-xxxx

Then pass --sign and --notary-profile as shown above.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
ENTITLEMENTS = ROOT / "packaging" / "entitlements.plist"
ASSETS = ROOT / "stitcher" / "assets"
ICON_ICNS = ROOT / "packaging" / "Stitcher.icns"   # macOS app icon
ICON_ICO = ROOT / "packaging" / "Stitcher.ico"     # Windows app icon

# Leading 4 bytes of Mach-O objects (thin 32/64-bit + fat/universal, both
# endiannesses). Used to find every binary that must be signed inside the app.
_MACHO_MAGIC = {
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",   # 32-bit
    b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",   # 64-bit
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",   # fat / universal
}


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def build_app(bundle_id: str) -> None:
    import PyInstaller.__main__  # imported lazily so --help works without it

    # bundle the runtime assets (app icon shown in the window / dock / taskbar)
    add_sep = ";" if sys.platform == "win32" else ":"
    args = [
        str(ROOT / "main.py"),
        "--name", "Stitcher",
        "--windowed",              # GUI app: no console window
        "--noconfirm",             # overwrite a previous build
        "--clean",
        "--osx-bundle-identifier", bundle_id,
        "--collect-submodules", "pyembroidery",
        "--add-data", f"{ASSETS}{add_sep}stitcher/assets",
    ]

    # per-platform packaged-app icon (ignored on Linux)
    icon = ICON_ICNS if sys.platform == "darwin" else ICON_ICO
    if sys.platform in ("darwin", "win32") and icon.exists():
        args += ["--icon", str(icon)]

    PyInstaller.__main__.run(args)


def _is_macho(path: pathlib.Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(4) in _MACHO_MAGIC
    except OSError:
        return False


def _iter_macho(app: pathlib.Path):
    """Every Mach-O file inside the bundle, deepest paths first (sign inside-out)."""
    files = [p for p in app.rglob("*") if p.is_file() and not p.is_symlink() and _is_macho(p)]
    files.sort(key=lambda p: len(p.parts), reverse=True)
    return files


def sign_app(app: pathlib.Path, identity: str) -> None:
    """Deep-sign the bundle with the hardened runtime + secure timestamp."""
    if not ENTITLEMENTS.exists():
        raise SystemExit(f"Missing entitlements file: {ENTITLEMENTS}")

    base = ["codesign", "--force", "--options", "runtime", "--timestamp", "--sign", identity]

    # 1. Sign every nested binary first (frameworks, dylibs, .so extensions).
    for binary in _iter_macho(app):
        if binary == app / "Contents" / "MacOS" / app.stem:
            continue  # the main executable is signed with the bundle, below
        _run(base + [str(binary)])

    # 2. Sign the bundle itself, attaching entitlements to the main executable.
    _run(base + ["--entitlements", str(ENTITLEMENTS), str(app)])

    _run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)])
    print("Signed and verified:", app)


def notarize_app(app: pathlib.Path, profile: str) -> None:
    """Zip, submit to Apple's notary service, wait, then staple the ticket."""
    zip_path = app.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()

    _run(["ditto", "-c", "-k", "--keepParent", str(app), str(zip_path)])
    _run([
        "xcrun", "notarytool", "submit", str(zip_path),
        "--keychain-profile", profile, "--wait",
    ])
    _run(["xcrun", "stapler", "staple", str(app)])
    _run(["xcrun", "stapler", "validate", str(app)])
    print("Notarized and stapled:", app)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the standalone Stitcher app.")
    parser.add_argument(
        "--bundle-id", default=os.environ.get("STITCHER_BUNDLE_ID", "com.stitcher.app"),
        help="macOS bundle identifier (default: com.stitcher.app).",
    )
    parser.add_argument(
        "--sign", default=os.environ.get("STITCHER_SIGN_IDENTITY"),
        metavar="IDENTITY",
        help='Developer ID Application identity, e.g. "Developer ID Application: Name (TEAMID)".',
    )
    parser.add_argument(
        "--notary-profile", default=os.environ.get("STITCHER_NOTARY_PROFILE"),
        metavar="PROFILE",
        help="notarytool keychain profile name (implies --sign).",
    )
    args = parser.parse_args()

    signing = bool(args.sign or args.notary_profile)
    if signing and sys.platform != "darwin":
        parser.error("--sign / --notary-profile are only supported on macOS.")
    if args.notary_profile and not args.sign:
        parser.error("--notary-profile requires --sign.")

    build_app(args.bundle_id)

    if not signing:
        return

    app = ROOT / "dist" / "Stitcher.app"
    if not app.exists():
        raise SystemExit(f"Expected {app} after build; nothing to sign.")
    sign_app(app, args.sign)
    if args.notary_profile:
        notarize_app(app, args.notary_profile)


if __name__ == "__main__":
    main()
