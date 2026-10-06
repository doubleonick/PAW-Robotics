"""
hierarchy_builder.pyw
---------------------
Standalone launcher for the PAW Hierarchy Builder.

Double-click this file (or create a shortcut to it) to open the
Hierarchy Builder without launching the full Robot Ethology game
and without showing a console window.

On Windows: associate .pyw files with pythonw.exe (done automatically
when Python is installed) so the console window is suppressed.

To set the shortcut icon:
  Right-click the shortcut → Properties → Change Icon
  Browse to: materials/icons/hierarchy_builder.ico
"""

import os
import sys

# Ensure project root is on the path regardless of working directory
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Apply theme before any pygame/colour imports
import engine.theme as _T
_T.apply(_T.load_saved_theme())

import pygame
from games.ethology.hierarchy_builder import HierarchyBuilder

# Set window icon
_icon_path = os.path.join(_HERE, "materials", "icons", "hierarchy_builder.png")
if os.path.exists(_icon_path):
    pygame.init()
    icon_surf = pygame.image.load(_icon_path)
    pygame.display.set_icon(icon_surf)

# Launch in standalone mode (no robot label, no result path)
HierarchyBuilder().run()
