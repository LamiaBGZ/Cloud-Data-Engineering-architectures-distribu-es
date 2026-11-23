# Databricks notebook source
# MAGIC %md
# MAGIC # Ingestion relationnelle Bronze
# MAGIC Charge les cinq exports CSV du snapshot SQLite depuis un volume Unity Catalog.

# COMMAND ----------

import csv
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from pyspark.sql import functions as F
from pyspark.sql.types import DateType, StringType, StructField, StructType, TimestampType


dbutils.widgets.text("target_catalog", "", "Catalogue cible")
dbutils.widgets.text("source_directory", "", "Dossier source /Volumes/…")

catalog = dbutils.widgets.get("target_catalog").strip()
source_directory = dbutils.widgets.get("source_directory").strip().rstrip("/")
if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]*", catalog):
    raise ValueError("Renseigner target_catalog avec le nom d’un catalogue Unity Catalog.")
path_parts = source_directory.split("/")
if (
    path_parts[:2] != ["", "Volumes"]
    or len(path_parts) < 5
    or any(part in {"", ".", ".."} for part in path_parts[2:])
):
    raise ValueError("Renseigner source_directory avec un chemin absolu /Volumes/catalogue/schema/volume.")

target_schema = f"`{catalog}`.`bronze`"
NULL_TOKEN = "__VOLTANORD_SQL_NULL__"
APRIL_SNAPSHOT = date(2026, 4, 30)
JANUARY_SNAPSHOT = date(2026, 1, 1)

# La première colonne de chaque export est sa clé primaire.
TABLES = {
    "customers": (
        APRIL_SNAPSHOT,
        456,
        "customer_id customer_type first_name last_name company_name email phone "
        "birth_date iban created_at updated_at status",
    ),
    "sites": (
        APRIL_SNAPSHOT,
        502,
        "site_id customer_id address postal_code city region_label housing_type surface_m2 heating_type",
    ),
    "meters": (
        APRIL_SNAPSHOT,
        512,
        "meter_id site_id model firmware_version install_date removal_date status",
    ),
    "contracts": (
        JANUARY_SNAPSHOT,
        443,
        "contract_id customer_id site_id tariff_option subscribed_kva start_date end_date status",
    ),
    "tariffs": (
        APRIL_SNAPSHOT,
        6,
        "tariff_code tariff_option label price_base price_hp price_hc price_kva_month valid_from valid_to",
    ),
}

# COMMAND ----------


def read_snapshot(path, columns, expected_count):
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.reader(source, strict=True)
        if next(reader, None) != columns:
            raise ValueError(f"{path.name} : en-tête différent du schéma attendu.")
        rows = []
        for record_number, record in enumerate(reader, start=2):
            if len(record) != len(columns):
                raise ValueError(f"{path.name} : nombre de colonnes invalide à l’enregistrement {record_number}.")
            rows.append(tuple(None if value == NULL_TOKEN else value for value in record))

    if len(rows) != expected_count:
        raise ValueError(f"{path.name} : {len(rows)} lignes lues, {expected_count} attendues.")

    keys = Counter(row[0] for row in rows)
    missing = keys.pop(None, 0) + keys.pop("", 0)
    duplicate_rows = sum(count - 1 for count in keys.values())
    print(f"{path.name} : {len(rows)} lignes, {missing} clés absentes, {duplicate_rows} doublons de clé.")
    return rows


def snapshot_content(table, snapshot_date, schema):
    stored = spark.table(table)
    if [(field.name, field.dataType) for field in stored.schema] != [
        (field.name, field.dataType) for field in schema
    ]:
        raise ValueError(f"{table} : schéma Delta différent du schéma attendu.")

    rows = stored.where(F.col("snapshot_date") == F.lit(snapshot_date)).collect()
    if any(row["ingestion_timestamp"] is None for row in rows):
        raise ValueError(f"{table} : horodatage d’ingestion manquant.")
    return Counter(
        tuple(row[name] for name in schema.fieldNames() if name != "ingestion_timestamp")
        for row in rows
    )


# Valider tous les CSV avant la première écriture.
ingested_at = datetime.now(timezone.utc)
snapshots = {}
for name, (snapshot_date, expected_count, column_names) in TABLES.items():
    columns = column_names.split()
    path = Path(source_directory) / f"{name}.csv"
    rows = read_snapshot(path, columns, expected_count)
    schema = StructType(
        [StructField(column, StringType()) for column in columns]
        + [
            StructField("source_file", StringType()),
            StructField("ingestion_timestamp", TimestampType()),
            StructField("snapshot_date", DateType()),
        ]
    )
    expected = Counter(row + (str(path), snapshot_date) for row in rows)
    payload = [row + (str(path), ingested_at, snapshot_date) for row in rows]
    snapshots[name] = (snapshot_date, schema, expected, payload)

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {target_schema}")

# Contrôler toutes les cibles existantes avant de charger une table.
pending = []
for name, (snapshot_date, schema, expected, payload) in snapshots.items():
    table = f"{target_schema}.`{name}`"
    if spark.catalog.tableExists(table):
        details = spark.sql(f"DESCRIBE DETAIL {table}").select("format").first()
        if details["format"] != "delta":
            raise ValueError(f"{table} : la cible doit être une table Delta.")
        current = snapshot_content(table, snapshot_date, schema)
        if current:
            if current != expected:
                raise ValueError(f"{table} : le snapshot {snapshot_date} existe avec un contenu différent.")
            print(f"{table} : rejeu vérifié, {sum(current.values())} lignes déjà présentes.")
            continue
        pending.append((name, True))
    else:
        pending.append((name, False))

for name, exists in pending:
    snapshot_date, schema, expected, payload = snapshots[name]
    table = f"{target_schema}.`{name}`"
    writer = spark.createDataFrame(payload, schema).write.format("delta")
    if exists:
        writer = writer.mode("overwrite").option("replaceWhere", f"snapshot_date = DATE '{snapshot_date}'")
    else:
        writer = writer.mode("errorifexists")
    writer.saveAsTable(table)

    if snapshot_content(table, snapshot_date, schema) != expected:
        raise RuntimeError(f"{table} : le contenu Delta diffère de l’export chargé.")
    print(f"{table} : {sum(expected.values())} lignes validées pour le {snapshot_date}.")
