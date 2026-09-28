"""Protocol name -> driver class. Drivers register themselves on import
(see smartscopes/drivers/__init__.py, which imports every driver
package)."""
from __future__ import annotations

from smartscopes.base import ModelInfo, ScopeDriver

_DRIVERS: dict[str, type[ScopeDriver]] = {}


def register_driver(cls: type[ScopeDriver]) -> type[ScopeDriver]:
    if cls.protocol in _DRIVERS:
        raise ValueError(f"Duplicate driver protocol {cls.protocol!r}")
    _DRIVERS[cls.protocol] = cls
    return cls


def get_driver_class(protocol: str) -> type[ScopeDriver]:
    try:
        return _DRIVERS[protocol]
    except KeyError:
        raise KeyError(f"No driver registered for protocol {protocol!r}") from None


def all_drivers() -> list[type[ScopeDriver]]:
    return list(_DRIVERS.values())


def all_models() -> list[tuple[type[ScopeDriver], ModelInfo]]:
    """Every (driver, model) pair, for the "add a telescope" picker."""
    return [(drv, model) for drv in _DRIVERS.values() for model in drv.models.values()]
