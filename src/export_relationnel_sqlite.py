"""Exporte les cinq tables SQLite en CSV UTF-8 pour Bronze."""

import argparse
import csv
from pathlib import Path
import sqlite3
from contextlib import closing
from tempfile import TemporaryDirectory


TABLES = ("customers", "sites", "meters", "contracts", "tariffs")
NULL_TOKEN = "__VOLTANORD_SQL_NULL__"
DEFAULT_SOURCE = (
    Path(__file__).resolve().parents[1] / "source_relationnelle" / "voltanord.sqlite"
)


def export_csv(source: Path, destination: Path) -> dict[str, int]:
    source = source.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists():
        raise FileExistsError(f"Le dossier de destination existe déjà : {destination}")

    counts = {}
    uri = source.as_uri() + "?mode=ro&immutable=1"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Le contrôle d’intégrité SQLite a échoué.")

        with TemporaryDirectory(dir=destination.parent) as temporary:
            staging = Path(temporary) / "export"
            staging.mkdir()
            for table in TABLES:
                rows = connection.execute(f'SELECT * FROM "{table}"')
                with (staging / f"{table}.csv").open(
                    "x", encoding="utf-8", newline=""
                ) as output:
                    writer = csv.writer(output)
                    writer.writerow(column[0] for column in rows.description)
                    count = 0
                    for row in rows:
                        if NULL_TOKEN in row or any(isinstance(value, bytes) for value in row):
                            raise ValueError(f"{table} : valeur incompatible avec le format CSV.")
                        writer.writerow(NULL_TOKEN if value is None else value for value in row)
                        count += 1
                    counts[table] = count
            staging.rename(destination)
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="Nouveau dossier dans un parent existant")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    for name, count in export_csv(args.source, args.destination).items():
        print(f"{name}: {count} lignes")
