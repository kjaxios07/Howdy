"""Kip's modules — defined in howdy.config.json, loaded here.

Add or edit a module by editing that JSON file and restarting. No code change.
"""

from __future__ import annotations

from .appconfig import Module, module_ids, modules

MODULES: tuple[Module, ...] = modules()
MODULE_IDS: frozenset[str] = module_ids()

__all__ = ["Module", "MODULES", "MODULE_IDS"]
