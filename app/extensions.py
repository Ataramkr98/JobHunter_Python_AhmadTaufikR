"""Flask extensions, instantiated once and bound to the app in create_app().

Keeping them here (rather than in app/__init__.py) avoids circular imports —
models and services can `from app.extensions import db` safely.
"""
import sqlite3

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()

login_manager.login_view = "accounts.login"
login_manager.login_message = "Please log in to access that page."
login_manager.login_message_category = "info"


@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    """SQLite does not enforce declared foreign keys unless enabled per connection."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
