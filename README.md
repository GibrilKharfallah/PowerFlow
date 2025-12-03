# ⚡ PowerFlow — France Cross-Border Electricity Explorer

A **Streamlit** data-storytelling application to analyze France’s cross-border electricity exchanges.

## 🚀 Run the Application

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

streamlit run src/app.py --server.headless true
```

## 🧠 Storytelling (Narrative Arc)

- **Problem** : When is France a net exporter ? With which partners, and at what moments does the balance shift ?
- **Analysis** : Time series (net balance), stacked-area view by partner, hour × day heatmap.
- **Insights** : Identification of export/import periods, dominant partners, hourly patterns.
- **Implications** : Decisions related to flexibility, arbitrage, and grid planning.

## 🔧 Techniques

- **Ingestion & cleaning** : robust separator/encoding detection, date parsing, and hourly slot normalization.
- **Caching** : `st.cache_data` for performance.
- **Agregations** : hourly, daily, weekly, and monthly resampling.
- **KPIs** : export, import, net balance.
- **Visualization** : Plotly (line, area, bar, heatmap).

## 📁 Structure

```bash
PowerFlow/
├── data/                                       
│   ├── processed/
│   │   └── processed-imports-exports.csv       # Processed dataset
│   └── raw/
│       └── imports-exports-commerciaux.csv     # Raw dataset (before cleaning & preparation)
├── notebooks
│   └── data_processing.ipynb                   # Jupyter notebook for data preparation
├── src
│   └── app.py                                  # Streamlit application
├── .gitignore                                  # .gitignore file
├── README.md                                   # README file for project documentation
└── requirements.txt                            # Libraries and dependencies
```

## 📊 Pipeline Diagram — Data Flow Overview

```text
                            ┌──────────────────────────┐
                            │   Raw Data (CSV)         │
                            │ imports-exports-...csv   │
                            └────────────┬─────────────┘
                                         │
                                         ▼
                        ┌──────────────────────────────────┐
                        │  Jupyter Notebook (ETL Process)  │
                        │  notebooks/data_processing.ipynb │
                        │                                  │
                        │  • Cleaning & formatting         │
                        │  • Datetime parsing              │
                        │  • Hourly slot normalization     │
                        │  • Computation of bilateral      │
                        │    net flows (net_*)             │
                        │  • Export of processed dataset   │
                        └────────────────┬─────────────────┘
                                         │
                                         ▼
                        ┌──────────────────────────────────────┐
                        │ Processed Dataset                    │
                        │ data/processed/processed-*.csv       │
                        └────────────────┬─────────────────────┘
                                         │
                                         ▼
            ┌─────────────────────────────────────────────────────────┐
            │                 Streamlit Application                   │
            │                     src/app.py                          │
            │                                                         │
            │  • Loads processed dataset (fast, lightweight)          │
            │  • Applies filters (date range, partners, granularity)  │
            │  • Aggregation (H/D/W/M) using resampling               │
            │  • KPI computation: export / import / net balance       │
            │  • Visual storytelling with Plotly:                     │
            │        - Time series (net balance)                      │
            │        - Stacked area by partner                        │
            │        - Heatmaps (Hour × Day, Weekday × Hour)          │
            │        - Distribution & correlations                    │
            └────────────────────────────┬────────────────────────────┘
                                         │
                                         ▼
                    ┌────────────────────────────────────────┐
                    │              Insights                  │
                    │ • When France is net exporter/importer │
                    │ • Which partners drive the balance     │
                    │ • Seasonal + intraday behaviour        │
                    │ • Strategic implications (flexibility, │
                    │   planning, arbitrage, grid design)    │
                    └────────────────────────────────────────┘

```

## 📝 Assumptions & Limitations

- `Tranche horaire du programme d'échange` is interpreted as an **hour** block (0–23 or 1–24).
- If export/import total columns are missing, the **net balance** is computed as the **sum of available bilateral balances**.
- The **CWE/Core** group is treated as an aggregated partner when present.
