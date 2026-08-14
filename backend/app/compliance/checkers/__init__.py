"""Deterministic statutory checkers, one module per department. Each module
self-registers its framework checkers via ``@register`` at import; the registry
discovers them lazily. Add a new department by dropping a module here - no
central edit needed."""
