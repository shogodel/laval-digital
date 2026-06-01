import csv
import os
import logging
from pathlib import Path
from typing import Dict, List

import requests

logger = logging.getLogger(__name__)


def scrape_google_maps(
    business_type: str,
    city: str,
    max_results: int = 20,
) -> List[Dict]:
    """
    Search Google Maps Places API for local businesses.

    Args:
        business_type: Type of business to search for (e.g. "plumber", "dentist").
        city: City to search in (e.g. "Laval").
        max_results: Maximum number of results to return.

    Returns:
        List of dicts with keys: name, address, phone, website, rating,
        review_count, place_id.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")

    if api_key:
        try:
            return _maps_api_request(business_type, city, max_results, api_key)
        except Exception as e:
            logger.warning("Google Maps API failed: %s — falling back to sample data", e)
            return _sample_businesses(business_type, city)
    else:
        logger.info("No GOOGLE_MAPS_API_KEY set — using sample data for testing")
        return _sample_businesses(business_type, city)


def _maps_api_request(
    business_type: str,
    city: str,
    max_results: int,
    api_key: str,
) -> List[Dict]:
    """Call the Google Maps Places API and parse results."""
    results: List[Dict] = []
    query = f"{business_type} in {city}"

    params = {
        "query": query,
        "key": api_key,
        "region": "ca",
        "language": "en",
    }

    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "OK":
        logger.warning("Maps API returned status: %s", data.get("status"))
        return results

    for place in data.get("results", [])[:max_results]:
        name = place.get("name", "")
        address = place.get("formatted_address", "")
        rating = place.get("rating")
        review_count = place.get("user_ratings_total", 0)
        place_id = place.get("place_id", "")

        phone = ""
        website = ""
        if place_id:
            details = _get_place_details(place_id, api_key)
            phone = details.get("phone", "")
            website = details.get("website", "")

        results.append({
            "name": name,
            "address": address,
            "phone": phone,
            "website": website,
            "rating": rating,
            "review_count": review_count,
            "place_id": place_id,
        })

    return results


def _get_place_details(place_id: str, api_key: str) -> Dict:
    """Fetch phone number and website for a place."""
    url = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields": "formatted_phone_number,website",
        "key": api_key,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        return {
            "phone": result.get("formatted_phone_number", ""),
            "website": result.get("website", ""),
        }
    except Exception as e:
        logger.debug("Failed to fetch details for %s: %s", place_id, e)
        return {"phone": "", "website": ""}


def _sample_businesses(business_type: str, city: str) -> List[Dict]:
    """Return hardcoded sample data for testing when no API key is available."""
    samples = [
        {
            "name": f"{business_type.title()} Pro Laval",
            "address": f"123 Rue Principale, {city}, QC",
            "phone": "(450) 555-0101",
            "website": "",
            "rating": 4.2,
            "review_count": 47,
            "place_id": "sample_001",
        },
        {
            "name": f"Rapid {business_type.title()} Services",
            "address": f"456 Boulevard des Industries, {city}, QC",
            "phone": "(450) 555-0102",
            "website": f"https://rapid{business_type}.ca",
            "rating": 3.8,
            "review_count": 31,
            "place_id": "sample_002",
        },
        {
            "name": f"{business_type.title()} Express Inc.",
            "address": f"789 Avenue du Parc, {city}, QC",
            "phone": "(450) 555-0103",
            "website": "",
            "rating": 4.5,
            "review_count": 112,
            "place_id": "sample_003",
        },
        {
            "name": f"Expert {business_type.title()} Solutions",
            "address": f"321 Rue de la Gare, {city}, QC",
            "phone": "(450) 555-0104",
            "website": f"https://expert{business_type}solutions.ca",
            "rating": 3.5,
            "review_count": 8,
            "place_id": "sample_004",
        },
        {
            "name": f"Affordable {business_type.title()}",
            "address": f"654 Chemin du Lac, {city}, QC",
            "phone": "(450) 555-0105",
            "website": "",
            "rating": 4.7,
            "review_count": 85,
            "place_id": "sample_005",
        },
    ]
    return samples


def find_best_prospects(
    business_type: str,
    city: str,
    min_rating: float = 3.0,
    max_rating: float = 4.5,
    no_website_only: bool = True,
) -> List[Dict]:
    """
    Find the best prospect businesses for outreach.

    Filters Google Maps results by rating range and optionally by
    whether the business has no website. Results are sorted by
    review count ascending (fewer reviews = more likely to need help).

    Args:
        business_type: Type of business to search for.
        city: City to search in.
        min_rating: Minimum rating threshold (inclusive).
        max_rating: Maximum rating threshold (inclusive).
        no_website_only: If True, only include businesses with no website.

    Returns:
        Filtered and sorted list of prospect dicts.
    """
    businesses = scrape_google_maps(business_type, city, max_results=50)

    prospects = []
    for b in businesses:
        rating = b.get("rating") or 0
        if rating < min_rating or rating > max_rating:
            continue
        if no_website_only and b.get("website"):
            continue
        prospects.append(b)

    prospects.sort(key=lambda x: x.get("review_count", 0))
    return prospects


def export_to_csv(prospects: List[Dict], filename: str) -> str:
    """
    Export a list of prospect dicts to a CSV file.

    Creates the data/prospects/ directory if it doesn't exist.
    Returns the full path to the saved file.

    Args:
        prospects: List of prospect dicts with consistent keys.
        filename: Name for the CSV file (e.g. "plumbers_laval.csv").

    Returns:
        Absolute path to the saved CSV file.
    """
    output_dir = Path("/var/www/laval-digital/data/prospects")
    output_dir.mkdir(parents=True, exist_ok=True)

    filepath = output_dir / filename

    if not prospects:
        logger.warning("No prospects to export — writing empty CSV")
        filepath.write_text("")
        return str(filepath.resolve())

    fieldnames = list(prospects[0].keys())
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(prospects)

    logger.info("Exported %d prospects to %s", len(prospects), filepath)
    return str(filepath.resolve())
