# Do NOT redefine User here — it is already defined in database.py.
# Import from there so the whole app shares one SQLAlchemy model.
from database import User

__all__ = ["User"]