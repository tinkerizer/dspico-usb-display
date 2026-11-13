# Third-party code and assets

This project is licensed under the GPL, version 3 or later: see [LICENSE](LICENSE). It includes
or links the following, each under its own licence, all compatible with the GPL.

| What | Where | Licence |
|---|---|---|
| [libtwl](https://github.com/blocksds/libtwl) | `libs/libtwl` (submodule) | zlib |
| [TinyUSB](https://github.com/hathach/tinyusb) | `libs/tinyusb` (submodule) | MIT |
| [DSpico](https://github.com/LNH-team) firmware, loader and launcher | `dspico/` (submodules) | zlib |
| DSpico TinyUSB port, from `dspico-usb-examples` | `platform/` | zlib, see `platform/LICENSE.txt` |
| DSpico DLDI driver | `libs/dsupdate/DSpico.dldi` | zlib, see `DSpico.dldi.LICENSE.txt` |
| [Fusion Pixel](https://github.com/TakWolf/fusion-pixel-font) fonts | `app/assets/fonts` | SIL OFL 1.1, see `OFL.txt` there |
| Varela Round, as outlines | `app/dsdash/web/shell.svg` | SIL OFL 1.1 |
| [motion](https://motion.dev), [floating-ui](https://floating-ui.com) | `app/dsdash/web/vendor` | MIT |
| [pixelarticons](https://pixelarticons.com) | the undo, redo and reset tool icons | MIT |

## Thanks

The menu art in the built-in themes is the classic DS menu art from
[TWiLight Menu++](https://github.com/DS-Homebrew/TWiLightMenu). Thank you to everyone who works on it.

The Windows installer also bundles Python packages: Pillow (MIT-CMU), numpy, pyserial and psutil
(BSD), pystray (LGPL 3), and PyInstaller's bootloader (GPL 2 with an exception for bundled apps).
