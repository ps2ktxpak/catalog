"""Streaming GNU-tar contract validator shared by producer and consumer checks.

Mirrors the contract of the ARMSX2 Android app's TarTextureExtractor one-for-one, so a
pack this accepts is one the app installs:

  accepts   : ustar/gnu headers, the root "./" directory, directories, regular
              files, and one bounded NUL-terminated GNU `L` long-name record
              applying to the next entry
  rejects   : links/devices/FIFOs/sparse/pax records, bad checksums, malformed
              octal, base-256 fields, absolute or escaping paths, invalid UTF-8,
              duplicates, case/normalization collisions, ancestor conflicts,
              truncation, missing end blocks, nonzero trailing padding
  limits    : records 100000, per-file payload 512 MiB, path 4096 bytes /
              32 components / 255-byte components, long-name payload 4097
              bytes including NUL

One pass over `zstd -dc <archive>` yields BOTH the consumer verdict and the
exact decompressed stream length (headers, payloads, padding, end blocks, and
trailing zeros included), which is what the catalog publishes as
decompressedSizeBytes.
"""

import subprocess
import unicodedata
from pathlib import Path

RECORD = 512
MAX_ENTRIES = 100_000
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_PATH_BYTES = 4096
MAX_COMPONENTS = 32
MAX_COMPONENT_BYTES = 255
MAX_LONGNAME_BYTES = 4097  # payload including the required NUL

SKIP_CHUNK = 1 << 20

FILE_TYPES = (0, ord("0"))       # typeflag 0 or NUL
DIR_TYPE = ord("5")
LONGNAME_TYPE = ord("L")

ZERO_RECORD = b"\0" * RECORD


class TarContractError(Exception):
    pass


def _octal(field: bytes, what: str) -> int:
    if field and field[0] & 0x80:
        raise TarContractError(f"base-256 {what} not accepted")
    text = field.split(b"\0")[0].strip(b" ")
    if not text:
        return 0
    try:
        return int(text, 8)
    except ValueError:
        raise TarContractError(f"malformed octal {what}")


def _checksum_ok(header: bytes) -> bool:
    stored = _octal(header[148:156], "checksum")
    unsigned = sum(header[:148]) + 8 * 0x20 + sum(header[156:])
    if unsigned == stored:
        return True
    signed = sum(b - 256 if b > 127 else b for b in header[:148]) \
        + 8 * 0x20 \
        + sum(b - 256 if b > 127 else b for b in header[156:])
    return signed == stored


def _split_components(path: str) -> list:
    parts = path.rstrip("/").split("/")
    if any(p == "" for p in parts):
        raise TarContractError(f"empty path component in {path!r}")
    if len(parts) > MAX_COMPONENTS:
        raise TarContractError(f"path depth exceeds {MAX_COMPONENTS}: {path!r}")
    for part in parts:
        if part == "..":
            raise TarContractError(f"parent traversal rejected: {path!r}")
        if part == ".":
            raise TarContractError(f"dot component in {path!r}")
        if len(part.encode("utf-8")) > MAX_COMPONENT_BYTES:
            raise TarContractError(
                f"component exceeds {MAX_COMPONENT_BYTES} bytes: {path!r}")
    return parts


def _collision_key(path: str) -> str:
    return unicodedata.normalize("NFC", path).lower()


def validate_tar_stream(stream, expect_ktx: int = None) -> dict:
    """Validate one raw tar byte stream. Returns a summary dict on success.

    stream: readable binary file-like object (already decompressed).
    expect_ktx: optional exact .ktx entry count to enforce.
    Raises TarContractError on any contract violation.
    """
    entries = 0
    ktx_count = 0
    total = 0
    pending_longname = None
    seen_files, seen_dirs = set(), set()

    def read_record() -> bytes:
        nonlocal total
        data = stream.read(RECORD)
        total += len(data)
        if len(data) != RECORD:
            raise TarContractError("truncated tar stream")
        return data

    def skip_payload(size: int, what: str) -> None:
        nonlocal total
        remaining = (size + RECORD - 1) // RECORD * RECORD
        while remaining > 0:
            chunk = stream.read(min(remaining, SKIP_CHUNK))
            total += len(chunk)
            if not chunk:
                raise TarContractError(f"truncated {what}")
            remaining -= len(chunk)

    while True:
        header = read_record()
        if header == ZERO_RECORD:
            break  # first of the two end blocks

        entries += 1
        if entries > MAX_ENTRIES:
            raise TarContractError(f"entry count exceeds {MAX_ENTRIES}")
        if not _checksum_ok(header):
            raise TarContractError("header checksum mismatch")
        magic = header[257:263]
        if magic not in (b"ustar ", b"ustar\0"):
            raise TarContractError(f"unknown tar magic {magic!r}")
        typeflag = header[156:157][0] if header[156:157] else 0
        size = _octal(header[124:136], "size")

        if typeflag == LONGNAME_TYPE:
            if pending_longname is not None:
                raise TarContractError("GNU L record without a following entry")
            if size == 0 or size > MAX_LONGNAME_BYTES:
                raise TarContractError(
                    f"GNU L payload must be 1..{MAX_LONGNAME_BYTES} bytes")
            payload = bytearray()
            remaining = (size + RECORD - 1) // RECORD * RECORD
            while remaining > 0:
                chunk = stream.read(min(remaining, SKIP_CHUNK))
                total += len(chunk)
                if not chunk:
                    raise TarContractError("truncated GNU L payload")
                take = chunk[:remaining]
                payload += take
                remaining -= len(take)
            if payload[size - 1] != 0:
                raise TarContractError("GNU L payload is not NUL-terminated")
            pending_longname = bytes(payload[:size - 1])
            continue

        is_dir = typeflag == DIR_TYPE
        if not is_dir and typeflag not in FILE_TYPES:
            raise TarContractError(
                f"unsupported entry type {chr(typeflag)!r} (links/devices/pax "
                "are outside the producer contract)")

        name = pending_longname if pending_longname is not None \
            else header[0:100].split(b"\0")[0]
        pending_longname = None
        if len(name) > MAX_PATH_BYTES:
            raise TarContractError(f"path exceeds {MAX_PATH_BYTES} bytes")
        try:
            path = name.decode("utf-8")
        except UnicodeDecodeError:
            raise TarContractError("entry name is not valid UTF-8")
        if path.startswith("./"):
            path = path[2:]
        if path.startswith("/") or path.startswith("../") or path == "..":
            raise TarContractError(f"absolute or escaping path rejected: {path!r}")

        if not path:
            if not is_dir or size != 0:
                raise TarContractError("empty entry name on a non-root entry")
            continue  # producer's root "./" directory

        parts = _split_components(path)
        key = _collision_key(path)
        if key in seen_files or key in seen_dirs:
            raise TarContractError(f"duplicate or colliding destination: {path!r}")
        for i in range(1, len(parts)):
            if _collision_key("/".join(parts[:i])) in seen_files:
                raise TarContractError(
                    "file/directory ancestor conflict at " + "/".join(parts[:i]))

        if is_dir:
            seen_dirs.add(key)
        else:
            seen_files.add(key)
            if size > MAX_FILE_BYTES:
                raise TarContractError(f"payload exceeds {MAX_FILE_BYTES}")
            if path.lower().endswith(".ktx"):
                ktx_count += 1

        skip_payload(size, "entry payload")

    second = stream.read(RECORD)
    total += len(second)
    if len(second) != RECORD or second != ZERO_RECORD:
        raise TarContractError("missing second end block")
    while True:
        chunk = stream.read(SKIP_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if chunk.strip(b"\0"):
            raise TarContractError("nonzero trailing tar padding")

    if expect_ktx is not None and ktx_count != expect_ktx:
        raise TarContractError(
            f"ktx count mismatch: stream has {ktx_count}, expected {expect_ktx}")
    return {"entries": entries, "ktx_files": ktx_count,
            "decompressed_size": total}


def validate_tar_zst(archive: Path, expect_ktx: int = None) -> dict:
    """Validate a .tar.zst archive, returning the summary above."""
    proc = subprocess.Popen(
        ["zstd", "-d", "-c", "--long=27", str(archive)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        result = validate_tar_stream(proc.stdout, expect_ktx=expect_ktx)
    except TarContractError:
        proc.kill()
        proc.wait()
        proc.stdout.close()
        proc.stderr.close()
        raise
    proc.stdout.close()
    err = proc.stderr.read().decode(errors="replace")
    proc.stderr.close()
    if proc.wait() != 0:
        raise TarContractError(f"zstd decode failed: {err.strip()[-200:]}")
    return result
