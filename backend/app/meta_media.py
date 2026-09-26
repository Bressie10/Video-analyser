"""Resolve short-lived media URLs and download to bounded temporary storage."""

import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit

import httpx

from app import meta

MAX_BYTES = 500 * 1024 * 1024


class MediaUnavailable(ValueError):
    pass


def media_url(client, item):
    if item["platform"] == "instagram":
        payload = client.get(item["external_id"], {"fields": "id,media_type,media_url"})
        field = "media_url"
    else:
        provider = (
            client.for_page(item["account_external_id"])
            if item["account_external_id"].isdigit()
            else client
        )
        payload = provider.get(item["external_id"], {"fields": "id,source"})
        field = "source"
    if payload.get("id") != item["external_id"]:
        raise meta.MetaError("Unexpected video identity.")
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise MediaUnavailable(
            "Meta does not provide downloadable media for this item."
        )
    return value


def validate_url(url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or not any(
                host.endswith("." + domain)
                for domain in ("fbcdn.net", "cdninstagram.com", "facebook.com")
            )
        ):
            raise ValueError()
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(row[4][0]).is_global for row in addresses
        ):
            raise ValueError()
    except (ValueError, OSError):
        raise MediaUnavailable("Meta returned an unsupported media location.") from None


def download(url, destination):
    # No access-token headers on CDN requests and no automatic redirects. Do not
    # log signed URLs; httpx INFO logging is redacted by the shared Meta filter.
    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(30, connect=10),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            for _ in range(4):
                validate_url(url)
                with client.stream("GET", url) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    if response.status_code in (403, 404, 410):
                        raise MediaUnavailable(
                            "Meta media is not currently downloadable."
                        )
                    response.raise_for_status()
                    length = response.headers.get("content-length")
                    if length and int(length) > MAX_BYTES:
                        raise MediaUnavailable("Video exceeds the 500 MiB limit.")
                    size = 0
                    with destination.open("wb") as output:
                        for chunk in response.iter_bytes(1024 * 1024):
                            size += len(chunk)
                            if size > MAX_BYTES or time.monotonic() - started > 300:
                                raise MediaUnavailable("Video exceeds download limits.")
                            output.write(chunk)
                    if not size:
                        raise MediaUnavailable("Meta returned empty media.")
                    return
            raise MediaUnavailable("Too many media redirects.")
    except (httpx.HTTPError, ValueError) as error:
        if isinstance(error, MediaUnavailable):
            raise
        raise meta.MetaError("Media download failed.") from None
