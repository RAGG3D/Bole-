from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DENYLIST = ROOT / ".pii_denylist.txt"


class PiiSentinelTests(unittest.TestCase):
    def test_tracked_files_do_not_contain_local_denylist_terms(self) -> None:
        if not DENYLIST.is_file():
            self.skipTest(".pii_denylist.txt 仅存在于维护者本地")

        terms = [
            line.strip()
            for line in DENYLIST.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
        )
        paths = [
            ROOT / raw.decode("utf-8", errors="surrogateescape")
            for raw in result.stdout.split(b"\0")
            if raw
        ]
        hits: list[str] = []
        for path in paths:
            if not path.is_file():
                continue
            text = path.read_bytes().decode("utf-8", errors="ignore").casefold()
            for term in terms:
                if term.casefold() in text:
                    hits.append(f"{path.relative_to(ROOT)}: {term}")

        self.assertFalse(
            hits,
            "PII 哨兵命中 git tracked 文件：\n" + "\n".join(hits),
        )


if __name__ == "__main__":
    unittest.main()
