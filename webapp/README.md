# SmartPlant Dashboard (local)

This small app serves a static dashboard and provides two API endpoints that read the JSONL logs from the `data_logs/` folder in the project root.

Endpoints:
- `GET /` - dashboard (static HTML)
- `GET /api/env` - returns latest environment JSON from `data_logs/env_*.jsonl`
- `GET /api/plants` - returns latest plants JSON from `data_logs/plants_*.jsonl`

Quick start (Windows PowerShell):

1. Create virtual environment and activate:

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r webapp\requirements.txt
```

3. Run the app:

```powershell
python webapp\app.py
```

4. Open your browser at `http://localhost:5000`

Notes:
- The backend picks the latest matching JSONL file by modification time and returns the last JSON object (last non-empty line). Ensure files in `data_logs/` are JSONL (one JSON object per line).
- If logs use a different shape, you may need to adapt `webapp/app.py` and `webapp/static/main.js` to match the real keys.
