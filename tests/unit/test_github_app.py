"""Unit tests for GitHub App Authentication (visorqa-bot[bot]).

Tests:
- RS256 JWT generation, clock drift, and claims validation
- Installation access token exchange & in-memory caching with TTL
- Private key loading (inline PEM vs file path)
- Error handling for missing credentials, non-numeric IDs, and invalid keys
- Token masking security
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from backend.adapters.github_app import (
    GitHubAppAuth,
    GitHubAppAuthError,
    GitHubAppConfigError,
    mask_token,
)


@pytest.fixture(scope="module")
def sample_rsa_keys():
    """Generate ephemeral RSA public/private key pair for testing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem, key.public_key()


def test_mask_token():
    assert mask_token("") == "<none>"
    assert mask_token("short") == "***"
    token = "ghs_1234567890abcdefghijklmnopqrstuvwxyz"
    masked = mask_token(token)
    assert masked.startswith("ghs_")
    assert masked.endswith("wxyz (40 chars)")
    assert "1234567890" not in masked


def test_generate_jwt_success(sample_rsa_keys):
    private_pem, _, public_key = sample_rsa_keys
    auth = GitHubAppAuth(app_id="998877", private_key=private_pem)

    token = auth.generate_jwt()
    assert isinstance(token, str)

    # Decode and verify with public key
    decoded = jwt.decode(token, public_key, algorithms=["RS256"])
    assert decoded["iss"] == "998877"
    assert decoded["exp"] > decoded["iat"]
    # Check valid ~9 minutes (540s) + 60s clock drift
    assert 500 <= (decoded["exp"] - decoded["iat"]) <= 650


def test_generate_jwt_missing_app_id(sample_rsa_keys):
    private_pem, _, _ = sample_rsa_keys
    auth = GitHubAppAuth(app_id="", private_key=private_pem)
    with pytest.raises(GitHubAppConfigError, match="GITHUB_APP_ID is not configured"):
        auth.generate_jwt()


def test_generate_jwt_missing_private_key():
    auth = GitHubAppAuth(app_id="12345", private_key="", private_key_path="")
    with pytest.raises(GitHubAppConfigError):
        auth.generate_jwt()


def test_resolve_private_key_from_file(tmp_path, sample_rsa_keys):
    private_pem, _, _ = sample_rsa_keys
    key_file = tmp_path / "test-bot.pem"
    key_file.write_text(private_pem, encoding="utf-8")

    auth = GitHubAppAuth(app_id="12345", private_key_path=str(key_file))
    loaded_pem = auth.resolve_private_key()
    assert loaded_pem.strip() == private_pem.strip()


def test_resolve_private_key_file_not_found(tmp_path):
    missing_path = tmp_path / "nonexistent.pem"
    auth = GitHubAppAuth(app_id="12345", private_key_path=str(missing_path))
    with pytest.raises(GitHubAppConfigError, match="not found"):
        auth.resolve_private_key()


@pytest.mark.asyncio
async def test_get_installation_token_non_numeric_id_error(sample_rsa_keys):
    private_pem, _, _ = sample_rsa_keys
    auth = GitHubAppAuth(
        app_id="12345",
        private_key=private_pem,
        default_installation_id="Iv23li1HgZecFgqUY3J1",
    )
    with pytest.raises(GitHubAppConfigError, match="Client ID"):
        await auth.get_installation_token()


@pytest.mark.asyncio
async def test_get_installation_token_success_and_cache(sample_rsa_keys):
    private_pem, _, _ = sample_rsa_keys
    auth = GitHubAppAuth(
        app_id="12345",
        private_key=private_pem,
        default_installation_id="11223344",
    )

    from datetime import datetime, timezone, timedelta
    fake_response = {
        "token": "ghs_test_token_1234567890abcdef",
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }

    mock_client = AsyncMock()
    mock_post = AsyncMock()
    mock_res = MagicMock()
    mock_res.status_code = 200
    mock_res.json.return_value = fake_response
    mock_res.raise_for_status.return_value = None
    mock_post.return_value = mock_res
    mock_client.post = mock_post
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("httpx.AsyncClient", return_value=mock_client):
        # 1. First call fetches from API
        token1 = await auth.get_installation_token()
        assert token1 == "ghs_test_token_1234567890abcdef"
        assert mock_post.call_count == 1

        # 2. Second call should return cached token without calling API again
        token2 = await auth.get_installation_token()
        assert token2 == token1
        assert mock_post.call_count == 1  # No additional network call

        # 3. Forced refresh makes another network call
        token3 = await auth.get_installation_token(force_refresh=True)
        assert token3 == token1
        assert mock_post.call_count == 2


@pytest.mark.asyncio
async def test_get_installation_token_rejection(sample_rsa_keys):
    private_pem, _, _ = sample_rsa_keys
    auth = GitHubAppAuth(
        app_id="12345",
        private_key=private_pem,
        default_installation_id="11223344",
    )

    mock_client = AsyncMock()
    mock_res = AsyncMock()
    mock_res.status_code = 401
    mock_client.post.return_value = mock_res
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(GitHubAppAuthError, match="GitHub rejected JWT: unauthorized"):
            await auth.get_installation_token()
