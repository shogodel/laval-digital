import os
import logging
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


def scrape_google_maps(
    business_type: str,
    city: str,
    max_results: int = 20,
) -> List[Dict]:
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
        })

    return results


def _get_place_details(place_id: str, api_key: str) -> Dict:
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
    samples = [
        {
            "name": f"{business_type.title()} Pro Laval",
            "address": f"123 Rue Principale, {city}, QC",
            "phone": "(450) 555-0101",
            "website": "",
            "rating": 4.2,
            "review_count": 47,
        },
        {
            "name": f"Rapid {business_type.title()} Services",
            "address": f"456 Boulevard des Industries, {city}, QC",
            "phone": "(450) 555-0102",
            "website": f"https://rapid{business_type}.ca",
            "rating": 3.8,
            "review_count": 31,
        },
        {
            "name": f"{business_type.title()} Express Inc.",
            "address": f"789 Avenue du Parc, {city}, QC",
            "phone": "(450) 555-0103",
            "website": "",
            "rating": 4.5,
            "review_count": 112,
        },
        {
            "name": f"Expert {business_type.title()} Solutions",
            "address": f"321 Rue de la Gare, {city}, QC",
            "phone": "(450) 555-0104",
            "website": f"https://expert{business_type}solutions.ca",
            "rating": 3.3,
            "review_count": 18,
        },
        {
            "name": f"Affordable {business_type.title()}",
            "address": f"654 Chemin du Lac, {city}, QC",
            "phone": "(450) 555-0105",
            "website": "",
            "rating": 4.7,
            "review_count": 85,
        },
    ]
    return samples


def find_best_prospects(
    business_type: str,
    city: str,
    min_rating: float = 3.5,
    max_rating: float = 4.5,
    no_website_only: bool = False,
) -> List[Dict]:
    businesses = scrape_google_maps(business_type, city, max_results=50)

    prospects = []
    for b in businesses:
        rating = b.get("rating") or 0
        if rating < min_rating or rating > max_rating:
            continue
        if no_website_only and b.get("website"):
            continue
        prospects.append(b)

    prospects.sort(key=lambda x: x.get("review_count", 0), reverse=True)
    return prospects


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    prospects = find_best_prospects(
        business_type="plumber",
        city="Laval",
        min_rating=3.0,
        max_rating=5.0,
        no_website_only=True,
    )

    print(f"\n{'='*60}")
    print(f"  Top {len(prospects)} Prospects — Plumbers in Laval")
    print(f"{'='*60}\n")

    for i, b in enumerate(prospects[:5], 1):
        print(f"  {i}. {b['name']}")
        print(f"     Address: {b['address']}")
        print(f"     Phone:   {b['phone']}")
        print(f"     Website: {b['website'] or 'N/A'}")
        print(f"     Rating:  {b['rating']} ({b['review_count']} reviews)")
        print()
