# Dashboard and verification fixtures

All records in this folder are synthetic. `bank.csv` is the local independent transaction evidence used by the demo API; never replace it with real account data. `dashboard.json` seeds the group, initial ledger and audit. `scenarios.json` provides five reproducible outcomes. `screenshot_manifest.json` contains synthetic metadata only; the app previews uploaded images in the browser and asks the user to correct fields manually.

`dashboard_contract.json` describes the dashboard seed shape. FastAPI serves these files from `/data/`; the demo ledger state is held in memory and restored by `POST /api/reset`.

