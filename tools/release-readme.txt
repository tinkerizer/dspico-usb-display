DS Display {version} ({date})
=============================

Turns a DS Lite or DSi with a DSpico into a USB stats display for your PC.

On the PC (Windows)
-------------------
1. Run "DS-Display-Setup-{version}.exe". It installs for your user only, with no admin rights needed, and
   starts the app. It sits in the system tray, and the tray icon opens the editor.
2. To uninstall, use "Installed apps" in Windows Settings.

Running it again over an older version upgrades it and keeps your layout, themes and GIFs.

On the DS
---------
1. Copy usb-display.nds to the SD card, for example into the "apps" folder.
2. Start it from the DSpico menu and plug the DSpico into the PC.

After that, the PC app keeps the DS up to date by itself. When a newer build comes with the app,
it pushes it to the DS and copies it onto the SD card once, so you don't need to copy it by hand
again. That needs usb-display.nds to be on the SD card exactly once, under that name.

Licence
-------
DS Display is free software under the GPL, version 3 or later. The libraries and fonts it uses
keep their own licences, listed in THIRD_PARTY.md in the source.
