import json
import sys
from argparse import ArgumentParser
from typing import Any, Never

from app.modules.catalog.admin import delete_product, read_product, save_product
from scripts._catalog_cli import run_catalog_command


def main() -> None:
    parser = ArgumentParser(description="Управлять товаром по его артикулу.")
    parser.add_argument("action", choices=("show", "create", "update", "delete"))
    parser.add_argument("sku", help="Артикул товара.")
    args = parser.parse_args()
    if not args.sku or len(args.sku) > 64 or args.sku != args.sku.strip():
        parser.error("Укажите артикул длиной до 64 символов без пробелов по краям.")

    if args.action == "show":
        result = run_catalog_command(parser, lambda session: read_product(session, args.sku))
    elif args.action == "delete":
        run_catalog_command(parser, lambda session: delete_product(session, args.sku))
        print(f"Товар {args.sku} удалён.")
        return
    else:
        payload = _read_payload(parser)
        result = run_catalog_command(
            parser,
            lambda session: save_product(
                session, args.sku, payload, update_existing=args.action == "update"
            ),
        )
    print(json.dumps(result, default=str, ensure_ascii=False, indent=2))


def _read_payload(parser: ArgumentParser) -> dict[str, Any]:
    try:
        payload = json.load(sys.stdin, parse_constant=_reject_non_finite)
    except ValueError as error:
        parser.error(f"Не удалось прочитать JSON из stdin. {error}")
    if not isinstance(payload, dict):
        parser.error("Передайте JSON-объект через stdin.")
    return payload


def _reject_non_finite(value: str) -> Never:
    raise ValueError(f"Значение {value} недопустимо в JSON.")


if __name__ == "__main__":
    main()
