#!/usr/bin/env python3
"""Packs a built mod into dist/ for a GitHub release:

    dist/<id>-v<version>-windows.zip   a mod (kind "mod"): <file>.dll, LICENSE, NOTICE (if the repo has
                                       one), <Stem>.plugin.json (if the mod has settings) and a SHA256SUMS
                                       over those. Flat, fixed dates, so the same files make the same zip.
    dist/<Stem>-<version>.zip          a content pack (kind "pack"): plugins/ and content/<content id>/
    dist/echo-mod.json                 echo-mod.json with version, prerelease, package and the source
                                       filled in; for a pack also its sha256 and size. A mod's has no
                                       sha256 or size: the release signer changes the DLL's bytes.
    dist/SHA256SUMS                    the zip (or a pack's) and echo-mod.json

    python3 tools/package.py --dll build/mingw/ExampleMod.dll

The release workflow runs this; it works the same locally. Python 3.8+, no packages.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_mod import is_prerelease  # noqa: E402


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def add(zf, path, name):
    """Adds a file with a fixed date, so the same files always make the same zip."""
    add_bytes(zf, Path(path).read_bytes(), name)


def add_bytes(zf, data, name):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    zf.writestr(info, data)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dll", required=True, help="the built DLL")
    ap.add_argument("--manifest", default="echo-mod.json")
    ap.add_argument("--out", default="dist")
    args = ap.parse_args()

    root = Path(args.manifest).resolve().parent
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    entry = dict(manifest)
    entry["prerelease"] = is_prerelease(manifest["version"])
    settings = manifest.get("settings")
    if isinstance(settings, str) and settings:
        entry["settings"] = json.loads((root / settings).read_text(encoding="utf-8"))["settings"]

    stem = manifest["file"][:-4]
    if manifest.get("kind", "mod") == "pack":
        content = manifest["pack"]["content"]
        name = f"{stem}-{manifest['version']}.zip"
        files = [(Path(args.dll), f"plugins/{manifest['file']}")]
        if isinstance(settings, str) and settings:
            files.append((root / settings, f"plugins/{stem}.plugin.json"))
        content_dir = root / "content" / content
        for path in sorted(p for p in content_dir.rglob("*") if p.is_file()):
            files.append((path, f"content/{content}/{path.relative_to(content_dir).as_posix()}"))
        with zipfile.ZipFile(out / name, "w") as zf:
            for path, arcname in files:
                add(zf, path, arcname)
        # "file" stays: the plugin in the pack, which nEVR loads.
        entry["pack"] = {
            "file": name,
            "sha256": sha256(out / name),
            "size": (out / name).stat().st_size,
            "content": content,
            "plugins": [manifest["file"]],
        }
    else:
        # The release signer signs the DLL inside this zip and rewrites the zip: the final hashes are
        # in SHA256SUMS, not in echo-mod.json. LICENSE and NOTICE travel in the zip (MIT: "in all copies").
        name = f"{manifest['id']}-v{manifest['version']}-windows.zip"
        files = [(Path(args.dll), manifest["file"])]
        for notice in ("LICENSE", "NOTICE"):
            if (root / notice).is_file():
                files.append((root / notice, notice))
            elif notice == "LICENSE":
                sys.exit(f"package.py: {root / notice} is missing: a release carries the mod's LICENSE")
        if isinstance(settings, str) and settings:
            files.append((root / settings, f"{stem}.plugin.json"))
        inner = "".join(f"{sha256(path)}  {arcname}\n" for path, arcname in files)
        with zipfile.ZipFile(out / name, "w") as zf:
            for path, arcname in files:
                add(zf, path, arcname)
            add_bytes(zf, inner.encode("utf-8"), "SHA256SUMS")
        entry["package"] = name

    if os.environ.get("GITHUB_ACTIONS") == "true":
        entry["source"] = {
            "repository": os.environ.get("GITHUB_REPOSITORY", ""),
            "repository_id": os.environ.get("GITHUB_REPOSITORY_ID", ""),
            "tag": os.environ.get("GITHUB_REF_NAME", ""),
            "commit": os.environ.get("GITHUB_SHA", ""),
            "workflow": os.environ.get("GITHUB_WORKFLOW_REF", ""),
        }

    (out / "echo-mod.json").write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sums = "".join(f"{sha256(p)}  {p.name}\n" for p in sorted(out.iterdir()) if p.name != "SHA256SUMS")
    (out / "SHA256SUMS").write_text(sums, encoding="utf-8")
    print(sums, end="")


if __name__ == "__main__":
    main()
