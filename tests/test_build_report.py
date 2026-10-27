from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.build_report import build_report, literal, read_json, write_json

# Byte fingerprints from the original JavaScript generator.
VISUAL_HASHES = {
    "category_filter": "e75cf7db8574145bd82abb6ab057a165fa9ac51fee478ce6f8a1d7ce46e988ab",
    "page_title": "075fa58ca33c1c08fde023a008934d0f0680300f7663cc565caa2e14b0789f6e",
    "product_detail": "28b74509f976c2d4f4ba4e30c24d3e795cb21ee54c03602d6c4d7acada9c5d94",
    "product_ranking": "e39073f6c9172bc56d91f3ab2d038377c9244a0013ece8697e59c2e9012d952c",
    "total_quantity": "21342e7757fec9a025c73657caf9c54d43bc030ad519a42c21449ecd11172f8c",
    "total_sales": "8ff3544de1db92374168f817279fd5f26bc6de57fc906068a6a80e68b46e1c05",
}


class ReportBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.report = Path(temporary.name) / "Sample.Report"
        self.pages = self.report / "definition" / "pages"
        self.page_dir = self.pages / "sample-page"
        self.page_path = self.page_dir / "page.json"
        self.page = {
            "name": "sample-page", "displayName": "Sales", "width": 800, "height": 600,
        }
        write_json(self.pages / "pages.json", {
            "pageOrder": ["sample-page"], "activePageName": "sample-page",
        })
        write_json(self.page_path, self.page)

    def snapshot(self):
        return {
            path.relative_to(self.report): path.read_bytes()
            for path in self.report.rglob("*") if path.is_file()
        }

    def test_six_visuals_match_original_generator_byte_for_byte(self):
        self.assertEqual(build_report(self.report), self.page_dir)
        visual_files = list(self.page_dir.glob("visuals/*/visual.json"))
        self.assertEqual({path.parent.name for path in visual_files}, set(VISUAL_HASHES))
        for path in visual_files:
            with self.subTest(visual=path.parent.name):
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    VISUAL_HASHES[path.parent.name],
                )
        self.assertEqual(
            self.page_path.read_bytes(),
            (json.dumps({**self.page, "width": 1920, "height": 1080}, indent=2) + "\n")
            .encode("utf-8"),
        )

    def test_repeated_builds_are_identical(self):
        build_report(self.report)
        original = self.snapshot()
        build_report(self.report)
        self.assertEqual(self.snapshot(), original)

    def test_module_command_works_without_site_packages(self):
        root = self.report.parent / "cli"
        report = root / "solution" / "reporting" / "Sales.Report"
        shutil.copytree(self.report, report)
        scripts = root / "scripts"
        scripts.mkdir()
        source = Path(__file__).resolve().parent.parent / "scripts"
        for name in ("__init__.py", "build_report.py"):
            shutil.copyfile(source / name, scripts / name)
        result = subprocess.run(
            [sys.executable, "-E", "-S", "-m", "scripts.build_report"],
            cwd=root, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Generated six visuals", result.stdout)
        visual_files = list(report.glob("definition/pages/*/visuals/*/visual.json"))
        self.assertEqual({path.parent.name for path in visual_files}, set(VISUAL_HASHES))
        for path in visual_files:
            with self.subTest(visual=path.parent.name):
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                    VISUAL_HASHES[path.parent.name],
                )

    def test_shell_other_pages_and_unmanaged_visuals_are_preserved(self):
        for relative in (
            Path(".platform"),
            Path("definition.pbir"),
            Path("definition") / "report.json",
            Path("definition") / "pages" / "other-page" / "page.json",
            Path("definition") / "pages" / "sample-page" / "visuals" / "custom" / "visual.json",
        ):
            write_json(self.report / relative, {"custom": "keep unchanged"})
        original = self.snapshot()
        original.pop(self.page_path.relative_to(self.report))
        build_report(self.report)
        for relative, expected in original.items():
            with self.subTest(file=relative):
                self.assertEqual((self.report / relative).read_bytes(), expected)

    def test_dimensions_change_without_losing_page_metadata(self):
        self.page["displayName"] = "Custom sales overview"
        self.page["objects"] = {"custom": [{"properties": {"preserved": True}}]}
        write_json(self.page_path, self.page)
        build_report(self.report)
        self.assertEqual(
            read_json(self.page_path), {**self.page, "width": 1920, "height": 1080}
        )

    def test_missing_or_invalid_shell_fails_explicitly(self):
        metadata = self.pages / "pages.json"
        metadata.unlink()
        with self.assertRaises(FileNotFoundError):
            build_report(self.report)
        metadata.write_text("invalid json", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            build_report(self.report)

    def test_literal_encodings(self):
        for value, expected in (
            (True, "true"), (False, "false"), (0, "0D"), (16, "16D"), (1.5, "1.5D"),
            ("Product's sales", "'Product''s sales'"),
        ):
            with self.subTest(value=value):
                self.assertEqual(literal(value), {"expr": {"Literal": {"Value": expected}}})


if __name__ == "__main__":
    unittest.main()
