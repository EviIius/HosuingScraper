"""Unit tests for scraper.py – all network calls are mocked."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scraper import _parse_new, _parse_old, scrape_craigslist_housing

# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

OLD_LISTING_HTML = """
<li class="result-row" data-pid="123">
  <p class="result-info">
    <a class="result-title hdrlnk" href="https://sfbay.craigslist.org/apa/123.html">
      Sunny 2BR near BART
    </a>
    <span class="result-meta">
      <span class="result-price">$2,200</span>
      <span class="result-hood"> (Mission District) </span>
      <span class="housing">2br - 900ft²</span>
      <time class="result-date" datetime="2024-01-15T10:00:00">Jan 15</time>
    </span>
  </p>
</li>
"""

NEW_LISTING_HTML = """
<li class="cl-search-result cl-search-view-mode-gallery">
  <div class="gallery-card">
    <a class="posting-title cl-app-anchor" href="https://sfbay.craigslist.org/apa/456.html">
      <span class="label">Modern Studio Downtown</span>
    </a>
    <span class="priceinfo">$1,650</span>
    <div class="meta">
      <span>SoMa</span>
      <span>1br</span>
      <span>550ft2</span>
      <time datetime="2024-01-16T08:00:00">Jan 16</time>
    </div>
  </div>
</li>
"""

EMPTY_LISTING_HTML = "<li class='result-row'></li>"


# ---------------------------------------------------------------------------
# _parse_old
# ---------------------------------------------------------------------------

class TestParseOld:
    def _parse(self, html):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        item = soup.find("li")
        return _parse_old(item)

    def test_title(self):
        result = self._parse(OLD_LISTING_HTML)
        assert result is not None
        assert "Sunny 2BR" in result["title"]

    def test_price(self):
        result = self._parse(OLD_LISTING_HTML)
        assert result["price"] == "$2,200"

    def test_location(self):
        result = self._parse(OLD_LISTING_HTML)
        assert "Mission" in result["location"]

    def test_bedrooms(self):
        result = self._parse(OLD_LISTING_HTML)
        assert result["bedrooms"] == "2"

    def test_sqft(self):
        result = self._parse(OLD_LISTING_HTML)
        assert result["sqft"] == "900"

    def test_url(self):
        result = self._parse(OLD_LISTING_HTML)
        assert "craigslist.org" in result["url"]

    def test_date_posted(self):
        result = self._parse(OLD_LISTING_HTML)
        assert result["date_posted"] == "2024-01-15T10:00:00"

    def test_returns_none_for_empty_item(self):
        result = self._parse(EMPTY_LISTING_HTML)
        assert result is None


# ---------------------------------------------------------------------------
# _parse_new
# ---------------------------------------------------------------------------

class TestParseNew:
    def _parse(self, html):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        item = soup.find("li")
        return _parse_new(item)

    def test_title(self):
        result = self._parse(NEW_LISTING_HTML)
        assert result is not None
        assert "Modern Studio" in result["title"]

    def test_price(self):
        result = self._parse(NEW_LISTING_HTML)
        assert result["price"] == "$1,650"

    def test_location(self):
        result = self._parse(NEW_LISTING_HTML)
        assert result["location"] == "SoMa"

    def test_bedrooms(self):
        result = self._parse(NEW_LISTING_HTML)
        assert result["bedrooms"] == "1"

    def test_sqft(self):
        result = self._parse(NEW_LISTING_HTML)
        assert result["sqft"] == "550"

    def test_url(self):
        result = self._parse(NEW_LISTING_HTML)
        assert "craigslist.org" in result["url"]

    def test_date_posted(self):
        result = self._parse(NEW_LISTING_HTML)
        assert result["date_posted"] == "2024-01-16T08:00:00"


# ---------------------------------------------------------------------------
# scrape_craigslist_housing (network mocked)
# ---------------------------------------------------------------------------

OLD_PAGE_HTML = f"""
<html><body>
  <ul id="search-results">
    {OLD_LISTING_HTML}
    {OLD_LISTING_HTML.replace('123', '124').replace('Sunny 2BR near BART', 'Bright Studio').replace('https://sfbay.craigslist.org/apa/123.html', 'https://sfbay.craigslist.org/apa/124.html')}
  </ul>
</body></html>
"""

NEW_PAGE_HTML = f"""
<html><body>
  <ul>
    {NEW_LISTING_HTML}
  </ul>
</body></html>
"""


class TestScrapeCraigslistHousing:
    def test_returns_list(self, mocker):
        mock_resp = mocker.MagicMock()
        mock_resp.text = OLD_PAGE_HTML
        mock_resp.raise_for_status = mocker.MagicMock()
        mocker.patch("scraper.requests.get", return_value=mock_resp)
        mocker.patch("scraper.time.sleep")  # don't actually wait

        results = scrape_craigslist_housing(city="sfbay", max_pages=1)
        assert isinstance(results, list)

    def test_enriches_with_metadata(self, mocker):
        mock_resp = mocker.MagicMock()
        mock_resp.text = OLD_PAGE_HTML
        mock_resp.raise_for_status = mocker.MagicMock()
        mocker.patch("scraper.requests.get", return_value=mock_resp)
        mocker.patch("scraper.time.sleep")

        results = scrape_craigslist_housing(city="sfbay", max_pages=1)
        for r in results:
            assert r["source"] == "craigslist"
            assert r["city"] == "sfbay"
            assert "date_scraped" in r

    def test_uses_new_structure_when_present(self, mocker):
        mock_resp = mocker.MagicMock()
        mock_resp.text = NEW_PAGE_HTML
        mock_resp.raise_for_status = mocker.MagicMock()
        mocker.patch("scraper.requests.get", return_value=mock_resp)
        mocker.patch("scraper.time.sleep")

        results = scrape_craigslist_housing(city="sfbay", max_pages=1)
        assert len(results) == 1
        assert "Modern Studio" in results[0]["title"]

    def test_handles_network_error_gracefully(self, mocker):
        import requests as req
        mocker.patch("scraper.requests.get", side_effect=req.RequestException("timeout"))
        mocker.patch("scraper.time.sleep")

        results = scrape_craigslist_housing(city="sfbay", max_pages=2)
        assert results == []

    def test_stops_when_no_items_found(self, mocker):
        empty_html = "<html><body><ul></ul></body></html>"
        mock_resp = mocker.MagicMock()
        mock_resp.text = empty_html
        mock_resp.raise_for_status = mocker.MagicMock()
        get_mock = mocker.patch("scraper.requests.get", return_value=mock_resp)
        mocker.patch("scraper.time.sleep")

        scrape_craigslist_housing(city="sfbay", max_pages=3)
        # Should stop after first page since no items found
        assert get_mock.call_count == 1
