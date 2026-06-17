import os
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

DATASETS = {
    "northwind": {
        "url": "https://raw.githubusercontent.com/jpwhite3/northwind-SQLite3/main/dist/northwind.db",
        "industry": "B2B Distribution & Retail",
        "description": (
            "Northwind Traders is a specialty food wholesale company that sells to "
            "restaurants, hotels, and retailers across North America and Europe. "
            "The database tracks orders, customers, products, suppliers, and employees."
        ),
        "color": "#7aa2f7",
        "emoji": "🏭",
    },
    "chinook": {
        "url": "https://github.com/lerocha/chinook-database/raw/master/ChinookDatabase/DataSources/Chinook_Sqlite.sqlite",
        "industry": "Digital Media & E-commerce",
        "description": (
            "Chinook Digital Store sells music tracks, albums, and playlists online. "
            "With customers across 25 countries, it tracks purchases, invoices, artists, "
            "and a global team of sales support agents."
        ),
        "color": "#bb9af7",
        "emoji": "🎵",
    },
    "factbook": {
        "url": "https://github.com/factbook/factbook.sql/releases/latest/download/factbook.db",
        "industry": "Demographics & Government",
        "description": (
            "CIA World Factbook data covering 261 countries and territories. "
            "Tracks population, GDP, area, birth/death rates, internet users, and more — "
            "ideal for economic analysis, policy research, and cross-country comparisons."
        ),
        "color": "#9ece6a",
        "emoji": "🌍",
    },
}


def _download(url: str, dest: Path) -> bool:
    try:
        import requests  # lazy: only needed when a bundled dataset is missing
        r = requests.get(url, timeout=60, allow_redirects=True)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return True
    except Exception as e:
        print(f"  Download failed for {dest.name}: {e}")
        if dest.exists():
            dest.unlink()
        return False


def ensure_datasets() -> dict[str, Path]:
    available = {}
    for ds_id, meta in DATASETS.items():
        ext = ".sqlite" if ds_id == "chinook" else ".db"
        path = DATA_DIR / f"{ds_id}{ext}"
        if not path.exists():
            print(f"Downloading {ds_id}...")
            ok = _download(meta["url"], path)
            if not ok:
                continue
        # Quick sanity check — make sure it's a valid SQLite file
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            conn.execute("SELECT 1")
            conn.close()
            available[ds_id] = path
            print(f"  ✓ {ds_id} ready at {path}")
        except Exception as e:
            print(f"  ✗ {ds_id} invalid: {e}")
    return available
