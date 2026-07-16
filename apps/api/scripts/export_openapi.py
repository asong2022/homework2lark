from __future__ import annotations

import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT / "src"))

from mistake_notebook_api.main import create_app  # noqa: E402


def main() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    output = repository_root / "packages" / "contracts" / "openapi.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True)
    output.write_text(f"{payload}\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
