from __future__ import annotations

from app.services.graph_service import seed_minimal_kg


def main() -> None:
    result = seed_minimal_kg()
    print(result)


if __name__ == "__main__":
    main()
