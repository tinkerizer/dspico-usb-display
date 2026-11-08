# Changelog

Each release's version is in [VERSION](VERSION). `tools/release --publish` uses the section for that
version as the release notes.

## Unreleased

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
