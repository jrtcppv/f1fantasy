"""Transactional season snapshots; all financial values stored as decimal text."""
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3

from .models import Dataset
from .providers.csv_provider import parse_bundle


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS races (
 id TEXT PRIMARY KEY, season INTEGER NOT NULL, round INTEGER NOT NULL,
 name TEXT NOT NULL, date TEXT NOT NULL, completed INTEGER NOT NULL, location TEXT NOT NULL,
 UNIQUE(season, round));
CREATE TABLE IF NOT EXISTS assets (
 id TEXT PRIMARY KEY, season INTEGER NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL,
 kind TEXT NOT NULL, active INTEGER, team TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS fantasy_scores (
 asset_id TEXT REFERENCES assets(id), race_id TEXT REFERENCES races(id), points TEXT, status TEXT,
 PRIMARY KEY(asset_id, race_id));
CREATE TABLE IF NOT EXISTS prices (
 asset_id TEXT REFERENCES assets(id), race_id TEXT REFERENCES races(id), price TEXT,
 PRIMARY KEY(asset_id, race_id));
CREATE TABLE IF NOT EXISTS price_changes (
 asset_id TEXT REFERENCES assets(id), race_id TEXT REFERENCES races(id), change TEXT NOT NULL,
 PRIMARY KEY(asset_id, race_id));
CREATE TABLE IF NOT EXISTS snapshots (
 season INTEGER PRIMARY KEY, source TEXT, fetched_at TEXT, warnings TEXT);
"""


def bundle(dataset: Dataset) -> dict:
    return {"races": [asdict(x) for x in dataset.races], "assets": [asdict(x) for x in dataset.assets],
            "fantasy_scores": [asdict(x) for x in dataset.scores], "prices": [asdict(x) for x in dataset.prices],
            "price_changes": [asdict(x) for x in dataset.price_changes], "source": dataset.source,
            "fetched_at": dataset.fetched_at, "warnings": dataset.warnings}


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.executescript(SCHEMA)
        if "team" not in {r[1] for r in connection.execute("PRAGMA table_info(assets)")}:
            connection.execute("ALTER TABLE assets ADD COLUMN team TEXT NOT NULL DEFAULT ''")
        return connection

    def save(self, dataset: Dataset, season: int) -> None:
        dataset.check()
        if any(r.season != season for r in dataset.races):
            raise ValueError("Import one season per dataset; --season must match the races")
        con = self._connect()
        try:
            with con:
                # A full season snapshot replaces old rows so a newly missing score cannot
                # accidentally retain an obsolete value. Other seasons are untouched.
                for table in ("fantasy_scores", "prices", "price_changes"):
                    con.execute(f"DELETE FROM {table} WHERE race_id IN (SELECT id FROM races WHERE season=?)", (season,))
                con.execute("DELETE FROM races WHERE season=?", (season,))
                con.execute("DELETE FROM assets WHERE season=?", (season,))
                con.executemany("INSERT INTO races VALUES (?,?,?,?,?,?,?)", [
                    (r.id, r.season, r.round, r.name, r.date.isoformat(), r.completed, r.location) for r in dataset.races])
                con.executemany("INSERT INTO assets VALUES (?,?,?,?,?,?,?)", [
                    (a.id, season, a.code, a.name, a.kind, a.active, a.team) for a in dataset.assets])
                con.executemany("INSERT INTO fantasy_scores VALUES (?,?,?,?)", [
                    (s.asset_id, s.race_id, None if s.points is None else str(s.points), s.status) for s in dataset.scores])
                con.executemany("INSERT INTO prices VALUES (?,?,?)", [
                    (p.asset_id, p.race_id, None if p.price is None else str(p.price)) for p in dataset.prices])
                con.executemany("INSERT INTO price_changes VALUES (?,?,?)", [
                    (p.asset_id, p.race_id, str(p.change)) for p in dataset.price_changes])
                con.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)",
                            (season, dataset.source, dataset.fetched_at, json.dumps(dataset.warnings)))
        finally:
            con.close()

    def load(self, season: int) -> Dataset:
        if not self.path.exists():
            raise ValueError("No SQLite data yet. Run sync, use --local PATH, or run rollover online.")
        con = self._connect()
        try:
            meta = con.execute("SELECT * FROM snapshots WHERE season=?", (season,)).fetchone()
            if not meta:
                raise ValueError(f"No stored snapshot for {season}")
            data = {"source": meta["source"], "fetched_at": meta["fetched_at"], "warnings": json.loads(meta["warnings"])}
            for table in ("races", "assets"):
                data[table] = [dict(r) for r in con.execute(f"SELECT * FROM {table} WHERE season=?", (season,))]
            for table in ("fantasy_scores", "prices", "price_changes"):
                data[table] = [dict(r) for r in con.execute(
                    f"SELECT t.* FROM {table} t JOIN races r ON r.id=t.race_id WHERE r.season=?", (season,))]
            return parse_bundle(data)
        finally:
            con.close()
