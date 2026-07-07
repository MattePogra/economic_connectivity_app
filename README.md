# Country Connectivity Map

Interactive world map of bilateral country ties, one dimension at a time
(a suite of separate indices, deliberately never blended into a composite).
Pick a dimension, a year, and a target country: the target turns red and
every other country is shaded by how tied it is to the target.

- **Economic (trade)**: goods + services trade with the target as a share
  of own total trade, or of own GDP (CEPII BACI, OECD-WTO BaTIS, WDI).
- **UN voting alignment**: 1 − normalized ideal-point distance from UNGA
  roll-call votes (Bailey/Strezhnev/Voeten), 0–1, symmetric.
- **Cultural-historical proximity**: mean of four grouped binary ties —
  border, language, colonial links, shared past (CEPII GeoDist), 0–1, static.
- **Migration (migrant stock)**: migrants born in the target and living in
  the shaded country / shaded country's population (UN DESA, WDI).
- **Facebook social connectedness**: Meta/Facebook friendship connectedness
  between the shaded country and target country (Meta AI for Good / HDX SCI).
- **Aid dependence**: gross ODA received from the target / own GNI
  (OECD DAC2A, WDI), directed and sparse.

Coverage 2010-2024 where yearly data exist; cultural and Facebook SCI are
time-invariant snapshots; ~175-230 countries per dimension.

## Data

The app loads one trimmed parquet panel per dimension, built by
`prepare_app_panels.py` from the research project's coded index files.
Each panel is looked up in this order:

1. `data/<panel>.parquet` (local runs; not committed)
2. Cloudflare R2 `derived/economic_connectivity/<panel>.parquet` via
   `st.secrets["r2"]` (deployed app)

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
