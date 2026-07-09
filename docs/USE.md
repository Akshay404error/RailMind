# Usage Guide

## Setup
```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Data
Place downloaded datasets into `data/raw/`. Then open
`notebooks/explore_datasets.ipynb` to inspect their structure before
running any processing scripts.

## Running (to be expanded as components are built)
- Data processing: `python -m src.data.clean`
- Build network graph: `python -m src.network.graph_builder`
- Run optimizer: `python -m src.optimizer.cp_sat_model`
- Run API: `uvicorn src.api.main:app --reload`
- Run dashboard: `cd dashboard && npm install && npm run dev`
