"""Salesforce Outbound Message SOAP parser unit tests (Phase 10).

Pure parsing: no DB, no network. Covers the real Salesforce envelope
shape (partner namespaces, repeated Notifications, sf:-prefixed field
elements, xsi:type object names) plus the rejection paths.
"""

from __future__ import annotations

from app.api.salesforce_events import ack_xml, parse_outbound_message

ENVELOPE = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <soapenv:Header>
    <SessionHeader xmlns="urn:partner.soap.sforce.com">
      <sessionId>00D...!AQIAQF...</sessionId>
    </SessionHeader>
  </soapenv:Header>
  <soapenv:Body>
    <notifications xmlns="http://soap.sforce.com/2005/09/outbound">
      <OrganizationId>00D5g00000XXXXX</OrganizationId>
      <ActionId>04k5g000000XXXX</ActionId>
      <MessageId>04l5g00000MSGID1</MessageId>
      <Notification xsi:type="LeadNotification">
        <Id>04t5g00000NOTIF1</Id>
        <sObject xsi:type="Lead">
          <sf:Id xmlns:sf="urn:sobjects.soap.sforce.com">00Q5g00000LEADID</sf:Id>
          <sf:Email xmlns:sf="urn:sobjects.soap.sforce.com">ada@example.com</sf:Email>
          <sf:LastName xmlns:sf="urn:sobjects.soap.sforce.com">Lovelace</sf:LastName>
          <sf:Company xmlns:sf="urn:sobjects.soap.sforce.com">Analytical Engines</sf:Company>
        </sObject>
      </Notification>
      <Notification xsi:type="ContactNotification">
        <Id>04t5g00000NOTIF2</Id>
        <sObject xsi:type="Contact">
          <sf:Id xmlns:sf="urn:sobjects.soap.sforce.com">0035g00000CONTACT</sf:Id>
          <sf:Email xmlns:sf="urn:sobjects.soap.sforce.com">alan@example.com</sf:Email>
        </sObject>
      </Notification>
    </notifications>
  </soapenv:Body>
</soapenv:Envelope>
"""


def test_parses_envelope_metadata_and_notifications():
    msg = parse_outbound_message(ENVELOPE.encode())
    assert msg is not None
    assert msg.organization_id == "00D5g00000XXXXX"
    assert msg.action_id == "04k5g000000XXXX"
    assert msg.message_id == "04l5g00000MSGID1"
    assert len(msg.notifications) == 2


def test_notification_fields_namespaced_and_typed():
    msg = parse_outbound_message(ENVELOPE.encode())
    lead = msg.notifications[0]
    # xsi:type on sObject wins; namespace prefixes stripped from fields.
    assert lead.object_type == "Lead"
    assert lead.notification_id == "04t5g00000NOTIF1"
    assert lead.record_id == "00Q5g00000LEADID"
    assert lead.record["Email"] == "ada@example.com"
    assert lead.record["Company"] == "Analytical Engines"

    contact = msg.notifications[1]
    assert contact.object_type == "Contact"
    assert contact.record_id == "0035g00000CONTACT"


def test_as_item_carries_envelope_context():
    msg = parse_outbound_message(ENVELOPE.encode())
    item = msg.notifications[0].as_item(msg)
    assert item["object_type"] == "Lead"
    assert item["record_id"] == "00Q5g00000LEADID"
    assert item["message_id"] == "04l5g00000MSGID1"
    assert item["organization_id"] == "00D5g00000XXXXX"
    assert item["action_id"] == "04k5g000000XXXX"
    assert item["notification_id"] == "04t5g00000NOTIF1"


def test_rejects_non_soap_and_malformed():
    assert parse_outbound_message(b"<html><body>nope</body></html>") is None
    assert parse_outbound_message(b"not xml at all") is None
    assert parse_outbound_message(b"") is None

    soap_no_notifications = (
        '<Envelope xmlns="http://schemas.xmlsoap.org/soap/envelope/">'
        "<Body><other/></Body></Envelope>"
    )
    assert parse_outbound_message(soap_no_notifications.encode()) is None


def test_rejects_entity_expansion_attacks():
    """defusedxml must refuse DTDs (billion-laughs class)."""
    evil = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">]>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<soapenv:Body>&lol;</soapenv:Body></soapenv:Envelope>"
    )
    assert parse_outbound_message(evil.encode()) is None


def test_empty_optional_metadata_is_tolerated():
    minimal = (
        '<Envelope xmlns="http://schemas.xmlsoap.org/soap/envelope/">'
        '<Body><notifications xmlns="http://soap.sforce.com/2005/09/outbound">'
        "<MessageId>04lMINIMAL</MessageId>"
        "</notifications></Body></Envelope>"
    )
    msg = parse_outbound_message(minimal.encode())
    assert msg is not None
    assert msg.message_id == "04lMINIMAL"
    assert msg.organization_id == ""
    assert msg.notifications == []


def test_ack_envelope_shape():
    text = ack_xml(True)
    assert "<Ack>true</Ack>" in text
    assert "http://soap.sforce.com/2005/09/outbound" in text
    assert ack_xml(False).find("<Ack>false</Ack>") != -1
