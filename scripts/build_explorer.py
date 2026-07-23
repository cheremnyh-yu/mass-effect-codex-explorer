import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
TEMPLATE = ROOT / "explorer" / "explorer_template.html"
DATA_SRC = ROOT / "data" / "processed" / "graph_data.json"
OUT = ROOT / "explorer" / "codex_explorer.html"

PLACEHOLDER = "__GRAPH_DATA_JSON__"


def main():
    data = json.loads(DATA_SRC.read_text(encoding="utf-8"))
    payload = json.dumps(data, ensure_ascii=False)

    template = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise ValueError(f"placeholder {PLACEHOLDER!r} not found in {TEMPLATE.name}")

    html = template.replace(PLACEHOLDER, payload)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({len(html):,} chars) from {DATA_SRC.name} ({len(data['nodes'])} nodes)")


if __name__ == "__main__":
    main()
