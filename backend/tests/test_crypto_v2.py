"""Tests for cipher.encryptV2 (AES-256-GCM) and backwards compatibility."""

import json
import pytest

from app.security.crypto import (
    CredentialDecryptionError,
    cipher,
    cipher_decrypt_v2,
    cipher_encrypt_v2,
    decrypt_text,
    encrypt_text,
)


class TestFernetV1:
    """Existing Fernet encryption still works."""

    def test_roundtrip(self):
        plaintext = '{"api_key": "sk-1234"}'
        encrypted = encrypt_text(plaintext)
        assert encrypted.startswith(b"k0:")
        assert decrypt_text(encrypted) == plaintext

    def test_cipher_module_v1(self):
        pt = "hello-v1"
        ct = cipher.encrypt(pt)
        assert cipher.decrypt(ct) == pt


class TestCipherV2:
    """AES-256-GCM cipher.encryptV2 tests."""

    def test_roundtrip(self):
        plaintext = '{"secret": "my-api-key-12345"}'
        encrypted = cipher_encrypt_v2(plaintext)
        assert encrypted.startswith(b"v2:")
        decrypted = cipher_decrypt_v2(encrypted)
        assert decrypted == plaintext

    def test_cipher_module_v2(self):
        pt = "enterprise-secret"
        ct = cipher.encryptV2(pt)
        assert cipher.decryptV2(ct) == pt

    def test_format_structure(self):
        encrypted = cipher_encrypt_v2("test")
        parts = encrypted.decode().split(":")
        assert len(parts) == 4
        assert parts[0] == "v2"

    def test_unique_nonces(self):
        """Each encryption must produce a unique nonce."""
        ct1 = cipher_encrypt_v2("same-data")
        ct2 = cipher_encrypt_v2("same-data")
        assert ct1 != ct2  # Different nonces

    def test_tampered_ciphertext_fails(self):
        encrypted = cipher_encrypt_v2("sensitive-data")
        parts = encrypted.decode().split(":")
        # Tamper with ciphertext (last part)
        tampered_ct = parts[3][:-2] + "XX"
        tampered = f"v2:{parts[1]}:{parts[2]}:{tampered_ct}".encode()
        with pytest.raises(CredentialDecryptionError):
            cipher_decrypt_v2(tampered)

    def test_tampered_tag_fails(self):
        encrypted = cipher_encrypt_v2("sensitive-data")
        parts = encrypted.decode().split(":")
        # Tamper with auth tag
        tampered_tag = parts[2][:-2] + "ZZ"
        tampered = f"v2:{parts[1]}:{tampered_tag}:{parts[3]}".encode()
        with pytest.raises(CredentialDecryptionError):
            cipher_decrypt_v2(tampered)


class TestAutoDetection:
    """decrypt_text auto-detects v1 (Fernet) vs v2 (AES-256-GCM)."""

    def test_v1_via_decrypt_text(self):
        ct = encrypt_text("fernet-secret")
        assert decrypt_text(ct) == "fernet-secret"

    def test_v2_via_decrypt_text(self):
        ct = cipher_encrypt_v2("gcm-secret")
        assert decrypt_text(ct) == "gcm-secret"

    def test_aes_gcm_json_format(self):
        """decrypt_text handles standard { iv, authTag, ciphertext } JSON format."""
        # First encrypt normally, then reformat as AES-GCM JSON
        import base64
        import hashlib
        import os
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from app.security.crypto import _current_key, _derive_aes_256_key

        key = _derive_aes_256_key(_current_key())
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        plaintext = "migrated-secret"
        ct_with_tag = aesgcm.encrypt(nonce, plaintext.encode(), None)
        ciphertext = ct_with_tag[:-16]
        tag = ct_with_tag[-16:]

        gcm_json = json.dumps({
            "iv": base64.b64encode(nonce).decode(),
            "authTag": base64.b64encode(tag).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
        })
        assert decrypt_text(gcm_json) == plaintext
