"""Unit tests for database.py"""

import os
import tempfile

import pytest

# Ensure the backend package is importable when running from the repo root.
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from database import (
    get_listing_count,
    get_listings,
    get_scrape_history,
    init_db,
    log_scrape,
    upsert_listings,
)


@pytest.fixture()
def db(tmp_path):
    """Return the path to a fresh, initialised temp database."""
    path = str(tmp_path / "test.db")
    init_db(db_path=path)
    return path


def _sample_listing(**kwargs):
    base = {
        "title": "Cozy 2BR Apartment",
        "price": "$1,800",
        "location": "Mission District",
        "bedrooms": "2",
        "sqft": "800",
        "url": "https://sfbay.craigslist.org/test/123",
        "date_posted": "2024-01-01T10:00:00",
        "date_scraped": "2024-01-02T08:00:00",
        "source": "craigslist",
        "city": "sfbay",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

class TestInitDb:
    def test_creates_tables(self, db):
        """Tables should exist after init_db."""
        import sqlite3
        conn = sqlite3.connect(db)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "listings" in tables
        assert "scrape_log" in tables

    def test_idempotent(self, db):
        """Calling init_db twice should not raise."""
        init_db(db_path=db)


# ---------------------------------------------------------------------------
# upsert_listings
# ---------------------------------------------------------------------------

class TestUpsertListings:
    def test_insert_new_listing(self, db):
        listings = [_sample_listing()]
        new_count = upsert_listings(listings, db_path=db)
        assert new_count == 1

    def test_duplicate_url_ignored(self, db):
        listing = _sample_listing()
        upsert_listings([listing], db_path=db)
        new_count = upsert_listings([listing], db_path=db)
        assert new_count == 0

    def test_multiple_listings(self, db):
        listings = [
            _sample_listing(url="https://sfbay.craigslist.org/test/1"),
            _sample_listing(url="https://sfbay.craigslist.org/test/2"),
        ]
        new_count = upsert_listings(listings, db_path=db)
        assert new_count == 2

    def test_partial_duplicate(self, db):
        listings = [
            _sample_listing(url="https://sfbay.craigslist.org/test/1"),
            _sample_listing(url="https://sfbay.craigslist.org/test/2"),
        ]
        upsert_listings([listings[0]], db_path=db)
        new_count = upsert_listings(listings, db_path=db)
        assert new_count == 1  # only the second one is new


# ---------------------------------------------------------------------------
# get_listings
# ---------------------------------------------------------------------------

class TestGetListings:
    def _seed(self, db):
        listings = [
            _sample_listing(
                url="https://sfbay.craigslist.org/test/1",
                city="sfbay",
                bedrooms="1",
            ),
            _sample_listing(
                url="https://sfbay.craigslist.org/test/2",
                city="sfbay",
                bedrooms="2",
            ),
            _sample_listing(
                url="https://newyork.craigslist.org/test/3",
                city="newyork",
                bedrooms="1",
            ),
        ]
        upsert_listings(listings, db_path=db)

    def test_returns_all_without_filter(self, db):
        self._seed(db)
        results = get_listings(db_path=db)
        assert len(results) == 3

    def test_filter_by_city(self, db):
        self._seed(db)
        results = get_listings(city="sfbay", db_path=db)
        assert len(results) == 2
        assert all(r["city"] == "sfbay" for r in results)

    def test_filter_by_bedrooms(self, db):
        self._seed(db)
        results = get_listings(bedrooms="1", db_path=db)
        assert len(results) == 2

    def test_limit_and_offset(self, db):
        self._seed(db)
        page1 = get_listings(limit=2, offset=0, db_path=db)
        page2 = get_listings(limit=2, offset=2, db_path=db)
        assert len(page1) == 2
        assert len(page2) == 1

    def test_empty_db_returns_empty_list(self, db):
        results = get_listings(db_path=db)
        assert results == []


# ---------------------------------------------------------------------------
# get_listing_count
# ---------------------------------------------------------------------------

class TestGetListingCount:
    def test_count_after_insert(self, db):
        upsert_listings([_sample_listing()], db_path=db)
        assert get_listing_count(db_path=db) == 1

    def test_count_by_city(self, db):
        upsert_listings(
            [
                _sample_listing(url="u1", city="sfbay"),
                _sample_listing(url="u2", city="newyork"),
            ],
            db_path=db,
        )
        assert get_listing_count(city="sfbay", db_path=db) == 1
        assert get_listing_count(city="newyork", db_path=db) == 1
        assert get_listing_count(db_path=db) == 2


# ---------------------------------------------------------------------------
# Scrape log
# ---------------------------------------------------------------------------

class TestScrapeLog:
    def test_log_and_retrieve(self, db):
        log_scrape(
            city="sfbay",
            listings_found=10,
            listings_new=5,
            started_at="2024-01-01T00:00:00",
            completed_at="2024-01-01T00:01:00",
            status="success",
            db_path=db,
        )
        history = get_scrape_history(db_path=db)
        assert len(history) == 1
        entry = history[0]
        assert entry["city"] == "sfbay"
        assert entry["listings_found"] == 10
        assert entry["listings_new"] == 5
        assert entry["status"] == "success"
        assert entry["error"] is None

    def test_log_error_entry(self, db):
        log_scrape(
            city="chicago",
            listings_found=0,
            listings_new=0,
            started_at="2024-01-01T00:00:00",
            completed_at="2024-01-01T00:00:05",
            status="error",
            error="Connection refused",
            db_path=db,
        )
        history = get_scrape_history(db_path=db)
        assert history[0]["status"] == "error"
        assert "Connection refused" in history[0]["error"]

    def test_history_limit(self, db):
        for i in range(15):
            log_scrape("sfbay", i, i, "s", "e", "success", db_path=db)
        history = get_scrape_history(limit=5, db_path=db)
        assert len(history) == 5
