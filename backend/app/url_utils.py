"""Conservative resource URL normalization; security validation also runs at connect time."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


class UnsafeURL(ValueError):
    pass


TRACKING_PARAMS = frozenset({
    "fbclid", "gclid", "dclid", "msclkid", "igshid", "spm_id_from", "vd_source",
    "from_spmid", "spmid", "share_source", "share_medium", "share_plat",
    "share_session_id", "share_tag", "mc_cid", "mc_eid",
})


def host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def assert_public_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise UnsafeURL("DNS 返回的地址无效") from exc
    if not address.is_global or address.is_multicast or address.is_unspecified:
        raise UnsafeURL("禁止访问非公网地址")
    if isinstance(address, ipaddress.IPv6Address):
        # Translation / tunneling ranges can hide nonpublic IPv4 destinations.
        if address.ipv4_mapped is not None:
            assert_public_ip(str(address.ipv4_mapped))
        if address.sixtofour is not None or address.teredo is not None:
            raise UnsafeURL("不允许 IPv6 隧道地址")
        if address in ipaddress.ip_network("64:ff9b::/96") or address in ipaddress.ip_network("64:ff9b:1::/48"):
            raise UnsafeURL("不允许 IPv6 地址转换范围")
    return str(address)


def normalize_url(url: str) -> str:
    if not isinstance(url, str) or not url or len(url) > 8192:
        raise UnsafeURL("URL 为空或过长")
    if any(ord(char) < 32 or ord(char) == 127 for char in url) or "\\" in url:
        raise UnsafeURL("URL 含控制字符或反斜杠")
    try:
        parts = urlsplit(url.strip())
        if parts.scheme.lower() not in {"https", "http"}:
            raise UnsafeURL("只允许 HTTP/HTTPS 页面")
        if parts.username is not None or parts.password is not None:
            raise UnsafeURL("URL 不允许包含凭据")
        hostname = (parts.hostname or "").rstrip(".").lower()
        if not hostname or "%" in hostname:
            raise UnsafeURL("URL 主机名无效")
        hostname = hostname.encode("idna").decode("ascii")
        port = parts.port
        if port not in {None, 80, 443}:
            raise UnsafeURL("仅允许标准网页端口")
        if hostname == "localhost" or "." not in hostname and ":" not in hostname:
            raise UnsafeURL("禁止访问本地主机名称")
        if any(host_matches(hostname, domain) for domain in ("localhost", "local", "internal", "lan", "home", "test", "invalid")):
            raise UnsafeURL("禁止访问本地或保留域名")
        if hostname in {"metadata.google.internal", "metadata.azure.internal", "instance-data.ec2.internal"}:
            raise UnsafeURL("禁止访问实例元数据服务")
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            assert_public_ip(hostname)
        netloc = f"[{hostname}]" if ":" in hostname else hostname
        if port is not None and not (parts.scheme.lower() == "https" and port == 443 or parts.scheme.lower() == "http" and port == 80):
            netloc += f":{port}"
        # Search/share links can append uid without changing the BVID or part.
        # Keep it on original links/evidence, not the recognized video's identity.
        bilibili_video = host_matches(hostname, "bilibili.com") and re.fullmatch(
            r"/video/(?:BV[0-9A-Za-z]{10}|av\d+)/?", parts.path
        ) is not None
        # Never drop p/course/chapter/term/version or other unknown query parameters.
        query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                 if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
                 and not (bilibili_video and key.lower() == "uid")]
        return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", urlencode(query), parts.fragment))
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, UnsafeURL):
            raise
        raise UnsafeURL("URL 无法解析") from exc


def platform_for_url(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return "other"
    for domain, name in (("bilibili.com", "bilibili"), ("b23.tv", "bilibili"),
                         ("icourse163.org", "icourse163"), ("xuetangx.com", "xuetangx")):
        if host_matches(host, domain):
            return name
    return "other"


def safe_thumbnail_url(value, base_url: str | None = None) -> str | None:
    """Validate an observed image reference without fetching or inventing one.

    Image CDN query syntax can be signed or use bare keys, so retain its exact
    path/query after the ordinary public HTTP(S) URL safety checks.
    """
    if not isinstance(value, str) or not value.strip() or len(value) > 8192:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value) or "\\" in value:
        return None
    try:
        absolute = urljoin(base_url, value.strip()) if base_url else value.strip()
        checked = urlsplit(normalize_url(absolute))
        original = urlsplit(absolute)
        # Browsers interpret abbreviated/octal/hex IPv4 forms differently from
        # Python's ipaddress. Reject those ambiguous numeric host spellings.
        host = checked.hostname or ""
        if re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)(?:\.(?:[0-9]+|0x[0-9a-f]+))*", host, re.I):
            assert_public_ip(host)
        return urlunsplit((checked.scheme, checked.netloc, original.path or "/", original.query, ""))
    except (UnsafeURL, TypeError, ValueError):
        return None
