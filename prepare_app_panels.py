"""
Build the trimmed data panels the connectivity app serves, one per
dimension, and (with --upload) push them to R2 under
derived/economic_connectivity/.

Reads the coded index files from the research project; run from anywhere
inside the repo after rebuilding any index:
  python prepare_app_panels.py [--upload]
"""

import argparse
import os

import duckdb

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
CODED = os.path.abspath(os.path.join(APP_DIR, "..", "..", "data", "coded"))

EXPO = f"{CODED}/economic_exposure/bilateral_economic_exposure_master_country_pair_year_2010_2024.csv"
UN = f"{CODED}/connectivity_indices/un_alignment_index_country_pair_year_2010_2024.csv"
CULT = f"{CODED}/connectivity_indices/cultural_proximity_index_country_pair.csv"
AID = f"{CODED}/connectivity_indices/aid_dependence_index_country_pair_year_2010_2024.csv"
MIG = f"{CODED}/connectivity_indices/migration_index_country_pair_year_2010_2024_interpolated.csv"

R2_PREFIX = "derived/economic_connectivity/"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", action="store_true")
    args = ap.parse_args()
    os.makedirs(DATA_DIR, exist_ok=True)
    con = duckdb.connect()

    # name lookup from the exposure master (widest coverage)
    con.sql(f"""
        CREATE TEMP TABLE names AS
        SELECT country_i_iso3 AS iso3, any_value(country_i_name) AS name
        FROM read_csv('{EXPO}') GROUP BY 1
    """)

    jobs = {
        "app_panel.parquet": f"""
            SELECT year, country_i_iso3 AS i_iso3, country_i_name AS i_name,
                   country_j_iso3 AS j_iso3, country_j_name AS j_name,
                   goods_services_trade_share, goods_services_exposure_gdp,
                   gdp_current_usd AS gdp_i
            FROM read_csv('{EXPO}')
            WHERE country_i_iso3 <> country_j_iso3
              AND (goods_services_trade_share IS NOT NULL
                   OR goods_services_exposure_gdp IS NOT NULL)""",
        "un_alignment_panel.parquet": f"""
            SELECT year, country_i_iso3 AS i_iso3, country_i_name AS i_name,
                   country_j_iso3 AS j_iso3, country_j_name AS j_name,
                   un_alignment_index
            FROM read_csv('{UN}')""",
        "cultural_proximity_panel.parquet": f"""
            SELECT c.country_i_iso3 AS i_iso3, coalesce(ni.name, c.country_i_iso3) AS i_name,
                   c.country_j_iso3 AS j_iso3, coalesce(nj.name, c.country_j_iso3) AS j_name,
                   c.cultural_proximity_index
            FROM read_csv('{CULT}') c
            LEFT JOIN names ni ON ni.iso3 = c.country_i_iso3
            LEFT JOIN names nj ON nj.iso3 = c.country_j_iso3""",
        "aid_dependence_panel.parquet": f"""
            SELECT a.year, a.country_i_iso3 AS i_iso3,
                   coalesce(ni.name, a.country_i_iso3) AS i_name,
                   a.country_j_iso3 AS j_iso3,
                   coalesce(nj.name, a.country_j_iso3) AS j_name,
                   a.aid_dependence_index, a.gross_oda_usd
            FROM read_csv('{AID}') a
            LEFT JOIN names ni ON ni.iso3 = a.country_i_iso3
            LEFT JOIN names nj ON nj.iso3 = a.country_j_iso3
            WHERE a.aid_dependence_index IS NOT NULL""",
        "migration_panel.parquet": f"""
            SELECT year, country_i_iso3 AS i_iso3, country_i_name AS i_name,
                   country_j_iso3 AS j_iso3, country_j_name AS j_name,
                   migrant_stock_share, migrant_stock
            FROM read_csv('{MIG}')
            WHERE migrant_stock_share IS NOT NULL""",
    }
    for fname, sql in jobs.items():
        out = os.path.join(DATA_DIR, fname)
        con.sql(f"COPY ({sql}) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")
        n = con.sql(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
        print(f"{fname}: {n:,} rows, {os.path.getsize(out)/1e6:.1f} MB")

    if args.upload:
        import boto3
        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto")
        for fname in jobs:
            s3.upload_file(os.path.join(DATA_DIR, fname),
                           os.environ["R2_BUCKET"], R2_PREFIX + fname)
            print(f"uploaded {R2_PREFIX}{fname}")


if __name__ == "__main__":
    main()
