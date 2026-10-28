#!/usr/bin/env python3
"""Checks a mod the way the echo-mods review does: echo-mod.json, the DLL, and (optionally) what
the smoke host found when it loaded the DLL.

    python3 tools/check_mod.py                         # echo-mod.json only
    python3 tools/check_mod.py --dll build/mingw/ExampleMod.dll
    python3 tools/check_mod.py --dll ... --smoke smoke.json --tag v0.1.0
    python3 tools/check_mod.py --published dist --tag v0.1.0   # a release as package.py made it

--published checks what a release publishes (echo-mod.json, the mod's <id>-v<version>-windows.zip
or the pack's zip, SHA256SUMS) by the rules the echo-mods check, the launcher's catalogue and the
release signer apply to every release: the release workflow runs it before it creates the draft.
A mod's release is exactly three files, and the DLL inside the zip carries one
NEVR-PLUGIN-BUILD <version> <commit> literal that release-signer compares with the tag.

Exit code 0 when nothing is wrong. Warnings don't fail the check. Python 3.8+, no packages.
"""
import argparse
import atexit
import hashlib
import json
import re
import shutil
import stat
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

# semver.org's own regex for a semantic version (2.0.0).
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)
ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
FILE = re.compile(r"^[A-Za-z0-9._-]{1,64}\.dll$")
RANGE_PART = re.compile(r"^(>=|<=|>|<|=|\^|~)?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$")

CAPABILITIES = {
    "observes-only": 0x01,
    "cosmetic": 0x02,
    "alters-gameplay": 0x04,
    "alters-rules": 0x08,
    "network": 0x10,
    "hooks-engine": 0x20,
}
KINDS = {"mod", "pack"}
TARGETS = {"client", "server", "both"}
VISIBILITY = {"public", "unlisted", "private"}

# File names a mod can never use: the loader slot, nEVR's own files, and the files the community
# update ships or the launcher manages. Compared case-insensitively.
RESERVED_FILES = {
    "bugsplat64.dll", "bugsplat64.nevr.dll", "dbgcore.dll", "nevr.dll", "log_filter.dll", "log-filter.dll",
    "echovr.exe", "pnsradgameserver.dll", "pnsrad.dll", "pnsovr.dll",
    "nvrassetpatches.dll", "nvrxmlhttpfix.dll", "nvrgpurating.dll", "nvrcontentoverlay.dll",
    "nvrmissingtextures.dll", "nvrserverpatches.dll",
    "echoxr.dll", "libovrrt64_1.dll", "echoxr-hands.dll", "handtracking.dll",
}
RESERVED_IDS = {
    "asset-patches", "xmlhttp-fix", "gpu-rating", "content-overlay", "missing-textures", "server-patches",
    "nevr", "nevr-runtime", "echoxr", "echoxr-hands", "echocombat",
}
# Whole families: nEVR's and EchoXR's names, and the launcher's own Nvr*.dll plugins.
RESERVED_ID_PREFIXES = ("nevr", "echoxr", "echotools")
RESERVED_FILE_PREFIXES = ("nvr", "nevr", "echoxr")
# Not published yet: mods for game servers.
UNPUBLISHED_TARGETS = {"server"}
# Content packs (game data beside the DLL) aren't published yet: players' launchers can't
# install them until the content overlay is in the launcher's own catalogue.
UNPUBLISHED_KINDS = {"pack"}
PACKS_LATER = "\"kind\": \"pack\" isn't published yet (content packs come later): a \"mod\" (one DLL)"

# Exports nEVR looks up. GetInfo is required; the template exports all of them.
EXPORTS_REQUIRED = {"NvrPluginGetInfo"}
EXPORTS_EXPECTED = {
    "NvrPluginGetApiVersion", "NvrPluginGetCapabilities", "NvrPluginInitEx", "NvrPluginInit", "NvrPluginShutdown",
}

# DLLs every Windows 10 has in System32 (and Wine/Proton provides). Anything else has to be linked
# in statically: nEVR loads plugins with a search path of their own folder and System32 only.
SYSTEM_DLLS = {
    "kernel32.dll", "kernelbase.dll", "ntdll.dll", "user32.dll", "gdi32.dll", "advapi32.dll", "shell32.dll",
    "shlwapi.dll", "ole32.dll", "oleaut32.dll", "uuid.dll", "comdlg32.dll", "comctl32.dll", "version.dll",
    "psapi.dll", "dbghelp.dll", "imagehlp.dll", "bcrypt.dll", "crypt32.dll", "ncrypt.dll", "secur32.dll",
    "rpcrt4.dll", "setupapi.dll", "winmm.dll", "imm32.dll", "uxtheme.dll", "dwmapi.dll", "userenv.dll",
    "msvcrt.dll", "ucrtbase.dll", "d3d11.dll", "dxgi.dll", "d3dcompiler_47.dll", "d3d9.dll", "dinput8.dll",
    "xinput1_3.dll", "xinput1_4.dll", "xinput9_1_0.dll", "dsound.dll", "mmdevapi.dll", "avrt.dll",
    "ws2_32.dll", "mswsock.dll", "wininet.dll", "winhttp.dll", "iphlpapi.dll", "dnsapi.dll", "normaliz.dll",
    "wtsapi32.dll", "powrprof.dll", "hid.dll", "cfgmgr32.dll", "opengl32.dll", "vulkan-1.dll",
}
NETWORK_DLLS = {"ws2_32.dll", "mswsock.dll", "wininet.dll", "winhttp.dll", "iphlpapi.dll", "dnsapi.dll"}
# Runtimes that are never there: link them statically (-static / /MT).
RUNTIME_DLLS = re.compile(r"^(libstdc\+\+|libgcc_s|libwinpthread|vcruntime|msvcp|concrt|vcomp|ucrtbased|msvcr\d)",
                          re.I)

# The build identity every DLL carries (src/plugin.cpp): one NUL-bounded literal, which
# release-signer compares with the release's tag and the attested commit. Never NEVR-BUILD: the
# nEVR installer takes any DLL holding "NEVR-BUILD " for the runtime itself.
IDENTITY = re.compile(rb"\x00NEVR-PLUGIN-BUILD ([0-9A-Za-z.+-]+) ([0-9a-f]{40})\x00")
# What a mod's release zip may hold (flat, no directories), and the date every entry has.
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
ZIP_ENTRY_MAX = 16 << 20
# Names Windows treats as the same file, or can't create.
WINDOWS_BAD_NAME = re.compile(r'[<>:"|?*\x00-\x1f]|[. ]$')


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.notes = []

    def error(self, text):
        self.errors.append(text)

    def warn(self, text):
        self.warnings.append(text)

    def note(self, text):
        self.notes.append(text)

    def print(self):
        for text in self.notes:
            print(f"  {text}")
        for text in self.warnings:
            print(f"warning: {text}")
        for text in self.errors:
            print(f"error: {text}")
        print("ok" if not self.errors else f"{len(self.errors)} error(s)")


def is_prerelease(version):
    m = SEMVER.match(version)
    return bool(m and m.group(4))


def check_range(text):
    """A version range: space-separated comparators (">=4.1.0 <6.0.0"), "^1.2.0", "~1.2.0" or "*"."""
    if text.strip() == "*":
        return True
    parts = text.split()
    return bool(parts) and all(RANGE_PART.match(p) for p in parts)


def check_manifest(m, report, root, published=False):
    """echo-mod.json as it is in the repo (`root` its folder), or, `published`, as package.py
    filled it in for a release (settings as an object, a pack's zip described in "pack")."""
    def need(key, kind):
        if not isinstance(m.get(key), kind):
            report.error(f"echo-mod.json: \"{key}\" is missing or not a {kind.__name__}")
            return None
        return m[key]

    if m.get("schema") != 1:
        report.error("echo-mod.json: \"schema\" must be 1")
    mod_id = need("id", str)
    if mod_id is not None:
        if not ID.match(mod_id):
            report.error(f"id \"{mod_id}\": lowercase letters, digits, '.', '-', '_' (at most 64), starting with a "
                         "letter or digit")
        elif mod_id in RESERVED_IDS or mod_id.startswith(RESERVED_ID_PREFIXES):
            report.error(f"id \"{mod_id}\" is reserved (nevr*, echoxr* and echotools* are the projects' own)")
    for key in ("name", "summary", "author"):
        value = need(key, str)
        if value is not None and not value.strip():
            report.error(f"\"{key}\" is empty")
    if m.get("author") == "Your name":
        report.warn("\"author\" is still the template's")
    if m.get("id") == "example-mod":
        report.warn("\"id\" is still the template's example-mod")
    version = need("version", str)
    if version is not None and not SEMVER.match(version):
        report.error(f"version \"{version}\" is not a semantic version (semver.org): MAJOR.MINOR.PATCH, optionally "
                     "-prerelease and +build")
    kind = m.get("kind", "mod")
    if kind not in KINDS:
        report.error(f"kind \"{kind}\": one of {sorted(KINDS)}")
    elif kind in UNPUBLISHED_KINDS:
        report.error(PACKS_LATER)
    file = need("file", str)
    if file is not None:
        if not FILE.match(file):
            report.error(f"file \"{file}\": letters, digits, '.', '-', '_', ending in .dll (at most 64)")
        elif file.lower() in RESERVED_FILES or file.lower().startswith(RESERVED_FILE_PREFIXES):
            report.error(f"file \"{file}\" is reserved (Nvr*, nEVR* and EchoXR* are the projects' own)")
    api = m.get("api", 5)
    # 7 adds plugin-carried assets (nevr-runtime docs/reference/plugin-assets.md), 8 the game's main
    # level in every context (level_symbol, level_name); 5 and 6 still pass.
    if api not in (5, 6, 7, 8):
        report.error("\"api\": 5, 6, 7 or 8")
    caps = m.get("capabilities")
    if not isinstance(caps, list) or not caps:
        report.error("\"capabilities\": declare at least one of " + ", ".join(CAPABILITIES))
    else:
        for cap in caps:
            if cap not in CAPABILITIES:
                report.error(f"capability \"{cap}\": one of " + ", ".join(CAPABILITIES))
        if "observes-only" in caps and len(caps) > 1:
            report.error("\"observes-only\" can't go with other capabilities: a mod that changes something "
                         "doesn't only observe")
    if m.get("target", "client") not in TARGETS:
        report.error(f"\"target\": one of {sorted(TARGETS)}")
    elif m.get("target", "client") in UNPUBLISHED_TARGETS:
        report.error("\"target\": \"server\" isn't published yet (mods for game servers come later): "
                     "\"client\" or \"both\"")
    if m.get("visibility", "public") not in VISIBILITY:
        report.error(f"\"visibility\": one of {sorted(VISIBILITY)}")
    for flag in ("required", "shipped"):
        if m.get(flag):
            report.error(f"\"{flag}\" is only for the launcher's own mods")
    requires = m.get("requires", {})
    if not isinstance(requires, dict):
        report.error("\"requires\" must be an object")
        requires = {}
    if "nevr" in requires and not (isinstance(requires["nevr"], str) and check_range(requires["nevr"])):
        report.error("requires.nevr: a version range such as \">=4.1.0\"")
    for dep in requires.get("mods", []):
        if not (isinstance(dep, dict) and isinstance(dep.get("id"), str) and ID.match(dep["id"])
                and check_range(dep.get("version", "*"))):
            report.error(f"requires.mods: each one {{\"id\": \"...\", \"version\": \">=1.0.0\"}}, not {dep!r}")
        elif dep["id"] == mod_id:
            report.error("a mod can't require itself")
    for other in m.get("conflicts", []):
        if not (isinstance(other, str) and ID.match(other)):
            report.error(f"conflicts: mod ids, not {other!r}")
    if not isinstance(m.get("license"), str) or not m["license"].strip():
        report.error("\"license\": an SPDX id such as MIT, Apache-2.0, GPL-3.0-only")
    homepage = m.get("homepage", "")
    if homepage and not homepage.startswith("https://"):
        report.error("\"homepage\" must start with https://")
    if not isinstance(m.get("args", {}), dict):
        report.error("\"args\" must be an object")
    settings = m.get("settings")
    if settings and published:
        if not isinstance(settings, dict):
            report.error("\"settings\": the release's echo-mod.json carries the settings object")
    elif settings:
        if not isinstance(settings, str):
            report.error("\"settings\": the path of a <Stem>.plugin.json in the repo")
        else:
            path = root / settings
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                if doc.get("schema") != 1 or not isinstance(doc.get("settings"), dict):
                    report.error(f"{settings}: needs \"schema\": 1 and a \"settings\" object (see the launcher's "
                                 "docs/plugins/settings.md)")
            except (OSError, ValueError) as e:
                report.error(f"{settings}: {e}")
    if kind == "pack":
        pack = m.get("pack")
        if not isinstance(pack, dict) or not isinstance(pack.get("content"), str) or not ID.match(pack["content"]):
            report.error("a pack needs \"pack\": {\"content\": \"<content id>\"} and content/<content id>/content.json")
        elif published:
            if not isinstance(pack.get("file"), str) or not re.match(r"^[A-Za-z0-9._+-]{1,96}\.zip$", pack["file"]):
                report.error("pack.file: the pack's zip (package.py names it)")
        elif not (root / "content" / pack["content"] / "content.json").is_file():
            report.error(f"content/{pack['content']}/content.json is missing")


def read_pe(data, report):
    """(exports, imports) of a PE file, or None when it isn't a 64-bit DLL."""
    if data[:2] != b"MZ":
        report.error("the DLL isn't a Windows PE file")
        return None
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        report.error("the DLL has no PE header")
        return None
    machine, sections, _, _, _, opt_size, characteristics = struct.unpack_from("<HHIIIHH", data, pe + 4)
    if machine != 0x8664:
        report.error(f"the DLL isn't x64 (machine 0x{machine:04x}): Echo VR is 64-bit")
        return None
    if not characteristics & 0x2000:
        report.error("the file is an executable, not a DLL")
        return None
    opt = pe + 24
    if struct.unpack_from("<H", data, opt)[0] != 0x20B:
        report.error("the DLL isn't PE32+")
        return None
    dirs = opt + 112
    export_rva, _ = struct.unpack_from("<II", data, dirs)
    import_rva, _ = struct.unpack_from("<II", data, dirs + 8)
    table = opt + opt_size
    secs = [struct.unpack_from("<8sIIII", data, table + 40 * i) for i in range(sections)]

    def offset(rva):
        for _, vsize, vaddr, rsize, raw in secs:
            if vaddr <= rva < vaddr + max(vsize, rsize):
                return raw + rva - vaddr
        return None

    def cstr(rva):
        o = offset(rva)
        if o is None:
            return ""
        return data[o:data.index(b"\0", o)].decode("ascii", "replace")

    exports = set()
    if export_rva:
        o = offset(export_rva)
        count, names_rva = struct.unpack_from("<I", data, o + 24)[0], struct.unpack_from("<I", data, o + 32)[0]
        names = offset(names_rva)
        for i in range(count):
            exports.add(cstr(struct.unpack_from("<I", data, names + 4 * i)[0]))
    imports = []
    if import_rva:
        o = offset(import_rva)
        while o is not None:
            name_rva = struct.unpack_from("<I", data, o + 12)[0]
            if not name_rva:
                break
            imports.append(cstr(name_rva))
            o += 20
    return exports, imports


def check_identity(data, manifest, report, commit=None):
    """The DLL holds exactly one NEVR-PLUGIN-BUILD literal; its version is the manifest's and, when
    `commit` is given (a release), its commit is that one."""
    if b"NEVR-BUILD " in data:
        report.error("the DLL contains \"NEVR-BUILD \": that is the nEVR runtime's own stamp (the installer would "
                     "take the DLL for the runtime); a mod carries NEVR-PLUGIN-BUILD")
    found = IDENTITY.findall(data)
    if len(found) != 1 or data.count(b"NEVR-PLUGIN-BUILD") != 1:
        report.error("the DLL must contain exactly one \\0NEVR-PLUGIN-BUILD <version> <commit>\\0 literal (src/plugin.cpp "
                     f"has it; it is referenced at run time so the linker keeps it): found {len(found)} well-formed, "
                     f"{data.count(b'NEVR-PLUGIN-BUILD')} mention(s)")
        return
    version, sha = (x.decode("ascii") for x in found[0])
    if version != manifest.get("version"):
        report.error(f"the DLL's NEVR-PLUGIN-BUILD says version {version}, echo-mod.json {manifest.get('version')}")
    if commit is not None and sha != commit:
        report.error(f"the DLL's NEVR-PLUGIN-BUILD says commit {sha}, the release is built from {commit}")


def check_dll(path, manifest, report, commit=None):
    data = Path(path).read_bytes()
    if Path(path).name != manifest.get("file"):
        report.error(f"the DLL is called {Path(path).name}, echo-mod.json says {manifest.get('file')}")
    pe = read_pe(data, report)
    if pe is None:
        return
    exports, imports = pe
    for name in sorted(EXPORTS_REQUIRED - exports):
        report.error(f"missing export {name}: nEVR can't load the DLL without it")
    for name in sorted(EXPORTS_EXPECTED - exports):
        report.warn(f"no export {name}")
    stray = sorted(e for e in exports if not e.startswith("Nvr"))
    if stray:
        report.error("exports other than the Nvr* plugin ABI (src/exports.def lists exactly what leaves the DLL): "
                     + ", ".join(stray[:10]) + (" ..." if len(stray) > 10 else ""))
    check_identity(data, manifest, report, commit)
    report.note(f"{len(data)} bytes, imports: " + ", ".join(imports))
    caps = set(manifest.get("capabilities") or [])
    for dll in imports:
        low = dll.lower()
        if RUNTIME_DLLS.match(low):
            report.error(f"imports {dll}: link the C/C++ runtime statically (MinGW -static, MSVC /MT)")
        elif low not in SYSTEM_DLLS and not low.startswith(("api-ms-win-", "ext-ms-win-")):
            report.error(f"imports {dll}, which isn't part of Windows: link it statically or leave it out")
        if low in NETWORK_DLLS and "network" not in caps:
            report.error(f"imports {dll} (network) but doesn't declare the \"network\" capability")


def check_smoke(path, manifest, report):
    found = json.loads(Path(path).read_text(encoding="utf-8").strip().splitlines()[0])
    version = manifest.get("version", "")
    core = version.split("-")[0].split("+")[0]
    if found.get("version") != core:
        report.error(f"NvrPluginGetInfo says version {found.get('version')}, echo-mod.json {version}")
    if found.get("name") != manifest.get("id"):
        report.warn(f"NvrPluginGetInfo's name is {found.get('name')!r}, the id {manifest.get('id')!r}")
    want = 0
    for cap in manifest.get("capabilities") or []:
        want |= CAPABILITIES.get(cap, 0)
    if found.get("capabilities") != want:
        report.error(f"NvrPluginGetCapabilities gives 0x{found.get('capabilities', 0):02x}, echo-mod.json declares "
                     f"0x{want:02x}")
    if found.get("api") != manifest.get("api", 5):
        report.error(f"NvrPluginGetApiVersion gives {found.get('api')}, echo-mod.json says {manifest.get('api', 5)}")
    if not found.get("has_shutdown"):
        report.warn("no NvrPluginShutdown: nEVR then keeps a failed plugin loaded until the game exits")
    report.note(f"smoke: {found}")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main_file(manifest):
    """The file a release publishes: the DLL, or a pack's zip."""
    if manifest.get("kind", "mod") == "pack":
        return (manifest.get("pack") or {}).get("file")
    return manifest.get("file")


def parse_sums(text):
    """{name: digest} of a SHA256SUMS text; None when a line isn't `<sha256>  <name>`."""
    sums = {}
    for line in text.splitlines():
        parts = line.split("  ", 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]) or parts[1] in sums:
            return None
        sums[parts[1]] = parts[0]
    return sums


def release_zip_name(manifest):
    return f"{manifest.get('id')}-v{manifest.get('version')}-windows.zip"


def check_release(work, manifest, report):
    """A mod's release as release-signer takes it: exactly three files in `work` --
    <id>-v<version>-windows.zip, echo-mod.json (without sha256 or size: signing changes the DLL's
    bytes), SHA256SUMS (the zip and echo-mod.json) -- and in the zip, flat and with fixed dates: the
    DLL, LICENSE, NOTICE if there is one, <Stem>.plugin.json when the mod has settings, and a
    SHA256SUMS over the others. Returns (manifest, the DLL to load-test, or None)."""
    package = release_zip_name(manifest)
    if manifest.get("package") != package:
        report.error(f"echo-mod.json: \"package\" must be {package} (<id>-v<version>-windows.zip), not "
                     f"{manifest.get('package')!r}")
    for key in ("sha256", "size"):
        if key in manifest:
            report.error(f"echo-mod.json: \"{key}\" doesn't belong in a release: signing changes the DLL's bytes, "
                         "the final hashes are in SHA256SUMS")
    names = sorted(p.name for p in work.iterdir())
    for name in names:
        if name not in (package, "echo-mod.json", "SHA256SUMS"):
            report.error(f"the release has {name}: its files are exactly {package}, echo-mod.json and SHA256SUMS")
    if not (work / package).is_file():
        report.error(f"the release lacks {package}")
        return manifest, None

    try:
        top = parse_sums((work / "SHA256SUMS").read_text(encoding="utf-8"))
    except OSError:
        top = None
        report.error("the release has no SHA256SUMS")
    else:
        want = {package: sha256(work / package), "echo-mod.json": sha256(work / "echo-mod.json")}
        if top != want:
            report.error("SHA256SUMS must have exactly one line for the zip and one for echo-mod.json, matching them")

    settings = manifest.get("settings")
    sheet = f"{str(manifest.get('file'))[:-4]}.plugin.json"
    required = {str(manifest.get("file")), "LICENSE", "SHA256SUMS"} | ({sheet} if settings else set())
    allowed = required | {"NOTICE"}
    try:
        zf = zipfile.ZipFile(work / package)
    except zipfile.BadZipFile:
        report.error(f"{package} isn't a zip")
        return manifest, None
    with zf:
        infos = zf.infolist()
        seen = set()
        for info in infos:
            name = info.filename
            if info.is_dir() or "/" in name or "\\" in name:
                report.error(f"{package}: {name!r}: the zip is flat, files only")
            elif name not in allowed:
                report.error(f"{package}: {name!r} isn't one of: " + ", ".join(sorted(allowed)))
            if WINDOWS_BAD_NAME.search(name) or name.lower() in seen:
                report.error(f"{package}: {name!r} is not a name Windows can hold apart from the others")
            seen.add(name.lower())
            mode = info.external_attr >> 16
            if mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                kind = "a symlink" if stat.S_ISLNK(mode) else "a special entry"
                report.error(f"{package}: {name!r} is {kind}")
            if info.date_time != ZIP_DATE:
                report.error(f"{package}: {name!r} has the date {info.date_time}, not the fixed {ZIP_DATE}")
            if info.file_size > ZIP_ENTRY_MAX:
                report.error(f"{package}: {name!r} is over {ZIP_ENTRY_MAX >> 20} MiB")
        have = {i.filename for i in infos}
        for name in sorted(required - have):
            report.error(f"{package} lacks {name}")
        if len(have) != len(infos):
            report.error(f"{package} has an entry twice")
        if "SHA256SUMS" in have:
            inner = parse_sums(zf.read("SHA256SUMS").decode("utf-8", "replace"))
            body = {i.filename: hashlib.sha256(zf.read(i.filename)).hexdigest()
                    for i in infos if i.filename != "SHA256SUMS" and i.file_size <= ZIP_ENTRY_MAX}
            if inner != body:
                report.error(f"{package}: the inner SHA256SUMS doesn't list exactly the other files, matching them")
        file = str(manifest.get("file"))
        if file not in have or any(i.file_size > ZIP_ENTRY_MAX for i in infos if i.filename == file):
            return manifest, None
        # Outside the release's folder: the release workflow uploads all of it.
        out = Path(tempfile.mkdtemp(prefix="check_mod-"))
        atexit.register(shutil.rmtree, out, True)
        (out / file).write_bytes(zf.read(file))
        return manifest, out / file


def release_commit(manifest):
    """The commit a release was built from (package.py records it from GITHUB_SHA), or None."""
    commit = (manifest.get("source") or {}).get("commit")
    return commit if isinstance(commit, str) and commit else None


def check_published(work, tag, prerelease, report):
    """A release as the release workflow publishes it, in folder `work`: echo-mod.json, the DLL
    or the pack's zip, SHA256SUMS. `tag` is the release's tag, `prerelease` its GitHub flag.
    Returns (manifest, the DLL to load-test) -- the DLL None when there is none to test."""
    work = Path(work)
    try:
        manifest = json.loads((work / "echo-mod.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        report.error(f"echo-mod.json: {e}")
        return None, None
    if not isinstance(manifest, dict):
        report.error("echo-mod.json isn't an object")
        return None, None
    check_manifest(manifest, report, work, published=True)
    version = str(manifest.get("version", ""))
    if tag != f"v{version}":
        report.error(f"tag {tag} doesn't match echo-mod.json's version: tag v{version}")
    if SEMVER.match(version) and bool(prerelease) != is_prerelease(version):
        report.error("the GitHub prerelease flag doesn't match the version: a version with a prerelease part "
                     "(1.2.0-beta.1) is a prerelease, any other isn't")
    if manifest.get("kind", "mod") != "pack":
        return check_release(work, manifest, report)
    main = main_file(manifest)
    if not isinstance(main, str) or not (work / main).is_file():
        report.error(f"the release lacks {main}, the file its echo-mod.json names")
        return manifest, None
    sums = {}
    try:
        for line in (work / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2:
                sums[parts[1].lstrip("*")] = parts[0]
    except OSError:
        report.error("the release has no SHA256SUMS")
    digest = sha256(work / main)
    for name, have in ((main, digest), ("echo-mod.json", sha256(work / "echo-mod.json"))):
        if sums and sums.get(name) != have:
            report.error(f"{name} doesn't match SHA256SUMS")
    if (manifest.get("pack") or {}).get("sha256") != digest:
        report.error(f"{main} doesn't match the sha256 in echo-mod.json")
    # A pack: plugins/<file> and content/<content id>/, nothing else, no path out of either.
    content = str((manifest.get("pack") or {}).get("content", ""))
    inner = f"plugins/{manifest.get('file')}"
    try:
        with zipfile.ZipFile(work / main) as zf:
            names = zf.namelist()
            bad = [n for n in names if n.startswith("/") or "\\" in n or ".." in n.split("/")
                   or not (n.startswith("plugins/") or n.startswith(f"content/{content}/"))]
            if bad:
                report.error("the pack has files outside plugins/ and content/<content id>/: " + ", ".join(bad[:5]))
            if f"content/{content}/content.json" not in names:
                report.error(f"the pack has no content/{content}/content.json")
            if inner not in names:
                report.error(f"the pack has no {inner}")
                return manifest, None
            # Outside the release's folder: the release workflow uploads all of it.
            out = Path(tempfile.mkdtemp(prefix="check_mod-")) / "plugins"
            atexit.register(shutil.rmtree, out.parent, True)
            out.mkdir()
            (out / str(manifest["file"])).write_bytes(zf.read(inner))
            return manifest, out / str(manifest["file"])
    except zipfile.BadZipFile:
        report.error(f"{main} isn't a zip")
        return manifest, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default="echo-mod.json")
    ap.add_argument("--dll", help="the built DLL")
    ap.add_argument("--smoke", help="the smoke host's output (a JSON line)")
    ap.add_argument("--tag", help="the git tag being released: must be v<version>")
    ap.add_argument("--published", metavar="DIR", help="a release's files as package.py made them (needs --tag)")
    args = ap.parse_args()

    report = Report()
    if args.published:
        if args.tag is None:
            ap.error("--published needs --tag")
        version = json.loads((Path(args.published) / "echo-mod.json").read_text(encoding="utf-8")).get("version", "")
        manifest, dll = check_published(args.published, args.tag, is_prerelease(str(version)), report)
        if dll is not None:
            check_dll(str(dll), manifest, report, commit=release_commit(manifest))
        if args.smoke and manifest:
            check_smoke(args.smoke, manifest, report)
        report.print()
        return 1 if report.errors else 0
    manifest_path = Path(args.manifest)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: {args.manifest}: {e}")
        return 1
    check_manifest(manifest, report, manifest_path.resolve().parent)
    if args.tag is not None and args.tag != "v" + str(manifest.get("version")):
        report.error(f"tag {args.tag} doesn't match echo-mod.json's version: tag v{manifest.get('version')}")
    if args.dll:
        check_dll(args.dll, manifest, report)
    if args.smoke:
        check_smoke(args.smoke, manifest, report)
    report.print()
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
