"""Reset password for a user by email — uses bcrypt directly (no app imports)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

os.environ["APP_ENV"] = "development"
import bcrypt
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/arinedge_portal",
)

email = sys.argv[1] if len(sys.argv) > 1 else "arinedgehq@gmail.com"
password = sys.argv[2] if len(sys.argv) > 2 else "Admin@123"

hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

engine = create_engine(DATABASE_URL)
with engine.connect() as conn:
    result = conn.execute(
        text("SELECT id FROM users WHERE email = :email"),
        {"email": email},
    )
    row = result.fetchone()
    if not row:
        print(f"User {email} not found!")
        sys.exit(1)
    conn.execute(
        text("UPDATE users SET hashed_password = :hash WHERE email = :email"),
        {"hash": hashed, "email": email},
    )
    conn.commit()
    print(f"Password reset to '{password}' for {email} (id={row[0]})")
