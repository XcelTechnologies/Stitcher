# Stitcher

A small embroidery design app: draw strokes, fill shapes, and stitch lettering
on a hoop, watch a live stitch preview, and export machine files (DST, PES, EXP,
JEF, VP3, XXX, U01) or SVG/PNG — built on
[pyembroidery](https://github.com/EmbroidePy/pyembroidery) and
[PySide6](https://doc.qt.io/qtforpython/).

## Run from source

```bash
pip install -r requirements.txt
python main.py
```

## Using it

Pick a **Tool** from the toolbar, set its options, then work on the hoop. Every
object keeps its own thread colour and settings, so change them between objects
as you like.

- **Select / move** — click an object to select it (a dashed box appears), drag
  to reposition it, and press `Delete` (or `Backspace`) to remove it. You can
  also **Shift+click** an object with *any* tool active to select it without
  switching tools.
- **Edit a selection** — while an object is selected, the toolbar switches to
  that object's settings and editing them changes *that object* live (rather than
  setting defaults for the next one). Shift+click a text box, for example, and the
  toolbar shows its font, height and colour; change them and the lettering
  updates. Strokes expose stitch type / satin width, fills expose row spacing /
  angle, and everything exposes colour, stitch length and underlay. Click empty
  space to deselect and the toolbar returns to new-object settings.
- **Stroke** — press, drag, and release to lay down one continuous needle run.
  The **Stitch** menu chooses how it's sewn:
  - *Running* — a single line of evenly spaced stitches.
  - *Bean (triple)* — each stitch sewn forward-back-forward for a bolder line.
  - *Satin* — a smooth zig-zag column; **Width mm** sets how wide it is.
- **Fill region** — press, drag, and release to trace a closed outline; it's
  filled with parallel (tatami) rows. **Row mm** sets the gap between rows and
  **Angle°** their direction.
- **Text** — click where you want the lettering, then type it. Pick any system
  **Font** and set the cap **Height mm**; the glyph outlines are filled with the
  same tatami rows (letter holes like *o*, *a*, *e* are kept open). Fills and
  text share the **Row mm** / **Angle°** controls. **Double-click** an existing
  text to re-type its string (clearing it removes the text).
- **Underlay** — for satin columns and fills, sews a stabilizing pass first (a
  centre run under satin, an outline run under fills) so the cover stitches sit
  up instead of sinking into the fabric. On by default; toggle it in the toolbar.
- **Thread / Stitch mm** — pick a palette colour (or *Custom…*) and the stitch
  length used along a run or fill row.
- **Preview** — the right pane renders the actual encoded pattern: coloured
  stitches, dashed jumps, and needle points, plus tie-in/tie-off tacks.
- **File** — New, Open, Save, Save As, Import, and Export. Projects are saved as
  `.stitch` (JSON); Export writes the machine format chosen in the dialog. Older
  `.stitch` files (strokes only) still open.
- **Import** — open an existing machine file (DST, PES, EXP, JEF, VP3, XXX, U01)
  and it's converted into editable running strokes you can select, move, recolour
  and re-export. Conversion is lossy: a machine file only stores stitches, so
  everything comes in as running stitches in its original thread colours.
- **Trace image** — auto-digitize a picture. Any format your Qt build can read
  works (PNG, JPG, BMP, GIF, TIFF, WebP, HEIC, …), plus **SVG** vector art (which
  is rasterized at high resolution first). An options dialog lets you set the
  number of **thread colours**, the **target width** (how big the art lands on
  the hoop — height follows the aspect ratio; leave it to fit the hoop), the
  **fill angle**, and a **min region size** to drop specks. The picture is
  quantized to that many colours and each colour becomes one editable fill
  **region** (holes and separate blobs are handled, so counters and cut-outs stay
  open). Then tidy it up with the tools above — recolour, re-angle, move or delete
  regions (e.g. remove a background). Works best on flat-colour logos, clip-art
  and vector graphics; photographs need true photo-stitch and won't trace well.

Keyboard: `Ctrl+N` new, `Ctrl+O` open, `Ctrl+S` save, `Ctrl+Shift+S` save as,
`Ctrl+I` import, `Ctrl+T` trace image, `Ctrl+E` export, `Ctrl+Z` undo the last
object.

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite (`tests/`) covers the data model and serialization, stitch generation
(running / bean / satin, tatami fills, holes, underlay), machine-file export and
import, text-outline and image tracing, and the canvas / window behaviour
(hit-testing, selection, live editing). Qt runs headless via the *offscreen*
platform, so no display is needed.

## Build a standalone app

```bash
pip install -r requirements-dev.txt
python build.py
```

This produces a double-clickable app under `dist/`:

- **macOS** — `dist/Stitcher.app`
- **Windows** — `dist/Stitcher/Stitcher.exe`
- **Linux** — `dist/Stitcher/Stitcher`

Build on the OS you want to target — PyInstaller does not cross-compile.

### App icon

The icon lives in `stitcher/assets/icon.svg` and shows up in the window, dock
and taskbar at runtime. Pre-rendered raster icons for packaging sit in
`packaging/` (`Stitcher.icns` for macOS, `Stitcher.ico` for Windows) and are
passed to PyInstaller automatically by `build.py`. To change the logo, replace
`icon.svg` and re-generate the assets:

```bash
python -c "from stitcher.assets import regenerate; regenerate()"
```

### Signing & notarizing the macOS app

To hand `Stitcher.app` to other people without a Gatekeeper warning, sign and
notarize it. This needs a paid Apple Developer account (a **Developer ID
Application** certificate).

One-time setup:

```bash
# 1. Confirm your signing identity is in the keychain:
security find-identity -v -p codesigning

# 2. Store notary credentials once (app-specific password from appleid.apple.com):
xcrun notarytool store-credentials stitcher-notary \
    --apple-id you@example.com --team-id TEAMID \
    --password xxxx-xxxx-xxxx-xxxx
```

Then build, sign, and notarize in one step:

```bash
python build.py \
    --sign "Developer ID Application: Your Name (TEAMID)" \
    --notary-profile stitcher-notary
```

`build.py` deep-signs every nested binary with the hardened runtime, signs the
bundle with `packaging/entitlements.plist`, submits it to Apple's notary
service (`--wait`), and staples the ticket. Pass only `--sign` to sign without
notarizing. Override the bundle id with `--bundle-id` (default
`com.stitcher.app`).
