# ChitMirror

Screenshot in, verified ledger out. A four-person, six-hour hackathon project. A screenshot is a payment claim; local transaction evidence is required before the demo ledger records it.

## Run locally

Use Python 3.12 or newer. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m uvicorn backend.main:app --reload
```

On macOS/Linux use `.venv/bin/python` in place of `.\.venv\Scripts\python`. Open http://127.0.0.1:8000/dashboard/ for the foreman demo and http://127.0.0.1:8000/chat/ for the chat page. No Node build step or internet connection is needed after installing dependencies.

The dashboard includes the monthly overview, payment verification queue, shared ledger, auction calculator, members, member view, statement CSV export, reports, audit history and group setup. Screenshots are previewed in the browser. OCR is not included; the member or foreman can correct the extracted fields manually before submitting them.

The local API exposes `/api/state`, `/api/verify` and `/api/reset`. `/data/` serves the synthetic dashboard and evidence fixtures. The verification endpoint checks the 12-digit UTR, amount, date, receiver and member against `data/bank.csv`. It adds only matched payments to the in-memory demo ledger. The initial ledger and audit are restored on reset or server restart.

**Demo boundary:** `data/bank.csv` is synthetic and is not a live bank feed or financial evidence. Auction values are illustrative. The demo does not initiate payouts or provide authentication.

## Team folders

| Owner | Workspace |
| --- | --- |
| A | Reader and verification modules under `backend/`; tests under `tests/` |
| B | `backend/`: contract, services, storage, API and engine integration |
| C | `chat-ui/`: independent chat page; demo script and pitch |
| D | `dashboard/` and `data/`: dashboard, fixtures and demo verification flow |

The existing `chit_engine.py` and `chitmirror_final.mermaid` were not present in the empty repository. Their owner should supply the originals; do not recreate the completed engine or diagram. Integration belongs to T09.

## Checks

```powershell
.\.venv\Scripts\python -m pytest tests/test_app.py
.\.venv\Scripts\python -m playwright install chromium
```

With the development server running, in a second terminal:

```powershell
.\.venv\Scripts\python -m pytest tests/ui --base-url http://127.0.0.1:8000
```

No external bank, OCR, or payment service is called by this demo.

