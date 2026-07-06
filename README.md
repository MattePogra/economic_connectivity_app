# Economic Connectivity Map

Interactive world map of bilateral economic exposure. Pick a year and a
target country: the target turns red and every other country is shaded by
how economically tied it is to the target, under one of two metrics:

- **Share of own total trade**: goods + services trade with the target /
  the country's total goods + services trade.
- **Share of own GDP**: goods + services trade with the target / the
  country's GDP (current USD).

Sources: CEPII BACI (goods trade, HS92), OECD-WTO BaTIS (services trade,
balanced values), World Bank WDI (GDP). Coverage 2010-2024, ~230 countries.

## Data

The app loads a trimmed parquet panel (one row per country-pair-year). It
looks for it in this order:

1. `data/app_panel.parquet` (local runs; not committed)
2. the coded master CSV in the research project (local dev fallback)
3. Cloudflare R2 via `st.secrets["r2"]` (deployed app)

Secrets format for deployment (Streamlit Cloud -> App settings -> Secrets):

```toml
[r2]
account_id = "..."
access_key_id = "..."        # read-only token
secret_access_key = "..."
bucket = "gdelt-v2"
```

## Run locally

```
streamlit run economic_connectivity_app.py
```
