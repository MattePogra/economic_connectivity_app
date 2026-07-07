#!/usr/bin/env python
"""
Country Connectivity Map.

Interactive world map of bilateral country ties, one dimension at a time
(separate indices, never a composite): economic exposure (trade), UN voting
alignment, cultural-historical proximity, and aid dependence. Pick a
dimension, a year, and a target country: the target turns red and every
other country is shaded by how tied it is to the target on that dimension.

Data: trimmed parquet panels built by prepare_app_panels.py from the coded
index files (country_i = the shaded country, country_j = the target).

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
R2_PREFIX = "derived/economic_connectivity/"

# Economic sub-metrics (column, unit words)
ECON_METRICS = {
    "Share of own total trade": ("goods_services_trade_share", "of its total trade"),
    "Share of own GDP": ("goods_services_exposure_gdp", "of its GDP"),
}

# One entry per connectivity dimension (separate indices, no composite).
# scale: "log" = fixed log10 gradient over percent values;
#        "linear01" = fixed linear gradient over a bounded 0-1 index.
DIMENSIONS = {
    "Economic (trade)": dict(
        file="app_panel.parquet", yearly=True,
        scale="log", log_ticks=[-1.5, -1.0, 0.0, 1.0, 1.5],
        log_labels=["≤0.03%", "0.1%", "1%", "10%", "≥30%"],
        tie_phrase="trade ties", value_word="trade with",
        sources="CEPII BACI (goods), OECD-WTO BaTIS (services), "
                "World Bank WDI (GDP)",
        how="- **Numerator** (both metrics): goods exports + imports between "
            "*i* and the target (CEPII BACI) plus services exports + imports "
            "(OECD-WTO BaTIS). Pairs without BaTIS coverage are not shown.\n"
            "- **Share of own total trade** = numerator / *i*'s total "
            "goods+services trade with the world, same year.\n"
            "- **Share of own GDP** = numerator / *i*'s GDP in current USD "
            "(World Bank WDI), same year."),
    "UN voting alignment": dict(
        file="un_alignment_panel.parquet", col="un_alignment_index",
        yearly=True, scale="linear01",
        tie_phrase="UN voting alignment", value_word="alignment with",
        unit="(0–1)",
        sources="Bailey/Strezhnev/Voeten UNGA ideal points (Harvard Dataverse)",
        how="- Each country-year has an estimated **ideal point** from UN "
            "General Assembly roll-call votes (Bailey, Strezhnev & Voeten "
            "2017).\n- The index is 1 − |ideal point difference| / the "
            "largest difference observed anywhere in 2010–2024, so **1 = "
            "identical revealed preferences**, 0 = the most opposed pair "
            "observed. Symmetric: i's alignment with j equals j's with i."),
    "Cultural-historical proximity": dict(
        file="cultural_proximity_panel.parquet", col="cultural_proximity_index",
        yearly=False, scale="linear01",
        tie_phrase="cultural-historical ties", value_word="proximity to",
        unit="(0–1)",
        sources="CEPII GeoDist (Mayer & Zignago 2011)",
        how="- The index is the average of six yes/no ties: shared border, "
            "common official language, language spoken by ≥9% in both, "
            "colonial relationship, common colonizer after 1945, and having "
            "been the same country.\n- Time-invariant (no year selector) and "
            "symmetric. Most country pairs share none of the six (index 0)."),
    "Aid dependence": dict(
        file="aid_dependence_panel.parquet", col="aid_dependence_index",
        yearly=True, scale="log",
        log_ticks=[-3.0, -2.0, -1.0, 0.0, 1.0, 1.5],
        log_labels=["≤0.001%", "0.01%", "0.1%", "1%", "10%", "≥30%"],
        tie_phrase="aid dependence", value_word="aid received from",
        unit="of its GNI",
        sources="OECD DAC2A (gross ODA disbursements), World Bank WDI (GNI)",
        how="- **Gross ODA disbursed by the target to country *i*** in the "
            "selected year (OECD DAC2A, current USD) divided by *i*'s GNI "
            "(World Bank WDI).\n- Directed: the map shows who depends on the "
            "target's aid. Only country donors appear as targets (pick e.g. "
            "USA, Japan, Germany, France); most pairs have no aid flow at "
            "all and stay unshaded."),
}

# Palette matched to the GDELT Election Media Atlas (gdelt_country_map/app.R)
AMBER = "#F59E0B"
YELLOW = "#FACC15"
RED = "#EF4444"

st.set_page_config(page_title="Country Connectivity", layout="wide",
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


@st.cache_data(show_spinner="Loading connectivity panel ...")
def load_panel(fname):
    """Local file next to the app (dev runs) or R2 via st.secrets (deployed)."""
    local = os.path.join(APP_DIR, "data", fname)
    if not os.path.exists(local):
        import boto3
        r2 = st.secrets["r2"]
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{r2['account_id']}.r2.cloudflarestorage.com",
            aws_access_key_id=r2["access_key_id"],
            aws_secret_access_key=r2["secret_access_key"],
            region_name="auto",
        )
        local = f"/tmp/{fname}"
        client.download_file(r2["bucket"], R2_PREFIX + fname, local)
    return duckdb.sql(f"SELECT * FROM read_parquet('{local}')").df()


# ── sidebar controls ─────────────────────────────────────────────────────────
st.sidebar.title("⚙ Controls")
dim_label = st.sidebar.radio(
    "Dimension", list(DIMENSIONS), index=0,
    help="Separate indices for separate kinds of ties — deliberately never "
         "combined into one number, because the dimensions can disagree "
         "(a pair can be economically tight and geopolitically opposed).")
dim = DIMENSIONS[dim_label]

df = load_panel(dim["file"])

if dim_label == "Economic (trade)":
    metric_label = st.sidebar.radio(
        "Metric", list(ECON_METRICS), index=0,
        help="Share of own total trade = how salient the target is among "
             "this country's trade partners. Share of own GDP = how "
             "dependent the whole economy is on trade with the target.")
    val_col, unit = ECON_METRICS[metric_label]
else:
    val_col, unit = dim["col"], dim.get("unit", "")

if dim["yearly"]:
    years = sorted(df.year.unique(), reverse=True)
    year = st.sidebar.selectbox("Year", years, index=0)
else:
    year = None

scale_label = st.sidebar.radio(
    "Map colors", ["Absolute (comparable across targets)",
                   "Relative to this target (rank)"], index=0,
    help="Absolute: fixed scale, identical for every target and year, so "
         "weakly connected targets are visibly darker overall. Relative: "
         "colors spread by rank within the selected target.")
absolute_scale = scale_label.startswith("Absolute")

targets = (df[["j_iso3", "j_name"]].drop_duplicates()
           .sort_values("j_name").reset_index(drop=True))
if "target" not in st.session_state:
    st.session_state.target = "USA"
target_name_by_iso = dict(zip(targets.j_iso3, targets.j_name))
tlist = targets.j_iso3.tolist()
pick = st.sidebar.selectbox(
    "Target country (or click the map)", tlist,
    index=tlist.index(st.session_state.target)
    if st.session_state.target in set(tlist)
    else (tlist.index("USA") if "USA" in set(tlist) else 0),
    format_func=lambda c: f"{target_name_by_iso.get(c, c)} ({c})")
if pick != st.session_state.target:
    st.session_state.target = pick

hide_small = False
if dim_label == "Economic (trade)":
    hide_small = st.sidebar.checkbox(
        "Hide small economies (GDP < $25B) from ranking", value=True,
        help="Offshore financial centers show inflated services-trade "
             "exposure and would dominate the top-10 table. Affects only "
             "the ranking below the map.")

st.sidebar.caption(f"Sources: {dim['sources']}.")

target = st.session_state.target if st.session_state.target in set(tlist) else tlist[0]
tname = target_name_by_iso.get(target, target)
year_txt = f" in **{year}**" if year else ""
pct_dim = dim["scale"] == "log"   # log dims are percent-valued

st.title("Country Connectivity")
st.caption(f"**{tname}** in red. Every other country glows by its "
           f"**{dim['tie_phrase']}** {'with' if not pct_dim else 'to'} "
           f"{tname}{year_txt}: bright amber = strongest ties, dark = "
           "weakest. Hover for exact numbers, click a country to make it "
           "the target.")

# ── data slice ───────────────────────────────────────────────────────────────
sl = df[df.j_iso3 == target].copy()
if dim["yearly"]:
    sl = sl[sl.year == year]
sl["val"] = sl[val_col] * (100 if pct_dim else 1)
sl = sl[sl.val.notna()]
if pct_dim:
    sl = sl[sl.val > 0]

if sl.empty:
    st.info(f"No {dim['tie_phrase']} data with {tname} as target"
            f"{' in ' + str(year) if year else ''} — for aid dependence, "
            "pick a donor country (USA, Japan, Germany, France, ...).")
    st.stop()

sl["rank"] = sl.val.rank(ascending=False, method="min").astype(int)
sl["pctile"] = sl.val.rank(pct=True)

if absolute_scale and pct_dim:
    # fixed log10 gradient over percent values; clamped at both ends so
    # the colors are spent where countries actually differ
    z_lo, z_hi = dim["log_ticks"][0], dim["log_ticks"][-1]
    sl["z"] = np.clip(np.log10(sl.val), z_lo, z_hi)
    cbar_tickvals = dim["log_ticks"]
    cbar_ticktext = dim["log_labels"]
    cbar_title = f"{dim['value_word']} target<br>(% {unit}, log scale)"
elif absolute_scale:
    z_lo, z_hi = 0.0, 1.0
    sl["z"] = sl.val
    cbar_tickvals = [0.0, 0.25, 0.5, 0.75, 1.0]
    cbar_ticktext = ["0", "0.25", "0.5", "0.75", "1"]
    cbar_title = f"{dim['value_word']} target<br>{unit}"
else:
    z_lo, z_hi = 0.0, 1.0
    sl["z"] = sl.pctile
    cbar_tickvals = [0.02, 0.5, 0.98]
    cbar_ticktext = ["least tied", "median", "most tied"]
    cbar_title = "how tied to target<br>(rank among countries)"

val_suffix = f"% {unit}" if pct_dim else f" {unit}"

# ── map ──────────────────────────────────────────────────────────────────────
gj = load_geojson()
fig = go.Figure()

fig.add_trace(go.Choroplethmap(
    geojson=gj, locations=sl.i_iso3, z=sl.z,
    customdata=np.stack([sl.i_iso3, sl.i_name, sl.val.round(3),
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
                   + dim["value_word"] + " " + tname
                   + ": %{customdata[2]}" + val_suffix
                   + "<br>rank: #%{customdata[3]}<br>"
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
    if clicked and clicked != target and clicked in set(tlist):
        st.session_state.target = clicked
        st.rerun()

# ── top-10 table ─────────────────────────────────────────────────────────────
st.subheader(f"Most tied to {tname}" + (f" ({year})" if year else ""))
ranked = sl.copy()
if hide_small and "gdp_i" in ranked.columns:
    ranked = ranked[ranked.gdp_i >= 25e9].copy()
ranked["rank"] = ranked.val.rank(ascending=False, method="min").astype(int)
val_header = (f"{dim['value_word']} target (%{' ' + unit if unit else ''})"
              if pct_dim else f"{dim['value_word']} target {unit}")
top = (ranked.nlargest(10, "val")[["rank", "i_name", "i_iso3", "val"]]
       .rename(columns={"i_name": "country", "i_iso3": "iso3",
                        "val": val_header}))
st.dataframe(top.round(3), hide_index=True, use_container_width=True)
if hide_small:
    st.caption("Ranked among economies with GDP ≥ $25B. The map (and its "
               "hover rank) still includes the smaller economies.")

with st.expander("How this is computed"):
    st.markdown(dim["how"])
    st.caption("Part of a suite of separate bilateral connectivity indices "
               "(economic, geopolitical, cultural, aid) — deliberately kept "
               "separate rather than blended into one composite number.")
