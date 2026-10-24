"""Native SAML 2.0 service-provider endpoints.

Implements SP-initiated and, when explicitly enabled, IdP-initiated Web SSO
with signed assertion/response validation, audience and recipient checks,
replay protection, and just-in-time user provisioning.

This is intentionally a focused SAML Web SSO implementation. It supports
Single Logout, encrypted assertions, and group-claim-to-role mapping, but not
workspace-level group synchronization.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import secrets
import textwrap
import threading
import time
import uuid
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode, urlparse
from xml.sax.saxutils import escape, quoteattr

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.padding import PKCS7
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from lxml import etree  # type: ignore[attr-defined]
from signxml import methods
from signxml.signer import XMLSigner
from signxml.verifier import SignatureConfiguration, XMLVerifier
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.sso import (
    _SSO_STATE_TTL,
    _cookie_secure,
    _new_sso_state,
    _sso_base_url,
    _verify_sso_state,
)
from app.audit import LOGIN, REGISTER, USER_ROLE_CHANGE, log_event
from app.config import Settings, get_settings
from app.db import get_db
from app.models import User
from app.security.jwt import create_token, decode_token, hash_password
from app.security.safe_http_client import SafeHTTPClient
from app.services.user_provisioning import apply_default_scope

logger = logging.getLogger("saml")

router = APIRouter(prefix="/api/auth/sso/saml", tags=["saml"])

_SAML_STATE_COOKIE = "flowsmith_saml_state"
_SAML_STATE_PATH = "/api/auth/sso/saml"
_SAML_NS = "urn:oasis:names:tc:SAML:2.0:assertion"
_SAMLP_NS = "urn:oasis:names:tc:SAML:2.0:protocol"
_MD_NS = "urn:oasis:names:tc:SAML:2.0:metadata"
_DS_NS = "http://www.w3.org/2000/09/xmldsig#"
_XENC_NS = "http://www.w3.org/2001/04/xmlenc#"
_EMAIL_NAME_ID = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
_BEARER_METHOD = "urn:oasis:names:tc:SAML:2.0:cm:bearer"
_REDIRECT_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
_POST_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
_SUCCESS_STATUS = "urn:oasis:names:tc:SAML:2.0:status:Success"
_MAX_XML_BYTES = 2 * 1024 * 1024
_MAX_METADATA_BYTES = 1024 * 1024

_EMAIL_ATTRIBUTE_NAMES = frozenset({
    "email",
    "mail",
    "emailaddress",
    "email-address",
    "urn:oid:0.9.2342.19200300.100.1.3",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
    "http://schemas.microsoft.com/ws/2008/06/identity/claims/emailaddress",
})

_METADATA_CACHE: dict[str, tuple[float, "IdPMetadata"]] = {}
_REPLAY_CACHE: dict[str, float] = {}
_REPLAY_LOCK = threading.Lock()


@dataclass(frozen=True)
class IdPMetadata:
    entity_id: str
    sso_url: str
    cert_pem: str
    slo_url: str = ""
    slo_binding: str = ""


def _q(namespace: str, local_name: str) -> str:
    return f"{{{namespace}}}{local_name}"


def _parse_xml(raw: bytes | str) -> Any:
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    if len(data) > _MAX_XML_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "SAML XML is too large.")
    if data.startswith((b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only UTF-8 SAML XML is accepted.")
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "DTD and entity declarations are not allowed.")
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
    )
    try:
        return etree.fromstring(data, parser)
    except etree.XMLSyntaxError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid SAML XML.") from exc


def _text(element: Any, path: str) -> str:
    node = element.find(path)
    return (node.text or "").strip() if node is not None else ""


def _parse_instant(value: str | None, label: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid {label} timestamp.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _check_window(
    value: datetime | None,
    *,
    now: datetime,
    skew: int,
    label: str,
    not_before: bool = False,
) -> None:
    if value is None:
        return
    if not_before:
        if now + timedelta(seconds=skew) < value:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{label} is not valid yet.")
    elif now - timedelta(seconds=skew) >= value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{label} has expired.")


def _certificate_pem(value: str) -> str:
    """Normalize a PEM or base64-DER certificate and verify its validity."""
    text = (value or "").strip().replace("\\n", "\n")
    if not text:
        raise ValueError("Certificate is empty.")
    if "BEGIN CERTIFICATE" not in text:
        encoded = re.sub(r"\s+", "", text)
        text = (
            "-----BEGIN CERTIFICATE-----\n"
            + "\n".join(textwrap.wrap(encoded, 64))
            + "\n-----END CERTIFICATE-----\n"
        )
    try:
        cert = x509.load_pem_x509_certificate(text.encode("utf-8"))
    except Exception as exc:
        raise ValueError("Certificate is not valid PEM or base64 DER.") from exc
    now = datetime.now(UTC)
    if cert.not_valid_before_utc > now:
        raise ValueError("Certificate is not valid yet.")
    if cert.not_valid_after_utc < now:
        raise ValueError("Certificate has expired.")
    return text


def _certificate_b64(cert_pem: str) -> str:
    return "".join(cert_pem.splitlines()[1:-1])


def _direct_signature(element: Any) -> Any | None:
    for child in element:
        if not isinstance(child.tag, str):
            continue
        qname = etree.QName(child)
        if qname.namespace == _DS_NS and qname.localname == "Signature":
            return child
    return None


def _verify_signature(element: Any, cert_pem: str) -> Any:
    config = SignatureConfiguration(
        require_x509=True,
        location=".",
        expect_references=1,
    )
    try:
        result = XMLVerifier().verify(
            element,
            x509_cert=cert_pem,
            expect_config=config,
            validate_schema=False,
            id_attribute="ID",
        )
    except Exception as exc:
        logger.warning("SAML signature verification failed: %s", exc)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "SAML signature verification failed.",
        ) from exc
    if isinstance(result, list):
        if len(result) != 1:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML response has ambiguous signatures.")
        result = result[0]
    signed_xml = getattr(result, "signed_xml", None)
    if signed_xml is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML signature did not cover a document.")
    return signed_xml


def _load_sp_private_key(settings: Settings) -> Any:
    raw = (settings.saml_sp_private_key or "").strip().replace("\\n", "\n")
    if not raw:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Encrypted SAML assertions require SAML_SP_PRIVATE_KEY.",
        )
    try:
        return serialization.load_pem_private_key(raw.encode("utf-8"), password=None)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SAML_SP_PRIVATE_KEY is not a valid unencrypted PEM key.",
        ) from exc


def _decrypt_encrypted_assertion(encrypted_assertion: Any, settings: Settings) -> Any:
    encrypted_data = encrypted_assertion.find(f".//{_q(_XENC_NS, 'EncryptedData')}")
    if encrypted_data is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML EncryptedAssertion has no EncryptedData.")
    encrypted_key = encrypted_data.find(f".//{_q(_XENC_NS, 'EncryptedKey')}")
    if encrypted_key is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML encrypted assertion has no EncryptedKey.")
    key_method = encrypted_key.find(_q(_XENC_NS, "EncryptionMethod"))
    data_method = encrypted_data.find(_q(_XENC_NS, "EncryptionMethod"))
    key_alg = (key_method.get("Algorithm") if key_method is not None else "") or ""
    data_alg = (data_method.get("Algorithm") if data_method is not None else "") or ""
    if "rsa-oaep" not in key_alg:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only RSA-OAEP encrypted SAML keys are supported.")
    key_cipher = encrypted_key.find(
        f"{_q(_XENC_NS, 'CipherData')}/{_q(_XENC_NS, 'CipherValue')}"
    )
    data_cipher = encrypted_data.find(
        f"{_q(_XENC_NS, 'CipherData')}/{_q(_XENC_NS, 'CipherValue')}"
    )
    if key_cipher is None or data_cipher is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML encrypted assertion is missing ciphertext.")
    try:
        encrypted_key_bytes = base64.b64decode("".join((key_cipher.text or "").split()), validate=True)
        encrypted_data_bytes = base64.b64decode("".join((data_cipher.text or "").split()), validate=True)
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML encrypted assertion is not valid base64.") from exc
    private_key = _load_sp_private_key(settings)
    symmetric_key = None
    for digest in (hashes.SHA1(), hashes.SHA256()):
        try:
            symmetric_key = private_key.decrypt(
                encrypted_key_bytes,
                asym_padding.OAEP(
                    mgf=asym_padding.MGF1(algorithm=digest),
                    algorithm=digest,
                    label=None,
                ),
            )
            break
        except Exception:
            continue
    if symmetric_key is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Could not decrypt the SAML assertion key.")

    if data_alg.endswith("aes256-gcm") or data_alg.endswith("aes128-gcm"):
        if len(encrypted_data_bytes) < 28:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML AES-GCM ciphertext is too short.")
        iv = encrypted_data_bytes[:12]
        ciphertext = encrypted_data_bytes[12:-16]
        tag = encrypted_data_bytes[-16:]
        try:
            plaintext = AESGCM(symmetric_key).decrypt(iv, ciphertext + tag, None)
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML AES-GCM decryption failed.") from exc
    elif data_alg.endswith("aes256-cbc") or data_alg.endswith("aes128-cbc"):
        if len(encrypted_data_bytes) < 32:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML AES-CBC ciphertext is too short.")
        iv = encrypted_data_bytes[:16]
        ciphertext = encrypted_data_bytes[16:]
        try:
            decryptor = Cipher(algorithms.AES(symmetric_key), modes.CBC(iv)).decryptor()
            padded = decryptor.update(ciphertext) + decryptor.finalize()
            unpadder = PKCS7(128).unpadder()
            plaintext = unpadder.update(padded) + unpadder.finalize()
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML AES-CBC decryption failed.") from exc
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported SAML assertion encryption algorithm.")
    assertion = _parse_xml(plaintext)
    if etree.QName(assertion).namespace != _SAML_NS or etree.QName(assertion).localname != "Assertion":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Decrypted SAML payload is not an Assertion.")
    return assertion


def _parse_idp_metadata(raw: bytes | str, settings: Settings) -> IdPMetadata:
    root = _parse_xml(raw)
    qname = etree.QName(root)
    if qname.localname == "EntitiesDescriptor":
        descriptor = root.find(f".//{_q(_MD_NS, 'EntityDescriptor')}")
        if descriptor is None:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "IdP metadata has no EntityDescriptor.")
        root = descriptor
    if etree.QName(root).localname != "EntityDescriptor":
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "IdP metadata is not a SAML EntityDescriptor.")
    entity_id = (root.get("entityID") or "").strip()
    if not entity_id:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "IdP metadata has no entityID.")
    if settings.saml_idp_entity_id and entity_id != settings.saml_idp_entity_id.strip():
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "IdP metadata entityID does not match SAML_IDP_ENTITY_ID.")
    descriptor = root.find(_q(_MD_NS, "IDPSSODescriptor"))
    if descriptor is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "IdP metadata has no IDPSSODescriptor.")
    sso_url = ""
    for service in descriptor.findall(_q(_MD_NS, "SingleSignOnService")):
        if service.get("Binding") == _REDIRECT_BINDING:
            sso_url = (service.get("Location") or "").strip()
            break
    if not sso_url:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "IdP metadata has no HTTP-Redirect SingleSignOnService.",
        )
    slo_url = ""
    slo_binding = ""
    for service in descriptor.findall(_q(_MD_NS, "SingleLogoutService")):
        if service.get("Binding") in (_POST_BINDING, _REDIRECT_BINDING):
            slo_url = (service.get("Location") or "").strip()
            slo_binding = service.get("Binding") or ""
            if slo_url:
                break
    parsed_sso = urlparse(sso_url)
    if parsed_sso.scheme != "https" and settings.app_env != "development":
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "IdP SSO URL must use HTTPS.")
    if slo_url:
        parsed_slo = urlparse(slo_url)
        if parsed_slo.scheme != "https" and settings.app_env != "development":
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "IdP SLO URL must use HTTPS.")
    cert_value = (settings.saml_idp_x509_cert or "").strip()
    if not cert_value:
        key_descriptors = descriptor.findall(_q(_MD_NS, "KeyDescriptor"))
        for wanted_use in ("signing", None):
            for key_descriptor in key_descriptors:
                if key_descriptor.get("use") != wanted_use:
                    continue
                certificate = key_descriptor.find(f".//{_q(_DS_NS, 'X509Certificate')}")
                if certificate is not None and (certificate.text or "").strip():
                    cert_value = (certificate.text or "").strip()
                    break
            if cert_value:
                break
    if not cert_value:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "IdP metadata has no signing certificate; set SAML_IDP_X509_CERT.",
        )
    try:
        cert_pem = _certificate_pem(cert_value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return IdPMetadata(
        entity_id=entity_id,
        sso_url=sso_url,
        cert_pem=cert_pem,
        slo_url=slo_url,
        slo_binding=slo_binding,
    )


async def _fetch_metadata(url: str) -> bytes:
    settings = get_settings()
    parsed = urlparse(url)
    if parsed.scheme != "https" and settings.app_env != "development":
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SAML metadata URL must use HTTPS.")
    client = SafeHTTPClient(timeout_s=10.0)
    try:
        response = await client.get(
            url,
            headers={"Accept": "application/samlmetadata+xml, application/xml;q=0.9"},
            max_response_bytes=_MAX_METADATA_BYTES,
        )
        if response.status_code != 200:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"IdP metadata returned HTTP {response.status_code}.",
            )
        return response.content
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Failed to fetch SAML IdP metadata from %s: %s", parsed.netloc, exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Failed to fetch SAML IdP metadata.") from exc
    finally:
        await client.close()


async def _load_idp_metadata() -> IdPMetadata:
    settings = get_settings()
    xml = (settings.saml_idp_metadata_xml or "").strip()
    url = (settings.saml_idp_metadata_url or "").strip()
    if not xml and not url:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SAML is enabled but no IdP metadata is configured.",
        )
    cache_key = "|".join((
        "xml" if xml else "url",
        xml,
        url,
        settings.saml_idp_entity_id,
        settings.saml_idp_x509_cert,
        settings.app_env,
    ))
    ttl = max(0, min(int(settings.saml_metadata_cache_seconds or 0), 3600))
    now = time.monotonic()
    cached = _METADATA_CACHE.get(cache_key)
    if cached and ttl and now - cached[0] < ttl:
        return cached[1]
    raw: bytes | str = xml if xml else await _fetch_metadata(url)
    metadata = _parse_idp_metadata(raw, settings)
    if ttl:
        _METADATA_CACHE[cache_key] = (now, metadata)
    return metadata


def _sp_entity_id(request: Request) -> str:
    settings = get_settings()
    configured = (settings.saml_sp_entity_id or "").strip()
    return (configured or _sso_base_url(request)).rstrip("/")


def _sp_acs_url(request: Request) -> str:
    settings = get_settings()
    configured = (settings.saml_sp_acs_url or "").strip()
    return configured or f"{_sso_base_url(request)}/api/auth/sso/saml/acs"


def _sp_slo_url(request: Request) -> str:
    return f"{_sso_base_url(request)}/api/auth/sso/saml/slo"


def _sp_signing_material() -> tuple[str | None, str | None]:
    settings = get_settings()
    raw_key = (settings.saml_sp_private_key or "").strip().replace("\\n", "\n")
    raw_cert = (settings.saml_sp_x509_cert or "").strip()
    if not raw_key and not raw_cert:
        return None, None
    if raw_key and not raw_cert:
        # The private key alone is valid for decrypting encrypted assertions;
        # it cannot sign AuthnRequests without the matching certificate.
        try:
            serialization.load_pem_private_key(raw_key.encode("utf-8"), password=None)
        except Exception as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "SAML SP private key is not a valid unencrypted PEM key.",
            ) from exc
        return raw_key, None
    if raw_cert and not raw_key:
        return None, None
    try:
        serialization.load_pem_private_key(raw_key.encode("utf-8"), password=None)
        cert_pem = _certificate_pem(raw_cert)
    except ValueError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SAML SP private key is not a valid unencrypted PEM key.",
        ) from exc
    return raw_key, cert_pem


def _sp_metadata_xml(request: Request) -> str:
    settings = get_settings()
    entity_id = _sp_entity_id(request)
    acs_url = _sp_acs_url(request)
    _, cert_pem = _sp_signing_material()
    cert_xml = ""
    if cert_pem:
        try:
            normalized = _certificate_pem(cert_pem)
        except ValueError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        cert_xml = (
            '<md:KeyDescriptor use="signing"><ds:KeyInfo><ds:X509Data>'
            f"<ds:X509Certificate>{_certificate_b64(normalized)}</ds:X509Certificate>"
            "</ds:X509Data></ds:KeyInfo></md:KeyDescriptor>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<md:EntityDescriptor xmlns:md="{_MD_NS}" xmlns:ds="{_DS_NS}" '
        f'entityID={quoteattr(entity_id)}>'
        f'<md:SPSSODescriptor AuthnRequestsSigned="{str(bool(cert_xml)).lower()}" '
        'WantAssertionsSigned="true" '
        'protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        f"{cert_xml}"
        '<md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</md:NameIDFormat>'
        f'<md:AssertionConsumerService Binding="{_POST_BINDING}" '
        f'Location={quoteattr(acs_url)} index="0" isDefault="true"/>'
        f'<md:SingleLogoutService Binding="{_POST_BINDING}" '
        f'Location={quoteattr(_sp_slo_url(request))}/>'
        "</md:SPSSODescriptor></md:EntityDescriptor>"
    )


def _build_authn_request(request: Request, destination: str) -> tuple[str, str]:
    entity_id = _sp_entity_id(request)
    acs_url = _sp_acs_url(request)
    request_id = "_" + uuid.uuid4().hex
    issue_instant = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    xml = (
        f'<samlp:AuthnRequest xmlns:samlp="{_SAMLP_NS}" xmlns:saml="{_SAML_NS}" '
        f'ID={quoteattr(request_id)} Version="2.0" IssueInstant={quoteattr(issue_instant)} '
        f'Destination={quoteattr(destination)} '
        f'ProtocolBinding="{_POST_BINDING}" '
        f'AssertionConsumerServiceURL={quoteattr(acs_url)}>'
        f"<saml:Issuer>{escape(entity_id)}</saml:Issuer>"
        f'<samlp:NameIDPolicy Format="{_EMAIL_NAME_ID}" AllowCreate="true"/>'
        "</samlp:AuthnRequest>"
    )
    root = _parse_xml(xml)
    key, cert = _sp_signing_material()
    if key and cert:
        root = XMLSigner(
            method=methods.enveloped,
            signature_algorithm="rsa-sha256",
            digest_algorithm="sha256",
        ).sign(root, key=key, cert=cert, reference_uri=request_id, id_attribute="ID")
    serialized = etree.tostring(root, encoding="UTF-8")
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    compressed = compressor.compress(serialized) + compressor.flush()
    return base64.b64encode(compressed).decode("ascii"), request_id


def _deflate_b64(raw: bytes) -> str:
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    compressed = compressor.compress(raw) + compressor.flush()
    return base64.b64encode(compressed).decode("ascii")


def _decode_slo_payload(value: str, *, redirect_binding: bool) -> bytes:
    encoded = "".join(value.split())
    raw = base64.b64decode(encoded, validate=True)
    if redirect_binding:
        return zlib.decompress(raw, -15)
    return raw


def _sign_saml_xml(root: Any, request_id: str) -> Any:
    key, cert = _sp_signing_material()
    if not key or not cert:
        return root
    return XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
    ).sign(root, key=key, cert=cert, reference_uri=request_id, id_attribute="ID")


def _build_logout_request(request: Request, metadata: IdPMetadata, email: str) -> tuple[str, str]:
    request_id = "_" + uuid.uuid4().hex
    issue_instant = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    xml = (
        f'<samlp:LogoutRequest xmlns:samlp="{_SAMLP_NS}" xmlns:saml="{_SAML_NS}" '
        f'ID={quoteattr(request_id)} Version="2.0" IssueInstant={quoteattr(issue_instant)} '
        f'Destination={quoteattr(metadata.slo_url)}>'
        f"<saml:Issuer>{escape(_sp_entity_id(request))}</saml:Issuer>"
        f'<saml:NameID Format="{_EMAIL_NAME_ID}">{escape(email)}</saml:NameID>'
        "</samlp:LogoutRequest>"
    )
    root = _sign_saml_xml(_parse_xml(xml), request_id)
    raw = etree.tostring(root, encoding="UTF-8")
    if metadata.slo_binding == _REDIRECT_BINDING:
        return _deflate_b64(raw), request_id
    return base64.b64encode(raw).decode("ascii"), request_id


def _build_logout_response(
    request: Request,
    metadata: IdPMetadata,
    *,
    in_response_to: str,
    success: bool = True,
) -> str:
    request_id = "_" + uuid.uuid4().hex
    issue_instant = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    status_value = _SUCCESS_STATUS if success else "urn:oasis:names:tc:SAML:2.0:status:Requester"
    xml = (
        f'<samlp:LogoutResponse xmlns:samlp="{_SAMLP_NS}" xmlns:saml="{_SAML_NS}" '
        f'ID={quoteattr(request_id)} Version="2.0" IssueInstant={quoteattr(issue_instant)} '
        f'Destination={quoteattr(metadata.slo_url)} '
        f'InResponseTo={quoteattr(in_response_to)}>'
        f"<saml:Issuer>{escape(_sp_entity_id(request))}</saml:Issuer>"
        f'<samlp:Status><samlp:StatusCode Value="{status_value}"/></samlp:Status>'
        "</samlp:LogoutResponse>"
    )
    root = _sign_saml_xml(_parse_xml(xml), request_id)
    return base64.b64encode(etree.tostring(root, encoding="UTF-8")).decode("ascii")


def _auto_post_html(action: str, fields: dict[str, str]) -> str:
    inputs = "".join(
        f"<input type=\"hidden\" name={quoteattr(key)} value={quoteattr(value)}/>"
        for key, value in fields.items()
    )
    return (
        "<!doctype html><html><body>"
        f"<form method=\"post\" action={quoteattr(action)}>{inputs}"
        "<noscript><button type=\"submit\">Continue</button></noscript>"
        "</form><script>document.forms[0].submit()</script></body></html>"
    )


def _safe_relay_state(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/#logged_out"


def _validate_logout_request(
    xml_bytes: bytes,
    *,
    metadata: IdPMetadata,
    settings: Settings,
) -> tuple[str, str]:
    root = _parse_xml(xml_bytes)
    if etree.QName(root).namespace != _SAMLP_NS or etree.QName(root).localname != "LogoutRequest":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML payload is not a LogoutRequest.")
    request_id = (root.get("ID") or "").strip()
    if not request_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML LogoutRequest has no ID.")
    issuer = _text(root, _q(_SAML_NS, "Issuer"))
    if issuer != metadata.entity_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML LogoutRequest issuer mismatch.")
    destination = (root.get("Destination") or "").strip()
    if destination and destination != f"{settings.public_url.rstrip('/')}/api/auth/sso/saml/slo":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML LogoutRequest destination mismatch.")
    now = datetime.now(UTC)
    skew = max(0, min(int(settings.saml_clock_skew_seconds or 0), 600))
    _check_window(
        _parse_instant(root.get("NotOnOrAfter"), "LogoutRequest.NotOnOrAfter"),
        now=now,
        skew=skew,
        label="SAML logout request",
    )
    if _direct_signature(root) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML LogoutRequest is not signed.")
    _verify_signature(root, metadata.cert_pem)
    name_id = root.find(_q(_SAML_NS, "NameID"))
    if name_id is None or not (name_id.text or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML LogoutRequest has no NameID.")
    return _validated_email(name_id.text or ""), request_id


def _validate_logout_response(
    xml_bytes: bytes,
    *,
    metadata: IdPMetadata,
) -> None:
    root = _parse_xml(xml_bytes)
    if etree.QName(root).namespace != _SAMLP_NS or etree.QName(root).localname != "LogoutResponse":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML payload is not a LogoutResponse.")
    issuer = _text(root, _q(_SAML_NS, "Issuer"))
    if issuer != metadata.entity_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML LogoutResponse issuer mismatch.")
    status_code = root.find(f"{_q(_SAMLP_NS, 'Status')}/{_q(_SAMLP_NS, 'StatusCode')}")
    if status_code is None or status_code.get("Value") != _SUCCESS_STATUS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML LogoutResponse status is not success.")
    if _direct_signature(root) is not None:
        _verify_signature(root, metadata.cert_pem)


def _state_cookie_samesite(request: Request) -> Literal["none", "lax"]:
    # SAML ACS is a cross-site POST from the IdP. A Lax cookie is not sent on
    # that request. Production deployments are HTTPS, so SameSite=None works;
    # local HTTP development should use HTTPS or a tunnel for browser SSO.
    return "none" if _cookie_secure(request) else "lax"


def _require_saml() -> Settings:
    settings = get_settings()
    if not settings.saml_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SAML is not enabled.")
    return settings


@router.get("/metadata")
def saml_metadata(request: Request) -> Response:
    _require_saml()
    return Response(
        content=_sp_metadata_xml(request),
        media_type="application/samlmetadata+xml",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/login")
async def saml_login(request: Request) -> RedirectResponse:
    _require_saml()
    metadata = await _load_idp_metadata()
    encoded_request, request_id = _build_authn_request(request, metadata.sso_url)
    state, nonce = _new_sso_state("saml", {"request_id": request_id})
    separator = "&" if "?" in metadata.sso_url else "?"
    location = (
        f"{metadata.sso_url}{separator}"
        + urlencode({"SAMLRequest": encoded_request, "RelayState": state})
    )
    response = RedirectResponse(url=location, status_code=status.HTTP_302_FOUND)
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        _SAML_STATE_COOKIE,
        nonce,
        max_age=_SSO_STATE_TTL,
        httponly=True,
        secure=_cookie_secure(request),
        samesite=_state_cookie_samesite(request),
        path=_SAML_STATE_PATH,
    )
    return response


def _extract_email(assertion: Any, name_id: Any) -> str:
    names = {name.lower() for name in _EMAIL_ATTRIBUTE_NAMES}
    for attribute in assertion.findall(f".//{_q(_SAML_NS, 'Attribute')}"):
        name = (attribute.get("Name") or "").strip()
        if name.lower() not in names:
            continue
        for value in attribute.findall(_q(_SAML_NS, "AttributeValue")):
            raw = "".join(value.itertext()).strip()
            if raw and "@" in raw:
                return _validated_email(raw)
    name_id_text = ""
    name_id_format = ""
    if name_id is not None:
        name_id_text = (name_id.text or "").strip()
        name_id_format = name_id.get("Format") or ""
    if name_id_text and ("@" in name_id_text or name_id_format == _EMAIL_NAME_ID):
        return _validated_email(name_id_text)
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML assertion has no email identity.")


def _validated_email(raw: str) -> str:
    try:
        result = validate_email(raw.strip(), check_deliverability=False)
    except EmailNotValidError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML assertion has an invalid email address.") from exc
    return result.normalized.lower()


def _extract_role(assertion: Any, attribute_name: str) -> str | None:
    wanted = (attribute_name or "").strip().lower()
    if not wanted:
        return None
    for attribute in assertion.findall(f".//{_q(_SAML_NS, 'Attribute')}"):
        if (attribute.get("Name") or "").strip().lower() != wanted:
            continue
        for value in attribute.findall(_q(_SAML_NS, "AttributeValue")):
            role = "".join(value.itertext()).strip().lower()
            if role in ("admin", "member"):
                return role
            if role == "owner":
                return "admin"
    return None


def _extract_groups(assertion: Any, attribute_name: str) -> tuple[str, ...]:
    wanted = (attribute_name or "").strip().lower()
    if not wanted:
        return ()
    groups: set[str] = set()
    for attribute in assertion.findall(f".//{_q(_SAML_NS, 'Attribute')}"):
        if (attribute.get("Name") or "").strip().lower() != wanted:
            continue
        for value in attribute.findall(_q(_SAML_NS, "AttributeValue")):
            group = "".join(value.itertext()).strip()
            if group:
                groups.add(group)
    return tuple(sorted(groups))


def _group_role(assertion: Any, settings: Settings) -> str | None:
    raw_map = (settings.saml_group_role_map or "").strip()
    if not raw_map:
        return None
    try:
        role_map = json.loads(raw_map)
    except ValueError:
        logger.warning("SAML_GROUP_ROLE_MAP is not valid JSON; ignoring group role mapping")
        return None
    if not isinstance(role_map, dict):
        return None
    normalized_map = {
        str(group).strip().lower(): str(role).strip().lower()
        for group, role in role_map.items()
    }
    mapped: set[str] = set()
    for group in _extract_groups(assertion, settings.saml_group_attribute):
        role = normalized_map.get(group.strip().lower(), "")
        if role in ("admin", "member"):
            mapped.add(role)
    if "admin" in mapped:
        return "admin"
    if "member" in mapped:
        return "member"
    return None


def _validate_assertion(
    assertion: Any,
    *,
    metadata: IdPMetadata,
    request_id: str,
    acs_url: str,
    sp_entity_id: str,
    settings: Settings,
) -> tuple[str, str | None, str, datetime]:
    assertion_id = (assertion.get("ID") or "").strip()
    if not assertion_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML assertion has no ID.")
    if assertion.get("Version") != "2.0":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML assertion version is not 2.0.")
    issuer = _text(assertion, _q(_SAML_NS, "Issuer"))
    if issuer != metadata.entity_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML assertion issuer does not match IdP metadata.")

    now = datetime.now(UTC)
    skew = max(0, min(int(settings.saml_clock_skew_seconds or 0), 600))
    conditions = assertion.find(_q(_SAML_NS, "Conditions"))
    if conditions is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML assertion has no Conditions.")
    _check_window(
        _parse_instant(conditions.get("NotBefore"), "Conditions.NotBefore"),
        now=now,
        skew=skew,
        label="SAML assertion",
        not_before=True,
    )
    conditions_expiry = _parse_instant(conditions.get("NotOnOrAfter"), "Conditions.NotOnOrAfter")
    _check_window(conditions_expiry, now=now, skew=skew, label="SAML assertion")
    audiences = [
        (node.text or "").strip()
        for node in conditions.findall(f".//{_q(_SAML_NS, 'Audience')}")
    ]
    if sp_entity_id not in audiences:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML assertion audience does not match this service provider.")

    subject = assertion.find(_q(_SAML_NS, "Subject"))
    if subject is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML assertion has no Subject.")
    name_id = subject.find(_q(_SAML_NS, "NameID"))
    expiry_candidates: list[datetime] = []
    if conditions_expiry is not None:
        expiry_candidates.append(conditions_expiry)
    has_valid_confirmation = False
    for confirmation in subject.findall(_q(_SAML_NS, "SubjectConfirmation")):
        if confirmation.get("Method") != _BEARER_METHOD:
            continue
        data = confirmation.find(_q(_SAML_NS, "SubjectConfirmationData"))
        if data is None:
            continue
        if (data.get("Recipient") or "").strip() != acs_url:
            continue
        in_response_to = (data.get("InResponseTo") or "").strip()
        if request_id:
            if in_response_to != request_id:
                continue
        elif in_response_to:
            continue
        confirmation_expiry = _parse_instant(
            data.get("NotOnOrAfter"), "SubjectConfirmationData.NotOnOrAfter"
        )
        if confirmation_expiry is None:
            continue
        try:
            _check_window(
                confirmation_expiry,
                now=now,
                skew=skew,
                label="SAML subject confirmation",
            )
            _check_window(
                _parse_instant(data.get("NotBefore"), "SubjectConfirmationData.NotBefore"),
                now=now,
                skew=skew,
                label="SAML subject confirmation",
                not_before=True,
            )
        except HTTPException:
            continue
        has_valid_confirmation = True
        expiry_candidates.append(confirmation_expiry)
        break
    if not has_valid_confirmation:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "SAML assertion has no valid bearer subject confirmation.",
        )
    if not expiry_candidates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML assertion has no expiry.")
    if assertion.find(_q(_SAML_NS, "AuthnStatement")) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML assertion has no AuthnStatement.")
    return (
        _extract_email(assertion, name_id),
        _extract_role(assertion, settings.saml_role_attribute)
        or _group_role(assertion, settings),
        assertion_id,
        min(expiry_candidates),
    )


def _validate_saml_response(
    xml_bytes: bytes,
    *,
    metadata: IdPMetadata,
    request_id: str,
    acs_url: str,
    sp_entity_id: str,
    settings: Settings,
) -> tuple[str, str | None, str, datetime]:
    root = _parse_xml(xml_bytes)
    if etree.QName(root).namespace != _SAMLP_NS or etree.QName(root).localname != "Response":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML payload is not a Response.")
    now = datetime.now(UTC)
    skew = max(0, min(int(settings.saml_clock_skew_seconds or 0), 600))
    _check_window(
        _parse_instant(root.get("IssueInstant"), "Response.IssueInstant"),
        now=now,
        skew=skew,
        label="SAML response",
        not_before=True,
    )
    status_code = root.find(f"{_q(_SAMLP_NS, 'Status')}/{_q(_SAMLP_NS, 'StatusCode')}")
    if status_code is None or status_code.get("Value") != _SUCCESS_STATUS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML response status is not success.")
    issuer = _text(root, _q(_SAML_NS, "Issuer"))
    if issuer and issuer != metadata.entity_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML response issuer does not match IdP metadata.")
    destination = (root.get("Destination") or "").strip()
    if destination and destination != acs_url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML response destination does not match this ACS.")
    in_response_to = (root.get("InResponseTo") or "").strip()
    if request_id:
        if in_response_to != request_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML response InResponseTo does not match the request.")
    elif in_response_to:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsolicited SAML response has InResponseTo.")

    response_verified = False
    if _direct_signature(root) is not None:
        root = _verify_signature(root, metadata.cert_pem)
        response_verified = True

    encrypted_assertions = root.findall(f".//{_q(_SAML_NS, 'EncryptedAssertion')}")
    assertions = root.findall(f".//{_q(_SAML_NS, 'Assertion')}")
    if encrypted_assertions:
        if len(encrypted_assertions) != 1 or assertions:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "SAML response must contain exactly one assertion.",
            )
        assertion = _decrypt_encrypted_assertion(encrypted_assertions[0], settings)
        if not response_verified:
            if _direct_signature(assertion) is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML response is not signed.")
            assertion = _verify_signature(assertion, metadata.cert_pem)
    else:
        if len(assertions) != 1:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "SAML response must contain exactly one assertion.",
            )
        assertion = assertions[0]
        if not response_verified:
            if _direct_signature(assertion) is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML response is not signed.")
            assertion = _verify_signature(assertion, metadata.cert_pem)
    return _validate_assertion(
        assertion,
        metadata=metadata,
        request_id=request_id,
        acs_url=acs_url,
        sp_entity_id=sp_entity_id,
        settings=settings,
    )


def _consume_assertion(assertion_id: str, expires: datetime) -> None:
    ttl = max(60, int((expires - datetime.now(UTC)).total_seconds()) + 60)
    key = f"saml_assertion:{assertion_id}"
    try:
        from app.security.redis_client import get_shared_redis

        redis = get_shared_redis()
        if redis is not None:
            if not redis.set(key, "1", nx=True, ex=ttl):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML assertion has already been used.")
            return
    except HTTPException:
        raise
    except Exception:
        logger.warning("Redis unavailable for SAML replay protection; using process-local cache")
    now = time.monotonic()
    with _REPLAY_LOCK:
        expired = [item for item, deadline in _REPLAY_CACHE.items() if deadline <= now]
        for item in expired:
            _REPLAY_CACHE.pop(item, None)
        if key in _REPLAY_CACHE:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML assertion has already been used.")
        _REPLAY_CACHE[key] = now + ttl


def _find_or_create_user(
    db: Session,
    *,
    email: str,
    saml_role: str | None,
    settings: Settings,
) -> User:
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is not None:
        if not user.active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been deactivated.")
        if saml_role == "admin" and user.role != "admin":
            previous_role = user.role
            user.role = "admin"
            db.commit()
            log_event(
                db,
                USER_ROLE_CHANGE,
                target_type="user",
                target_id=str(user.id),
                user_id=user.id,
                detail={"from": previous_role, "to": "admin", "source": "saml"},
            )
        return user
    if not settings.saml_jit_provisioning:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "SAML JIT provisioning is disabled.")
    from app.api.auth import _BOOTSTRAP_ADVISORY_KEY, _REGISTRATION_BOOTSTRAP_LOCK

    with _REGISTRATION_BOOTSTRAP_LOCK:
        try:
            if db.get_bind().dialect.name == "postgresql":
                db.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": _BOOTSTRAP_ADVISORY_KEY},
                )
            user = db.scalar(select(User).where(func.lower(User.email) == email))
            if user is not None:
                if not user.active:
                    raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been deactivated.")
                return user
            is_first = (db.scalar(select(func.count()).select_from(User)) or 0) == 0
            if is_first and settings.registration_bootstrap_token:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "The first admin must be created with the password bootstrap flow.",
                )
            default_role = (settings.saml_default_role or "member").strip().lower()
            desired_role = "admin" if is_first else (saml_role or default_role)
            if desired_role not in ("admin", "member"):
                desired_role = "member"
            user = User(
                email=email,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                role=desired_role,
            )
            db.add(user)
            try:
                db.flush()
            except IntegrityError as exc:
                db.rollback()
                existing = db.scalar(select(User).where(func.lower(User.email) == email))
                if existing is None:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        "Could not provision the SAML account.",
                    ) from exc
                if not existing.active:
                    raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been deactivated.")
                return existing
            apply_default_scope(
                db,
                user,
                settings.saml_default_organization_id,
                settings.saml_default_workspace_id,
            )
            db.commit()
            db.refresh(user)
            log_event(db, REGISTER, target_type="user", target_id=str(user.id), user_id=user.id,
                      detail={"source": "saml"})
            return user
        except HTTPException:
            db.rollback()
            raise
        except ValueError as exc:
            db.rollback()
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"SAML default organization/workspace is invalid: {exc}",
            ) from exc
        except Exception:
            db.rollback()
            raise


@router.post("/logout")
async def saml_logout(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> Response:
    _require_saml()
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "A bearer token is required for SAML logout.")
    try:
        payload = decode_token(authorization.split(" ", 1)[1].strip())
        user_id = int(payload["sub"])
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bearer token.") from exc
    user = db.get(User, user_id)
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid bearer token.")
    metadata = await _load_idp_metadata()
    if not metadata.slo_url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "IdP metadata has no SingleLogoutService.")
    user.tokens_valid_from = datetime.now(UTC)
    db.commit()
    encoded_request, _ = _build_logout_request(request, metadata, user.email)
    fields = {"SAMLRequest": encoded_request, "RelayState": "/#logged_out"}
    if metadata.slo_binding == _REDIRECT_BINDING:
        separator = "&" if "?" in metadata.slo_url else "?"
        response = RedirectResponse(
            url=f"{metadata.slo_url}{separator}{urlencode(fields)}",
            status_code=status.HTTP_302_FOUND,
        )
    else:
        response = Response(
            content=_auto_post_html(metadata.slo_url, fields),
            media_type="text/html",
        )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/slo")
@router.post("/slo")
async def saml_slo(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    settings = _require_saml()
    metadata = await _load_idp_metadata()
    if not metadata.slo_url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "IdP metadata has no SingleLogoutService.")
    parameters = dict(request.query_params)
    if request.method == "POST":
        form = await request.form()
        parameters.update({key: str(value) for key, value in form.items()})
    relay_state = parameters.get("RelayState")
    redirect_binding = request.method == "GET"
    try:
        if parameters.get("SAMLRequest"):
            xml_bytes = _decode_slo_payload(parameters["SAMLRequest"], redirect_binding=redirect_binding)
            email, request_id = _validate_logout_request(
                xml_bytes,
                metadata=metadata,
                settings=settings,
            )
            user = db.scalar(select(User).where(func.lower(User.email) == email))
            if user is not None:
                user.tokens_valid_from = datetime.now(UTC)
                db.commit()
            encoded_response = _build_logout_response(
                request,
                metadata,
                in_response_to=request_id,
            )
            if metadata.slo_binding == _REDIRECT_BINDING:
                encoded_response = _deflate_b64(base64.b64decode(encoded_response))
                separator = "&" if "?" in metadata.slo_url else "?"
                response = RedirectResponse(
                    url=f"{metadata.slo_url}{separator}"
                        + urlencode({"SAMLResponse": encoded_response,
                                     "RelayState": _safe_relay_state(relay_state)}),
                    status_code=status.HTTP_302_FOUND,
                )
            else:
                response = Response(
                    content=_auto_post_html(metadata.slo_url, {
                        "SAMLResponse": encoded_response,
                        "RelayState": _safe_relay_state(relay_state),
                    }),
                    media_type="text/html",
                )
        elif parameters.get("SAMLResponse"):
            xml_bytes = _decode_slo_payload(parameters["SAMLResponse"], redirect_binding=redirect_binding)
            _validate_logout_response(xml_bytes, metadata=metadata)
            response = RedirectResponse(
                url=_safe_relay_state(relay_state),
                status_code=status.HTTP_302_FOUND,
            )
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAMLRequest or SAMLResponse is required.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("SAML SLO request rejected: %s", exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid SAML logout message.") from exc
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/acs")
async def saml_acs(
    request: Request,
    SAMLResponse: str = Form(...),
    RelayState: str = Form(default=""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    settings = _require_saml()
    content_length = request.headers.get("content-length")
    try:
        too_large = bool(content_length) and int(content_length or "0") > _MAX_XML_BYTES * 2
    except ValueError:
        too_large = False
    if too_large:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "SAML response is too large.")
    metadata = await _load_idp_metadata()
    request_id = ""
    if RelayState:
        state = _verify_sso_state(
            RelayState,
            "saml",
            request.cookies.get(_SAML_STATE_COOKIE),
        )
        request_id = str(state.get("request_id") or "")
        if not request_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML state is missing its request ID.")
    elif not settings.saml_allow_idp_initiated:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAML RelayState is required.")
    try:
        encoded_response = "".join(SAMLResponse.split())
        xml_bytes = base64.b64decode(encoded_response, validate=True)
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "SAMLResponse is not valid base64.") from exc
    acs_url = _sp_acs_url(request)
    sp_entity_id = _sp_entity_id(request)
    email, role, assertion_id, expiry = _validate_saml_response(
        xml_bytes,
        metadata=metadata,
        request_id=request_id,
        acs_url=acs_url,
        sp_entity_id=sp_entity_id,
        settings=settings,
    )
    _consume_assertion(assertion_id, expiry)
    user = _find_or_create_user(db, email=email, saml_role=role, settings=settings)
    log_event(db, LOGIN, target_type="user", target_id=str(user.id), user_id=user.id,
              detail={"source": "saml"})
    jwt_token = create_token(user.id, email=user.email)
    response = RedirectResponse(
        url=f"/#sso_token={jwt_token}",
        status_code=status.HTTP_302_FOUND,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.delete_cookie(
        _SAML_STATE_COOKIE,
        path=_SAML_STATE_PATH,
        secure=_cookie_secure(request),
        httponly=True,
        samesite=_state_cookie_samesite(request),
    )
    return response
