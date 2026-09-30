"""Offline regression checks for repeated searches and combined exports."""
import argparse
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import facebook_group_scanner as scanner


class MenuTests(unittest.TestCase):
    def test_repeated_searches_export_unique_groups_and_reload(self):
        first = {"group_name": "Gardeners", "url": "https://www.facebook.com/groups/123/"}
        duplicate = {"group_name": "Gardeners", "url": "https://www.facebook.com/groups/123/?ref=search"}
        second = {"group_name": "Café club", "url": "https://www.facebook.com/groups/456/"}
        args = argparse.Namespace(max_results=None, skip_login_wait=False)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(scanner, "EXPORT_DIR", Path(directory)), patch(
                "builtins.input", side_effect=["1", "gardening", "10", "1", "coffee", "20", "2", "3"]
            ), patch.object(scanner, "scan_facebook", side_effect=[[first], [duplicate, second]]) as scan:
                self.assertEqual(scanner.interactive_menu(args), 0)
                self.assertEqual([call.args[:2] for call in scan.call_args_list], [("gardening", 10), ("coffee", 20)])
                outputs = list(Path(directory).glob("facebook_groups_all_searches_*.csv"))
                self.assertEqual(len(outputs), 1)
                self.assertTrue(outputs[0].read_bytes().startswith(b"\xef\xbb\xbf"))
                with outputs[0].open(encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle)
                    self.assertEqual(reader.fieldnames, ["group_name", "url"])
                    self.assertEqual(list(reader), [first, second])
                self.assertEqual(len(scanner.load_saved_groups()), 2)

    def test_failed_search_keeps_previous_results_exportable(self):
        row = {"group_name": "Group", "url": "https://www.facebook.com/groups/123/"}
        args = argparse.Namespace(max_results=10, skip_login_wait=False)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(scanner, "EXPORT_DIR", Path(directory)), patch(
                "builtins.input", side_effect=["2", "1", "first", "1", "failure", "2", "3"]
            ), patch.object(scanner, "scan_facebook", side_effect=[[row], scanner.FacebookScannerError("blocked")]):
                self.assertEqual(scanner.interactive_menu(args), 0)
                self.assertEqual(list(scanner.load_saved_groups().values()), [row])
                self.assertEqual(len(list(Path(directory).glob("facebook_groups_all_searches_*.csv"))), 1)


if __name__ == "__main__":
    unittest.main()
