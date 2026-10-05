import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parents[2].parent / "backend"
sys.path.insert(0, str(backend_dir))

from app.db import SessionLocal
from app.models import User
from app.security.jwt import create_token

db = SessionLocal()
u = db.query(User).first()
if not u:
    # Create demo user if not present
    from app.security.passwords import hash_password
    u = User(email="e2e_audit@flowsmith.local", password_hash=hash_password("Password123!"))
    db.add(u)
    db.commit()
    db.refresh(u)

token = create_token(u.id, u.email)
print(token)
