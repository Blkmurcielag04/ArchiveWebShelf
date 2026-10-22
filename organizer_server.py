from __future__ import annotations

import copy
import gzip
import hashlib
import json
import mimetypes
import os
import re
import shutil
import threading
import uuid
import webbrowser
import zipfile
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import parse_qs, unquote, urlparse, urlunparse
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent
LIBRARY = Path(os.environ.get("ARCHIVE_SHELF_LIBRARY_DIR", ROOT / "library")).resolve()
DATA_FILE = Path(os.environ.get("ARCHIVE_SHELF_DATA_FILE", ROOT / "archive-shelf-data.json")).resolve()
SUPPORTED = {".wacz", ".warc", ".har", ".cdx", ".cdxj"}
START_PORT = int(os.environ.get("ARCHIVE_SHELF_PORT", "8765"))
MAX_JSON_BYTES = 1024 * 1024
MAX_UPLOAD_BYTES = int(os.environ.get("ARCHIVE_SHELF_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024 * 1024)))
ARCHIVE_ID = re.compile(r"^[a-f0-9]{32}$")
EXTENSION_ID = re.compile(r"^[a-p]{32}$")
STATE_LOCK = threading.RLock()

APP_STATIC = {
    "/": ROOT / "index.html",
    "/index.html": ROOT / "index.html",
    "/archive-shelf-logo.png": ROOT / "archive-shelf-logo.png",
    "/archive-shelf-logo.svg": ROOT / "archive-shelf-logo.svg",
}
REPLAY_STATIC = {
    "/replay-viewer.html": ROOT / "replay-viewer.html",
    "/replay-viewer.js": ROOT / "replay-viewer.js",
    "/replay/ui.js": ROOT / "replay" / "ui.js",
    "/replay/sw.js": ROOT / "replay" / "sw.js",
    "/replay/": ROOT / "replay" / "index.html",
    "/replay/index.html": ROOT / "replay" / "index.html",
}


def normalize_page_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Enter a complete http:// or https:// page URL.")
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower()
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("That page URL has an invalid port.") from error
    netloc = host
    if ":" in host and not host.startswith("["):
        netloc = f"[{host}]"
    if port and not (scheme == "http" and port == 80) and not (scheme == "https" and port == 443):
        netloc += f":{port}"
    return urlunparse((scheme, netloc, parsed.path or "/", parsed.params, parsed.query, ""))


def page_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
    except (TypeError, ValueError):
        return ""


def page_cdx_timestamps(value: str) -> set[str]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
        seconds = parsed.strftime("%Y%m%d%H%M%S")
        milliseconds = parsed.microsecond // 1000
        return {seconds, f"{seconds}{milliseconds:03d}"}
    except (AttributeError, TypeError, ValueError):
        return set()

def find_archived_pages(url: str) -> list[dict]:
    wanted = normalize_page_url(url)
    matches = []
    with STATE_LOCK:
        items = list(load_data()["items"])
    for item in items:
        if Path(str(item.get("name", ""))).suffix.lower() != ".wacz":
            continue
        archive_id = str(item.get("id", ""))
        if not ARCHIVE_ID.fullmatch(archive_id):
            continue
        archive_path = (LIBRARY / archive_id / str(item.get("name", ""))).resolve()
        if not archive_path.is_relative_to(LIBRARY) or not archive_path.is_file():
            continue
        try:
            with zipfile.ZipFile(archive_path) as archive:
                with archive.open("pages/pages.jsonl") as pages:
                    for raw_line in pages:
                        try:
                            page = json.loads(raw_line)
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            continue
                        if isinstance(page, dict):
                            try:
                                page_url = normalize_page_url(str(page.get("url", "")))
                            except ValueError:
                                continue
                            if page_url != wanted:
                                continue
                            matches.append({
                                "id": archive_id,
                                "name": str(item.get("name", "")),
                                "folder": str(item.get("folder", "")),
                                "title": str(page.get("title") or page.get("url") or wanted)[:300],
                                "url": wanted,
                                "ts": page_timestamp(str(page.get("ts", ""))),
                            })
                            break
        except (OSError, KeyError, zipfile.BadZipFile, RuntimeError):
            continue
    return matches

def archive_file_for_id(archive_id: str) -> Path:
    if not ARCHIVE_ID.fullmatch(archive_id):
        raise FileNotFoundError("That archive could not be found.")
    with STATE_LOCK:
        data = load_data()
        item = next((entry for entry in data["items"] if entry.get("id") == archive_id), None)
    if item is None:
        raise FileNotFoundError("That archive is no longer in the organizer.")
    name = str(item.get("name", ""))
    if Path(name).suffix.lower() != ".wacz" or PureWindowsPath(name.replace("/", "\\")).name != name:
        raise ValueError("Saved-page management is available for WACZ archives only.")
    library_root = LIBRARY.resolve()
    archive_path = (library_root / archive_id / name).resolve()
    if not archive_path.is_relative_to(library_root) or not archive_path.is_file():
        raise FileNotFoundError("That WACZ file could not be found.")
    return archive_path


def page_rows_from_bytes(raw_pages: bytes) -> tuple[list[bytes], list[dict]]:
    lines = raw_pages.splitlines(keepends=True)
    if raw_pages and not lines:
        lines = [raw_pages]
    occurrences: dict[bytes, int] = {}
    pages = []
    for line_index, raw_line in enumerate(lines):
        line = raw_line.rstrip(b"\r\n")
        if not line:
            continue
        try:
            page = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(page, dict) or not page.get("url") or not page.get("ts"):
            continue
        try:
            url = normalize_page_url(str(page.get("url", "")))
        except ValueError:
            continue
        fingerprint = hashlib.sha256(line).digest()
        duplicate_number = occurrences.get(fingerprint, 0)
        occurrences[fingerprint] = duplicate_number + 1
        key = hashlib.sha256(fingerprint + b":" + str(duplicate_number).encode("ascii")).hexdigest()
        pages.append({
            "key": key,
            "line": line_index,
            "title": str(page.get("title") or url)[:300],
            "url": url,
            "ts": str(page.get("ts", ""))[:100],
            "size": page.get("size") if isinstance(page.get("size"), int) else 0,
        })
    return lines, pages


def list_archive_pages(archive_id: str) -> list[dict]:
    archive_path = archive_file_for_id(archive_id)
    with zipfile.ZipFile(archive_path) as archive:
        if "pages/pages.jsonl" not in archive.namelist():
            raise ValueError("This WACZ does not contain a saved-pages list.")
        _, pages = page_rows_from_bytes(archive.read("pages/pages.jsonl"))
    return pages


def delete_archive_page(archive_id: str, page_key: str) -> dict:
    if not re.fullmatch(r"[a-f0-9]{64}", page_key):
        raise FileNotFoundError("That saved page is no longer in this archive.")
    with STATE_LOCK:
        archive_path = archive_file_for_id(archive_id)
        temporary = archive_path.with_name(f".{archive_path.name}.{uuid.uuid4().hex}.tmp")
        temporary_warc = None
        try:
            with zipfile.ZipFile(archive_path, "r") as source:
                names = source.namelist()
                pages_path = "pages/pages.jsonl"
                digest_path = "datapackage-digest.json"
                if pages_path not in names or "datapackage.json" not in names or digest_path not in names:
                    raise ValueError("This WACZ is missing required page metadata.")
                if any("signature" in name.lower() or name.lower().endswith("wacz-auth.json") for name in names):
                    raise ValueError("This signed or protected WACZ cannot be edited safely.")
                package = json.loads(source.read("datapackage.json"))
                digest = json.loads(source.read(digest_path))
                if digest.get("signedData"):
                    raise ValueError("This signed WACZ cannot be edited safely.")

                resources = package.get("resources", [])
                index_paths = list(dict.fromkeys(
                    str(resource.get("path", ""))
                    for resource in resources
                    if str(resource.get("path", "")).startswith("indexes/")
                    and str(resource.get("path", "")).lower().endswith((".cdx", ".cdxj", ".cdx.gz", ".cdxj.gz"))
                    and str(resource.get("path", "")) in names
                ))
                if not index_paths:
                    index_paths = [
                        name for name in names
                        if name.startswith("indexes/")
                        and name.lower().endswith((".cdx", ".cdxj", ".cdx.gz", ".cdxj.gz"))
                    ]
                if not index_paths:
                    raise ValueError("This WACZ does not contain a replay index.")

                page_lines, pages = page_rows_from_bytes(source.read(pages_path))
                selected = next((page for page in pages if page["key"] == page_key), None)
                if selected is None:
                    raise FileNotFoundError("That saved page is no longer in this archive.")

                index_data = {}
                index_candidates = []
                target_timestamps = page_cdx_timestamps(selected["ts"])
                for index_path in index_paths:
                    stored_index = source.read(index_path)
                    is_compressed = index_path.lower().endswith(".gz")
                    decoded_index = gzip.decompress(stored_index) if is_compressed else stored_index
                    lines = decoded_index.splitlines(keepends=True)
                    index_data[index_path] = (is_compressed, lines)
                    matches = []
                    for line_index, raw_line in enumerate(lines):
                        parts = raw_line.strip().split(None, 2)
                        if len(parts) != 3 or parts[1].decode("ascii", "ignore") not in target_timestamps:
                            continue
                        try:
                            record = json.loads(parts[2])
                            record_url = normalize_page_url(str(record.get("url", ""))) if isinstance(record, dict) else ""
                        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                            continue
                        if record_url == selected["url"]:
                            try:
                                filename = str(record["filename"])
                                offset = int(record["offset"])
                                length = int(record["length"])
                            except (KeyError, TypeError, ValueError):
                                raise ValueError("The replay index does not identify this page’s WARC record safely.")
                            if not filename or offset < 0 or length <= 0:
                                raise ValueError("The replay index has an invalid WARC record range.")
                            matches.append((line_index, record, filename, offset, length))
                    if len(matches) > 1:
                        raise ValueError("This capture shares an index timestamp with another saved record. Archive Shelf left it unchanged.")
                    if matches:
                        index_candidates.append(matches[0][1:])
                if not index_candidates:
                    raise ValueError("Archive Shelf could not safely locate this saved page’s WARC record, so it left the archive unchanged.")

                record_locations = {(filename, offset, length) for _, filename, offset, length in index_candidates}
                if len(record_locations) != 1:
                    raise ValueError("This page points to different WARC records in its indexes. Archive Shelf left the archive unchanged.")
                target_filename, target_offset, target_length = next(iter(record_locations))
                target_record = index_candidates[0][0]
                warc_paths = [
                    str(resource.get("path", ""))
                    for resource in resources
                    if str(resource.get("path", "")).startswith("archive/")
                    and (str(resource.get("path", "")) == target_filename
                         or PurePosixPath(str(resource.get("path", ""))).name == PurePosixPath(target_filename).name)
                ]
                if not warc_paths:
                    warc_paths = [
                        name for name in names
                        if name.startswith("archive/")
                        and PurePosixPath(name).name == PurePosixPath(target_filename).name
                    ]
                warc_paths = list(dict.fromkeys(path for path in warc_paths if path in names))
                if len(warc_paths) != 1:
                    raise ValueError("Archive Shelf could not safely match the page to one WARC file.")
                warc_path = warc_paths[0]
                warc_info = source.getinfo(warc_path)
                if target_offset + target_length > warc_info.file_size:
                    raise ValueError("The replay index points outside the WARC file. Archive Shelf left it unchanged.")

                target_digest = target_record.get("digest")
                if target_digest and target_record.get("mime") != "warc/revisit":
                    for _, lines in index_data.values():
                        for raw_line in lines:
                            parts = raw_line.strip().split(None, 2)
                            if len(parts) != 3:
                                continue
                            try:
                                record = json.loads(parts[2])
                                record_offset = int(record.get("offset", -1)) if isinstance(record, dict) else -1
                            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                                continue
                            if (
                                isinstance(record, dict)
                                and record.get("filename") == target_filename
                                and record_offset == target_offset
                            ):
                                continue
                            if (
                                isinstance(record, dict)
                                and record.get("mime") == "warc/revisit"
                                and record.get("digest") == target_digest
                            ):
                                raise ValueError("Another saved page reuses this page’s response. Archive Shelf left the archive unchanged to protect that page.")

                updated_pages = b"".join(
                    line for index, line in enumerate(page_lines)
                    if index != selected["line"]
                )
                updated_indexes = {}
                removed_index_rows = 0
                for index_path, (is_compressed, lines) in index_data.items():
                    rewritten_lines = []
                    for raw_line in lines:
                        ending = b"\r\n" if raw_line.endswith(b"\r\n") else b"\n" if raw_line.endswith(b"\n") else b""
                        body = raw_line[:-len(ending)] if ending else raw_line
                        parts = body.split(None, 2)
                        if len(parts) != 3:
                            rewritten_lines.append(raw_line)
                            continue
                        try:
                            record = json.loads(parts[2])
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            rewritten_lines.append(raw_line)
                            continue
                        if not isinstance(record, dict) or record.get("filename") != target_filename:
                            rewritten_lines.append(raw_line)
                            continue
                        try:
                            record_offset = int(record.get("offset", -1))
                        except (TypeError, ValueError):
                            rewritten_lines.append(raw_line)
                            continue
                        if record_offset == target_offset:
                            removed_index_rows += 1
                            continue
                        if record_offset > target_offset:
                            old_offset = record.get("offset")
                            shifted_offset = record_offset - target_length
                            record["offset"] = str(shifted_offset) if isinstance(old_offset, str) else shifted_offset
                            encoded_record = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                            rewritten_lines.append(parts[0] + b" " + parts[1] + b" " + encoded_record + ending)
                        else:
                            rewritten_lines.append(raw_line)
                    updated_index = b"".join(rewritten_lines)
                    updated_indexes[index_path] = gzip.compress(updated_index, mtime=0) if is_compressed else updated_index
                if not removed_index_rows:
                    raise ValueError("Archive Shelf could not remove this page from the replay index, so it left the archive unchanged.")

                temporary_warc = archive_path.with_name(f".{archive_path.name}.{uuid.uuid4().hex}.warc.tmp")
                warc_hash = hashlib.sha256()
                warc_size = 0
                with source.open(warc_path, "r") as original, temporary_warc.open("xb") as rewritten:
                    def copy_warc_bytes(count: int | None) -> None:
                        nonlocal warc_size
                        remaining = count
                        while remaining is None or remaining > 0:
                            block = original.read(1024 * 1024 if remaining is None else min(1024 * 1024, remaining))
                            if not block:
                                if remaining not in (None, 0):
                                    raise ValueError("The WARC file ended before the selected record range.")
                                break
                            rewritten.write(block)
                            warc_hash.update(block)
                            warc_size += len(block)
                            if remaining is not None:
                                remaining -= len(block)

                    copy_warc_bytes(target_offset)
                    remaining_to_remove = target_length
                    while remaining_to_remove:
                        skipped = original.read(min(1024 * 1024, remaining_to_remove))
                        if not skipped:
                            raise ValueError("The WARC file ended inside the selected record range.")
                        remaining_to_remove -= len(skipped)
                    copy_warc_bytes(None)

                package["modified"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                for resource in resources:
                    resource_path = str(resource.get("path", ""))
                    if resource_path == pages_path:
                        resource["bytes"] = len(updated_pages)
                        resource["hash"] = "sha256:" + hashlib.sha256(updated_pages).hexdigest()
                    elif resource_path in updated_indexes:
                        index_bytes = updated_indexes[resource_path]
                        resource["bytes"] = len(index_bytes)
                        resource["hash"] = "sha256:" + hashlib.sha256(index_bytes).hexdigest()
                    elif resource_path == warc_path:
                        resource["bytes"] = warc_size
                        resource["hash"] = "sha256:" + warc_hash.hexdigest()
                package_bytes = (json.dumps(package, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                digest["hash"] = "sha256:" + hashlib.sha256(package_bytes).hexdigest()
                digest_bytes = (json.dumps(digest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                replacements = {
                    pages_path: updated_pages,
                    **updated_indexes,
                    "datapackage.json": package_bytes,
                    digest_path: digest_bytes,
                }

                with zipfile.ZipFile(temporary, "w", allowZip64=True) as target:
                    target.comment = source.comment
                    for info in source.infolist():
                        copied_info = copy.copy(info)
                        if info.filename in replacements:
                            target.writestr(copied_info, replacements[info.filename])
                        elif info.filename == warc_path:
                            with temporary_warc.open("rb") as rewritten, target.open(copied_info, "w", force_zip64=True) as output:
                                shutil.copyfileobj(rewritten, output, 1024 * 1024)
                        else:
                            with source.open(info, "r") as original, target.open(copied_info, "w", force_zip64=True) as copied:
                                shutil.copyfileobj(original, copied, 1024 * 1024)

            with zipfile.ZipFile(temporary, "r") as check:
                corrupt_entry = check.testzip()
                if corrupt_entry:
                    raise OSError(f"The updated WACZ failed its integrity check at {corrupt_entry}.")
            os.replace(temporary, archive_path)
            try:
                data = load_data()
                item = next((entry for entry in data["items"] if entry.get("id") == archive_id), None)
                if item is not None:
                    item["size"] = archive_path.stat().st_size
                    save_data(data)
            except OSError:
                pass
            return {
                "ok": True,
                "page": {key: selected[key] for key in ("title", "url", "ts")},
                "remaining": len(pages) - 1,
            }
        finally:
            for temporary_file in (temporary, temporary_warc):
                if temporary_file is not None:
                    try:
                        temporary_file.unlink(missing_ok=True)
                    except OSError:
                        pass

class RequestTooLarge(ValueError):
    pass


def clean_path(value: str) -> str:
    return " / ".join(part.strip() for part in value.replace("\\", "/").split("/") if part.strip())


def load_data() -> dict:
    if not DATA_FILE.exists():
        return {"groups": [], "items": []}
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("groups"), list) or not isinstance(data.get("items"), list):
            raise ValueError("Invalid organizer data")
        return data
    except (OSError, ValueError, json.JSONDecodeError):
        return {"groups": [], "items": []}


def save_data(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = DATA_FILE.with_name(f".{DATA_FILE.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, DATA_FILE)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def ensure_groups(data: dict, folder: str) -> None:
    parts = clean_path(folder).split(" / ") if clean_path(folder) else []
    existing = {str(group).casefold() for group in data["groups"]}
    for index in range(1, len(parts) + 1):
        group = " / ".join(parts[:index])
        if group.casefold() not in existing:
            data["groups"].append(group)
            existing.add(group.casefold())


def open_app(url: str) -> None:
    if os.environ.get("ARCHIVE_SHELF_NO_BROWSER") != "1":
        webbrowser.open(url)


class ArchiveShelfHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format, *args):
        print("Archive Shelf:", format % args, flush=True)

    def host_kind(self) -> str | None:
        port = self.server.server_port
        host = self.headers.get("Host", "").strip().lower()
        if host in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            return "app"
        if host == f"replay.localhost:{port}":
            return "replay"
        return None

    def valid_origin(self, kind: str, *, allow_missing: bool = False) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return allow_missing
        parsed = urlparse(origin)
        port = self.server.server_port
        if kind == "app":
            if parsed.scheme == "http" and parsed.netloc.lower() in {
                f"127.0.0.1:{port}", f"localhost:{port}"
            } and parsed.path in ("", "/"):
                return True
            return parsed.scheme == "chrome-extension" and bool(EXTENSION_ID.fullmatch(parsed.netloc)) and parsed.path in ("", "/")
        return (
            parsed.scheme == "http"
            and parsed.netloc.lower() == f"replay.localhost:{port}"
            and parsed.path in ("", "/")
        )

    def check_request(self, *, mutation: bool = False) -> str | None:
        kind = self.host_kind()
        if not kind:
            self.send_error(403, "Archive Shelf only accepts local host names.")
            return None
        if mutation and kind != "app":
            self.send_error(403, "Changes are disabled on the replay viewer host.")
            return None
        if not self.valid_origin(kind, allow_missing=not mutation):
            self.send_error(403, "The request origin is not allowed.")
            return None
        return kind

    def allow_extension_origin(self) -> None:
        origin = self.headers.get("Origin", "")
        parsed = urlparse(origin)
        if parsed.scheme == "chrome-extension" and EXTENSION_ID.fullmatch(parsed.netloc):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def respond(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.allow_extension_origin()
        self.end_headers()
        self.wfile.write(body)

    def send_static_file(self, filename: Path, *, cache: str = "no-store") -> None:
        if not filename.is_file():
            self.send_error(404, "File not found.")
            return
        size = filename.stat().st_size
        content_type = mimetypes.guess_type(str(filename))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if filename == ROOT / "index.html":
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; connect-src 'self'; frame-src http://replay.localhost:*; "
                "object-src 'none'; base-uri 'self'; frame-ancestors 'self'",
            )
        elif filename == ROOT / "replay-viewer.html":
            port = self.server.server_port
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; connect-src 'self'; frame-src 'self'; worker-src 'self'; "
                f"object-src 'none'; base-uri 'self'; frame-ancestors http://localhost:{port} http://127.0.0.1:{port}",
            )
        self.end_headers()
        if self.command != "HEAD":
            with filename.open("rb") as source:
                shutil.copyfileobj(source, self.wfile)

    def serve_library_file(self, raw_path: str, include_body: bool) -> None:
        relative = unquote(raw_path.removeprefix("/library/"))
        parts = PurePosixPath(relative).parts
        if len(parts) != 2 or not ARCHIVE_ID.fullmatch(parts[0]):
            self.send_error(404, "Archive file not found.")
            return
        archive_id, filename = parts
        with STATE_LOCK:
            item = next((entry for entry in load_data()["items"] if entry.get("id") == archive_id), None)
        if not item or item.get("name") != filename:
            self.send_error(404, "Archive file not found.")
            return

        library_root = LIBRARY.resolve()
        archive_path = (library_root / archive_id / filename).resolve()
        if not archive_path.is_relative_to(library_root) or not archive_path.is_file():
            self.send_error(404, "Archive file not found.")
            return

        size = archive_path.stat().st_size
        start, end, status = 0, size - 1, 200
        range_header = self.headers.get("Range")
        if range_header:
            try:
                unit, values = range_header.split("=", 1)
                if unit.strip().lower() != "bytes" or "," in values:
                    raise ValueError("Only one byte range is supported")
                first, last = values.strip().split("-", 1)
                if first:
                    start = int(first)
                    end = int(last) if last else size - 1
                else:
                    suffix_length = int(last)
                    if suffix_length <= 0:
                        raise ValueError("Invalid suffix range")
                    start = max(size - suffix_length, 0)
                    end = size - 1
                if size <= 0 or start < 0 or start >= size or end < start:
                    raise ValueError("Range is outside the archive")
                end = min(end, size - 1)
                status = 206
            except (ValueError, IndexError):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

        content_length = max(end - start + 1, 0)
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(str(archive_path))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(content_length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()

        if include_body and content_length:
            with archive_path.open("rb") as archive:
                archive.seek(start)
                remaining = content_length
                while remaining:
                    block = archive.read(min(1024 * 1024, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)

    def do_GET(self):
        kind = self.check_request()
        if not kind:
            return
        parsed = urlparse(self.path)
        if kind == "app":
            if parsed.path == "/api/find-page":
                query = parse_qs(parsed.query)
                raw_url = query.get("url", [""])[0]
                if len(raw_url) > 4096:
                    self.respond(400, {"error": "That page URL is too long."})
                    return
                try:
                    matches = find_archived_pages(raw_url)
                except ValueError as error:
                    self.respond(400, {"error": str(error)})
                    return
                self.respond(200, {"matches": matches})
                return
            if parsed.path == "/api/archive-pages":
                archive_id = parse_qs(parsed.query).get("id", [""])[0]
                try:
                    self.respond(200, {"pages": list_archive_pages(archive_id)})
                except FileNotFoundError as error:
                    self.respond(404, {"error": str(error)})
                except ValueError as error:
                    self.respond(400, {"error": str(error)})
                except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError, RuntimeError) as error:
                    self.respond(422, {"error": f"Could not read saved pages from this WACZ: {error}"})
                return
            if parsed.path == "/api/state":
                with STATE_LOCK:
                    state = load_data()
                self.respond(200, {"application": "archive-shelf", "protocol": 1, **state})
                return
            static_file = APP_STATIC.get(parsed.path)
            if static_file:
                self.send_static_file(static_file)
                return
        else:
            if parsed.path.startswith("/library/"):
                self.serve_library_file(parsed.path, include_body=True)
                return
            static_file = REPLAY_STATIC.get(parsed.path)
            if static_file:
                self.send_static_file(static_file, cache="no-cache" if parsed.path.endswith(".html") else "no-store")
                return
        self.send_error(404, "Not found.")

    def do_HEAD(self):
        kind = self.check_request()
        if not kind:
            return
        parsed = urlparse(self.path)
        if kind == "replay" and parsed.path.startswith("/library/"):
            self.serve_library_file(parsed.path, include_body=False)
            return
        static_file = (APP_STATIC if kind == "app" else REPLAY_STATIC).get(parsed.path)
        if static_file:
            self.send_static_file(static_file)
            return
        self.send_error(404, "Not found.")

    def do_POST(self):
        if not self.check_request(mutation=True):
            return
        parsed = urlparse(self.path)

        if parsed.path == "/api/group":
            try:
                payload = self.read_json()
                folder = clean_path(str(payload.get("path", "")))
                if not folder:
                    self.respond(400, {"error": "Enter a folder name."})
                    return
                with STATE_LOCK:
                    data = load_data()
                    ensure_groups(data, folder)
                    save_data(data)
                self.respond(200, {"ok": True})
            except RequestTooLarge as error:
                self.respond(413, {"error": str(error)})
            except (ValueError, json.JSONDecodeError) as error:
                self.respond(400, {"error": str(error)})
            except OSError:
                self.respond(500, {"error": "Could not save the folder list."})
            return

        if parsed.path == "/api/import":
            query = parse_qs(parsed.query)
            original_name = query.get("name", ["archive.wacz"])[0]
            safe_name = PureWindowsPath(original_name.replace("/", "\\")).name
            safe_name = "".join("_" if ord(char) < 32 else char for char in safe_name).strip(" .")[:240]
            lower_name = safe_name.lower()
            extension = Path(safe_name).suffix.lower()
            if not safe_name or safe_name in {".", ".."}:
                self.respond(400, {"error": "Choose a file with a valid name."})
                return
            if extension not in SUPPORTED and not lower_name.endswith(".warc.gz"):
                self.respond(400, {"error": "Choose a WACZ, WARC, HAR, or CDX archive."})
                return

            transfer_encoding = self.headers.get("Transfer-Encoding", "").strip().lower()
            content_length_header = self.headers.get("Content-Length")
            is_chunked = transfer_encoding == "chunked"
            if transfer_encoding and not is_chunked or (is_chunked and content_length_header is not None):
                self.respond(400, {"error": "The upload used an unsupported transfer format."})
                return
            try:
                length = None if is_chunked else int(content_length_header or "0")
            except ValueError:
                self.respond(400, {"error": "The upload size was invalid."})
                return
            if length is not None and length <= 0:
                self.respond(400, {"error": "The selected archive is empty."})
                return
            if length is not None and length > MAX_UPLOAD_BYTES:
                self.respond(413, {"error": f"The archive is larger than the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit."})
                return

            migration_id = query.get("migrationId", [""])[0].strip()[:200]
            folder = clean_path(query.get("folder", [""])[0])
            archive_id = uuid.uuid4().hex
            target_dir = LIBRARY / archive_id
            target_dir.mkdir(parents=True, exist_ok=False)
            target = target_dir / safe_name
            try:
                with target.open("xb") as output:
                    if is_chunked:
                        length = self.copy_chunked_body(output, MAX_UPLOAD_BYTES)
                    else:
                        remaining = length
                        while remaining:
                            block = self.rfile.read(min(1024 * 1024, remaining))
                            if not block:
                                break
                            output.write(block)
                            remaining -= len(block)
                        if remaining:
                            raise ValueError("The archive upload did not finish.")
                if length <= 0:
                    raise ValueError("The selected archive is empty.")
            except RequestTooLarge as error:
                shutil.rmtree(target_dir, ignore_errors=True)
                self.respond(413, {"error": str(error)})
                return
            except (OSError, ValueError, OverflowError) as error:
                shutil.rmtree(target_dir, ignore_errors=True)
                self.respond(400, {"error": str(error) or "The archive upload did not finish."})
                return

            try:
                with STATE_LOCK:
                    data = load_data()
                    duplicate = next((entry for entry in data["items"] if migration_id and entry.get("migrationId") == migration_id), None)
                    if duplicate:
                        shutil.rmtree(target_dir, ignore_errors=True)
                        self.respond(200, {"ok": True, "id": duplicate["id"], "alreadyImported": True})
                        return
                    item = {"id": archive_id, "name": safe_name, "folder": folder, "size": length}
                    if migration_id:
                        item["migrationId"] = migration_id
                    data["items"].append(item)
                    ensure_groups(data, folder)
                    save_data(data)
            except OSError:
                shutil.rmtree(target_dir, ignore_errors=True)
                self.respond(500, {"error": "The archive was received, but Archive Shelf could not save its list."})
                return
            self.respond(200, {"ok": True, "id": archive_id})
            return

        if parsed.path == "/api/move":
            try:
                payload = self.read_json()
                archive_id = str(payload.get("id", ""))
                folder = clean_path(str(payload.get("folder", "")))
            except RequestTooLarge as error:
                self.respond(413, {"error": str(error)})
                return
            except (ValueError, json.JSONDecodeError) as error:
                self.respond(400, {"error": str(error)})
                return
            with STATE_LOCK:
                data = load_data()
                item = next((entry for entry in data["items"] if entry.get("id") == archive_id), None)
                if item is None:
                    self.respond(404, {"error": "That archive is no longer in the organizer."})
                    return
                item["folder"] = folder
                ensure_groups(data, folder)
                try:
                    save_data(data)
                except OSError:
                    self.respond(500, {"error": "Could not save the new folder location."})
                    return
            self.respond(200, {"ok": True, "folder": folder})
            return

        if parsed.path == "/api/move-group":
            try:
                payload = self.read_json()
                source = clean_path(str(payload.get("path", "")))
                parent = clean_path(str(payload.get("parent", "")))
            except RequestTooLarge as error:
                self.respond(413, {"error": str(error)})
                return
            except (ValueError, json.JSONDecodeError) as error:
                self.respond(400, {"error": str(error)})
                return
            if not source:
                self.respond(400, {"error": "Choose a folder to move."})
                return

            source_parts = source.split(" / ")
            parent_parts = parent.split(" / ") if parent else []
            source_key = [part.casefold() for part in source_parts]
            if len(parent_parts) >= len(source_parts) and [part.casefold() for part in parent_parts[:len(source_parts)]] == source_key:
                self.respond(400, {"error": "A folder cannot be moved into itself or one of its own subfolders."})
                return

            def is_at_or_below(path: str, prefix_parts: list[str]) -> bool:
                parts = clean_path(path).split(" / ") if clean_path(path) else []
                return len(parts) >= len(prefix_parts) and [part.casefold() for part in parts[:len(prefix_parts)]] == [part.casefold() for part in prefix_parts]

            with STATE_LOCK:
                data = load_data()
                if parent:
                    canonical_parent = next((clean_path(str(group)) for group in data["groups"] if clean_path(str(group)).casefold() == parent.casefold()), None)
                    if canonical_parent is None:
                        self.respond(400, {"error": f"Destination folder “{parent}” does not exist. Choose an existing folder or create it first."})
                        return
                    parent = canonical_parent
                    parent_parts = parent.split(" / ")
                new_path = clean_path(" / ".join(parent_parts + [source_parts[-1]]))
                exists = any(is_at_or_below(str(group), source_parts) for group in data["groups"])
                exists = exists or any(is_at_or_below(str(item.get("folder", "")), source_parts) for item in data["items"])
                if not exists:
                    self.respond(404, {"error": "That folder is no longer in the organizer."})
                    return
                if new_path.casefold() == source.casefold():
                    self.respond(200, {"ok": True, "folder": new_path})
                    return

                def move_path(path: str) -> str:
                    parts = clean_path(path).split(" / ") if clean_path(path) else []
                    suffix = parts[len(source_parts):]
                    return clean_path(" / ".join(parent_parts + [source_parts[-1]] + suffix))

                moved_groups = []
                seen_groups = set()
                for group in data["groups"]:
                    old_group = clean_path(str(group))
                    updated = move_path(old_group) if is_at_or_below(old_group, source_parts) else old_group
                    key = updated.casefold()
                    if key not in seen_groups:
                        moved_groups.append(updated)
                        seen_groups.add(key)
                data["groups"] = moved_groups
                for item in data["items"]:
                    old_folder = clean_path(str(item.get("folder", "")))
                    if old_folder and is_at_or_below(old_folder, source_parts):
                        item["folder"] = move_path(old_folder)
                ensure_groups(data, new_path)
                try:
                    save_data(data)
                except OSError:
                    self.respond(500, {"error": "Could not save the moved folder."})
                    return
            self.respond(200, {"ok": True, "folder": new_path})
            return

        if parsed.path == "/api/rename-group":
            try:
                payload = self.read_json()
                source = clean_path(str(payload.get("path", "")))
                new_name = str(payload.get("name", "")).strip()
            except RequestTooLarge as error:
                self.respond(413, {"error": str(error)})
                return
            except (ValueError, json.JSONDecodeError) as error:
                self.respond(400, {"error": str(error)})
                return
            if not source:
                self.respond(400, {"error": "Choose a folder to rename."})
                return
            if not new_name or new_name in {".", ".."} or any(char in new_name for char in "/\\") or any(ord(char) < 32 for char in new_name):
                self.respond(400, {"error": "Enter a folder name without slashes or control characters."})
                return

            source_parts = source.split(" / ")
            target_parts = source_parts[:-1] + [new_name]
            new_path = clean_path(" / ".join(target_parts))

            def is_at_or_below(path: str, prefix_parts: list[str]) -> bool:
                parts = clean_path(path).split(" / ") if clean_path(path) else []
                return len(parts) >= len(prefix_parts) and [part.casefold() for part in parts[:len(prefix_parts)]] == [part.casefold() for part in prefix_parts]

            with STATE_LOCK:
                data = load_data()
                exists = any(is_at_or_below(str(group), source_parts) for group in data["groups"])
                exists = exists or any(is_at_or_below(str(item.get("folder", "")), source_parts) for item in data["items"])
                if not exists:
                    self.respond(404, {"error": "That folder is no longer in the organizer."})
                    return
                if new_path.casefold() != source.casefold():
                    conflict = any(is_at_or_below(str(group), target_parts) and not is_at_or_below(str(group), source_parts) for group in data["groups"])
                    conflict = conflict or any(is_at_or_below(str(item.get("folder", "")), target_parts) and not is_at_or_below(str(item.get("folder", "")), source_parts) for item in data["items"])
                    if conflict:
                        self.respond(409, {"error": "A folder with that name already exists here."})
                        return

                def rename_path(path: str) -> str:
                    parts = clean_path(path).split(" / ") if clean_path(path) else []
                    return clean_path(" / ".join(target_parts + parts[len(source_parts):]))

                renamed_groups = []
                seen_groups = set()
                for group in data["groups"]:
                    old_group = clean_path(str(group))
                    updated = rename_path(old_group) if is_at_or_below(old_group, source_parts) else old_group
                    key = updated.casefold()
                    if key not in seen_groups:
                        renamed_groups.append(updated)
                        seen_groups.add(key)
                data["groups"] = renamed_groups
                for item in data["items"]:
                    old_folder = clean_path(str(item.get("folder", "")))
                    if old_folder and is_at_or_below(old_folder, source_parts):
                        item["folder"] = rename_path(old_folder)
                ensure_groups(data, new_path)
                try:
                    save_data(data)
                except OSError:
                    self.respond(500, {"error": "Could not save the renamed folder."})
                    return
            self.respond(200, {"ok": True, "folder": new_path})
            return

        self.respond(404, {"error": "Unknown organizer action."})

    def do_DELETE(self):
        if not self.check_request(mutation=True):
            return
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/api/archive-page":
            archive_id = query.get("id", [""])[0]
            page_key = query.get("page", [""])[0]
            try:
                result = delete_archive_page(archive_id, page_key)
            except FileNotFoundError as error:
                self.respond(404, {"error": str(error)})
            except ValueError as error:
                self.respond(409, {"error": str(error)})
            except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError, RuntimeError) as error:
                self.respond(500, {"error": f"Could not update this WACZ: {error}"})
            else:
                self.respond(200, result)
            return
        if parsed.path == "/api/group":
            group = clean_path(query.get("path", [""])[0])
            if not group:
                self.respond(400, {"error": "Choose a folder to delete."})
                return
            with STATE_LOCK:
                data = load_data()
                prefix = group + " / "
                parent = group.rsplit(" / ", 1)[0] if " / " in group else ""
                new_groups = []
                for old in data["groups"]:
                    if old == group:
                        continue
                    if old.startswith(prefix):
                        suffix = old[len(prefix):]
                        new_groups.append(clean_path((parent + " / " if parent else "") + suffix))
                    else:
                        new_groups.append(old)
                data["groups"] = list(dict.fromkeys(new_groups))
                for item in data["items"]:
                    old = clean_path(item.get("folder", ""))
                    if old == group or old.startswith(prefix):
                        suffix = old[len(group):].lstrip(" / ")
                        item["folder"] = clean_path((parent + " / " if parent else "") + suffix)
                try:
                    save_data(data)
                except OSError:
                    self.respond(500, {"error": "Could not delete that folder."})
                    return
            self.respond(200, {"ok": True})
            return

        if parsed.path == "/api/archive":
            archive_id = query.get("id", [""])[0]
            if not ARCHIVE_ID.fullmatch(archive_id):
                self.respond(400, {"error": "That archive identifier is invalid."})
                return
            with STATE_LOCK:
                data = load_data()
                item = next((entry for entry in data["items"] if entry.get("id") == archive_id), None)
                if item is None:
                    self.respond(404, {"error": "That archive is no longer in the organizer."})
                    return
                data["items"] = [entry for entry in data["items"] if entry.get("id") != archive_id]
                folder = (LIBRARY / archive_id).resolve()
                if folder.is_relative_to(LIBRARY):
                    shutil.rmtree(folder, ignore_errors=True)
                try:
                    save_data(data)
                except OSError:
                    self.respond(500, {"error": "The archive copy was removed, but its organizer list could not be saved."})
                    return
            self.respond(200, {"ok": True})
            return

        self.respond(404, {"error": "Unknown organizer action."})

    def do_OPTIONS(self):
        kind = self.host_kind()
        if kind != "app" or not self.valid_origin(kind):
            self.send_error(403, "The request origin is not allowed.")
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.allow_extension_origin()
        # Chromium may preflight extension-to-loopback uploads as private
        # network requests. Only grant this after the extension origin check
        # above has passed.
        if self.headers.get("Access-Control-Request-Private-Network", "").lower() == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def read_json(self) -> dict:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("The request size was invalid.") from error
        if size < 0:
            raise ValueError("The request size cannot be negative.")
        if size > MAX_JSON_BYTES:
            raise RequestTooLarge("The request was too large.")
        if size == 0:
            raise ValueError("The request body was empty.")
        payload = json.loads(self.rfile.read(size).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("The request body must be a JSON object.")
        return payload

    def copy_chunked_body(self, output, limit: int) -> int:
        total = 0
        while True:
            line = self.rfile.readline(8192)
            if not line:
                raise ValueError("The archive upload did not finish.")
            try:
                chunk_size = int(line.split(b";", 1)[0].strip(), 16)
            except ValueError as error:
                raise ValueError("The archive upload had an invalid data chunk.") from error
            if chunk_size < 0:
                raise ValueError("The archive upload had an invalid data chunk.")
            if total + chunk_size > limit:
                raise RequestTooLarge(f"The archive is larger than the {limit // (1024 * 1024)} MB upload limit.")
            if chunk_size == 0:
                while True:
                    trailer = self.rfile.readline(8192)
                    if trailer in (b"\r\n", b"\n", b""):
                        return total
            remaining = chunk_size
            while remaining:
                block = self.rfile.read(min(1024 * 1024, remaining))
                if not block:
                    raise ValueError("The archive upload did not finish.")
                output.write(block)
                total += len(block)
                remaining -= len(block)
            if self.rfile.read(2) != b"\r\n":
                raise ValueError("The archive upload had an invalid data chunk.")


if __name__ == "__main__":
    LIBRARY.mkdir(parents=True, exist_ok=True)
    server = None
    app_url = None
    for port in range(START_PORT, START_PORT + 30):
        # Check for an existing Shelf before binding. Windows can permit two
        # SO_REUSEADDR listeners on the same port, which would split browser
        # requests between server instances.
        try:
            with urlopen(f"http://127.0.0.1:{port}/api/state", timeout=0.5) as response:
                state = json.loads(response.read().decode("utf-8"))
            if state.get("application") == "archive-shelf" and isinstance(state.get("groups"), list) and isinstance(state.get("items"), list):
                app_url = f"http://localhost:{port}/"
                print(f"Archive Shelf is already running at {app_url}", flush=True)
                threading.Timer(0.5, open_app, args=(app_url,)).start()
                raise SystemExit(0)
        except SystemExit:
            raise
        except Exception:
            pass

        try:
            server = ArchiveShelfHTTPServer(("127.0.0.1", port), Handler)
            app_url = f"http://localhost:{port}/"
            break
        except OSError:
            continue
    if server is None:
        raise SystemExit(f"Could not start Archive Shelf. Ports {START_PORT}–{START_PORT + 29} are in use.")

    print(f"Archive Shelf is running at {app_url}", flush=True)
    print("Keep this window open while you use the organizer. Press Ctrl+C to stop.", flush=True)
    threading.Timer(0.5, open_app, args=(app_url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArchive Shelf stopped.")
    finally:
        server.server_close()
