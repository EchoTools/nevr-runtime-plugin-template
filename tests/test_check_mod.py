#!/usr/bin/env python3
"""Tests of tools/check_mod.py and tools/package.py: a release as the release workflow makes it
passes the published check, mods and packs alike, and what the catalogue refuses is refused here.

    python3 tests/test_check_mod.py        # needs build/mingw/<file> (tools/ci-build.sh builds it)
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_mod  # noqa: E402

MANIFEST = json.loads((ROOT / "echo-mod.json").read_text(encoding="utf-8"))
DLL = ROOT / "build" / "mingw" / MANIFEST["file"]


def package(repo, out):
    subprocess.run([sys.executable, str(ROOT / "tools" / "package.py"), "--dll", str(DLL),
                    "--manifest", str(repo / "echo-mod.json"), "--out", str(out)],
                   check=True, capture_output=True, text=True)


def checked(work, tag, prerelease=False):
    report = check_mod.Report()
    manifest, dll = check_mod.check_published(work, tag, prerelease, report)
    if dll is not None:
        check_mod.check_dll(str(dll), manifest, report)
    return report


def repo_copy(tmp, notice=None, **changes):
    repo = Path(tmp) / "repo"
    repo.mkdir()
    # A plain mod unless the test asks for more (a mod repo's own echo-mod.json may be a pack).
    m = {**{k: v for k, v in MANIFEST.items() if k != "pack"}, "kind": "mod", "id": "test-mod", "author": "Tester",
         **changes}
    (repo / "echo-mod.json").write_text(json.dumps(m), encoding="utf-8")
    shutil.copy(ROOT / "LICENSE", repo / "LICENSE")
    if notice:
        (repo / "NOTICE").write_text(notice, encoding="utf-8")
    if isinstance(m.get("settings"), str):
        shutil.copy(ROOT / m["settings"], repo / m["settings"])
    return repo


@unittest.skipUnless(DLL.is_file(), f"no {DLL} (build first: tools/ci-build.sh)")
class Published(unittest.TestCase):
    def test_a_mod_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = repo_copy(tmp)
            package(repo, Path(tmp) / "dist")
            report = checked(Path(tmp) / "dist", f"v{MANIFEST['version']}")
            self.assertEqual(report.errors, [])

    def test_a_mod_is_exactly_three_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = repo_copy(tmp)
            dist = Path(tmp) / "dist"
            package(repo, dist)
            zip_name = f"test-mod-v{MANIFEST['version']}-windows.zip"
            self.assertEqual(sorted(p.name for p in dist.iterdir()), sorted([zip_name, "echo-mod.json", "SHA256SUMS"]))
            published = json.loads((dist / "echo-mod.json").read_text(encoding="utf-8"))
            self.assertEqual(published["package"], zip_name)
            self.assertNotIn("sha256", published)
            self.assertNotIn("size", published)
            sums = (dist / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
            self.assertEqual(sums, sorted([f"{check_mod.sha256(dist / zip_name)}  {zip_name}",
                                           f"{check_mod.sha256(dist / 'echo-mod.json')}  echo-mod.json"],
                                          key=lambda line: line.split()[1]))

    def test_the_zip_is_flat_dated_and_has_inner_sums(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = repo_copy(tmp, notice="Credits.\n")
            dist = Path(tmp) / "dist"
            package(repo, dist)
            with zipfile.ZipFile(dist / f"test-mod-v{MANIFEST['version']}-windows.zip") as zf:
                self.assertEqual(zf.namelist(), [MANIFEST["file"], "LICENSE", "NOTICE",
                                                 MANIFEST["file"][:-4] + ".plugin.json", "SHA256SUMS"])
                self.assertEqual({i.date_time for i in zf.infolist()}, {(1980, 1, 1, 0, 0, 0)})
                inner = zf.read("SHA256SUMS").decode("utf-8")
                for name in zf.namelist()[:-1]:
                    self.assertIn(f"{hashlib.sha256(zf.read(name)).hexdigest()}  {name}\n", inner)
            self.assertEqual(checked(dist, f"v{MANIFEST['version']}").errors, [])

    def test_notice_is_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "dist"
            package(repo_copy(tmp), dist)
            with zipfile.ZipFile(dist / f"test-mod-v{MANIFEST['version']}-windows.zip") as zf:
                self.assertNotIn("NOTICE", zf.namelist())

    def test_the_same_files_make_the_same_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = repo_copy(tmp)
            package(repo, Path(tmp) / "a")
            package(repo, Path(tmp) / "b")
            name = f"test-mod-v{MANIFEST['version']}-windows.zip"
            self.assertEqual((Path(tmp) / "a" / name).read_bytes(), (Path(tmp) / "b" / name).read_bytes())

    def test_a_mod_without_a_license_is_not_packed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = repo_copy(tmp)
            (repo / "LICENSE").unlink()
            result = subprocess.run([sys.executable, str(ROOT / "tools" / "package.py"), "--dll", str(DLL),
                                     "--manifest", str(repo / "echo-mod.json"), "--out", str(Path(tmp) / "dist")],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("LICENSE", result.stderr)

    def test_a_pack_passes_and_keeps_its_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = repo_copy(tmp, kind="pack", pack={"content": "test-content"})
            (repo / "content" / "test-content").mkdir(parents=True)
            (repo / "content" / "test-content" / "content.json").write_text("{}", encoding="utf-8")
            package(repo, Path(tmp) / "dist")
            published = json.loads((Path(tmp) / "dist" / "echo-mod.json").read_text(encoding="utf-8"))
            self.assertEqual(published["file"], MANIFEST["file"])
            self.assertTrue(published["pack"]["file"].endswith(".zip"))
            report = checked(Path(tmp) / "dist", f"v{MANIFEST['version']}")
            # Built and checked as a pack; only not published yet.
            self.assertEqual(report.errors, [check_mod.PACKS_LATER])
            # Only files in dist/: the release workflow uploads every entry (gh release create dist/*).
            self.assertEqual([p.name for p in (Path(tmp) / "dist").iterdir() if not p.is_file()], [])

    def test_a_pack_with_a_path_out_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = repo_copy(tmp, kind="pack", pack={"content": "test-content"})
            (repo / "content" / "test-content").mkdir(parents=True)
            (repo / "content" / "test-content" / "content.json").write_text("{}", encoding="utf-8")
            dist = Path(tmp) / "dist"
            package(repo, dist)
            m = json.loads((dist / "echo-mod.json").read_text(encoding="utf-8"))
            zf_path = dist / m["pack"]["file"]
            with zipfile.ZipFile(zf_path, "a") as zf:
                zf.writestr("content/test-content/../../BugSplat64.dll", b"x")
            m["pack"]["sha256"] = check_mod.sha256(zf_path)
            (dist / "echo-mod.json").write_text(json.dumps(m), encoding="utf-8")
            (dist / "SHA256SUMS").write_text("".join(f"{check_mod.sha256(p)}  {p.name}\n"
                                                     for p in sorted(dist.iterdir()) if p.is_file()
                                                     and p.name != "SHA256SUMS"), encoding="utf-8")
            report = checked(dist, f"v{MANIFEST['version']}")
            self.assertTrue(any("outside plugins/" in e for e in report.errors), report.errors)

    def test_tag_flag_and_sums(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = repo_copy(tmp, version="1.0.0-beta.1")
            dist = Path(tmp) / "dist"
            package(repo, dist)
            # (The DLL is the 0.1.0 build; its own version check has a test of its own, in Identity.)
            def errors(*args, **kw):
                return [e for e in checked(*args, **kw).errors if "NEVR-PLUGIN-BUILD" not in e]
            self.assertEqual(errors(dist, "v1.0.0-beta.1", prerelease=True), [])
            self.assertTrue(any("prerelease flag" in e for e in errors(dist, "v1.0.0-beta.1")))
            self.assertTrue(any("doesn't match echo-mod.json's version" in e
                                for e in errors(dist, "v1.0.0", prerelease=True)))
            zip_path = dist / "test-mod-v1.0.0-beta.1-windows.zip"
            zip_path.write_bytes(zip_path.read_bytes() + b"\0")
            bad = errors(dist, "v1.0.0-beta.1", prerelease=True)
            self.assertTrue(any("SHA256SUMS" in e for e in bad), bad)


def rewrite_zip(dist, mutate):
    """Rewrites the release's zip with `mutate(entries)` (a list of (ZipInfo, bytes)) and fixes the top-level
    SHA256SUMS to match, so a test fails on the one thing it changed and not on the sums."""
    m = json.loads((dist / "echo-mod.json").read_text(encoding="utf-8"))
    path = dist / m["package"]
    with zipfile.ZipFile(path) as zf:
        entries = [(i, zf.read(i.filename)) for i in zf.infolist()]
    entries = mutate(entries)
    with zipfile.ZipFile(path, "w") as zf:
        for info, data in entries:
            zf.writestr(info, data)
    write_sums(dist)


def write_sums(dist):
    (dist / "SHA256SUMS").write_text("".join(f"{check_mod.sha256(p)}  {p.name}\n" for p in sorted(dist.iterdir())
                                             if p.is_file() and p.name != "SHA256SUMS"), encoding="utf-8")


def inner_sums(entries):
    """A fresh inner SHA256SUMS for `entries` (every entry but SHA256SUMS itself)."""
    return "".join(f"{hashlib.sha256(d).hexdigest()}  {i.filename}\n" for i, d in entries
                   if i.filename != "SHA256SUMS").encode("utf-8")


@unittest.skipUnless(DLL.is_file(), f"no {DLL} (build first: tools/ci-build.sh)")
class Layout(unittest.TestCase):
    """What the release signer needs of a release: three assets, a flat zip, sums that agree."""

    def release(self, tmp, **changes):
        dist = Path(tmp) / "dist"
        package(repo_copy(tmp, notice="Credits.\n", **changes), dist)
        return dist

    def errors(self, dist):
        return checked(dist, f"v{MANIFEST['version']}").errors

    def test_an_extra_asset_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = self.release(tmp)
            (dist / "extra.txt").write_text("x", encoding="utf-8")
            self.assertTrue(any("extra.txt" in e for e in self.errors(dist)), self.errors(dist))

    def test_a_loose_dll_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = self.release(tmp)
            shutil.copy(DLL, dist / MANIFEST["file"])
            self.assertTrue(any(MANIFEST["file"] in e for e in self.errors(dist)), self.errors(dist))

    def test_final_hashes_do_not_belong_in_echo_mod_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = self.release(tmp)
            m = json.loads((dist / "echo-mod.json").read_text(encoding="utf-8"))
            m["sha256"] = "0" * 64
            (dist / "echo-mod.json").write_text(json.dumps(m), encoding="utf-8")
            write_sums(dist)
            self.assertTrue(any("sha256" in e for e in self.errors(dist)), self.errors(dist))

    def test_the_package_name_is_id_version_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = self.release(tmp)
            m = json.loads((dist / "echo-mod.json").read_text(encoding="utf-8"))
            (dist / m["package"]).rename(dist / "other.zip")
            m["package"] = "other.zip"
            (dist / "echo-mod.json").write_text(json.dumps(m), encoding="utf-8")
            write_sums(dist)
            self.assertTrue(any("-windows.zip" in e for e in self.errors(dist)), self.errors(dist))

    def test_the_top_level_sums_must_name_exactly_the_zip_and_the_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = self.release(tmp)
            with open(dist / "SHA256SUMS", "a", encoding="utf-8") as f:
                f.write(f"{'0' * 64}  something-else\n")
            self.assertTrue(any("SHA256SUMS" in e for e in self.errors(dist)), self.errors(dist))

    def test_zip_entries_are_exact(self):
        cases = {
            "a directory entry": lambda e: e + [(zipfile.ZipInfo("sub/"), b"")],
            "a nested file": lambda e: e + [(zipfile.ZipInfo("sub/x.txt"), b"x")],
            "a missing LICENSE": lambda e: [x for x in e if x[0].filename != "LICENSE"],
            "an unknown file": lambda e: e + [(zipfile.ZipInfo("README.md"), b"x")],
            "a Windows-colliding name": lambda e: e + [(zipfile.ZipInfo("license"), b"x")],
            "a backslash": lambda e: e + [(zipfile.ZipInfo("a\\b"), b"x")],
        }
        for label, mutate in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                dist = self.release(tmp)
                rewrite_zip(dist, mutate)
                self.assertTrue(self.errors(dist), f"{label} was accepted")

    def test_a_symlink_entry_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = self.release(tmp)

            def mutate(entries):
                link = zipfile.ZipInfo("NOTICE", date_time=(1980, 1, 1, 0, 0, 0))
                link.external_attr = 0o120777 << 16
                return [x for x in entries if x[0].filename != "NOTICE"] + [(link, b"/etc/passwd")]
            rewrite_zip(dist, mutate)
            self.assertTrue(any("symlink" in e for e in self.errors(dist)), self.errors(dist))

    def test_dates_are_fixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = self.release(tmp)

            def mutate(entries):
                out = []
                for info, data in entries:
                    info.date_time = (2026, 10, 26, 12, 0, 0)
                    out.append((info, data))
                return out
            rewrite_zip(dist, mutate)
            self.assertTrue(any("date" in e for e in self.errors(dist)), self.errors(dist))

    def test_the_inner_sums_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = self.release(tmp)

            def mutate(entries):
                return [(i, d if i.filename != "LICENSE" else d + b"tampered\n") for i, d in entries]
            rewrite_zip(dist, mutate)
            self.assertTrue(any("inner SHA256SUMS" in e for e in self.errors(dist)), self.errors(dist))

    def test_a_dll_that_is_not_the_manifests_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = self.release(tmp)

            def mutate(entries):
                out = []
                for info, data in entries:
                    if info.filename == MANIFEST["file"]:
                        info.filename = "Other.dll"
                    out.append((info, data))
                sums = next(x for x in out if x[0].filename == "SHA256SUMS")
                out.remove(sums)
                return out + [(sums[0], inner_sums(out))]
            rewrite_zip(dist, mutate)
            self.assertTrue(self.errors(dist))


@unittest.skipUnless(DLL.is_file(), f"no {DLL} (build first: tools/ci-build.sh)")
class Identity(unittest.TestCase):
    """The NEVR-PLUGIN-BUILD literal the release signer compares with the tag and the attested commit."""
    COMMIT = "0123456789abcdef0123456789abcdef01234567"

    def literal(self, data):
        found = check_mod.IDENTITY.findall(data)
        self.assertEqual(len(found), 1, found)
        return found[0]

    def dll_with(self, tmp, old, new):
        data = DLL.read_bytes()
        self.assertEqual(data.count(old), 1, old)
        path = Path(tmp) / MANIFEST["file"]
        path.write_bytes(data.replace(old, new))
        return path

    def errors(self, path, **kw):
        report = check_mod.Report()
        check_mod.check_dll(str(path), MANIFEST, report, **kw)
        return report.errors

    def test_the_built_dll_carries_one_literal_with_its_version(self):
        version, commit = self.literal(DLL.read_bytes())
        self.assertEqual(version.decode(), MANIFEST["version"])
        self.assertRegex(commit.decode(), r"^[0-9a-f]{40}$")
        self.assertEqual(self.errors(DLL), [])

    def test_never_the_runtime_s_literal(self):
        self.assertNotIn(b"NEVR-BUILD ", DLL.read_bytes())

    def test_the_wrong_version_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            version, commit = self.literal(DLL.read_bytes())
            other = b"9" * len(version)  # same length: the PE layout stays as it is
            path = self.dll_with(tmp, b"\0NEVR-PLUGIN-BUILD " + version + b" ", b"\0NEVR-PLUGIN-BUILD " + other + b" ")
            self.assertTrue(any(other.decode() in e for e in self.errors(path)), self.errors(path))

    def test_the_wrong_commit_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            version, commit = self.literal(DLL.read_bytes())
            path = self.dll_with(tmp, commit + b"\0", self.COMMIT.encode() + b"\0")
            self.assertEqual(self.errors(path), [])
            self.assertTrue(any("commit" in e for e in self.errors(path, commit="f" * 40)))

    def test_the_runtime_s_literal_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.dll_with(tmp, b"\0NEVR-PLUGIN-BUILD ", b"\0NEVR-BUILD xxxxxxx")  # same length
            self.assertTrue(any("NEVR-BUILD" in e for e in self.errors(path)), self.errors(path))

    def test_no_literal_and_two_literals_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            version, commit = self.literal(DLL.read_bytes())
            path = self.dll_with(tmp, b"\0NEVR-PLUGIN-BUILD ", b"\0NEVR-PLUGIN-BUILT ")
            self.assertTrue(any("NEVR-PLUGIN-BUILD" in e for e in self.errors(path)), self.errors(path))
            twice = Path(tmp) / "Twice.dll"
            twice.write_bytes(DLL.read_bytes() + b"\0NEVR-PLUGIN-BUILD " + version + b" " + commit + b"\0")
            report = check_mod.Report()
            check_mod.check_dll(str(twice), {**MANIFEST, "file": "Twice.dll"}, report)
            self.assertTrue(any("exactly one" in e for e in report.errors), report.errors)

    def test_an_unset_commit_is_fine_locally_and_refused_for_a_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            version, commit = self.literal(DLL.read_bytes())
            path = self.dll_with(tmp, commit + b"\0", b"0" * 40 + b"\0")
            self.assertEqual(self.errors(path), [])
            self.assertTrue(any("commit" in e for e in self.errors(path, commit="a" * 40)))


@unittest.skipUnless(DLL.is_file(), f"no {DLL} (build first: tools/ci-build.sh)")
class Exports(unittest.TestCase):
    """Only the Nvr* ABI leaves the DLL (AGENTS.md rule 7; the signer refuses anything else)."""

    def errors(self, path):
        report = check_mod.Report()
        check_mod.check_dll(str(path), MANIFEST, report)
        return report.errors

    def test_the_built_dll_exports_only_nvr_symbols(self):
        self.assertEqual(self.errors(DLL), [])

    def test_a_dll_exporting_an_extra_symbol_is_refused(self):
        data = DLL.read_bytes()
        old = b"\0NvrPluginShutdown\0"
        self.assertEqual(data.count(old), 1, "export table entry not found exactly once")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / MANIFEST["file"]
            path.write_bytes(data.replace(old, b"\0XvrPluginShutdown\0"))  # same length: the PE layout stays as it is
            errors = self.errors(path)
        self.assertTrue(any("XvrPluginShutdown" in e and "export" in e for e in errors), errors)


class Manifest(unittest.TestCase):
    def errors(self, **changes):
        report = check_mod.Report()
        check_mod.check_manifest({**MANIFEST, "id": "test-mod", **changes}, report, ROOT)
        return report.errors

    def test_the_template_passes(self):
        self.assertEqual(self.errors(), [])

    def test_reserved_families(self):
        self.assertTrue(self.errors(id="nevr-tools"))
        self.assertTrue(self.errors(id="echoxr-extra"))
        self.assertTrue(self.errors(file="NvrMyMod.dll"))
        self.assertTrue(self.errors(file="EchoXRThing.dll"))
        self.assertEqual(self.errors(file="CoolMod.dll"), [])

    def test_api_versions(self):
        for api in (5, 6, 7):
            self.assertEqual(self.errors(api=api), [], api)
        self.assertTrue(self.errors(api=4))
        self.assertTrue(self.errors(api=8))

    def test_server_mods_not_yet(self):
        self.assertTrue(self.errors(target="server"))

    def test_packs_come_later(self):
        self.assertIn(check_mod.PACKS_LATER, self.errors(kind="pack", pack={"content": "test-content"}))
        self.assertEqual(self.errors(target="both"), [])


if __name__ == "__main__":
    unittest.main()
