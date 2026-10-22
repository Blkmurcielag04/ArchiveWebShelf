"""Check for and optionally install a verified ReplayWeb.page viewer release."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import re
import shutil
import tarfile
import uuid
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


APP_DIR = Path(__file__).resolve().parent
REPLAY_DIR = APP_DIR / "replay"
VERSION_FILE = REPLAY_DIR / "version.txt"
REGISTRY_URL = "https://registry.npmjs.org/replaywebpage/latest"
UPDATE_FILES = {
    "ui.js": REPLAY_DIR / "ui.js",
    "sw.js": REPLAY_DIR / "sw.js",
    "LICENSE": REPLAY_DIR / "LICENSE.txt",
    "version.txt": VERSION_FILE,
}
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
MAX_PACKAGE_BYTES = 100 * 1024 * 1024
MAX_ASSET_BYTES = 30 * 1024 * 1024


def version_key(version: str) -> tuple[int, int, int, int]:
    numbers = version.split("-", 1)[0].split(".")
    stable = 0 if "-" in version else 1
    return int(numbers[0]), int(numbers[1]), int(numbers[2]), stable


def get_installed_version() -> str | None:
    try:
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return version if VERSION_RE.fullmatch(version) else None


def get_latest_package() -> dict:
    request = Request(
        REGISTRY_URL,
        headers={"User-Agent": "Archive-Shelf-ReplayWebpage-Update-Checker/2.0"},
    )
    with urlopen(request, timeout=20) as response:
        metadata = json.loads(response.read(2 * 1024 * 1024 + 1).decode("utf-8"))
    version = metadata.get("version")
    dist = metadata.get("dist") or {}
    tarball = dist.get("tarball")
    integrity = dist.get("integrity")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise ValueError("The package registry returned an unexpected version number.")
    if not isinstance(tarball, str) or not tarball.startswith("https://registry.npmjs.org/"):
        raise ValueError("The package registry returned an unexpected download address.")
    if not isinstance(integrity, str) or not integrity.startswith("sha512-"):
        raise ValueError("The package registry did not provide a SHA-512 package signature.")
    return {"version": version, "tarball": tarball, "integrity": integrity}


def download_package(package: dict) -> dict[str, bytes]:
    request = Request(
        package["tarball"],
        headers={"User-Agent": "Archive-Shelf-ReplayWebpage-Update-Checker/2.0"},
    )
    with urlopen(request, timeout=45) as response:
        archive_bytes = response.read(MAX_PACKAGE_BYTES + 1)
    if len(archive_bytes) > MAX_PACKAGE_BYTES:
        raise ValueError("The ReplayWeb.page package download is larger than expected.")

    expected = package["integrity"].removeprefix("sha512-")
    actual = base64.b64encode(hashlib.sha512(archive_bytes).digest()).decode("ascii")
    if not hmac.compare_digest(expected, actual):
        raise ValueError("The downloaded package did not match the registry's SHA-512 signature.")

    wanted = {"package/package.json", "package/ui.js", "package/sw.js", "package/LICENSE"}
    extracted: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
            for member in archive.getmembers():
                if member.name not in wanted:
                    continue
                if not member.isfile() or member.size < 0 or member.size > MAX_ASSET_BYTES:
                    raise ValueError(f"The package contains an invalid {member.name} file.")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"The package is missing {member.name}.")
                extracted[member.name] = stream.read(MAX_ASSET_BYTES + 1)
    except (tarfile.TarError, OSError) as error:
        raise ValueError("The downloaded ReplayWeb.page package could not be opened.") from error

    if set(extracted) != wanted:
        missing = ", ".join(sorted(wanted - set(extracted)))
        raise ValueError(f"The package is missing required viewer files: {missing}.")
    package_info = json.loads(extracted["package/package.json"].decode("utf-8"))
    if package_info.get("name") != "replaywebpage" or package_info.get("version") != package["version"]:
        raise ValueError("The downloaded viewer version did not match the registry information.")

    return {
        "ui.js": extracted["package/ui.js"],
        "sw.js": extracted["package/sw.js"],
        "LICENSE.txt": extracted["package/LICENSE"],
        "version.txt": (package["version"] + "\n").encode("utf-8"),
    }


def ask_to_update(version: str) -> bool:
    try:
        answer = input(f"Download and install ReplayWeb.page {version}? [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def install_package(version: str, updated: dict[str, bytes]) -> Path:
    originals = {name: path.read_bytes() for name, path in UPDATE_FILES.items() if path.exists()}
    missing = set(UPDATE_FILES) - set(originals)
    if missing:
        raise ValueError("The local viewer files are incomplete: " + ", ".join(sorted(missing)))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = APP_DIR / "backups" / f"replaywebpage-{version}-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    for name, path in UPDATE_FILES.items():
        shutil.copy2(path, backup_dir / name)

    temp_paths: dict[str, Path] = {}
    replaced: list[str] = []
    try:
        for name, path in UPDATE_FILES.items():
            temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.update-tmp")
            temporary.write_bytes(updated[name])
            temp_paths[name] = temporary
        for name, path in UPDATE_FILES.items():
            temp_paths[name].replace(path)
            replaced.append(name)
    except OSError:
        for name in replaced:
            UPDATE_FILES[name].write_bytes(originals[name])
        raise
    finally:
        for temporary in temp_paths.values():
            temporary.unlink(missing_ok=True)

    return backup_dir


def main() -> None:
    print("Archive Shelf — ReplayWeb.page update check")
    print("This checks the viewer package and asks before replacing its local files.\n")

    current = get_installed_version()
    if not current:
        print("I couldn't read replay/version.txt. The local viewer may be incomplete.")
        return

    print(f"Archive Shelf viewer: {current}")
    print(f"Archive Shelf replay worker: {current}")

    try:
        latest_package = get_latest_package()
        latest = latest_package["version"]
    except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
        print("I couldn't check the latest version online.")
        print(f"Details: {error}")
        print("Try again when the computer has an internet connection.")
        return

    print(f"Latest stable ReplayWeb.page package: {latest}")
    if version_key(latest) == version_key(current):
        print("You're up to date.")
        return
    if version_key(latest) < version_key(current):
        print("The installed viewer is newer than the registry's latest stable version. No downgrade was made.")
        return
    if not ask_to_update(latest):
        print("No files were changed.")
        return

    try:
        updated = download_package(latest_package)
        backup_dir = install_package(latest, updated)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print("The update could not be completed. Your archives were not changed.")
        print(f"Details: {error}")
        return

    print(f"Installed ReplayWeb.page {latest} locally.")
    print(f"Backup copies are in: {backup_dir}")
    print("Close and reopen Archive Shelf to load the updated viewer.")


if __name__ == "__main__":
    main()
