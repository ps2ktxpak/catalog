"""Turn a downloaded pack into the archive apps install: ASTC 6x6 KTX textures in a tar.zst.

The steps and their parameters are the ones the 517 inherited packs went through (kram,
astc6x6 quality 98, up to 7 mip levels, `tar --format=gnu | zstd -19 --long=27`), so a pack
converted here installs exactly like those. The archive holds one `replacements/` tree, as
PCSX2 lays a pack out under its game's serial folder."""
from __future__ import annotations

import concurrent.futures
import hashlib
import os
import re
import shutil
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import tarcheck

KRAM = os.environ.get("KRAM", "kram")
VALIDATE_KTX = os.environ.get("VALIDATE_KTX", "validate_ktx")
SEVEN_ZIP = os.environ.get("SEVEN_ZIP", "7zz")

TEXTURE_EXTS = (".dds", ".png")
ARCHIVE_RE = re.compile(r"\.(zip|7z|rar|tar|tgz|tar\.gz|tar\.zst)$", re.I)
# Only the first volume of a split archive is opened; 7-Zip reads the rest itself.
LATER_VOLUME_RE = re.compile(r"\.(part0*[2-9]\d*\.rar|part0*1\d+\.rar|r\d\d|z\d\d|7z\.0*[2-9]\d*|zip\.0*[2-9]\d*|0*[2-9]\d*)$", re.I)
FIRST_VOLUME_RE = re.compile(r"\.(7z|zip)\.0*1$", re.I)
SERIAL_RE = re.compile(r"^(S[CL][A-Z]{2}|PBP[XS]|PAPX|SCAJ|SCKA|TCES|TCPS|TLES)[-_]?\d{3}\.?\d{2}$", re.I)
MIP_RE = re.compile(r"-mip(\d+)$", re.I)
# The names the emulator loads (GSTextureReplacements::ParseReplacementName): TEX0 hash, optional CLUT hash,
# optional region (`r<w>x<h>`, or the old `r<hex>`), then the format bits. Anything else in a pack (a creator's
# working art, "… - Copy" duplicates, previews) is never loaded, so it is left out.
_HEX = r"[0-9a-f]{1,16}"
TEXTURE_NAME_RE = re.compile(rf"^{_HEX}(-{_HEX})?(-r\d+x\d+|-r{_HEX})?-[0-9a-f]{{1,8}}$", re.I)

MAX_TEXTURE_SIZE = 16384
MAX_MIP_LEVELS = 7
MAX_UNREADABLE = 3  # or 1%, whichever is more
ZSTD_LEVEL = 19
ZSTD_LONG = 27
PARAMS = ("astc6x6 quality 98, up to 7 mip levels; tar --format=gnu | zstd -19 --long=27; "
          "only files named as the emulator loads them")


class NeedsChoice(Exception):
    """The download holds more than one pack (sizes, variants); a person picks which we serve."""


class Empty(Exception):
    """No textures we can convert."""


class NoRoom(Exception):
    """Extracted, the download does not fit on the disk."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while data := f.read(1 << 20):
            h.update(data)
    return h.hexdigest()


# ---- extracting ---------------------------------------------------------------------------------

def is_archive(p: Path) -> bool:
    return bool(ARCHIVE_RE.search(p.name) or FIRST_VOLUME_RE.search(p.name)) and not LATER_VOLUME_RE.search(p.name)


def extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    p = subprocess.run([SEVEN_ZIP, "x", "-y", "-bd", "-bso0", "-bsp0", f"-o{dest}", str(archive)],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if p.returncode not in (0, 1):  # 1 is a warning (for example a file it skipped)
        if "errno=28" in p.stderr:
            raise NoRoom(f"{archive.name} does not fit on the disk extracted")
        raise RuntimeError(f"7-Zip could not extract {archive.name}: {p.stderr.strip()[-300:]}")


def unpack(files: list[Path], dest: Path) -> None:
    """Extract every archive among `files` into `dest`, and archives found inside them, two levels
    deep. Loose files (a folder download) are moved in as they are."""
    for i, f in enumerate(files):
        if is_archive(f):
            extract(f, dest / f"{i}-{f.name.split('.')[0]}")
        elif not LATER_VOLUME_RE.search(f.name):
            target = dest / f.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), target)
    for _ in range(2):
        inner = [p for p in dest.rglob("*") if p.is_file() and is_archive(p)]
        if not inner or _textures(dest):
            break
        for p in inner:
            extract(p, p.parent / (p.name.split(".")[0] + ".x"))
            p.unlink()


def _textures(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in TEXTURE_EXTS]


# ---- what to convert ----------------------------------------------------------------------------

@dataclass
class Layout:
    roots: list[Path]
    serials: list[str] = field(default_factory=list)


def find_layout(tree: Path) -> Layout:
    """The `replacements` folder(s) to convert. Several are merged only when each sits in its own
    serial folder (one pack, several regions); anything else is a choice for a person."""
    reps = sorted(p for p in tree.rglob("*") if p.is_dir() and p.name.lower() == "replacements" and _textures(p))
    if not reps:
        if not _textures(tree):
            raise Empty("no .dds or .png textures in the download")
        # No replacements folder: the textures are the pack, wherever they sit.
        return Layout([tree], _serials_above(tree, _textures(tree)))
    if len(reps) == 1:
        return Layout(reps, [s for s in [_serial_of(reps[0].parent)] if s])
    serials = [_serial_of(r.parent) for r in reps]
    if all(serials) and len(set(serials)) == len(serials):
        return Layout(reps, serials)
    listing = ", ".join(f"{r.relative_to(tree)} ({len(_textures(r))} textures)" for r in reps)
    raise NeedsChoice(f"the download holds {len(reps)} replacements folders: {listing}")


def _serial_of(d: Path) -> str | None:
    m = SERIAL_RE.match(d.name.strip())
    if not m:
        return None
    digits = re.sub(r"\D", "", d.name[4:])
    return f"{d.name[:4].upper()}-{digits}"


def _serials_above(tree: Path, files: list[Path]) -> list[str]:
    found = set()
    for f in files:
        for parent in f.relative_to(tree).parents:
            if s := _serial_of(tree / parent):
                found.add(s)
    return sorted(found)


# ---- converting ---------------------------------------------------------------------------------

def loadable(p: Path) -> bool:
    return bool(TEXTURE_NAME_RE.match(MIP_RE.sub("", p.stem)))


def unloadable(layout: Layout) -> list[str]:
    """The textures in the layout the emulator would never load, which `convert` leaves out."""
    return sorted(str(p.relative_to(root)) for root in layout.roots for p in _textures(root) if not loadable(p))


def prune(out: Path) -> list[str]:
    """Delete the KTX files under `out` the emulator would never load: what `convert` now leaves out,
    applied to a pack converted before it did. Returns them."""
    dropped = sorted(p for p in out.rglob("*.ktx") if not loadable(p))
    for p in dropped:
        p.unlink()
    for d in sorted((d for d in out.rglob("*") if d.is_dir()), key=lambda d: len(d.parts), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()
    return [str(p.relative_to(out)) for p in dropped]


def unpack_archive(archive: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with open(archive, "rb") as f:
        zstd = subprocess.Popen(["zstd", "-q", "-d", f"--long={ZSTD_LONG}", "-c"], stdin=f, stdout=subprocess.PIPE)
        tar = subprocess.run(["tar", "-x", "-C", str(out)], stdin=zstd.stdout, capture_output=True)
        zstd.stdout.close()
        if zstd.wait() or tar.returncode:
            raise RuntimeError(f"could not unpack {archive.name}: {tar.stderr.decode()[-200:]}")


def _families(root: Path) -> list[tuple[Path, dict]]:
    by_stem: dict = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in TEXTURE_EXTS and loadable(p):
            by_stem.setdefault((p.parent, MIP_RE.sub("", p.stem).lower()), []).append(p)
    families = []
    for files in by_stem.values():
        base = next((f for f in files if not MIP_RE.search(f.stem)), None)
        if base is None:
            continue
        sidecars = {int(m.group(1)): f for f in files if (m := MIP_RE.search(f.stem))}
        families.append((base, sidecars))
    return families


def _dims(p: Path) -> tuple[int, int] | None:
    """A PNG's or DDS's width and height, from its header."""
    with open(p, "rb") as f:
        head = f.read(24)
    if head[:8] == b"\x89PNG\r\n\x1a\n" and len(head) == 24:
        return struct.unpack(">II", head[16:24])
    if head[:4] == b"DDS " and len(head) >= 20:
        h, w = struct.unpack("<II", head[12:20])
        return w, h
    return None


def _encode_argv(base: Path, sidecars: dict, out: Path) -> list[str]:
    generated = [KRAM, "encode", "-i", str(base), "-f", "astc6x6", "-quality", "98",
                 "-mipcount", str(MAX_MIP_LEVELS), "-o", str(out)]
    if not sidecars:
        return generated
    count = max(sidecars) + 1
    if count > MAX_MIP_LEVELS or any(level not in sidecars for level in range(1, count)):
        return generated  # an unusable chain of mip files: make the mips from the base instead
    # Some packs ship full-size copies as their mip files, which kram refuses.
    size = _dims(base)
    if size is None or any(_dims(sidecars[level]) != (max(1, size[0] >> level), max(1, size[1] >> level))
                           for level in range(1, count)):
        return generated
    argv = [KRAM, "encode", "-i", str(base)]
    for level in range(1, count):
        argv += ["-mip", str(level), str(sidecars[level])]
    return argv + ["-f", "astc6x6", "-quality", "98", "-o", str(out)]


def convert(layout: Layout, out: Path, jobs: int | None = None) -> tuple[int, list[str]]:
    """Encode every texture family under the layout's roots into `out/replacements/`. Returns the count
    encoded and the textures kram could not read (a truncated PNG, say), which are left out as the
    emulator would skip them; more than a few of those means something else is wrong, and fails."""
    argvs, seen = [], set()
    for root in layout.roots:
        for base, sidecars in _families(root):
            rel = base.relative_to(root).with_suffix(".ktx")
            key = str(rel).lower()
            if key in seen:  # the same texture in two regions' folders: keep the first
                continue
            seen.add(key)
            dest = out / "replacements" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            argvs.append(_encode_argv(base, sidecars, dest))
    if not argvs:
        raise Empty("no texture is named the way the emulator loads them")

    def one(argv):
        p = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if p.returncode != 0:
            Path(argv[-1]).unlink(missing_ok=True)
            said = (p.stdout + p.stderr).strip()  # kram prints its errors to stdout
            return f"{Path(argv[argv.index('-i') + 1]).name} (exit {p.returncode}): {said[-300:]}"
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs or os.cpu_count()) as pool:
        failed = sorted(f for f in pool.map(one, argvs) if f)
    if len(failed) > max(MAX_UNREADABLE, len(argvs) // 100):
        raise RuntimeError(f"kram failed on {len(failed)} of {len(argvs)} textures, first {failed[0]}")
    return len(argvs) - len(failed), failed


def validate(out: Path, count: int) -> None:
    files = sorted(out.rglob("*.ktx"))
    if len(files) != count:
        raise RuntimeError(f"expected {count} KTX files, found {len(files)}")
    for i in range(0, len(files), 400):
        p = subprocess.run([VALIDATE_KTX, str(MAX_TEXTURE_SIZE), *map(str, files[i:i + 400])],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if p.returncode != 0:
            raise RuntimeError(f"the app's KTX parser rejects a file: {p.stderr.strip()[-300:]}")


def pack(out: Path, archive: Path, count: int) -> dict:
    """tar | zstd the converted tree, then check it the way the app will. Returns the archive facts."""
    archive.unlink(missing_ok=True)
    with open(archive, "wb") as f:
        tar = subprocess.Popen(["tar", "--format=gnu", "-C", str(out), "-cf", "-", "."], stdout=subprocess.PIPE)
        zstd = subprocess.Popen(["zstd", "-q", f"-{ZSTD_LEVEL}", f"--long={ZSTD_LONG}", "-T0", "-c", "-f"],
                                stdin=tar.stdout, stdout=f)
        tar.stdout.close()
        rc, rc2 = tar.wait(), zstd.wait()
    if rc or rc2:
        raise RuntimeError(f"tar | zstd failed ({rc}, {rc2})")
    summary = tarcheck.validate_tar_zst(archive, expect_ktx=count)
    return {"sha256": sha256_file(archive), "size_bytes": archive.stat().st_size,
            "decompressed_size_bytes": summary["decompressed_size"], "file_count": summary["ktx_files"]}
