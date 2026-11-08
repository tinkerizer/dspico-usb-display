# Themes and templates

There are three ways to change how the DS looks, from simplest to most work.

| Change | How | Where |
|---|---|---|
| Colours | A theme: paper, ink and bar colour | The **DS theme** button in the editor |
| An element made of other elements | A template: a JSON file | `templates/` folder |
| A new kind of drawing, such as a new graph | An element type: one Python file | `app/dsdash/elements/` |

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

`art:` refers to the bundled DS menu art in `app/assets/classic-ds/`, and `local:` to files you've
uploaded in the editor. To share a template that uses your own images, send the images along with
it, for upload.

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
