"""Every built-in element type, one module each. See docs/THEMES.md."""
import importlib
import pkgutil

# Each module has SCHEMA (label, size, props), ORDER (its place in the Add menu), and draw(canvas,
# element, stats, now), or draw = None if something else shows it.
MODULES = {}
for info in pkgutil.iter_modules(__path__):
    MODULES[info.name] = importlib.import_module(f"{__name__}.{info.name}")
MODULES = dict(sorted(MODULES.items(), key=lambda item: item[1].ORDER))

SCHEMA = {name: module.SCHEMA for name, module in MODULES.items()}
DRAW = {name: module.draw for name, module in MODULES.items() if module.draw}
