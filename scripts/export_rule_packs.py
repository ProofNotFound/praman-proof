"""Write every rule pack to frontend/public/demo/rule_packs.json, so the Rule packs screen works
without the API (recording mode). The API serves the same list at /api/rule-packs.

Usage: uv run scripts/export_rule_packs.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from praman.config import ROOT  # noqa: E402
from praman.rules import list_packs  # noqa: E402

OUT = ROOT / "frontend" / "public" / "demo" / "rule_packs.json"


def main() -> int:
    packs = list_packs()
    OUT.write_text(json.dumps(packs, ensure_ascii=False, indent=1) + "\n")
    print(
        f"{OUT.relative_to(ROOT)}: "
        + ", ".join(f"{p['name']} ({len(p['rules'])} rules)" for p in packs)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
