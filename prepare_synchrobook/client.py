"""Authenticated Nokturn API. Scoped keys live only in memory; redirects are refused."""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def server_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Podaj adres Nokturna, np. https://nokturn-library.pl.")
    if parsed.scheme == "http":
        try:
            local = ipaddress.ip_address(parsed.hostname).is_private or ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            local = parsed.hostname == "localhost"
        if not local:
            raise ValueError("Poza siecią lokalną użyj HTTPS, aby chronić dane logowania.")
    return value


class NokturnClient:
    def __init__(self, url: str):
        self.url = server_url(url)
        self.token = ""
        self.opener = build_opener(NoRedirect)

    def request(self, path: str, data=None, content_type="application/json", timeout=60):
        headers = {"Accept": "application/json", "Content-Type": content_type,
                   "User-Agent": "PrepareSynchrobook/0.1.0"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if data is not None and content_type == "application/json":
            data = json.dumps(data).encode()
        try:
            with self.opener.open(Request(self.url + path, data=data, headers=headers), timeout=timeout) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                detail = json.load(error).get("detail", "")
            except (ValueError, AttributeError):
                detail = ""
            if error.code == 401:
                self.token = ""
            raise ValueError(f"Nokturn: HTTP {error.code}. {detail or 'Sprawdź adres, połączenie i wersję serwera.'}") from None

    def connect(self, api_key: str):
        self.token = ""
        api_key = api_key.strip()
        if not api_key.startswith("nk_sync_") or len(api_key) > 160 or any(c.isspace() for c in api_key):
            raise ValueError("Wklej klucz API synchrobooków wygenerowany w Nokturnie (nk_sync_…).")
        self.token = api_key
        try:
            capabilities = self.request("/api/synchrobooks/capabilities")
            if capabilities.get("schema") != 1 or not capabilities.get("existing_epub_only"):
                raise ValueError("Serwer nie obsługuje tego formatu. Zaktualizuj Nokturna.")
        except Exception:
            self.token = ""
            raise
        return "klucz API"

    def search(self, query: str):
        return self.request("/api/synchrobooks/books?" + urlencode({"q": query}))["items"]

    def download_epub(self, audiobook_id: int, destination: Path):
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/epub+zip"}
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        try:
            with self.opener.open(Request(self.url + f"/api/synchrobooks/{int(audiobook_id)}/epub", headers=headers), timeout=180) as response:
                if response.headers.get_content_type() != "application/epub+zip":
                    raise ValueError("Serwer nie zwrócił EPUB przypisanego do tego audiobooka.")
                count = 0
                with temporary.open("wb") as stream:
                    while block := response.read(1024 * 1024):
                        count += len(block)
                        if count > 64 * 1024 * 1024:
                            raise ValueError("EPUB jest większy niż 64 MiB.")
                        stream.write(block)
            from .alignment import epub_paragraphs
            epub_paragraphs(temporary)
            temporary.replace(destination)
            return destination
        except HTTPError as error:
            if error.code == 401:
                self.token = ""
            raise ValueError(f"Nie udało się pobrać EPUB z Nokturna (HTTP {error.code}). Sprawdź przypisanie e-booka i zaloguj się ponownie, jeśli sesja wygasła.") from None
        finally:
            temporary.unlink(missing_ok=True)

    def upload(self, audiobook_id: int, package: Path):
        return self.request(f"/api/synchrobooks/{int(audiobook_id)}/import?" + urlencode({"reviewed": "true"}),
                            package.read_bytes(), "application/zip", timeout=1800)
