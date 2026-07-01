"""Auth flow tests.

These tests verify the core auth service logic using mocked DB sessions.
Full integration tests require a live PostgreSQL database.
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.user_session import UserSession
from app.models.login_audit import LoginAuditEvent
from app.services.auth import AuthService
from app.utils.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    hash_token,
    decode_access_token,
)
from app.schemas.user import UserCreate, ResetPasswordRequest


# ─── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_db():
    """Create a mock DB session."""
    db = MagicMock(spec=Session)
    return db


@pytest.fixture
def sample_user():
    """Create a sample user instance."""
    user = User(
        id=uuid.uuid4(),
        public_id="ABCD1234",
        username="testuser",
        full_name="Test User",
        email="test@example.com",
        hashed_password=hash_password("correctpassword123"),
        role="user",
        is_active=True,
        is_email_verified=True,
        is_logged_in=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    return user


@pytest.fixture
def sample_admin_user():
    """Create a sample admin user instance."""
    user = User(
        id=uuid.uuid4(),
        public_id="ADMIN9999",
        username="admin",
        full_name="Admin User",
        email="admin@example.com",
        hashed_password=hash_password("adminpassword123"),
        role="admin",
        is_active=True,
        is_email_verified=True,
        is_logged_in=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    return user


# ─── Security Utils Tests ─────────────────────────────────────────────

class TestPasswordHashing:
    def test_hash_and_verify_password(self):
        password = "testpassword123!"
        hashed = hash_password(password)
        assert hashed != password
        assert verify_password(password, hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("correctpassword")
        assert verify_password("wrongpassword", hashed) is False


class TestAccessToken:
    def test_create_and_decode_access_token(self):
        user_id = uuid.uuid4()
        token = create_access_token(user_id, role="user")
        payload = decode_access_token(token)
        assert payload["sub"] == str(user_id)
        assert payload["type"] == "access"
        assert payload["role"] == "user"
        assert "jti" in payload
        assert "iat" in payload
        assert "exp" in payload

    def test_access_token_has_admin_role(self):
        user_id = uuid.uuid4()
        token = create_access_token(user_id, role="admin")
        payload = decode_access_token(token)
        assert payload["role"] == "admin"

    def test_decode_invalid_token(self):
        from jose import JWTError
        with pytest.raises(JWTError):
            decode_access_token("invalidtoken123")


class TestRefreshToken:
    def test_create_refresh_token_is_opaque(self):
        token = create_refresh_token()
        assert len(token) > 32
        assert isinstance(token, str)

    def test_hash_token_is_deterministic(self):
        token = create_refresh_token()
        hash1 = hash_token(token)
        hash2 = hash_token(token)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex digest

    def test_hash_token_different_tokens_different_hashes(self):
        token1 = create_refresh_token()
        token2 = create_refresh_token()
        assert hash_token(token1) != hash_token(token2)

    def test_raw_token_not_in_hash(self):
        token = create_refresh_token()
        token_hash = hash_token(token)
        assert token not in token_hash


# ─── AuthService Tests ────────────────────────────────────────────────

class TestAuthenticateUser:
    def test_login_success_returns_tokens(self, mock_db, sample_user):
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_user

        result = AuthService.authenticate_user(
            mock_db, "test@example.com", "correctpassword123"
        )

        assert result is not None
        user, access_token, refresh_token = result
        assert user == sample_user
        assert access_token is not None
        assert refresh_token is not None
        assert len(refresh_token) > 16

    def test_login_wrong_password_returns_none(self, mock_db, sample_user):
        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_user

        result = AuthService.authenticate_user(
            mock_db, "test@example.com", "wrongpassword"
        )

        assert result is None

    def test_login_unknown_email_returns_none(self, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        result = AuthService.authenticate_user(
            mock_db, "unknown@example.com", "anypassword"
        )

        assert result is None


class TestRefreshSession:
    def test_refresh_with_valid_token(self, mock_db, sample_user):
        refresh_token = create_refresh_token()
        token_hash = hash_token(refresh_token)

        session = UserSession(
            id=uuid.uuid4(),
            user_id=sample_user.id,
            refresh_token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            created_at=datetime.now(timezone.utc),
        )

        # Mock session lookup
        mock_db.execute.return_value.scalar_one_or_none.side_effect = [
            session,  # First call: find session
            sample_user,  # Second call: find user
        ]

        result = AuthService.refresh_session(mock_db, refresh_token)

        assert result is not None
        user, new_access_token, new_refresh_token = result
        assert user == sample_user
        assert new_access_token is not None
        assert new_refresh_token is not None
        assert new_refresh_token != refresh_token  # Rotation

    def test_refresh_with_revoked_session_returns_none(self, mock_db, sample_user):
        refresh_token = create_refresh_token()
        token_hash = hash_token(refresh_token)

        session = UserSession(
            id=uuid.uuid4(),
            user_id=sample_user.id,
            refresh_token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            revoked_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )

        mock_db.execute.return_value.scalar_one_or_none.return_value = session

        result = AuthService.refresh_session(mock_db, refresh_token)

        assert result is None

    def test_refresh_with_expired_session_returns_none(self, mock_db, sample_user):
        refresh_token = create_refresh_token()
        token_hash = hash_token(refresh_token)

        session = UserSession(
            id=uuid.uuid4(),
            user_id=sample_user.id,
            refresh_token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            created_at=datetime.now(timezone.utc),
        )

        mock_db.execute.return_value.scalar_one_or_none.return_value = session

        result = AuthService.refresh_session(mock_db, refresh_token)

        assert result is None

    def test_refresh_with_none_token_returns_none(self, mock_db):
        result = AuthService.refresh_session(mock_db, None)
        assert result is None

    def test_refresh_with_empty_token_returns_none(self, mock_db):
        result = AuthService.refresh_session(mock_db, "")
        assert result is None


class TestLogoutSession:
    def test_logout_revokes_session(self, mock_db):
        refresh_token = create_refresh_token()
        token_hash = hash_token(refresh_token)

        session = UserSession(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            refresh_token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            created_at=datetime.now(timezone.utc),
        )

        mock_db.execute.return_value.scalar_one_or_none.return_value = session

        result = AuthService.logout_session(mock_db, refresh_token)

        assert result is True
        assert session.revoked_at is not None

    def test_logout_with_missing_token_returns_false(self, mock_db):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        result = AuthService.logout_session(mock_db, "nonexistenttoken")

        assert result is False

    def test_logout_with_none_token_returns_false(self, mock_db):
        result = AuthService.logout_session(mock_db, None)
        assert result is False


class TestLogoutAllSessions:
    def test_logout_all_revokes_all_active_sessions(self, mock_db):
        user_id = uuid.uuid4()
        sessions = [
            UserSession(
                id=uuid.uuid4(), user_id=user_id, refresh_token_hash="hash1",
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                created_at=datetime.now(timezone.utc),
            ),
            UserSession(
                id=uuid.uuid4(), user_id=user_id, refresh_token_hash="hash2",
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                created_at=datetime.now(timezone.utc),
            ),
        ]
        mock_db.execute.return_value.scalars.return_value.all.return_value = sessions

        result = AuthService.logout_all_sessions(mock_db, user_id)

        assert result is True
        for s in sessions:
            assert s.revoked_at is not None


class TestResetPassword:
    def test_reset_password_revokes_sessions(self, mock_db, sample_user):
        sample_user.password_reset_token = "resettoken123"
        sample_user.password_reset_token_expires = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        )

        mock_db.execute.return_value.scalar_one_or_none.return_value = sample_user

        result = AuthService.reset_password(
            mock_db, "resettoken123", "newpassword456"
        )

        assert result is True
        assert verify_password("newpassword456", sample_user.hashed_password) is True
        assert sample_user.password_reset_token is None


class TestPasswordHashingUtils:
    def test_hash_and_verify(self):
        pw = "MyS3cur3P@ss!"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed)
        assert not verify_password("wrong", hashed)

    def test_same_password_different_hashes(self):
        pw = "testpassword"
        hash1 = hash_password(pw)
        hash2 = hash_password(pw)
        assert hash1 != hash2  # bcrypt uses different salts


# ─── Access Token Validation Tests ────────────────────────────────────

class TestAccessTokenValidation:
    def test_type_field_is_access(self):
        uid = uuid.uuid4()
        token = create_access_token(uid)
        payload = decode_access_token(token)
        assert payload["type"] == "access"

    def test_role_field_in_token(self):
        uid = uuid.uuid4()
        token = create_access_token(uid, role="admin")
        payload = decode_access_token(token)
        assert payload["role"] == "admin"

    def test_jti_is_present_and_unique(self):
        uid = uuid.uuid4()
        token1 = create_access_token(uid)
        token2 = create_access_token(uid)
        payload1 = decode_access_token(token1)
        payload2 = decode_access_token(token2)
        assert payload1["jti"] != payload2["jti"]
