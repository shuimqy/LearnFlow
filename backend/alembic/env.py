from alembic import context
from app import models  # noqa: F401
from app.core.database import Base, engine


def run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
        include_object=lambda obj, name, type_, reflected, compare_to: (
            type_ != "table"
            or name
            not in {"checkpoint_migrations", "checkpoints", "checkpoint_blobs", "checkpoint_writes"}
        ),
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=str(engine.url), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif context.config.attributes.get("connection") is not None:
    run_migrations(context.config.attributes["connection"])
else:
    with engine.connect() as connection:
        run_migrations(connection)
