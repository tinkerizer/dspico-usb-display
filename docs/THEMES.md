# Themes and templates

There are three ways to change how the DS looks, from simplest to most work.

| Change | How | Where |
|---|---|---|
| Everything on the DS | A theme: a folder with its layout, colours, images and sounds | The editor, or `themes/` folders |
| An element made of other elements | A template: a JSON file | `templates/` folder |
| A new kind of drawing, such as a new graph | An element type: one Python file | `app/dsdash/elements/` |

## Themes

A theme is the whole dashboard: its layout, colours, images, GIFs and sounds, in one folder. Two
themes can look nothing alike, and a theme can be copied or shared as a folder. Themes don't share
files: the same image in two themes is two copies.

```
classic/
  theme.json        name, colours, sleep screen and layout
  uploads/          images and GIFs added in the editor
  sleep/            the sleep screen's GIF
  background/       menu backgrounds
  battery/  grf/  quickmenu/  topbar/  ui/  volume/
  sound/            the editor's sounds
```

```json
{"name": "Classic", "paper": "#ffffff", "ink": "#000000", "boost": 0, "lift": 0, "bar": 11,
 "sleep": {"file": "art:sleep/sleepy_cat.gif", "screen": "top", "brightness": 30},
 "layout": {"version": 1, "elements": [...]}}
```

| Field | Meaning |
|---|---|
| `name` | Shown in the editor, up to 24 characters |
| `paper`, `ink` | Greys in the art are mapped from ink (black) to paper (white) |
| `boost` | 0 to 100: how much brighter colours get |
| `lift` | 0 to 60: how dark a grey has to be to become full ink |
| `bar` | 0 to 15: the top bar's colour, one of the DS profile colours |
| `sleep` | What the DS shows while the PC sleeps, below |
| `layout` | The elements, as the editor's JSON tab shows them |

### Sleep screen

When the app stops sending, as when the PC sleeps, the DS waits 5 seconds and then shows the sleep
screen: black, with the theme's sleep GIF playing at its own brightness. It's set in the **DS
theme** menu, under **When the PC sleeps**, and saved as you change it.

- `file`: a GIF in the theme's folder, or `""` for just black. The GIF is cropped to what's drawn
  in it, ignoring its background colour, shrunk if it's bigger than a screen, and centred.
- `screen`: `top` or `bottom`.
- `brightness`: 0 to 100.

When the PC is back, the dashboard returns as it was.

The app loads themes from two folders when it starts:

- `app/assets/themes/`: the built-in ones, Classic and Dark.
- `%LOCALAPPDATA%\DSDisplay\data\themes\`: your own, and your changes to the built-in ones.

Editing works on the active theme, and switching themes switches the layout too.

- **Save as a new name**, in the **DS theme** menu, copies the whole active theme: layout, art and
  uploads.
- **Changing a built-in theme** writes a copy of it to your folder, which is used from then on.
  **Reset** puts the original back.
- **Delete** removes one of your themes, with its folder.

`art:` paths, like `art:topbar/11.png` or `art:uploads/cat.gif`, come from the active theme's
folder, as do the editor's own buttons, icons and sounds. Restart the app to pick up art you've
changed outside the editor.

## Templates

A template is an element built from other elements, such as the top bar: a bar image, a name, the
time and date, and two icons. Its settings appear in the editor's settings panel when it's selected,
like any other element's. Templates contain no code, so they're safe to share.

The app loads every `.json` file in two folders when it starts:

- `app/assets/templates/`: the built-in ones, such as [top_bar.json](../app/assets/templates/top_bar.json).
- `%LOCALAPPDATA%\DSDisplay\data\templates\`: your own, or ones you've been sent. A file here with the
  same `type` as a built-in one replaces it.

A file that doesn't load is skipped, and the reason is written to `%LOCALAPPDATA%\DSDisplay\dsdisplay.log`.
Restart the app to pick up changes.

### The file

```json
{
  "type": "top_bar",
  "label": "Top bar",
  "size": [256, 16],
  "props": [
    {"key": "colour", "label": "Bar colour", "kind": "swatch", "default": "theme", "theme": "bar",
     "options": ["theme", "0", "1"], "preview": "art:topbar/{value}.png"},
    {"key": "show_time", "label": "Show time", "kind": "select", "options": ["yes", "no"], "default": "yes"}
  ],
  "children": [
    {"id": "bar", "type": "image", "x": 0, "y": 0, "w": 256, "h": 16, "props": {"file": "art:topbar/{colour}.png"}},
    {"id": "time", "type": "text", "x": 144, "y": 2, "w": 30, "h": 12, "if": "show_time",
     "props": {"text": "{time}", "align": "center"}}
  ]
}
```

| Field | Meaning |
|---|---|
| `type` | The element type's name: lower case letters, digits and `_` |
| `label` | What the editor calls it, in the **Add** menu and settings panel |
| `size` | Width and height in DS pixels. Templates can be moved but not resized. |
| `props` | Its settings, below |
| `children` | The elements it's made of, placed relative to its top-left corner |

### Settings

Each setting has a `key`, a `label`, a `kind` and a `default`:

| Kind | Shown as | Extra fields |
|---|---|---|
| `text` | A text box | |
| `number` | A number box | `min`, `max` |
| `color` | A colour picker | |
| `select` | A list, or a switch for `["yes", "no"]` | `options` |
| `swatch` | Pictures to pick from | `options`, and `preview`: a file with `{value}` in it |
| `file` | A list of images | |

A setting can follow the theme: give it `"theme": "bar"`, and the value `"theme"` then means the
active theme's bar colour. Any other value stays fixed whatever the theme.

### Children

A child is any built-in element: `image`, `text`, `clock`, `calendar`, `bar`, `graph`, `panel`,
`button`, `usb` or `temperature`. Templates can't contain other templates.

- **Filling in settings:** `{key}` in a child's props is replaced by that setting's value, so
  `art:topbar/{colour}.png` picks the bar image. Anything else in braces, like `{time}`, is left for
  the element to fill in as it draws. The tokens are listed in the editor's text settings.
- **Optional children:** `"if": "show_time"` leaves the child out when that setting is `no`.
- **Defaults:** props a child doesn't give take that element type's defaults.

### Files and art

`art:` paths come from the active theme's folder, so a template's images need to be in every theme
that uses it. To share a template that uses your own images, send the images along with it.

## Element types

The clock, calendar, graphs and other elements that draw something new each time are Python, one
file each in `app/dsdash/elements/`. The app picks up every file there, so a new kind of element is
one new file:

```python
from PIL import ImageDraw

ORDER = 12          # Its place in the editor's Add menu
SCHEMA = {
    "label": "Dot", "size": [8, 8],
    "props": [{"key": "color", "label": "Colour", "kind": "color", "default": "#d30000"}],
}


def draw(canvas, element, stats, now):
    x, y, w, h = element["x"], element["y"], element["w"], element["h"]
    ImageDraw.Draw(canvas).ellipse((x, y, x + w - 1, y + h - 1), fill=element["props"]["color"])
```

`SCHEMA` uses the same settings as templates. `stats` has the live values, and `now` is the time.
Shared help, such as fonts, the menu art and `{token}` text, is in `app/dsdash/widgets.py`: import
it inside `draw`, as the existing files do, so the folder loads without the rest of the app.

Element types ship with the app rather than being loaded from a folder of your own, because loading
code from a shared file would let it run anything.
