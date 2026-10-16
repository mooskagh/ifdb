import hashlib
import json
import os.path
import re
import shutil
import ssl
import urllib.request
from email.header import decode_header
from logging import getLogger
from typing import Any, cast
from urllib.parse import quote, unquote_to_bytes

from django.conf import settings
from django.utils import timezone

logger = getLogger("crawler")

LATIN_CYRILLIC_MIX = re.compile(
    r"[A-Za-z][\u0400-\u04ff]|[\u0400-\u04ff][A-Za-z]"
)


def decode_mojibake_filename(name: str | None) -> str | None:
    if not name:
        return name
    name = name.strip(" \t\r\n\"'")
    if not name:
        return name

    if "=?" in name and "?=" in name:
        try:
            parts = decode_header(name)
            name = "".join(
                part.decode(enc or "utf-8", errors="replace")
                if isinstance(part, bytes)
                else part
                for part, enc in parts
            )
            name = name.strip(" \t\r\n\"'")
        except Exception:
            pass

    if "%" in name:
        try:
            raw_bytes = unquote_to_bytes(name)
            try:
                candidate = raw_bytes.decode("utf-8")
                if candidate != name:
                    name = candidate
            except UnicodeDecodeError:
                try:
                    candidate = raw_bytes.decode("cp1251")
                    if any(
                        "\u0400" <= c <= "\u04ff" for c in candidate
                    ) and not LATIN_CYRILLIC_MIX.search(candidate):
                        name = candidate
                except UnicodeDecodeError:
                    pass
        except Exception:
            pass

    for enc in ("latin-1", "cp1252"):
        try:
            raw = name.encode(enc)
        except UnicodeEncodeError:
            continue

        try:
            u8 = raw.decode("utf-8")
            if u8 != name and any("\u0400" <= c <= "\u04ff" for c in u8):
                return u8
        except UnicodeDecodeError:
            pass

        try:
            cp = raw.decode("cp1251")
            if cp != name and any("\u0400" <= c <= "\u04ff" for c in cp):
                if not LATIN_CYRILLIC_MIX.search(cp):
                    return cp
        except UnicodeDecodeError:
            pass

    return name


def FetchUrlToString(
    url: str,
    use_cache: bool = True,
    encoding: str = "utf-8",
    headers: dict[str, str] | None = None,
) -> str:
    return cast(
        str,
        FetchUrlToFileLike(url, use_cache=use_cache, headers=headers)
        .read()
        .decode(encoding, "ignore"),
    )


def _ResponseInfoToMetadata(
    url: str,
    response_info: Any,
    final_url: str | None = None,
) -> dict[str, Any]:
    raw_filename = getattr(response_info, "get_filename", lambda: None)()
    if not raw_filename and hasattr(response_info, "get"):
        cd = response_info.get("content-disposition")
        if cd:
            if m := re.search(
                r'filename\*?=(?:UTF-8\'\'|")?([^";\r\n]+)', cd, re.I
            ):
                raw_filename = m.group(1).strip("\"' ")
    filename = decode_mojibake_filename(raw_filename) if raw_filename else None
    content_type = getattr(response_info, "get_content_type", lambda: None)()
    res: dict[str, Any] = {
        "url": url,
        "time": str(timezone.now()),
        "filename": filename,
        "content-type": content_type,
    }
    if final_url:
        res["final_url"] = final_url
    return res


def FetchUrlToFileLike(
    url: str,
    use_cache: bool = True,
    headers: dict[str, str] | None = None,
) -> Any:
    logger.info("Fetching: %s" % url)

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    quoted_url = quote(url.encode("utf-8"), safe="/+=&?%:@;!#$*()_-")
    request = urllib.request.Request(
        quoted_url, data=None, headers=headers or {}
    )
    if not settings.CRAWLER_CACHE_DIR or not use_cache:
        response = urllib.request.urlopen(request, context=ctx, timeout=300)
        final_url = response.geturl() if hasattr(response, "geturl") else None
        response.metadata = _ResponseInfoToMetadata(
            url, response.info(), final_url=final_url
        )
        return response

    urlhash = hashlib.md5(url.encode("utf-8")).hexdigest()
    filename = os.path.join(settings.CRAWLER_CACHE_DIR, urlhash)
    metadata_filename = os.path.join(
        settings.CRAWLER_CACHE_DIR, "%s.meta" % urlhash
    )
    listing_filename = os.path.join(
        settings.CRAWLER_CACHE_DIR, "%s.list" % timezone.now().date()
    )

    if os.path.isfile(metadata_filename):
        with open(metadata_filename, "r") as f_meta_in:
            metadata = json.loads(f_meta_in.read())
    else:
        response = urllib.request.urlopen(request, context=ctx, timeout=300)
        final_url = response.geturl() if hasattr(response, "geturl") else None
        metadata = _ResponseInfoToMetadata(
            url, response.info(), final_url=final_url
        )
        with open(filename, "wb") as f_out:
            shutil.copyfileobj(response, f_out)
        with open(metadata_filename, "w") as f_meta_out:
            f_meta_out.write(
                json.dumps(metadata, indent=2, separators=(",", ": "))
            )
        with open(listing_filename, "a") as f_list:
            f_list.write("%s %s\n" % (urlhash, url))

    f_res = open(filename, "rb")
    f_res.metadata = metadata  # type: ignore[attr-defined]
    return f_res
