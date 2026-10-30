#!/usr/bin/env python3
"""Configure an initialized Artemis 2.40 instance; never modifies journal data."""
import argparse
from pathlib import Path
import re
import shutil
from xml.dom import minidom

CORE = "urn:activemq:core"
def elements(parent, name):
    return [node for node in parent.childNodes
            if node.nodeType == node.ELEMENT_NODE
            and node.namespaceURI == CORE and node.localName == name]


def child(parent, name):
    matches = elements(parent, name)
    if matches:
        return matches[0]
    element = parent.ownerDocument.createElementNS(CORE, name)
    parent.appendChild(element)
    return element


def named(parent, kind, attribute, value):
    for element in elements(parent, kind):
        if element.getAttribute(attribute) == value:
            return element
    element = parent.ownerDocument.createElementNS(CORE, kind)
    element.setAttribute(attribute, value)
    parent.appendChild(element)
    return element


def text(element, value):
    for node in list(element.childNodes):
        element.removeChild(node)
    element.appendChild(element.ownerDocument.createTextNode(value))


def configure(xml_path, env_path):
    settings = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            settings[key.strip()] = value.strip()
    password = settings.get("BROKER_KEYSTORE_PASSWORD", "")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", password):
        raise ValueError("BROKER_KEYSTORE_PASSWORD must be 64 hexadecimal characters")
    document = minidom.parse(str(xml_path))
    cores = document.getElementsByTagNameNS(CORE, "core")
    if len(cores) != 1:
        raise ValueError("Artemis core configuration was not found")
    core = cores[0]
    acceptor = named(child(core, "acceptors"), "acceptor", "name", "lifeline-tls")
    text(acceptor, (
        "tcp://0.0.0.0:61617?protocols=CORE;sslEnabled=true;keyStoreType=PKCS12;"
        "keyStorePath=/var/lib/artemis-instance/tls/broker.p12;"
        "keyStorePassword=" + password
    ))
    text(child(core, "min-disk-free"), "10737418240")
    policy = named(child(core, "address-settings"), "address-setting", "match", "lifeline.case.jobs")
    for key, value in {
        "dead-letter-address": "lifeline.case.jobs.dlq",
        "redelivery-delay": "5000",
        "redelivery-delay-multiplier": "2",
        "max-redelivery-delay": "60000",
        "max-delivery-attempts": "5",
    }.items():
        text(child(policy, key), value)
    for queue_name in ("lifeline.case.jobs", "lifeline.case.jobs.dlq"):
        address = named(child(core, "addresses"), "address", "name", queue_name)
        named(child(address, "anycast"), "queue", "name", queue_name)
    backup = xml_path.with_suffix(".xml.before-azure")
    if not backup.exists():
        shutil.copy2(xml_path, backup)
        backup.chmod(0o600)
    # Preserve the original default namespaces and unprefixed <core> tag.
    xml_path.write_bytes(document.toxml(encoding="utf-8"))
    xml_path.chmod(0o600)
    print("Configured: TLS 61617, Lifeline queues and 10 GiB disk reserve.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml", type=Path, default=Path("instance/etc/broker.xml"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    args = parser.parse_args()
    configure(args.xml, args.env)
