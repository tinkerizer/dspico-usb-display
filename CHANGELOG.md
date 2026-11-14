# Changelog

Each release's version is in [VERSION](VERSION). `tools/release --publish` uses the section for that
version as the release notes.

## 1.3.1

- **DS updates ask first:** when the app comes with a newer DS app, the editor asks before sending
  it. A no lasts until the PC app is restarted.
- **New versions:** the installed app looks on GitHub once a day for a newer release, and the
  editor shows a link to it. Nothing is downloaded or installed by itself.
- **Shells:** both are drawn with gradients over one plastic colour. The DS Lite is re-measured:
  a larger lower screen surround that runs up to the hinge, larger corner pads, a softer shadow
  under the hinge, and evenly lit buttons. The DSi's screen border matches the DS Lite's.
- **Steadier page:** the tiles under the DS and the page's grid stay put when the shell changes,
  and Layers and JSON are the same width, so switching between them no longer moves the screens.

## 1.3.0

- **Sleep on more PCs:** the sleep screen now shows when the PC suspends its USB ports, which used
  to leave the DS black, and the dashboard always comes back after waking. The DS no longer treats
  a suspended port as a closed one, and the app starts a fresh session after any long pause. Needs
  DS build 18, which the app installs by itself.
- **Pulled cable:** the DS shows the sleep screen, as it can't tell that from a sleeping PC.
- **Settings beside the DS:** themes, colours, brightness and the sleep screen are always in a
  panel next to the preview, so changes show as you make them. Colour changes save to the theme
  as you go, with **Undo** (Ctrl+Z) to step back. Folded sections stay folded.
- **Themes as pictures:** each theme's card shows its real layout. **Export** saves a theme as a
  zip and **Import** adds one, so sharing no longer means finding the data folder.
- **Sleep preview:** **Preview** under **When the PC sleeps** shows the sleep screen in the page.
  The preview also dims with the brightness slider, as the DS does.
- **Under the DS:** the preview has an **Edit** tile, the DS Lite or DSi switch and the shell
  colours, all on the page's grid. The tools show only in the editor.
- **Select several:** Shift+click adds to the selection, to move, line up, copy or delete
  together. Each element has line-up buttons, and **Copy** (Ctrl+D) duplicates it.
- **Shortcuts:** E opens and closes the editor, L the layers, J the JSON, Ctrl+A selects all.
- **Whole pixels:** positions typed with a half pixel are rounded, and snapping no longer
  claims a centre it can't reach. The bottom screen's boxes were a pixel too wide for the grid
  behind them, with their contents off centre, and the top screen's background had a stray line
  down its right and bottom edges. Layouts and themes from earlier versions are corrected where
  they still have the old values.
- **The page's own look:** buttons, icons, the stylus and sounds no longer come from the active
  theme's folder, so a theme with different art can't change or break the page. Light mode's
  buttons match dark mode's, and the light and dark switch is a sun or moon.
- **DS Lite shell:** the hinge's ends are shaded as half spheres, its middle is the same height
  as its ends, and the shell is one flat colour like the DSi's. On both shells the D-pad's dark
  surround stays put when the pad is pressed.
- **Faster page:** the page's font is 56 KB instead of 4 MB, the app pushes changes to the page
  instead of being asked every second, and sounds load with the page, so the first click isn't
  late.

## 1.2.0

- **Sleep screen:** when the PC sleeps, the DS shows a sleeping cat at low brightness on black,
  instead of the last picture at full brightness. Each theme picks its GIF, screen and brightness,
  or just black, under **When the PC sleeps** in the DS theme menu. Needs DS build 17, which the app
  installs by itself.

## 1.1.0

- **Themes are whole dashboards:** each theme is a folder with its own layout, colours, art,
  sounds and uploads, so switching theme switches everything. Save as copies the whole theme.
  Changing Classic or Dark keeps a copy of your own, and **Reset** puts the original back.
- **Moving over:** saved themes become folders. The shared layout and uploads go to the active
  theme and your saved ones, and the old `layout.json` is kept as `layout.json.old`.

## 1.0.1

- **Releases:** `tools/release --publish` works on a public repository too.

## 1.0.0

The first versioned release.

- **Editor:** the page shows the whole DS, and clicking a screen opens a screens-only editor at
  twice the size or more. **Done** or Esc goes back.
- **Pixel perfect or Fill:** keep every DS pixel sharp, or make the DS as big as the window allows.
- **Snapping and nudging:** widgets snap to the screens and to each other, with guide lines. Alt
  places freely, and the arrow keys move the selection.
- **Templates:** an element made of other elements, described in a JSON file. The top bar is now
  one, with its colour picked from pictures. See [docs/THEMES.md](docs/THEMES.md).
- **Element types:** each is one Python file in `app/dsdash/elements/`.
- **GIF transparency on the DS:** live text and graphs show through the transparent parts of an
  animation. This needs DS build 14, which the app installs by itself.
- **Layout:** tools with their names under the DS, Layers and JSON in a drawer on the right, and
  dark buttons in dark mode.
- **Fixes:** pressing the shell's buttons no longer shifts the screens by half a pixel.
- **Licence:** GPL 3 or later. Third-party licences are listed in THIRD_PARTY.md.
- **USB name:** the DS calls itself "DS Display" over USB (DS build 15).
