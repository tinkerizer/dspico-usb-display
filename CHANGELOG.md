# Changelog

Each release's version is in [VERSION](VERSION). `tools/release --publish` uses the section for that
version as the release notes.

## Unreleased

- **Theme folders:** each theme is a folder with its colours and all of its art and sounds, in
  `app/assets/themes/` or, for your own, the app's data folder. Saved themes are converted on first
  start, with a copy of Classic's art.

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
