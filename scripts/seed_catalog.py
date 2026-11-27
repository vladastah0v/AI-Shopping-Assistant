from argparse import ArgumentParser

from app.modules.catalog.seeding import seed_catalog
from app.modules.catalog.synthetic import DEFAULT_SEED, MAX_SEED, PROFILE_SIZES
from scripts._catalog_cli import run_catalog_command


def main() -> None:
    parser = ArgumentParser(description="Заполнить каталог синтетическими товарами.")
    parser.add_argument("--profile", choices=PROFILE_SIZES, default="small", help="Размер набора.")
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED, help="Начальное число генератора."
    )
    args = parser.parse_args()
    if not 0 <= args.seed <= MAX_SEED:
        parser.error(f"Seed должен быть целым числом от 0 до {MAX_SEED}.")

    result = run_catalog_command(
        parser, lambda session: seed_catalog(session, args.profile, args.seed)
    )
    print(
        f"Профиль {args.profile}, seed {args.seed}. Новые записи — категории {result.categories}, "
        f"бренды {result.brands}, товары {result.products}, документы {result.documents}."
    )


if __name__ == "__main__":
    main()
