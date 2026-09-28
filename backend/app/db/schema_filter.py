"""Which database objects Alembic autogenerate should look at."""

# Tables owned by LangGraph's AsyncPostgresSaver (created by its own setup()). Without
# this filter autogenerate sees them as "removed" and emits DROP TABLE for them, which
# would wipe every conversation's history.
EXTERNALLY_MANAGED_TABLES = frozenset(
    {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}
)


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    if type_ == "table" and name in EXTERNALLY_MANAGED_TABLES:
        return False
    table = getattr(obj, "table", None)  # indexes/constraints belonging to those tables
    return not (table is not None and getattr(table, "name", None) in EXTERNALLY_MANAGED_TABLES)
