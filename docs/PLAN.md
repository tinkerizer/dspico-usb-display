# Features and roadmap

What DS Display does today, and what's planned. Changes by version are in the
[changelog](../CHANGELOG.md). Notes for working on the code are in [DESIGN.md](DESIGN.md).

## On the DS

- [x] Live PC stats: CPU, RAM, GPU load and memory, temperature, disk and network
- [x] Clock, calendar, date and the PC's name
- [x] Your own images, and GIFs that play on the DS itself, with live values showing through
      their transparent parts
- [x] Up to 8 GIFs at once, 512 KB in all
- [x] Brightness set from the PC
- [x] Sleep screen when the PC sleeps or the cable is pulled: a GIF at low brightness, or black
- [x] The dashboard comes back by itself when the PC wakes or the cable goes back in
- [x] Works on a DS Lite or DSi with a DSpico
- [x] The DS app updates itself over USB, with no need to take the SD card out
- [ ] Sleep screen the moment the PC sleeps, instead of after 5 seconds
- [ ] Start the display straight from power-on
- [ ] Use the DS's buttons and touch screen
- [ ] Bigger and smoother large GIFs

## Editor

- [x] Live preview inside a drawn DS Lite or DSi, in any shell colour
- [x] Click a screen to edit at 2× or more, with the DS updating as you go
- [x] Drag, resize, snap to edges and other elements, and nudge with the arrow keys
- [x] Select several elements to move, line up, copy or delete together
- [x] Undo and redo
- [x] Crop images and GIFs, and keep pixel art at whole-pixel sizes
- [x] Layers list, and the layout as JSON for editing by hand
- [x] Keyboard shortcuts
- [x] Light and dark mode
- [x] Preview of the sleep screen and of the brightness
- [ ] Sharp preview at 125% and 150% Windows scaling
- [ ] Show the DS's status and logs

## Themes

- [x] A theme is a whole dashboard: layout, colours, images and GIFs in one folder
- [x] Classic and Dark built in
- [x] Change a theme's colours, save copies, and reset the built-in ones
- [x] Export a theme as a zip, and import one
- [x] Templates: new elements built from existing ones, in a JSON file. See [THEMES.md](THEMES.md)
- [ ] Battery and volume indicators from the menu art
- [ ] Choose the clock's and calendar's art for each element

## PC app

- [x] One installer for Windows, with no admin rights needed
- [x] Runs from the system tray and starts with Windows
- [x] Reconnects by itself when the DS is plugged in
- [x] GPU stats on NVIDIA cards, and on other cards through Windows
- [ ] Remember the brightness between runs
