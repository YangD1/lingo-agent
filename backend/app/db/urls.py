from sqlalchemy.engine import make_url


def to_psycopg_conninfo(database_url: str) -> str:
    """SQLAlchemy URL (postgresql+psycopg://...) -> plain libpq URL for psycopg / LangGraph."""
    url = make_url(database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)
