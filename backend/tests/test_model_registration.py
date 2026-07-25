"""Every model module must be registered on Base.metadata.

Importing a model module is what registers its tables on ``Base.metadata``.
A module that nothing imports is invisible to ``Base.metadata.create_all``, so
the table is never created on SQLite/dev/test and the feature fails at runtime
with "no such table: ..." — while the ORM class itself looks perfectly fine.

That was a live bug: ``app/models/sync.py`` defined ``outbound_writes`` but
``app/models/__init__.py`` never imported it, so every sync during the test
suite logged `sqlite3.OperationalError: no such table: outbound_writes`. It only
"worked" in production because Alembic creates the table there, and only worked
elsewhere when ``app.main`` happened to import the right service first.

This test locks registration in: it walks the model package on disk and asserts
that importing ``app.models`` alone is enough to register every declared table.
"""
import pkgutil

from app.core.database import Base
import app.models as models_pkg


def _declared_tablenames_per_module() -> dict[str, set[str]]:
    """{module_name: {tablenames it declares}} for every app/models/*.py."""
    import importlib

    found: dict[str, set[str]] = {}
    for mod in pkgutil.iter_modules(models_pkg.__path__):
        if mod.name.startswith("_"):
            continue
        module = importlib.import_module(f"app.models.{mod.name}")
        names = {
            obj.__tablename__
            for obj in vars(module).values()
            if isinstance(obj, type)
            and hasattr(obj, "__tablename__")
            and getattr(obj, "__module__", "") == module.__name__
        }
        if names:
            found[mod.name] = names
    return found


def test_every_model_module_is_registered_on_metadata():
    """Importing app.models must register every model module's tables.

    If this fails, add the missing module to the metadata-completeness import
    block in app/models/__init__.py — do NOT rely on some other module happening
    to import it first.
    """
    registered = set(Base.metadata.tables.keys())
    per_module = _declared_tablenames_per_module()

    missing = {
        module: sorted(tables - registered)
        for module, tables in per_module.items()
        if tables - registered
    }
    assert not missing, (
        "model tables declared but NOT registered on Base.metadata: "
        f"{missing}. create_all() will not create them, so they fail at runtime "
        "with 'no such table'. Add the module to the metadata-completeness "
        "import block in app/models/__init__.py."
    )


def test_sync_outbound_writes_is_registered():
    """Regression lock for the specific table that was missing."""
    assert "outbound_writes" in Base.metadata.tables, (
        "outbound_writes vanished from Base.metadata — app/models/sync.py is no "
        "longer imported by app/models/__init__.py"
    )
