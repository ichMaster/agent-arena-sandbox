"""Pluggable game modules.

Pure game logic behind the ``GameInterface`` seam. This package imports nothing
from ``server/`` -- a game knows nothing of transport, persistence or identity.
New games arrive as new modules here, never as generalizations of an existing one.
"""
