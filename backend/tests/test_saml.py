"""Native SAML 2.0 SP tests with real signed XML assertions."""

from __future__ import annotations

import base64
import os
import uuid
import zlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from xml.sax.saxutils import escape, quoteattr

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509.oid import NameOID
from lxml import etree
from signxml import XMLSigner, XMLVerifier, methods

IDP_ENTITY = "https://idp.example.com/metadata"
SP_ENTITY = "https://flowsmith.example.com"
ACS_URL = "https://flowsmith.example.com/api/auth/sso/saml/acs"
_IDP_NS = "urn:oasis:names:tc:SAML:2.0:assertion"
_SAMLP_NS = "urn:oasis:names:tc:SAML:2.0:protocol"
_MD_NS = "urn:oasis:names:tc:SAML:2.0:metadata"
_DS_NS = "http://www.w3.org/2000/09/xmldsig#"


def _make_material() -> tuple[str, str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "idp.example.com")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    cert_b64 = base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()
    return key_pem, cert_pem, cert_b64


@pytest.fixture(scope="module")
def idp_material() -> tuple[str, str, str]:
    return _make_material()


def _metadata_xml(cert_b64: str) -> str:
    return (
        f'<md:EntityDescriptor xmlns:md="{_MD_NS}" xmlns:ds="{_DS_NS}" entityID="{IDP_ENTITY}">'
        f'<md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        '<md:KeyDescriptor use="signing"><ds:KeyInfo><ds:X509Data>'
        f"<ds:X509Certificate>{cert_b64}</ds:X509Certificate>"
        "</ds:X509Data></ds:KeyInfo></md:KeyDescriptor>"
        '<md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" '
        'Location="https://idp.example.com/sso"/>'
        '<md:SingleLogoutService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" '
        'Location="https://idp.example.com/slo"/>'
        "</md:IDPSSODescriptor></md:EntityDescriptor>"
    )


def _enable_saml(
    monkeypatch,
    *,
    cert_b64: str,
    sp_key: str = "",
    sp_cert: str = "",
    allow_idp_initiated: bool = False,
    jit: bool = True,
) -> None:
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "saml_enabled", True)
    monkeypatch.setattr(settings, "saml_display_name", "Test SAML")
    monkeypatch.setattr(settings, "saml_idp_metadata_url", "")
    monkeypatch.setattr(settings, "saml_idp_metadata_xml", _metadata_xml(cert_b64))
    monkeypatch.setattr(settings, "saml_idp_entity_id", IDP_ENTITY)
    monkeypatch.setattr(settings, "saml_idp_x509_cert", "")
    monkeypatch.setattr(settings, "saml_sp_entity_id", SP_ENTITY)
    monkeypatch.setattr(settings, "saml_sp_acs_url", ACS_URL)
    monkeypatch.setattr(settings, "saml_sp_x509_cert", sp_cert)
    monkeypatch.setattr(settings, "saml_sp_private_key", sp_key)
    monkeypatch.setattr(settings, "saml_jit_provisioning", jit)
    monkeypatch.setattr(settings, "saml_default_role", "member")
    monkeypatch.setattr(settings, "saml_role_attribute", "role")
    monkeypatch.setattr(settings, "saml_default_organization_id", "")
    monkeypatch.setattr(settings, "saml_default_workspace_id", "")
    monkeypatch.setattr(settings, "saml_allow_idp_initiated", allow_idp_initiated)
    monkeypatch.setattr(settings, "saml_clock_skew_seconds", 120)
    monkeypatch.setattr(settings, "saml_metadata_cache_seconds", 0)
    # TestClient speaks HTTP. Keep the secure-cookie flag off for the test;
    # SP entity ID and ACS URL stay HTTPS to exercise production-style values.
    monkeypatch.setattr(settings, "public_url", "http://testserver")


def _start_login(client) -> tuple[str, str]:
    response = client.get("/api/auth/sso/saml/login", follow_redirects=False)
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    relay_state = query["RelayState"][0]
    encoded_request = query["SAMLRequest"][0]
    request_xml = zlib.decompress(base64.b64decode(encoded_request), -15)
    request_root = etree.fromstring(request_xml)
    request_id = request_root.get("ID")
    assert request_id
    return request_id, relay_state


def _response_xml(
    key_pem: str,
    cert_pem: str,
    *,
    request_id: str | None,
    email: str = "ada@example.com",
    audience: str = SP_ENTITY,
    recipient: str = ACS_URL,
    not_after: datetime | None = None,
    signed: bool = True,
    sign_response: bool = False,
    role: str | None = None,
    email_attribute: bool = False,
    groups: list[str] | None = None,
    group_attribute: str = "groups",
) -> bytes:
    now = datetime.now(UTC)
    issue_instant = now - timedelta(minutes=1)
    expires = not_after or (now + timedelta(minutes=5))
    assertion_id = "_a" + uuid.uuid4().hex
    response_id = "_r" + uuid.uuid4().hex
    in_response_to = (
        f" InResponseTo={quoteattr(request_id)}" if request_id else ""
    )
    subject_in_response_to = (
        f" InResponseTo={quoteattr(request_id)}" if request_id else ""
    )
    conditions = f"""
      <saml:Conditions NotBefore="{issue_instant.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                       NotOnOrAfter="{expires.strftime('%Y-%m-%dT%H:%M:%SZ')}">
        <saml:AudienceRestriction><saml:Audience>{escape(audience)}</saml:Audience></saml:AudienceRestriction>
      </saml:Conditions>"""
    attribute_values = ""
    if email_attribute:
        attribute_values += (
            '<saml:Attribute Name="mail">'
            f"<saml:AttributeValue>{escape(email)}</saml:AttributeValue>"
            "</saml:Attribute>"
        )
    if role:
        attribute_values += (
            '<saml:Attribute Name="role">'
            f"<saml:AttributeValue>{escape(role)}</saml:AttributeValue>"
            "</saml:Attribute>"
        )
    if groups:
        values = "".join(
            f"<saml:AttributeValue>{escape(group)}</saml:AttributeValue>"
            for group in groups
        )
        attribute_values += (
            f'<saml:Attribute Name="{escape(group_attribute)}">{values}</saml:Attribute>'
        )
    attribute_statement = (
        f"<saml:AttributeStatement>{attribute_values}</saml:AttributeStatement>"
        if attribute_values else ""
    )
    name_id_value = "opaque-user-id" if email_attribute else email
    xml = (
        f'<samlp:Response xmlns:samlp="{_SAMLP_NS}" xmlns:saml="{_IDP_NS}" '
        f'ID="{response_id}" Version="2.0" '
        f'IssueInstant="{issue_instant.strftime("%Y-%m-%dT%H:%M:%SZ")}" '
        f'Destination={quoteattr(ACS_URL)}{in_response_to}>'
        f"<saml:Issuer>{IDP_ENTITY}</saml:Issuer>"
        '<samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/>'
        "</samlp:Status>"
        f'<saml:Assertion ID="{assertion_id}" Version="2.0" '
        f'IssueInstant="{issue_instant.strftime("%Y-%m-%dT%H:%M:%SZ")}">'
        f"<saml:Issuer>{IDP_ENTITY}</saml:Issuer>"
        "<saml:Subject>"
        f'<saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">'
        f"{escape(name_id_value)}</saml:NameID>"
        '<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
        f"<saml:SubjectConfirmationData Recipient={quoteattr(recipient)}"
        f"{subject_in_response_to} "
        f'NotOnOrAfter="{expires.strftime("%Y-%m-%dT%H:%M:%SZ")}"/>'
        "</saml:SubjectConfirmation></saml:Subject>"
        f"{conditions}"
        f'<saml:AuthnStatement AuthnInstant="{issue_instant.strftime("%Y-%m-%dT%H:%M:%SZ")}">'
        "<saml:AuthnContext><saml:AuthnContextClassRef>"
        "urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport"
        "</saml:AuthnContextClassRef></saml:AuthnContext></saml:AuthnStatement>"
        f"{attribute_statement}"
        "</saml:Assertion></samlp:Response>"
    )
    root = etree.fromstring(xml.encode())
    if not signed:
        return etree.tostring(root, encoding="UTF-8")
    signer = XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
    )
    if sign_response:
        root = signer.sign(
            root,
            key=key_pem,
            cert=cert_pem,
            reference_uri=response_id,
            id_attribute="ID",
        )
    else:
        assertion = root.find(f".//{{{_IDP_NS}}}Assertion")
        assert assertion is not None
        parent = assertion.getparent()
        assert parent is not None
        signed_assertion = signer.sign(
            assertion,
            key=key_pem,
            cert=cert_pem,
            reference_uri=assertion_id,
            id_attribute="ID",
        )
        parent.replace(assertion, signed_assertion)
    return etree.tostring(root, encoding="UTF-8")


def _encrypted_assertion_xml(assertion_xml: bytes, sp_cert_pem: str) -> bytes:
    cert = x509.load_pem_x509_certificate(sp_cert_pem.encode())
    key = os.urandom(32)
    iv = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(iv, assertion_xml, None)
    encrypted_key = cert.public_key().encrypt(
        key,
        asym_padding.OAEP(
            mgf=asym_padding.MGF1(algorithm=hashes.SHA1()),
            algorithm=hashes.SHA1(),
            label=None,
        ),
    )
    return (
        f'<saml:EncryptedAssertion xmlns:saml="{_IDP_NS}" '
        f'xmlns:xenc="http://www.w3.org/2001/04/xmlenc#" '
        f'xmlns:ds="{_DS_NS}">'
        '<xenc:EncryptedData Type="http://www.w3.org/2001/04/xmlenc#Element">'
        '<xenc:EncryptionMethod Algorithm="http://www.w3.org/2009/xmlenc11#aes256-gcm"/>'
        "<ds:KeyInfo><xenc:EncryptedKey>"
        '<xenc:EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#rsa-oaep-mgf1p"/>'
        f"<xenc:CipherData><xenc:CipherValue>{base64.b64encode(encrypted_key).decode()}"
        "</xenc:CipherValue></xenc:CipherData></xenc:EncryptedKey></ds:KeyInfo>"
        f"<xenc:CipherData><xenc:CipherValue>{base64.b64encode(iv + ciphertext).decode()}"
        "</xenc:CipherValue></xenc:CipherData></xenc:EncryptedData></saml:EncryptedAssertion>"
    ).encode()


def _encrypted_response_xml(
    idp_key: str,
    idp_cert: str,
    sp_cert: str,
    *,
    request_id: str,
    email: str,
) -> bytes:
    base = _response_xml(
        idp_key, idp_cert, request_id=request_id, email=email,
    )
    base_root = etree.fromstring(base)
    assertion = base_root.find(f".//{{{_IDP_NS}}}Assertion")
    assert assertion is not None
    encrypted = _encrypted_assertion_xml(etree.tostring(assertion), sp_cert)
    response_id = "_r" + uuid.uuid4().hex
    now = datetime.now(UTC)
    xml = (
        f'<samlp:Response xmlns:samlp="{_SAMLP_NS}" xmlns:saml="{_IDP_NS}" '
        f'ID="{response_id}" Version="2.0" '
        f'IssueInstant="{now.strftime("%Y-%m-%dT%H:%M:%SZ")}" '
        f'Destination="{ACS_URL}" InResponseTo="{request_id}">'
        f"<saml:Issuer>{IDP_ENTITY}</saml:Issuer>"
        '<samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/>'
        "</samlp:Status>"
        f"{encrypted.decode()}"
        "</samlp:Response>"
    )
    root = etree.fromstring(xml.encode())
    signed = XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
    ).sign(root, key=idp_key, cert=idp_cert, reference_uri=response_id, id_attribute="ID")
    return etree.tostring(signed, encoding="UTF-8")


def _logout_request_xml(
    key_pem: str,
    cert_pem: str,
    *,
    email: str,
    signed: bool = True,
) -> bytes:
    request_id = "_logout" + uuid.uuid4().hex
    now = datetime.now(UTC)
    xml = (
        f'<samlp:LogoutRequest xmlns:samlp="{_SAMLP_NS}" xmlns:saml="{_IDP_NS}" '
        f'ID="{request_id}" Version="2.0" '
        f'IssueInstant="{now.strftime("%Y-%m-%dT%H:%M:%SZ")}" '
        'Destination="http://testserver/api/auth/sso/saml/slo">'
        f"<saml:Issuer>{IDP_ENTITY}</saml:Issuer>"
        f'<saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">'
        f"{escape(email)}</saml:NameID>"
        "</samlp:LogoutRequest>"
    )
    root = etree.fromstring(xml.encode())
    if not signed:
        return etree.tostring(root, encoding="UTF-8")
    signed_root = XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
    ).sign(
        root,
        key=key_pem,
        cert=cert_pem,
        reference_uri=request_id,
        id_attribute="ID",
    )
    return etree.tostring(signed_root, encoding="UTF-8")


def _post_response(client, response_bytes: bytes, relay_state: str | None):
    payload = base64.b64encode(response_bytes).decode()
    data = {"SAMLResponse": payload}
    if relay_state is not None:
        data["RelayState"] = relay_state
    return client.post(
        "/api/auth/sso/saml/acs",
        data=data,
        follow_redirects=False,
    )


def _token_from_redirect(response) -> str:
    assert response.status_code == 302
    fragment = parse_qs(urlparse(response.headers["location"]).fragment)
    token = fragment["sso_token"][0]
    assert token
    return token


def test_saml_metadata_and_provider_discovery(client, monkeypatch, idp_material):
    _, _, cert_b64 = idp_material
    _enable_saml(monkeypatch, cert_b64=cert_b64)
    metadata = client.get("/api/auth/sso/saml/metadata")
    assert metadata.status_code == 200
    assert metadata.headers["content-type"].startswith("application/samlmetadata+xml")
    assert f'entityID="{SP_ENTITY}"' in metadata.text
    assert ACS_URL in metadata.text
    assert "/api/auth/sso/saml/slo" in metadata.text
    providers = client.get("/api/auth/sso/providers").json()["data"]
    assert any(provider["id"] == "saml" for provider in providers)


def test_saml_jit_provisioning_and_login(client, monkeypatch, idp_material):
    key_pem, cert_pem, cert_b64 = idp_material
    _enable_saml(monkeypatch, cert_b64=cert_b64)
    request_id, relay_state = _start_login(client)
    response = _response_xml(key_pem, cert_pem, request_id=request_id)
    acs = _post_response(client, response, relay_state)
    token = _token_from_redirect(acs)
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["data"]["email"] == "ada@example.com"
    assert me.json()["data"]["role"] == "admin"


def test_saml_response_signature_is_accepted(client, monkeypatch, idp_material):
    key_pem, cert_pem, cert_b64 = idp_material
    _enable_saml(monkeypatch, cert_b64=cert_b64)
    request_id, relay_state = _start_login(client)
    response = _response_xml(
        key_pem, cert_pem, request_id=request_id,
        email="grace@example.com", sign_response=True,
    )
    _token_from_redirect(_post_response(client, response, relay_state))


def test_saml_encrypted_assertion_is_accepted(client, monkeypatch, idp_material):
    idp_key, idp_cert, cert_b64 = idp_material
    sp_key, sp_cert, _ = _make_material()
    _enable_saml(
        monkeypatch, cert_b64=cert_b64, sp_key=sp_key, sp_cert=sp_cert,
    )
    request_id, relay_state = _start_login(client)
    response = _encrypted_response_xml(
        idp_key, idp_cert, sp_cert,
        request_id=request_id, email="encrypted@example.com",
    )
    token = _token_from_redirect(_post_response(client, response, relay_state))
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["data"]["email"] == "encrypted@example.com"


def test_saml_encrypted_assertion_requires_sp_private_key(client, monkeypatch, idp_material):
    idp_key, idp_cert, cert_b64 = idp_material
    _, sp_cert, _ = _make_material()
    _enable_saml(monkeypatch, cert_b64=cert_b64)
    request_id, relay_state = _start_login(client)
    response = _encrypted_response_xml(
        idp_key, idp_cert, sp_cert,
        request_id=request_id, email="encrypted@example.com",
    )
    acs = _post_response(client, response, relay_state)
    assert acs.status_code == 400
    assert "SAML_SP_PRIVATE_KEY" in acs.text


def test_saml_unsigned_response_is_rejected(client, monkeypatch, idp_material):
    key_pem, cert_pem, cert_b64 = idp_material
    _enable_saml(monkeypatch, cert_b64=cert_b64)
    request_id, relay_state = _start_login(client)
    response = _response_xml(
        key_pem, cert_pem, request_id=request_id, signed=False,
    )
    acs = _post_response(client, response, relay_state)
    assert acs.status_code == 400
    assert "not signed" in acs.text


def test_saml_wrong_signing_cert_is_rejected(client, monkeypatch, idp_material):
    _, _, cert_b64 = idp_material
    wrong_key, wrong_cert, _ = _make_material()
    _enable_saml(monkeypatch, cert_b64=cert_b64)
    request_id, relay_state = _start_login(client)
    response = _response_xml(wrong_key, wrong_cert, request_id=request_id)
    acs = _post_response(client, response, relay_state)
    assert acs.status_code == 400
    assert "signature" in acs.text.lower()


def test_saml_wrong_audience_is_rejected(client, monkeypatch, idp_material):
    key_pem, cert_pem, cert_b64 = idp_material
    _enable_saml(monkeypatch, cert_b64=cert_b64)
    request_id, relay_state = _start_login(client)
    response = _response_xml(
        key_pem, cert_pem, request_id=request_id,
        audience="https://another-sp.example.com",
    )
    acs = _post_response(client, response, relay_state)
    assert acs.status_code == 400
    assert "audience" in acs.text


def test_saml_expired_assertion_is_rejected(client, monkeypatch, idp_material):
    key_pem, cert_pem, cert_b64 = idp_material
    _enable_saml(monkeypatch, cert_b64=cert_b64)
    request_id, relay_state = _start_login(client)
    response = _response_xml(
        key_pem, cert_pem, request_id=request_id,
        not_after=datetime.now(UTC) - timedelta(minutes=5),
    )
    acs = _post_response(client, response, relay_state)
    assert acs.status_code == 400


def test_saml_assertion_replay_is_rejected(client, monkeypatch, idp_material):
    key_pem, cert_pem, cert_b64 = idp_material
    _enable_saml(monkeypatch, cert_b64=cert_b64)
    request_id, relay_state = _start_login(client)
    state_cookie = client.cookies.get("flowsmith_saml_state")
    response = _response_xml(key_pem, cert_pem, request_id=request_id)
    first = _post_response(client, response, relay_state)
    _token_from_redirect(first)
    assert state_cookie
    client.cookies.set(
        "flowsmith_saml_state",
        state_cookie,
        domain="testserver.local",
        path="/api/auth/sso/saml",
    )
    replay = _post_response(client, response, relay_state)
    assert replay.status_code == 400
    assert "already been used" in replay.text


def test_saml_idp_initiated_requires_opt_in(client, monkeypatch, idp_material):
    key_pem, cert_pem, cert_b64 = idp_material
    _enable_saml(monkeypatch, cert_b64=cert_b64)
    response = _response_xml(key_pem, cert_pem, request_id=None)
    assert _post_response(client, response, relay_state=None).status_code == 400

    _enable_saml(monkeypatch, cert_b64=cert_b64, allow_idp_initiated=True)
    response = _response_xml(
        key_pem, cert_pem, request_id=None, email="idp@example.com",
    )
    _token_from_redirect(_post_response(client, response, relay_state=None))


def test_saml_jit_can_be_disabled(client, monkeypatch, idp_material):
    key_pem, cert_pem, cert_b64 = idp_material
    _enable_saml(monkeypatch, cert_b64=cert_b64, jit=False)
    request_id, relay_state = _start_login(client)
    response = _response_xml(key_pem, cert_pem, request_id=request_id)
    acs = _post_response(client, response, relay_state)
    assert acs.status_code == 403
    assert "JIT" in acs.text


def test_saml_role_and_default_scope(client, monkeypatch, idp_material):
    key_pem, cert_pem, cert_b64 = idp_material
    from app.config import get_settings
    from app.db import get_session
    from app.models import Organization, OrganizationMember, User, Workspace, WorkspaceMember
    from app.security.jwt import hash_password

    db = get_session()
    try:
        seed = User(
            email="seed@example.com",
            password_hash=hash_password("seed-password"),
            role="member",
            active=True,
        )
        db.add(seed)
        db.flush()
        db.add(Organization(id="org_saml", name="SAML Org", founder_id=seed.id, is_public=False))
        db.add(Workspace(
            id="ws_saml", name="SAML Workspace", organization_id="org_saml",
            creator_id=seed.id, is_private=True,
        ))
        db.commit()
    finally:
        db.close()

    _enable_saml(monkeypatch, cert_b64=cert_b64)
    settings = get_settings()
    monkeypatch.setattr(settings, "saml_default_organization_id", "org_saml")
    monkeypatch.setattr(settings, "saml_default_workspace_id", "ws_saml")
    request_id, relay_state = _start_login(client)
    response = _response_xml(
        key_pem, cert_pem, request_id=request_id,
        email="scoped@example.com", role="admin", email_attribute=True,
    )
    _token_from_redirect(_post_response(client, response, relay_state))

    db = get_session()
    try:
        user = db.query(User).filter(User.email == "scoped@example.com").one()
        assert user.role == "admin"
        assert user.organization_id == "org_saml"
        assert user.workspace_id == "ws_saml"
        assert db.query(OrganizationMember).filter(OrganizationMember.user_id == user.id).count() == 1
        assert db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).count() == 1
    finally:
        db.close()


def test_saml_group_claim_maps_admin_role(client, monkeypatch, idp_material):
    key_pem, cert_pem, cert_b64 = idp_material
    from app.config import get_settings
    from app.db import get_session
    from app.models import User

    _enable_saml(monkeypatch, cert_b64=cert_b64)
    monkeypatch.setattr(
        get_settings(), "saml_group_role_map", '{"platform-admins": "admin"}'
    )
    request_id, relay_state = _start_login(client)
    response = _response_xml(
        key_pem,
        cert_pem,
        request_id=request_id,
        email="group-admin@example.com",
        groups=["Platform-Admins", "people"],
    )
    _token_from_redirect(_post_response(client, response, relay_state))

    db = get_session()
    try:
        user = db.query(User).filter(User.email == "group-admin@example.com").one()
        assert user.role == "admin"
    finally:
        db.close()


def test_saml_group_claim_promotes_existing_member(client, monkeypatch, idp_material):
    key_pem, cert_pem, cert_b64 = idp_material
    from app.config import get_settings
    from app.db import get_session
    from app.models import User
    from app.security.jwt import hash_password

    db = get_session()
    try:
        db.add(User(
            email="existing-group@example.com",
            password_hash=hash_password("existing-password"),
            role="member",
            active=True,
        ))
        db.commit()
    finally:
        db.close()

    _enable_saml(monkeypatch, cert_b64=cert_b64)
    monkeypatch.setattr(
        get_settings(), "saml_group_role_map", '{"platform-admins": "admin"}'
    )
    request_id, relay_state = _start_login(client)
    response = _response_xml(
        key_pem,
        cert_pem,
        request_id=request_id,
        email="existing-group@example.com",
        groups=["platform-admins"],
    )
    _token_from_redirect(_post_response(client, response, relay_state))

    db = get_session()
    try:
        user = db.query(User).filter(User.email == "existing-group@example.com").one()
        assert user.role == "admin"
    finally:
        db.close()


def test_saml_slo_invalidates_user_sessions(client, monkeypatch, idp_material):
    key_pem, cert_pem, cert_b64 = idp_material
    from app.db import get_session
    from app.models import User
    from app.security.jwt import hash_password

    db = get_session()
    try:
        db.add(User(
            email="slo@example.com",
            password_hash=hash_password("slo-password"),
            role="member",
            active=True,
        ))
        db.commit()
    finally:
        db.close()

    _enable_saml(monkeypatch, cert_b64=cert_b64)
    request_xml = _logout_request_xml(key_pem, cert_pem, email="slo@example.com")
    response = client.post(
        "/api/auth/sso/saml/slo",
        data={"SAMLRequest": base64.b64encode(request_xml).decode()},
    )
    assert response.status_code == 200
    assert "SAMLResponse" in response.text

    db = get_session()
    try:
        user = db.query(User).filter(User.email == "slo@example.com").one()
        assert user.tokens_valid_from is not None
    finally:
        db.close()


def test_saml_sp_initiated_logout_invalidates_token(client, monkeypatch, idp_material):
    _, _, cert_b64 = idp_material
    from app.db import get_session
    from app.models import User
    from app.security.jwt import create_token, hash_password

    db = get_session()
    try:
        user = User(
            email="sp-logout@example.com",
            password_hash=hash_password("logout-password"),
            role="member",
            active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id
    finally:
        db.close()

    _enable_saml(monkeypatch, cert_b64=cert_b64)
    token = create_token(user_id, email="sp-logout@example.com")
    response = client.post(
        "/api/auth/sso/saml/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert "SAMLRequest" in response.text
    db = get_session()
    try:
        user = db.get(User, user_id)
        assert user is not None and user.tokens_valid_from is not None
    finally:
        db.close()


def test_saml_slo_rejects_unsigned_request(client, monkeypatch, idp_material):
    key_pem, cert_pem, cert_b64 = idp_material
    _enable_saml(monkeypatch, cert_b64=cert_b64)
    request_xml = _logout_request_xml(
        key_pem, cert_pem, email="slo@example.com", signed=False,
    )
    response = client.post(
        "/api/auth/sso/saml/slo",
        data={"SAMLRequest": base64.b64encode(request_xml).decode()},
    )
    assert response.status_code == 400


def test_saml_can_sign_authn_requests(client, monkeypatch, idp_material):
    _, cert_pem, cert_b64 = idp_material
    sp_key = idp_material[0]
    _enable_saml(
        monkeypatch,
        cert_b64=cert_b64,
        sp_key=sp_key,
        sp_cert=cert_pem,
    )
    response = client.get("/api/auth/sso/saml/login", follow_redirects=False)
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    request_xml = zlib.decompress(base64.b64decode(query["SAMLRequest"][0]), -15)
    request_root = etree.fromstring(request_xml)
    signature = request_root.find(f"{{{_DS_NS}}}Signature")
    assert signature is not None
    verified = XMLVerifier().verify(request_root, x509_cert=cert_pem, id_attribute="ID")
    assert verified.signed_xml is not None
