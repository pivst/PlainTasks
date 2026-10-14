"""Release archives must be reproducible, complete, and independently verifiable."""

import hashlib
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from PlainTasks.tools import build_release as release


class TestReleaseBuild(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.source = self.directory / "source"
        self.source.mkdir()
        names = (
            *release.PACKAGE_FILES,
            "docs/installation.md",
            "docs/usage.md",
            "docs/development.md",
            "tests/editor_smoke.py",
            "tools/windows/Install.cmd",
            *(f"tools/windows/{name}" for name in release.WINDOWS_FILES),
        )
        for name in names:
            self.write(self.source / name, f"Fixture: {name}\n".encode())
        self.write(self.source / ".python-version", b"3.14\n")
        self.write(self.source / "VERSION", (release.VERSION + "\n").encode())
        self.libraries = self.make_libraries(self.directory / "libraries")
        for name, replacement in (
            ("ROOT", self.source),
            ("source_commit", lambda: "1" * 40),
            ("source_dirty", lambda: False),
        ):
            patcher = patch.object(release, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def write(path, contents):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    def symlink(self, path, target, *, directory=False):
        try:
            path.symlink_to(target, target_is_directory=directory)
        except OSError as error:
            if getattr(error, "winerror", None) == 1314:
                self.skipTest("Windows account lacks permission to create symlinks")
            raise

    def make_libraries(self, directory):
        self.write(directory / "dateutil/__init__.py", b"__version__ = '2.9.0.post0'\n")
        self.write(directory / "dateutil/parser/__init__.py", b"# Date parser fixture\n")
        self.write(directory / "six.py", b"__version__ = '1.17.0'\n")
        self.write(
            directory / "dateutil/zoneinfo/dateutil-zoneinfo.tar.gz", b"\x1f\x8bzoneinfo-fixture"
        )
        for distribution, (name, version) in release.LIBRARY_DISTRIBUTIONS.items():
            self.write(
                directory / distribution / "METADATA",
                f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n".encode(),
            )
            self.write(directory / distribution / "LICENSE", f"{name} license fixture\n".encode())
        return directory

    def build(self, output="output", libraries=True):
        result = release.build(self.directory / output, self.libraries if libraries else None)
        with (
            zipfile.ZipFile(result["package"]) as package,
            zipfile.ZipFile(result["bundle"]) as bundle,
        ):
            return (
                result,
                {name: package.read(name) for name in package.namelist()},
                {name: bundle.read(name) for name in bundle.namelist()},
            )

    def assert_records_match(self, records, contents):
        self.assertEqual({record["path"] for record in records}, set(contents))
        self.assertEqual(len(records), len(contents), "Each entry must appear exactly once")
        for record in records:
            with self.subTest(path=record["path"]):
                data = contents[record["path"]]
                self.assertEqual(record["size"], len(data))
                self.assertEqual(record["sha256"], hashlib.sha256(data).hexdigest())

    def test_release_bytes_do_not_depend_on_source_timestamps_or_modes(self):
        first, _, _ = self.build("first")
        for path in self.source.rglob("*"):
            if path.is_file():
                os.utime(path, (1700000000, 1700000000))
                path.chmod(0o755)
        second, _, _ = self.build("second")
        self.assertEqual(Path(first["package"]).read_bytes(), Path(second["package"]).read_bytes())
        self.assertEqual(Path(first["bundle"]).read_bytes(), Path(second["bundle"]).read_bytes())

    def test_package_declares_the_current_runtime_and_excludes_legacy_and_development_files(self):
        for name in (
            "PlainTasks.tmLanguage",
            "plist_parser.py",
            "tests/test_dates.py",
            "tools/surprise.py",
            "validation/report.json",
            "dist/stale.zip",
            "PlainTasks (OSX).sublime-settings",
            ".git/config",
            "__pycache__/legacy.pyc",
        ):
            self.write(self.source / name, b"Unwanted fixture")
        _, package, _ = self.build()
        metadata = json.loads(package["package-metadata.json"])
        self.assertEqual(metadata["version"], release.VERSION)
        self.assertEqual(metadata["sublime_text"], ">=4215")
        self.assertEqual(package[".python-version"].strip(), b"3.14")
        self.assertIn("PlainTasks.sublime-syntax", package)
        self.assertIn("LICENSE", package)
        self.assertNotIn("PlainTasks.tmLanguage", package)
        self.assertNotIn("plist_parser.py", package)
        self.assertFalse(
            any(
                name.startswith(("tests/", "tools/", "validation/", "dist/", ".git/"))
                or "__pycache__" in name
                or name.endswith((".pyc", ".pyo"))
                for name in package
            )
        )
        self.assertNotIn("PlainTasks (OSX).sublime-settings", package)

    def test_manifests_and_detached_checksums_verify_every_delivered_byte(self):
        result, package, bundle = self.build()
        package_manifest = json.loads(bundle["PlainTasks.package-manifest.json"])
        self.assert_records_match(package_manifest["files"], package)
        package_digest = hashlib.sha256(bundle[release.PACKAGE_NAME]).hexdigest()
        self.assertEqual(package_manifest["sha256"], package_digest)
        manifest = json.loads(bundle["manifest.json"])
        self.assertEqual(manifest["version"], release.VERSION)
        self.assertEqual(manifest["target"]["sublime_build"], 4215)
        self.assertTrue(manifest["dependency_libraries_included"])
        self.assertEqual(manifest["package_sha256"], package_digest)
        self.assert_records_match(
            manifest["files"],
            {
                name: data
                for name, data in bundle.items()
                if name not in ("manifest.json", "SHA256SUMS")
            },
        )
        checksum_entries = dict(
            line.split("  ", 1)[::-1] for line in bundle["SHA256SUMS"].decode().splitlines()
        )
        self.assertEqual(set(checksum_entries), set(bundle) - {"SHA256SUMS"})
        for name, digest in checksum_entries.items():
            self.assertEqual(digest, hashlib.sha256(bundle[name]).hexdigest())
        for kind in ("package", "bundle"):
            path = Path(result[kind])
            expected = hashlib.sha256(path.read_bytes()).hexdigest()
            detached, filename = (
                path.with_name(path.name + ".sha256")
                .read_text(encoding="utf-8")
                .strip()
                .split("  ", 1)
            )
            self.assertEqual(detached, expected)
            self.assertEqual(filename, path.name)
            self.assertEqual(result[f"{kind}_sha256"], expected)

    def test_dependency_package_data_and_licenses_survive_but_caches_and_other_packages_do_not(
        self,
    ):
        for name in (
            "dateutil/__pycache__/parser.pyc",
            "dateutil/parser.pyc",
            "dateutil/.DS_Store",
            "unrelated/__init__.py",
            "pip/__init__.py",
        ):
            self.write(self.libraries / name, b"Unwanted dependency fixture")
        _, _, bundle = self.build()
        self.assertEqual(
            bundle["lib/python314/dateutil/zoneinfo/dateutil-zoneinfo.tar.gz"],
            b"\x1f\x8bzoneinfo-fixture",
        )
        for distribution in release.LIBRARY_DISTRIBUTIONS:
            self.assertIn(f"lib/python314/{distribution}/LICENSE", bundle)
        self.assertIn("lib/python314/six.py", bundle)
        self.assertFalse(
            any(
                name.endswith((".pyc", ".pyo", ".DS_Store"))
                or "__pycache__" in name
                or "/unrelated/" in name
                or "/pip/" in name
                for name in bundle
            )
        )

    def test_optional_dependency_free_bundle_is_explicit(self):
        _, _, bundle = self.build(libraries=False)
        self.assertFalse(json.loads(bundle["manifest.json"])["dependency_libraries_included"])
        self.assertFalse(any(name.startswith("lib/") for name in bundle))

    def test_missing_and_wrong_dependency_metadata_are_rejected_before_output_is_written(self):
        for index, (distribution, (name, _)) in enumerate(release.LIBRARY_DISTRIBUTIONS.items()):
            for failure in ("missing", "version", "name"):
                with self.subTest(distribution=distribution, failure=failure):
                    directory = self.make_libraries(self.directory / f"invalid-{index}-{failure}")
                    metadata = directory / distribution / "METADATA"
                    if failure == "missing":
                        metadata.unlink()
                    elif failure == "version":
                        metadata.write_text(f"Name: {name}\nVersion: 0.0.0\n", encoding="utf-8")
                    else:
                        metadata.write_text(
                            "Name: unrelated-package\nVersion: 1.17.0\n", encoding="utf-8"
                        )
                    output = self.directory / f"output-{index}-{failure}"
                    with self.assertRaises(ValueError):
                        release.build(output, directory)
                    self.assertFalse(output.exists())

    def test_each_distribution_requires_its_own_license(self):
        for index, distribution in enumerate(release.LIBRARY_DISTRIBUTIONS):
            with self.subTest(distribution=distribution):
                directory = self.make_libraries(self.directory / f"unlicensed-{index}")
                (directory / distribution / "LICENSE").unlink()
                self.write(
                    directory / "LICENSE", b"A global license cannot replace distribution licenses"
                )
                with self.assertRaisesRegex(ValueError, "Missing license"):
                    release.collect_libraries(directory)

    def test_incomplete_dependencies_are_rejected(self):
        for index, name in enumerate(("dateutil/__init__.py", "six.py")):
            with self.subTest(name=name):
                directory = self.make_libraries(self.directory / f"incomplete-{index}")
                (directory / name).unlink()
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    release.collect_libraries(directory)

    def test_non_314_host_selector_is_rejected(self):
        self.write(self.source / ".python-version", b"3.3\n")
        with self.assertRaisesRegex(ValueError, "Python 3.14"):
            release.build(self.directory / "invalid-host", self.libraries)

    def test_symlinked_source_and_dependency_files_are_rejected(self):
        for path in (self.source / "PlainTasks.py", self.libraries / "six.py"):
            with self.subTest(path=path.name):
                data = path.read_bytes()
                target = self.directory / f"{path.name}-external"
                target.write_bytes(data)
                path.unlink()
                self.symlink(path, target)
                with self.assertRaisesRegex(ValueError, "symlink"):
                    if path.parent == self.source:
                        release.build(self.directory / "source-symlink", self.libraries)
                    else:
                        release.collect_libraries(self.libraries)
                path.unlink()
                path.write_bytes(data)

    def test_symlinked_dependency_directory_is_rejected(self):
        alias = self.directory / "libraries-alias"
        self.symlink(alias, self.libraries, directory=True)
        with self.assertRaises(ValueError):
            release.collect_libraries(alias)

    def test_symlinked_output_file_and_directory_are_rejected_without_changing_the_target(self):
        target = self.directory / "external-package"
        target.write_bytes(b"Keep this file")
        output = self.directory / "symlink-output"
        output.mkdir()
        self.symlink(output / release.PACKAGE_NAME, target)
        with self.assertRaisesRegex(ValueError, "symlink"):
            release.build(output, self.libraries)
        self.assertEqual(target.read_bytes(), b"Keep this file")
        actual_directory = self.directory / "external-directory"
        actual_directory.mkdir()
        alias = self.directory / "output-alias"
        self.symlink(alias, actual_directory, directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            release.build(alias, self.libraries)
        self.assertEqual(list(actual_directory.iterdir()), [])

    def test_embedded_package_is_the_same_archive_as_the_standalone_package(self):
        result, package, bundle = self.build()
        self.assertEqual(bundle[release.PACKAGE_NAME], Path(result["package"]).read_bytes())
        with zipfile.ZipFile(io.BytesIO(bundle[release.PACKAGE_NAME])) as archive:
            self.assertEqual(set(archive.namelist()), set(package))
