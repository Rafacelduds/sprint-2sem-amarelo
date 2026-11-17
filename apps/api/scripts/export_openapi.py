import json
from pathlib import Path

from api.main import app


def main() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    output = repository_root / "openapi.json"
    output.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
    print(f"OpenAPI exportado para {output}")


if __name__ == "__main__":
    main()
