"""Mailbox addresses: {login}@{mail domain}."""

from email.utils import parseaddr


def mailbox_address(login: str, domain: str) -> str:
    """Return the student's mail address in lower case."""
    return f"{login}@{domain}".lower()


def login_from_address(address: str, domain: str) -> str | None:
    """Return the login if the address belongs to our mail domain, else None."""
    _, addr = parseaddr(address)
    local, separator, host = addr.rpartition("@")
    if not separator or not local or host.lower() != domain.lower():
        return None
    return local.lower()


def address_domain(address: str) -> str | None:
    """Return the lower-case domain of an address, or None when it has none."""
    _, addr = parseaddr(address)
    _, separator, host = addr.rpartition("@")
    if not separator or not host:
        return None
    return host.lower().rstrip(".")
