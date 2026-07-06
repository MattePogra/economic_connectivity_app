#!/usr/bin/env python
"""
Economic Connectivity Map.

Interactive world map of bilateral economic exposure. Pick a year, click a
country (or pick it from the sidebar): the target turns red and every other
country is shaded by how economically important the target is for it
(goods + services trade with target / own GDP).

Data: analysis/data/coded/economic_exposure/
      bilateral_economic_exposure_master_country_pair_year_2010_2024.csv
      (annual descriptive file; country_i = exposed, country_j = target)

Run:
  streamlit run economic_connectivity_app.py
"""

import os

import duckdb
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_CSV = os.path.abspath(os.path.join(
    APP_DIR, "..", "..", "data", "coded", "economic_exposure",
    "bilateral_economic_exposure_master_country_pair_year_2010_2024.csv"))

# display label -> (column in master file, unit text for captions/hover)
METRICS = {
    "Share of own total trade": ("goods_services_trade_share", "of its total trade"),
    "Share of own GDP": ("goods_services_exposure_gdp", "of its GDP"),
}

# Palette matched to the GDELT Election Media Atlas (gdelt_country_map/app.R)
AMBER = "#F59E0B"
YELLOW = "#FACC15"
RED = "#EF4444"

st.set_page_config(page_title="Economic Connectivity", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
  .stApp {
    background: radial-gradient(circle at 20% 10%, #23252a 0%, #131418 42%, #0a0b0d 100%);
    color: #E5E7EB;
    font-family: 'IBM Plex Sans', sans-serif;
  }
  header[data-testid="stHeader"] { background: transparent; }
  section[data-testid="stSidebar"] {
    background-color: rgba(39, 43, 53, 0.88);
    border-right: 1px solid rgba(148, 163, 184, 0.22);
  }
  h1, h2, h3 {
    color: #FFF7ED;
    font-family: 'Space Grotesk', sans-serif;
    letter-spacing: -0.03em;
  }
  .stCaption, p, label { color: #A8B3C7 !important; }
  section[data-testid="stSidebar"] label { color: #FACC15 !important; font-weight: 600; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def load_geojson():
    import json
    path = os.path.join(APP_DIR, "data", "ne_50m_admin_0_countries.geojson")
    gj = json.load(open(path))
    for f in gj["features"]:
        iso = f["properties"].get("ISO_A3")
        if not iso or iso == "-99":
            iso = f["properties"].get("ADM0_A3")
        f["id"] = iso
    return gj


APP_PANEL_PARQUET = os.path.join(APP_DIR, "data", "app_panel.parquet")
R2_PANEL_KEY = "derived/economic_connectivity/app_panel.parquet"


@st.cache_data(show_spinner="Loading bilateral exposure panel ...")
def load_data():
    # (i_iso3, j_iso3, year) is unique since the Sudan BACI-code collapse
    # in 260704_build_bilateral_economic_exposure.py.
    # Three sources, in order: trimmed parquet next to the app (local runs),
    # the coded master CSV (local dev fallback), R2 via st.secrets (deployed).
    if os.path.exists(APP_PANEL_PARQUET):
        return duckdb.sql(
            f"SELECT * FROM read_parquet('{APP_PANEL_PARQUET}')").df()
    if os.path.exists(DATA_CSV):
        return duckdb.sql(f"""
            SELECT year,
                   country_i_iso3 AS i_iso3, country_i_name AS i_name,
                   country_j_iso3 AS j_iso3, country_j_name AS j_name,
                   goods_services_trade_share, goods_services_exposure_gdp,
                   gdp_current_usd AS gdp_i
            FROM read_csv('{DATA_CSV}')
            WHERE country_i_iso3 <> country_j_iso3
              AND (goods_services_trade_share IS NOT NULL
                   OR goods_services_exposure_gdp IS NOT NULL)
        """).df()
    import boto3
    r2 = st.secrets["r2"]
    client = boto3.client(
        "s3",
        endpoint_url=f"https://{r2['account_id']}.r2.cloudflarestorage.com",
        aws_access_key_id=r2["access_key_id"],
        aws_secret_access_key=r2["secret_access_key"],
        region_name="auto",
    )
    local = "/tmp/app_panel.parquet"
    client.download_file(r2["bucket"], R2_PANEL_KEY, local)
    return duckdb.sql(f"SELECT * FROM read_parquet('{local}')").df()


df = load_data()
years = sorted(df.year.unique(), reverse=True)
targets = (df[["j_iso3", "j_name"]].drop_duplicates()
           .sort_values("j_name").reset_index(drop=True))

# ── sidebar controls ─────────────────────────────────────────────────────────
st.sidebar.title("⚙ Controls")
year = st.sidebar.selectbox("Year", years, index=0)
metric_label = st.sidebar.radio(
    "Metric", list(METRICS), index=0,
    help="Share of own total trade = how salient the target is among this "
         "country's trade partners (bounded 0-100%). Share of own GDP = how "
         "dependent the whole economy is on trade with the target; large "
         "closed economies score low on everyone by construction.")
metric_col, metric_unit = METRICS[metric_label]
scale_label = st.sidebar.radio(
    "Map colors", ["Absolute (comparable across targets)",
                   "Relative to this target (rank)"], index=0,
    help="Absolute: fixed logarithmic scale, identical for every target and "
         "year, so a map for Uganda is visibly darker than one for the USA. "
         "Relative: colors spread by rank within the selected target, best "
         "for seeing who is most tied to it regardless of level.")
absolute_scale = scale_label.startswith("Absolute")
if "target" not in st.session_state:
    st.session_state.target = "USA"
target_name_by_iso = dict(zip(targets.j_iso3, targets.j_name))
pick = st.sidebar.selectbox(
    "Target country (or click the map)", targets.j_iso3.tolist(),
    index=targets.j_iso3.tolist().index(st.session_state.target)
    if st.session_state.target in set(targets.j_iso3) else 0,
    format_func=lambda c: f"{target_name_by_iso.get(c, c)} ({c})")
if pick != st.session_state.target:
    st.session_state.target = pick

hide_small = st.sidebar.checkbox(
    "Hide small economies (GDP < $25B) from ranking", value=True,
    help="Offshore financial centers (Barbados, Bermuda, Seychelles...) show "
         "inflated services-trade exposure and would dominate the top-10 "
         "table. Affects only the ranking below the map; the map always "
         "shows every country with data.")

st.sidebar.caption(
    "Numerator: goods + services trade with the target. "
    "Sources: BACI (goods), OECD-WTO BaTIS (services), World Bank WDI (GDP).")

target = st.session_state.target
tname = target_name_by_iso.get(target, target)

st.title("Economic Connectivity")
st.caption(f"**{tname}** in red. Every other country glows by how much "
           f"of its trade ties it to {tname} in **{year}** "
           f"({metric_label.lower()}): bright amber = strongest ties, "
           "dark = weakest. Hover for exact numbers, click a country to "
           "make it the target.")

# ── data slice (map shows every country with data; the GDP filter only
#    applies to the top-10 table) ─────────────────────────────────────────────
sl = df[(df.year == year) & (df.j_iso3 == target)].copy()
sl["pct"] = sl[metric_col] * 100
sl = sl[sl.pct > 0]
sl["rank"] = sl.pct.rank(ascending=False).astype(int)
sl["pctile"] = sl.pct.rank(pct=True)  # 0..1, spreads colors evenly

# color values: fixed log10 scale (absolute) or within-target percentile
if absolute_scale:
    # bounds in log10(percent), deliberately tighter than the data:
    # ties below 0.03% clamp to the floor (negligible) and GDP exposure
    # above 100% (offshore centers, 105 rows) clamps to the top, which
    # spends the gradient where differences are meaningful
    z_lo, z_hi = -1.5, 2.0
    sl["z"] = np.clip(np.log10(sl.pct), z_lo, z_hi)
    cbar_tickvals = [-1.5, -1.0, 0.0, 1.0, 2.0]
    cbar_ticktext = ["≤0.03%", "0.1%", "1%", "10%", "100%"]
    if metric_col == "goods_services_exposure_gdp":
        cbar_ticktext[-1] = "≥100%"
    cbar_title = f"trade with target<br>(% {metric_unit}, log scale)"
else:
    z_lo, z_hi = 0.0, 1.0
    sl["z"] = sl.pctile
    cbar_tickvals = [0.02, 0.5, 0.98]
    cbar_ticktext = ["least tied", "median", "most tied"]
    cbar_title = "how tied to target<br>(rank among countries)"

# ── map: dark web-map tiles (same style as the OECD country app) with
#    gradient by exposure RANK (spreads the colors evenly) ──────────────────
gj = load_geojson()
fig = go.Figure()

fig.add_trace(go.Choroplethmap(
    geojson=gj, locations=sl.i_iso3, z=sl.z,
    customdata=np.stack([sl.i_iso3, sl.i_name, sl.pct.round(3),
                         sl["rank"]], axis=-1),
    zmin=z_lo, zmax=z_hi,
    colorscale=[[0.0, "#0D1119"], [0.15, "#3E4756"], [0.35, "#7A5A16"],
                [0.55, "#D97706"], [0.75, YELLOW], [1.0, "#FFFBEB"]],
    marker_opacity=0.78, marker_line_color="#C7CDD6", marker_line_width=0.5,
    colorbar=dict(
        title=dict(text=cbar_title, font=dict(color="#A8B3C7", size=12)),
        tickvals=cbar_tickvals,
        ticktext=cbar_ticktext,
        tickfont=dict(color="#A8B3C7"), outlinewidth=0, len=0.6,
        x=1.02, xanchor="left", xpad=0),
    hovertemplate=("<b>%{customdata[1]}</b><br>"
                   "trade with " + tname + ": %{customdata[2]}% " + metric_unit +
                   "<br>rank: #%{customdata[3]}<br>"
                   "<i>click to make this the target</i><extra></extra>"),
))

fig.add_trace(go.Choroplethmap(
    geojson=gj, locations=[target], z=[1], showscale=False,
    colorscale=[[0, RED], [1, RED]],
    marker_opacity=0.9, marker_line_color="#ffffff", marker_line_width=1.5,
    hovertemplate=f"<b>{tname}</b> — TARGET<extra></extra>",
))

fig.update_layout(
    map=dict(style="carto-darkmatter-nolabels",
             center=dict(lat=28, lon=10), zoom=1.1),
    height=620, margin=dict(l=0, r=130, t=10, b=0),
    paper_bgcolor="rgba(0,0,0,0)",
)

event = st.plotly_chart(fig, use_container_width=True,
                        on_select="rerun", selection_mode="points",
                        key="worldmap")

# click on the map -> new target
if event and event.selection and event.selection.points:
    pt = event.selection.points[0]
    clicked = None
    if isinstance(pt, dict):
        cd = pt.get("customdata")
        clicked = (cd[0] if cd else None) or pt.get("location")
    if clicked and clicked != target and clicked in set(targets.j_iso3):
        st.session_state.target = clicked
        st.rerun()

# ── top-10 table ─────────────────────────────────────────────────────────────
st.subheader(f"Most tied to {tname} ({year})")
ranked = (sl[sl.gdp_i >= 25e9] if hide_small else sl).copy()
ranked["rank"] = ranked.pct.rank(ascending=False).astype(int)
top = (ranked.nlargest(10, "pct")[["rank", "i_name", "i_iso3", "pct"]]
       .rename(columns={"i_name": "country", "i_iso3": "iso3",
                        "pct": f"trade with target (% {metric_unit})"}))
st.dataframe(top.round(3), hide_index=True, use_container_width=True)
if hide_small:
    st.caption("Ranked among economies with GDP ≥ $25B. The map (and its "
               "hover rank) still includes the smaller economies.")

with st.expander("How this is computed"):
    st.markdown(f"""
For each country *i* and the selected target *j*, in the selected year:

- **Numerator** (both metrics): goods exports + goods imports between *i* and *j*
  (CEPII BACI, HS92) **plus** services exports + imports (OECD-WTO BaTIS,
  balanced values). Where BaTIS does not cover the pair, the combined
  measure is missing and the country is not shown.
- **Share of own total trade** = that numerator / country *i*'s total
  goods + services trade with the whole world, same year.
- **Share of own GDP** = that numerator / country *i*'s GDP in current USD
  (World Bank WDI), same year.
""")
