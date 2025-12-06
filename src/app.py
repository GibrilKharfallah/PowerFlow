import pandas as pd
import streamlit as st
import numpy as np
import plotly.express as px

st.set_page_config(
    page_title="France — Electricity Imports/Exports",
    layout="wide"
    )

@st.cache_data(show_spinner=False)
def load_data(path: str) -> pd.DataFrame:
    """
    Load the processed CSV and rebuild clean net flows:

    - Parse datetime
    - Force all physical flows (exports/imports) to be positive volumes
    - Recompute partner-level net flows:
        net_GBR, net_CHE, net_ITA, net_ESP, net_CWE/Core
        as (exports_from_FR - imports_to_FR)
    - Recompute net_total as the sum of all net_* columns
    - Rebuild date, year, month, day, hour
    """

    # --- Load file ---
    df = pd.read_csv(path, sep=";", encoding="utf-8", low_memory=False)

    # --- Parse datetime ---
    if "datetime" in df.columns:
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    elif "Date" in df.columns and "Tranche horaire du programme d'échange" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["hour"] = (
            df["Tranche horaire du programme d'échange"]
            .astype(float)
            .fillna(0)
            .astype(int)
            .clip(lower=0, upper=23)
        )
        df["datetime"] = df["Date"] + pd.to_timedelta(df["hour"], unit="h")
    else:
        raise RuntimeError(
            "Cannot construct 'datetime' – expected either 'datetime' "
            "or ('Date', 'Tranche horaire du programme d'échange')."
        )

    if df["datetime"].isna().all():
        raise RuntimeError("All 'datetime' values are NaT after conversion.")

    # --- Drop any existing net_* columns (they were computed with wrong signs) ---
    old_net_cols = [c for c in df.columns if c.startswith("net_")]
    if old_net_cols:
        df = df.drop(columns=old_net_cols)

    # --- Partner flow configuration ---
    partner_configs = {
        "GBR": ("FR vers GB (MWh)", "GB vers FR (MWh)"),
        "CHE": ("FR vers CH (MWh)", "CH vers FR (MWh)"),
        "ITA": ("FR vers IT (MWh)", "IT vers FR (MWh)"),
        "ESP": ("FR vers ES (MWh)", "ES vers FR (MWh)"),
        "CWE/Core": ("FR->CWE/Core", "CWE/Core->FR"),
    }

    # --- Recompute partner-level net flows, with imports as positive volumes ---
    for code, (exp_col, imp_col) in partner_configs.items():
        if exp_col in df.columns and imp_col in df.columns:
            export_mwh = df[exp_col].fillna(0.0).abs()
            import_mwh = df[imp_col].fillna(0.0).abs()

            # net = exports_from_FR - imports_to_FR
            net_col = f"net_{code}"
            df[net_col] = export_mwh - import_mwh

    # --- Recompute net_total as the sum of all partner net_* columns ---
    net_cols = [c for c in df.columns if c.startswith("net_")]

    if not net_cols:
        raise RuntimeError(
            "No net_* columns could be constructed – "
            "check that the expected export/import columns exist."
        )

    df["net_total"] = df[net_cols].sum(axis=1)

    # --- Rebuild time breakdown columns from datetime ---
    df["date"] = df["datetime"].dt.date
    df["year"] = df["datetime"].dt.year
    df["month"] = df["datetime"].dt.to_period("M").astype(str)
    df["day"] = df["datetime"].dt.day
    df["hour"] = df["datetime"].dt.hour

    return df

def aggregate(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Resample by frequency on datetime (H, D, W, M)."""
    
    agg = (
        df.set_index("datetime")
        .resample(freq)
        .agg({c: "sum" for c in df.columns
                if c.startswith(("FR vers","GB vers","CH vers","IT vers","ES vers",
                                    "Export France","Import France","net_","FR->CWE","CWE/Core->FR"))})
        .reset_index()
    )
    
    agg["date"] = agg["datetime"].dt.date
    
    agg["month"] = agg["datetime"].dt.to_period("M").astype(str)
    
    agg["year"] = agg["datetime"].dt.year
    
    return agg

def format_mwh(x):
    
    if pd.isna(x):
        return "—"
    
    abs_x = abs(x)
    
    if abs_x >= 1e6:
        return f"{x/1e6:,.1f} TWh".replace(",", " ")
    
    if abs_x >= 1e3:
        return f"{x/1e3:,.1f} GWh".replace(",", " ")
    
    return f"{x:,.0f} MWh".replace(",", " ")

st.title("⚡ France - Cross-Border Electricity Imports & Exports")

st.caption(
    "Interactive data storytelling dashboard exploring France's cross-border "
    "electricity exchanges (GBR, CHE, ITA, ESP, CWE/Core) at multiple time scales."
)

st.markdown(
"""
### Context & Key Questions

France is a **central hub** in the European power system, continuously importing
and exporting electricity with its neighbors (United Kingdom, Switzerland, Italy, Spain, CWE/Core region).

This dashboard is designed to answer a few **key questions**:

- When is France a **net exporter** and when is it a **net importer**?
- Which trading partners contribute the most to **surpluses** and **deficits**?
- What are the **seasonal** and **intra-day** patterns of cross-border flows?
- Which **extreme days** (very high exports or imports) deserve deeper investigation?

**Target audience:** energy analysts, regulators, students in power systems,
and junior traders/analysts interested in European cross-border flows.
"""
)

# ======================
# Sidebar (filters)
# ======================
with st.sidebar:
    st.header("Filters")
    
    df = load_data("data/processed/processed-imports-exports.csv")
    
    min_d, max_d = df["datetime"].min().date(), df["datetime"].max().date()
    
    date_range = st.date_input("Period", (min_d, max_d), min_value=min_d, max_value=max_d)
    
    freq = st.selectbox("Granularity", options=[("H","Hourly"),("D","Daily"),("W","Weekly"),("M","Monthly")],
                        index=3, format_func=lambda x: x[1])[0]
    
    partenaires = ["GBR","CHE","ITA","ESP"]
    if "net_CWE/Core" in df.columns:
        partenaires.append("CWE/Core")
    
    selected = st.multiselect("Partners", partenaires, default=partenaires)

# Filter period
mask = (df["date"] >= pd.to_datetime(date_range[0]).date()) & (df["date"] <= pd.to_datetime(date_range[1]).date())

df_f = df.loc[mask].copy()

agg = aggregate(df_f, freq)

# Global KPIs
exp_cols = [c for c in agg.columns if c.startswith("FR vers")]

imp_cols = [c for c in agg.columns if c.endswith("vers FR (MWh)") or "->FR" in c]

total_export = agg[exp_cols].sum().sum() if exp_cols else np.nan

total_import = agg[imp_cols].sum().sum() if imp_cols else np.nan

net_total = agg["net_total"].sum() if "net_total" in agg.columns else np.nan

# ======================
# === Tabs UI ==========
# ======================
tab_dash, tab_adv, tab_geo, tab_meth = st.tabs(["📈 Dashboard", "🔎 Advanced Analytics", "🗺️ Geo Flows", "🧭 Methodology"])


# ----------------------
# 📈 Dashboard
# ----------------------
with tab_dash:
    col1, col2, col3 = st.columns(3)
    
    col1.metric("Cumulative Export", format_mwh(total_export))
    col2.metric("Cumulative Import", format_mwh(total_import))
    col3.metric("Net Balance", format_mwh(net_total), delta=None)

    # Net balance time series
    ts = agg[["datetime","net_total"]].rename(columns={"net_total":"Net Balance (MWh)"})
    
    fig_net = px.line(ts, x="datetime", y="Net Balance (MWh)", title="Net Balance Over Time")
    
    fig_net.update_layout(
        title_font=dict(size=26)
    )
    
    st.plotly_chart(fig_net, use_container_width=True)
    
    st.markdown("""
    **Analysis — Net Balance Over Time**  
    This line chart shows the **net exchange balance** (exports - imports) over time.

    - A **persistent surplus** (above 0) indicates that France is acting as a **structural exporter**, with comfortable generation margins.  
    - Periods dropping **close to or below zero** signal **stress on the system**, where France becomes a **net importer**.  
    - The deep negative episode around 2021-2022 stands out as an **exceptional imbalance**, consistent with large nuclear outages and tight European markets.  

    Use the **granularity selector (H/D/W/M)** and **date filter** to zoom from detailed volatility to long-term system regimes.
    """)

    # Stacked area by partner (net)
    net_cols = [f"net_{p}" for p in selected if f"net_{p}" in agg.columns]
    
    if net_cols:
        area_df = agg[["datetime"] + net_cols].copy()
        
        area_long = area_df.melt(id_vars="datetime", var_name="Partner", value_name="MWh")
        area_long["Partner"] = area_long["Partner"].replace("net_","", regex=False)
        
        fig_area = px.area(area_long, x="datetime", y="MWh", color="Partner",
                            title="Partners' Contribution to Net Balance")
        
        fig_area.update_layout(
            title_font=dict(size=26)
        )
        
        st.plotly_chart(fig_area, use_container_width=True)
        
    st.markdown("""
    **Analysis — Contribution by Partner**  
    This stacked area chart decomposes the **overall net balance** into **bilateral contributions**.

    - Thick **positive bands** show partners to whom France is a **structural exporter** (they absorb French surplus).  
    - Bands dipping **below zero** correspond to partners that **supply France** during tight periods.  
    - The relative thickness and color of each area highlight which borders dominate in **normal times** vs during **crisis episodes** (for example in 2021–2022).

    Toggling partners on/off helps isolate **which neighbors drive the most change** when the system flips between surplus and deficit.
    """)

    # Cumulative bars by partner
    monthly = aggregate(df_f, "M")
    
    monthly_tot = monthly[[c for c in monthly.columns if c.startswith("net_")]].sum().sort_values(ascending=False).reset_index()
    
    monthly_tot.columns = ["Partner","Balance (MWh)"]
    
    monthly_tot["Partner"] = monthly_tot["Partner"].str.replace("net_","", regex=False)
    
    fig_bar = px.bar(monthly_tot, x="Partner", y="Balance (MWh)",
                    title="Cumulative Net Balance by Partner (Filtered Period)")
    
    fig_bar.update_layout(
        title_font=dict(size=26)
    )
    
    st.plotly_chart(fig_bar, use_container_width=True)
    
    st.markdown("""
    **Analysis — Cumulative Balance by Partner**  
    This ranking aggregates flows over the **selected period** to reveal France’s **structural relationships**.

    - Bars **above zero** correspond to partners that **buy net electricity from France** over the period.  
    - Bars **below zero** highlight partners that are **net suppliers to France**.  
    - The relative height of each bar shows how much each border contributes to shaping France’s **overall external position**.

    This view answers a simple question: *“Over this timeframe, who is France really exporting to, and who is it relying on when the system is tight?”*
    """)

    # Heatmap hour x day
    heat = df_f.pivot_table(index=df_f["datetime"].dt.date,
                            columns=df_f["datetime"].dt.hour,
                            values="net_total", aggfunc="sum").fillna(0)
    
    heat_long = heat.reset_index().melt(id_vars="datetime", var_name="Hour", value_name="MWh")
    heat_long.rename(columns={"datetime":"Day"}, inplace=True)
    
    fig_heat = px.density_heatmap(heat_long, x="Hour", y="Day", z="MWh", nbinsx=24,
                                    title="Net Balance Heatmap (Hour x Day)")
    
    fig_heat.update_layout(
        title_font=dict(size=26)
    )
    
    st.plotly_chart(fig_heat, use_container_width=True)
    
    st.markdown("""
    **Analysis — Intra-day Patterns**  
    This heatmap displays the **hour-by-hour net balance** for each day.

    - Darker bands indicate hours where exports are structurally **higher**; lighter or inverted colours correspond to moments of **weaker exports or imports**.  
    - Morning and evening periods typically align with **demand ramps** across Europe, where cross-border exchanges intensify.  
    - Changes in the colour pattern over certain years highlight **unusual operating conditions** (for example, when France temporarily loses its historical export profile).

    Scanning vertically reveals **daily profiles**, while scanning horizontally reveals how those profiles evolve over the **years**.
    """)


# ----------------------
# 🔎 Advanced Analytics
# ----------------------
with tab_adv:
    base = df_f.copy()


    # 1) Net distribution
    fig_dist = px.histogram(base, x="net_total", nbins=60, marginal="violin",
                            title="Net Balance Distribution (MWh)")
    
    fig_dist.update_layout(
        title_font=dict(size=26)
    )
    
    st.plotly_chart(fig_dist, use_container_width=True)
    
    st.markdown("""
    **Analysis — Distribution of Net Balance**  
    This distribution describes the **shape and dispersion** of France's net balance.

    - The central bulk of the histogram corresponds to **typical operating regimes**, where France exports moderately.  
    - The long **right-hand tail** reflects episodes of **very high exports**, usually when generation is abundant and demand is moderate.  
    - The **left-hand side** captures **import situations**: rare but sometimes very large negative values point to **stress events** in the system.

    Reading this chart is key for **risk analysis**: the wider and more skewed the distribution, the greater the exposure to extreme import needs.
    """)


    # 2) Seasonal boxplot
    base["month_str"] = base["datetime"].dt.to_period("M").astype(str)
    
    fig_box = px.box(base, x="month_str", y="net_total",
                    title="Seasonality: Monthly Net Balance Boxplot",
                    labels={"month_str":"Month","net_total":"MWh"})
    
    fig_box.update_layout(
        title_font=dict(size=26)
    )
    
    st.plotly_chart(fig_box, use_container_width=True)
    
    st.markdown("""
    **Analysis — Monthly Seasonality**  
    Each box summarises the **monthly distribution** of the net balance across all years.

    - Winter months tend to show **lower or more volatile net balances**, sometimes dipping into negative territory as domestic demand peaks.  
    - Summer months generally display **higher and more stable exports**, consistent with lower demand and solid generation.  
    - Outliers highlight **exceptional months**, often linked to extreme weather, large outages or major market events.

    This seasonal view reveals the **recurring rhythm** of the French power system and helps explain why certain periods are structurally more fragile.
    """)


    # 3) Weekday-hour heatmap
    base["weekday"] = base["datetime"].dt.weekday
    base["hour"] = base["datetime"].dt.hour

    wh = base.pivot_table(
        index="weekday",
        columns="hour",
        values="net_total",
        aggfunc="mean"
    ).reindex([0,1,2,3,4,5,6])

    wh.index = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

    fig_wh = px.imshow(
        wh,
        aspect="auto",
        title="Average Heatmap — Weekday x Hour (MWh)",
        text_auto=True
    )
    
    fig_wh.update_layout(
        title_font=dict(size=26)
    )

    st.plotly_chart(fig_wh, use_container_width=True)

    st.markdown("""
    **Analysis — Weekly Operational Profile**  
    This matrix shows the **average net balance** for each combination of **weekday and hour**.

    - Weekday daytimes (especially Tuesday - Thursday) concentrate the **highest export levels**, reflecting strong industrial and commercial activity in neighbouring systems.  
    - Nights (roughly 00:00 - 06:00) are flatter, with more modest exchanges, as overall European demand is lower.  
    - Weekends keep a similar pattern but at **reduced intensity**, highlighting a different operational regime.

    This view is particularly useful for **operations and forecasting**, as it captures the “typical week” behaviour of cross-border flows.
    """)



    # 4) Partner correlation matrix
    partner_cols = [c for c in base.columns if c.startswith("net_") and c not in ("net_total",)]
    
    if partner_cols:
        corr = base[partner_cols].corr()
    
        fig_corr = px.imshow(corr, text_auto=True, aspect="auto", title="Correlation Between Partners' Net Balances")
        
        fig_corr.update_layout(
            title_font=dict(size=26)
        )
    
        st.plotly_chart(fig_corr, use_container_width=True)
    
        st.markdown("""
        **Analysis — Partner Correlations**  
        This matrix measures how **bilateral net balances move together** over time.

        - **Positive correlations** mean that flows with two partners tend to **co-move** (for example, both importing from France during similar situations).  
        - **Low or near-zero correlations** indicate that exchanges are driven by **distinct local conditions**, providing diversification in France’s cross-border profile.  
        - Any negative correlation would point to **substitution effects**, where France diverts flows from one border to another.

        Overall, this chart helps assess whether France's external position is driven by a **single dominant border** or by a **diversified set of relationships**.
        """)


    # 5) Export vs import scatter
    exp_cols0 = [c for c in base.columns if c.startswith("FR vers")]

    imp_cols0 = [c for c in base.columns if c.endswith("vers FR (MWh)") or "->FR" in c]

    if exp_cols0 and imp_cols0:
        base["export_sum"] = base[exp_cols0].sum(axis=1)
        base["import_sum"] = base[imp_cols0].sum(axis=1)
        sample_n = min(len(base), 20000)

        # Sample for readability
        sample = base.sample(sample_n, random_state=0)

        # Scatter with OLS trendline + opacity for dense clouds
        fig_scatter = px.scatter(
            sample,
            x="import_sum",
            y="export_sum",
            trendline="ols",
            opacity=0.4,  # 🔹 transparency on points
            labels={"import_sum": "Import (MWh)", "export_sum": "Export (MWh)"},
            title="Export vs Import (Sampled)"
        )
        
        fig_scatter.update_layout(
            title_font=dict(size=26)
        )

        # Customize traces: red trendline + custom hover
        for trace in fig_scatter.data:
            # Points
            if trace.mode == "markers":
                trace.hovertemplate = (
                    "Import: %{x:.0f} MWh<br>"
                    "Export: %{y:.0f} MWh<br>"
                    "<extra></extra>"
                )
            # Trendline (OLS line)
            elif trace.mode == "lines":
                trace.line.color = "red"
                trace.line.width = 3
                trace.hovertemplate = (
                    "OLS trendline<br>"
                    "Import: %{x:.0f} MWh<br>"
                    "Export (fit): %{y:.0f} MWh<br>"
                    "<extra></extra>"
                )

        st.plotly_chart(fig_scatter, use_container_width=True)

    st.markdown("""
    **Analysis — Export vs Import Relationship**  
    Each point represents one period (depending on the chosen aggregation) with its **total imports** on the x-axis and **total exports** on the y-axis.

    - The cloud of points shows how France simultaneously participates in **supplying neighbours** and **covering its own needs**.  
    - Points **above the diagonal** correspond to situations where exports dominate; points closer to the bottom-right reflect **high import episodes**.  
    - The red **trendline** summarises the structural relationship between imports and exports and reveals how this balance behaves on average.

    This chart is useful to understand whether France acts more as a **flexible hub** or as a **one-sided exporter** in the selected period.
    """)


    # 6) Rolling 7-day average
    roll = (df_f.set_index("datetime")["net_total"]
            .resample("D").sum()
            .rolling(7, min_periods=1).mean()
            .reset_index())
    
    fig_roll = px.line(roll, x="datetime", y="net_total",
                    title="Net Balance — 7-Day Rolling Average")
    
    fig_roll.update_layout(
        title_font=dict(size=26)
    )
    
    st.plotly_chart(fig_roll, use_container_width=True)
    
    st.markdown("""
    **Analysis — Smoothed Trend (7-Day Average)**  
    The 7-day rolling mean filters out **short-term noise** to reveal **medium-term structural movements**.

    - Long stretches well **above zero** correspond to periods where France consistently exports electricity over several weeks.  
    - Persistent dips or long episodes **below zero** indicate **sustained import dependence**, often associated with major supply issues or exceptional demand.  
    - The sharp collapse around 2021-2022, followed by a recovery, clearly shows a **regime change** in the underlying system.

    This smoothed series is ideal for tracking **shifts in structural regime**, rather than focusing on individual days.
    """)


    # 7) Top days
    daily = df_f.set_index("datetime")["net_total"].resample("D").sum().reset_index()
    
    top_exp = daily.sort_values("net_total", ascending=False).head(10).rename(columns={"net_total":"MWh"}).assign(Type="Top export")
    
    top_imp = daily.sort_values("net_total", ascending=True).head(10).rename(columns={"net_total":"MWh"}).assign(Type="Top import")
    
    st.subheader("Top Days")
    
    st.dataframe(pd.concat([top_exp, top_imp]).sort_values(["Type","MWh"], ascending=[True, False]))
    
    st.markdown("""
    **Analysis — Noteworthy Days**  
    These tables list the **10 strongest export days** and **10 strongest import days** over the selected period.

    - Extreme **export days** often correspond to situations of abundant French generation and favourable market conditions in neighbouring countries.  
    - Extreme **import days** are typically associated with **system stress** (high demand, reduced nuclear availability, unexpected outages or regional price spikes).  

    These dates are prime candidates for **deep-dive investigations**, for example by cross-checking weather conditions, market prices or major grid events.
    """)

# ----------------------
# 🗺️ Geo Flows (Maps)
# ----------------------
with tab_geo:
    st.subheader("Geo View — France as a Regional Power Hub")

    geo_base = df_f.copy()

    partner_cols = [
        c for c in geo_base.columns
        if c.startswith("net_") and c not in ("net_total",)
    ]

    iso_map = {
        "GBR": "GBR",
        "CHE": "CHE",
        "ITA": "ITA",
        "ESP": "ESP",
    }

    if partner_cols:
        # --------------------------
        # Map 1 — Annual net balance per year
        # --------------------------
        yearly = (
            geo_base
            .groupby("year")[partner_cols]
            .sum()
            .reset_index()
        )

        yearly_long = (
            yearly
            .melt(id_vars="year", var_name="Partner_raw", value_name="MWh")
        )

        # net_GBR -> GBR
        yearly_long["Partner"] = yearly_long["Partner_raw"].str.replace("net_", "", regex=False)

        yearly_long = yearly_long[yearly_long["Partner"].isin(iso_map.keys())].copy()
        yearly_long["iso_code"] = yearly_long["Partner"].map(iso_map)

        yearly_long["Status"] = np.where(
            yearly_long["MWh"] >= 0,
            "Net exporter",
            "Net importer"
        )

        fig_geo_year = px.choropleth(
            yearly_long,
            locations="iso_code",
            color="MWh",
            hover_name="Partner",
            hover_data={"year": True, "Status": True, "iso_code": False},
            animation_frame="year",
            projection="natural earth",
            title="Net Cross-Border Balance by Partner (Yearly View)",
        )

        fig_geo_year.update_layout(
            title_font=dict(size=26),
            margin=dict(l=0, r=0, t=60, b=0)
        )

        st.plotly_chart(fig_geo_year, use_container_width=True)

        st.markdown(
            """
            **Analysis — Yearly Net Balance by Neighbour**  
            This map shows, year by year, whether France is a **net exporter** or **net importer**
            vis-à-vis each neighbouring country.

            - Countries in **positive shades** are **net buyers** of French electricity in that year.  
            - Countries in **negative shades** are **net suppliers** to France, reflecting periods of **import dependence**.  
            - Sliding through the years reveals how these relationships evolve, especially around **stress episodes**
                like the 2021 - 2022 nuclear outages.

            It turns the time series into a **geographical narrative**:
            *“In a given year, who relies on whom?”*
            """
        )

        st.markdown("---")

        # --------------------------
        # MAp 2 — Net position over the selected period
        # --------------------------
        total_net = (
            geo_base[partner_cols]
            .sum()
            .reset_index()
        )
        total_net.columns = ["Partner_raw", "MWh"]
        total_net["Partner"] = total_net["Partner_raw"].str.replace("net_", "", regex=False)

        total_net = total_net[total_net["Partner"].isin(iso_map.keys())].copy()
        total_net["iso_code"] = total_net["Partner"].map(iso_map)
        total_net["Status"] = np.where(
            total_net["MWh"] >= 0,
            "Net exporter (over selected period)",
            "Net importer (over selected period)"
        )

        fig_geo_total = px.choropleth(
            total_net,
            locations="iso_code",
            color="MWh",
            hover_name="Partner",
            hover_data={"Status": True, "iso_code": False},
            projection="natural earth",
            title="Net Cross-Border Balance by Partner (Selected Period)",
        )

        fig_geo_total.update_layout(
            title_font=dict(size=26),
            margin=dict(l=0, r=0, t=60, b=0)
        )

        st.plotly_chart(fig_geo_total, use_container_width=True)

        st.markdown(
            """
            **Analysis — Net Position Over the Selected Period**  
            Here, each country is aggregated over the **entire date range** chosen in the sidebar.

            - Partners with **strong positive balances** are those that **consistently buy** from France
                across the period.  
            - Negative balances highlight borders where France has been **structurally dependent on imports**.  
            - Comparing this map with the yearly animation helps distinguish **short-lived crises**
              from **long-lasting structural shifts**.

            This view answers:  
            *“Over the whole period I'm looking at, who is France really exporting to, and who is it relying on?”*
            """
        )

        st.markdown("---")

        # --------------------------
        # Map 3 — Structural intensity (absolute flows)
        # --------------------------
        total_abs = (
            geo_base[partner_cols]
            .abs()
            .sum()
            .reset_index()
        )
        total_abs.columns = ["Partner_raw", "Abs_MWh"]
        total_abs["Partner"] = total_abs["Partner_raw"].str.replace("net_", "", regex=False)

        total_abs = total_abs[total_abs["Partner"].isin(iso_map.keys())].copy()
        total_abs["iso_code"] = total_abs["Partner"].map(iso_map)

        fig_geo_intensity = px.choropleth(
            total_abs,
            locations="iso_code",
            color="Abs_MWh",
            hover_name="Partner",
            projection="natural earth",
            title="Structural Intensity of Cross-Border Exchanges (Selected Period)",
        )

        fig_geo_intensity.update_layout(
            title_font=dict(size=26),
            margin=dict(l=0, r=0, t=60, b=0)
        )

        st.plotly_chart(fig_geo_intensity, use_container_width=True)

        st.markdown(
            """
            **Analysis — Structural Intensity of Exchanges**  
            This third map ignores the **sign** of the flows and focuses on their **absolute volume**.

            - Darker shades indicate borders with **high structural exposure** — large volumes traded
                in both export and import directions.  
            - Lighter countries correspond to **second-order borders**, which matter less for France’s
                overall external balancing.  

            Together, the three maps tell a coherent story:

            - The **yearly map** captures the *trajectory* of each relationship over time.  
            - The **net position map** summarises **who France depends on** over the selected period.  
            - The **intensity map** highlights **which borders are systemically critical**, regardless of direction.
            """
        )

    else:
        st.info("No partner-level `net_*` columns available to build geographic views.")


# ----------------------
# 🧭 Methodology
# ----------------------
# with tab_meth:
#     st.markdown("""
#     ### Process & Assumptions

#     **Data Pipeline**
#     1. **Notebook (`data_processing.ipynb`)**: Full ETL workflow → outputs **`data/processed/processed-imports-exports.csv`**.  
#     2. **App (`app.py`)**: Loads the processed file only (no heavy transformations).

#     **Key Assumptions**
#     - `Exchange program time slot` = hour typically represented as 0-23 or 1-24 (cleaned and normalized).  
#     - `net_total = Export France (MWh) - Import France (MWh)` or sum of `net_*` columns when totals are not provided.  
#     - Time-derived fields come directly from `datetime`.

#     **Reading Guidelines**
#     - Net balance **> 0** → net exporter.  
#     - Net balance **< 0** → net importer.  
#     - Compare partners over time (stacked area) & analyze seasonality (monthly boxplot).  
#     - Use **Day x Hour heatmaps** to identify intra-week operational patterns.
#     """)

# --------------------------------------------------
# 🧭 Methodology, Data Quality & Insights
# --------------------------------------------------
with tab_meth:
    st.markdown(
        """
        ### Data Pipeline & Assumptions

        **Data pipeline**

        1. **Raw data (outside this app)**  
        Original file with cross-border commercial flows (hourly exchanges between France and its neighbors).  
        2. **Pre-processing (notebook or ETL script)**  
        - Construction of a unified `datetime` from calendar date + program hour.  
        - Computation of partner-level net flows (`net_GBR`, `net_CHE`, `net_ITA`, `net_ESP`, `net_CWE`)  
            as **France exports - France imports** (in MWh).  
        - Computation of the overall `net_total` (either direct or as a sum of net partners).  
        - Enrichment with temporal features: `year`, `month`, `day`, `hour`, etc.  
        → Output: **`processed-imports-exports.csv`**.  
        3. **This Streamlit app (`app.py`)**  
        - Loads the processed dataset only.  
        - Performs **light aggregations** (hourly / daily / weekly / monthly).  
        - Provides **interactive visual analytics** and narrative interpretations.

        **Core assumptions**

        - `net_*` for each partner = **Exports from France - Imports to France**, in MWh.  
        - `net_total` = `Export France (MWh)` - `Import France (MWh)` (or equivalent).  
        - Aggregations (D/W/M) are performed by **summing** net flows and volumes over the period.
        """
    )

    # Data Quality & coverage
    st.markdown("### Data Quality & Limitations")

    st.markdown("#### Duplicates & coverage")

    nb_dups = df.duplicated().sum()
    min_dt = df["datetime"].min()
    max_dt = df["datetime"].max()
    min_net = df["net_total"].min()
    max_net = df["net_total"].max()

    st.write(f"- Number of duplicated rows: **{nb_dups}**")
    st.write(f"- Time period covered: **{min_dt} → {max_dt}**")
    st.write(f"- Minimum net balance: **{format_mwh(min_net)}**")
    st.write(f"- Maximum net balance: **{format_mwh(max_net)}**")

    st.markdown(
        """
        #### Known limitations / potential biases

        - Timestamps are based on the **exchange program schedule**, which may differ slightly
        from real-time physical flows.  
        - The source (TSO / open data portal) may apply **ex-post corrections** to the historical series.  
        - Aggregations (from hourly to monthly) can mask **very short-term spikes** or intraday events.  
        - The dataset focuses on **commercial flows** and does not directly capture prices,
        redispatching actions, or detailed grid constraints.
        """
    )

    # Key Insights & Next Steps
    st.markdown("### Key Insights & Next Steps")

    st.success(
        """
        **Key insights**  

        - Over the analysed period, France appears to be **structurally net exporting**, with specific
            episodes of **high imports** (often in winter during demand peaks).  
        - Some partners (e.g., **GBR**, **CHE**, **ITA**, **ESP**, **CWE/Core**) play a major role in
            balancing France's surplus/deficit, with clear asymmetries in net flows.  
        - **Intra-day patterns** (Day x Hour heatmap) reveal recurring periods of strong exports or imports,
            especially around peak-load hours.

        **Retrospective & Future prospects**

        - Enrich this analysis with **market prices** (day-ahead, intraday) to assess the **economic value**
            of cross-border exchanges.  
        - Combine with **weather data** (temperature, wind, hydro inflows) to better understand how
            generation mix and demand drive cross-border flows.  
        - Extend the comparison to additional European countries or zones to benchmark France's structural
            position in the interconnected system.  
        """
    )
