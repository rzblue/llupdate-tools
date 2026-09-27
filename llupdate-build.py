#!/usr/bin/env python3
"""Create a llupdate package."""

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


class Args(argparse.Namespace):
    input_dir: Path
    rootfs: Path
    bootfs: Path
    hwtype: str
    pretty_hwtype: str
    cmdline_a_file: Path
    cmdline_b_file: Path
    pkg_version: str
    compression_level: int
    output: Path


def parse_args() -> Args:
    parser = argparse.ArgumentParser(description="Create a llupdate package.")

    parser.add_argument(
        "-i",
        "--input-dir",
        type=Path,
        help="Path to the input directory.",
        default=Path.cwd(),
        required=False,
    )

    parser.add_argument(
        "-r",
        "--rootfs",
        type=Path,
        help="Path to the rootfs image.",
        required=True,
        metavar="IMG",
    )

    parser.add_argument(
        "-b",
        "--bootfs",
        type=Path,
        help="Path to the bootfs image.",
        required=True,
        metavar="IMG",
    )

    parser.add_argument("--hwtype", type=str, help="hwtype string", required=True)

    parser.add_argument(
        "--pretty-hwtype", type=str, help="Pretty hwtype string", default=None
    )

    parser.add_argument(
        "--cmdline-a-file",
        type=Path,
        required=True,
        metavar="FILE",
        help="Path to a file containing the cmdline for boot slot A",
    )

    parser.add_argument(
        "--cmdline-b-file",
        type=Path,
        required=True,
        metavar="FILE",
        help="Path to a file containing the cmdline for boot slot B",
    )

    parser.add_argument(
        "--pkg-version",
        type=str,
        required=True,
        metavar="VERSION",
        help="Version string",
    )

    parser.add_argument(
        "-z",
        "--compression-level",
        type=int,
        default=3,
        choices=range(1, 20),
        metavar="LEVEL",
        help="zstd compression level (1-19, default: 3)",
    )

    parser.add_argument(
        "output",
        type=Path,
        default=None,
        nargs=argparse.OPTIONAL,
        help="Path to the output file or directory.",
    )

    args = parser.parse_args(namespace=Args())

    if not args.input_dir.exists():
        parser.error(f"Input directory {args.input_dir} does not exist.")
    if not args.input_dir.is_dir():
        parser.error(f"Input directory {args.input_dir} is not a directory.")

    # Resolve relative paths to input_dir
    if not args.rootfs.is_absolute():
        args.rootfs = args.input_dir / args.rootfs
    if not args.bootfs.is_absolute():
        args.bootfs = args.input_dir / args.bootfs
    if not args.cmdline_a_file.is_absolute():
        args.cmdline_a_file = args.input_dir / args.cmdline_a_file
    if not args.cmdline_b_file.is_absolute():
        args.cmdline_b_file = args.input_dir / args.cmdline_b_file

    if args.output is None or args.output.is_dir():
        if args.output is None:
            # If output is not specified, default to current working directory
            args.output = Path.cwd()
        args.output = args.output / f"{args.hwtype}.llupdate"

    return args


@dataclass
class LLUpdateImageMetadata:
    compressed_size: int
    uncompressed_size: int
    sha256: str
    file: str


@dataclass
class LLUpdateManifest:
    version: str
    format: int
    hwtype: str
    prettyhwtype: str
    retain_skip: list[str]
    retain_exclude: list[str]
    boot: LLUpdateImageMetadata
    rootfs: LLUpdateImageMetadata
    cmdline_a: str
    cmdline_b: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def gen_sha256(path: Path) -> str:
    """Generate SHA-256 of a file"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        chunk_size = 16 * 1024 * h.block_size
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def zstd_compress(src: Path, dst: Path, level: int = 3) -> None:
    """Compress src to dst with zstd"""
    subprocess.run(
        ["zstd", f"-{level}", "-f", "-T0", str(src), "-o", str(dst)],
        check=True,
    )


def read_cmdline(path: Path) -> str:
    """Read cmdline from file and strip whitespace."""
    return path.read_text().strip()


def main():
    args = parse_args()

    for p in (args.rootfs, args.bootfs, args.cmdline_a_file, args.cmdline_b_file):
        if not p.is_file():
            print(f"Error: {p} does not exist or is not a file.")
            raise SystemExit(1)

    # Set pretty hwtype to hwtype if not provided
    pretty_hwtype = args.pretty_hwtype if args.pretty_hwtype else args.hwtype

    print("Hashing boot image...")
    boot_uncompressed_size = args.bootfs.stat().st_size
    boot_sha256 = gen_sha256(args.bootfs)

    print("Hashing rootfs image...")
    rootfs_uncompressed_size = args.rootfs.stat().st_size
    rootfs_sha256 = gen_sha256(args.rootfs)

    # Read cmdlines
    try:
        cmdline_a = read_cmdline(args.cmdline_a_file)
    except (OSError, UnicodeDecodeError) as e:
        print(f"Error reading {args.cmdline_a_file}: {e}")
        raise SystemExit(1)
    try:
        cmdline_b = read_cmdline(args.cmdline_b_file)
    except (OSError, UnicodeDecodeError) as e:
        print(f"Error reading {args.cmdline_b_file}: {e}")
        raise SystemExit(1)

    print("Generating manifest...")
    with tempfile.TemporaryDirectory(prefix="llupdate-") as tmp:
        tmpdir = Path(tmp)
        boot_zst = tmpdir / "boot.img.zst"
        rootfs_zst = tmpdir / "rootfs.img.zst"
        print("Compressing boot image...")
        zstd_compress(
            args.bootfs.resolve(), boot_zst.resolve(), level=args.compression_level
        )
        print("Compressing rootfs image...")
        zstd_compress(
            args.rootfs.resolve(), rootfs_zst.resolve(), level=args.compression_level
        )

        # Create manifest
        manifest = LLUpdateManifest(
            version=args.pkg_version,
            format=1,
            hwtype=args.hwtype,
            prettyhwtype=pretty_hwtype,
            retain_skip=[],
            retain_exclude=[],
            boot=LLUpdateImageMetadata(
                compressed_size=boot_zst.stat().st_size,
                uncompressed_size=boot_uncompressed_size,
                sha256=boot_sha256,
                file="boot.img.zst",
            ),
            rootfs=LLUpdateImageMetadata(
                compressed_size=rootfs_zst.stat().st_size,
                uncompressed_size=rootfs_uncompressed_size,
                sha256=rootfs_sha256,
                file="rootfs.img.zst",
            ),
            cmdline_a=cmdline_a,
            cmdline_b=cmdline_b,
        )

        manifest_json = manifest.to_json().encode("utf-8")
        manifest_path = tmpdir / "manifest.json"
        manifest_path.write_bytes(manifest_json)

        # Reproducible mtime when the build sets SOURCE_DATE_EPOCH.
        mtime = int(os.environ.get("SOURCE_DATE_EPOCH", "0") or "0") or None

        # Create tar archive
        print(f"Creating llupdate package at {args.output}...")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(args.output, "w", format=tarfile.PAX_FORMAT) as tar:
            for arcname, src in (
                ("manifest.json", manifest_path),
                ("boot.img.zst", boot_zst),
                ("rootfs.img.zst", rootfs_zst),
            ):
                info = tar.gettarinfo(str(src), arcname=arcname)
                info.mtime = mtime if mtime is not None else info.mtime
                info.uid = 0
                info.gid = 0
                info.uname = "root"
                info.gname = "root"

                with src.open("rb") as f:
                    tar.addfile(info, f)

        if mtime is not None:
            try:
                os.utime(args.output, (mtime, mtime))
            except OSError as e:
                print(f"Failed to set mtime for {args.output}: {e}")


if __name__ == "__main__":
    main()
