"""Versioned capability selection, independent of queues and running sessions."""

from .router import RoutingError, select

__all__ = ["RoutingError", "select"]
