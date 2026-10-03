"""Best-effort nearby-hospital reference for a real emergency.

This is deliberately not ambulance dispatch or medical advice. The Zone 3 emergency agent
always alerts family and tells the elder to call 112 first; this lookup is extra context for
the caregiver when Google Places is configured.
"""
import math
import os

from raksha_common.agent import HOME_LAT, HOME_LNG
from raksha_common.http import request_json

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")


def distance_km(lat1, lng1, lat2, lng2):
    radius = 6371.0
    dlat, dlng = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return round(2 * radius * math.asin(math.sqrt(a)), 1)


def nearest_hospital():
    """Return (hospital, mocked). A missing/failed lookup never delays emergency handling."""
    if not GOOGLE_MAPS_API_KEY:
        return {}, True
    try:
        data = request_json(
            "https://places.googleapis.com/v1/places:searchNearby",
            method="POST",
            headers={
                "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
                "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location,places.nationalPhoneNumber,places.googleMapsUri,places.currentOpeningHours",
            },
            body={
                "includedTypes": ["hospital"],
                "maxResultCount": 1,
                "rankPreference": "DISTANCE",
                "locationRestriction": {"circle": {"center": {"latitude": HOME_LAT, "longitude": HOME_LNG}, "radius": 10000}},
            },
        )
        place = data["places"][0]
        location = place["location"]
        return {
            "name": place["displayName"]["text"],
            "address": place["formattedAddress"],
            "distance_km": distance_km(HOME_LAT, HOME_LNG, location["latitude"], location["longitude"]),
            "phone": place.get("nationalPhoneNumber", ""),
            "maps_url": place.get("googleMapsUri", ""),
            "open_now": (place.get("currentOpeningHours") or {}).get("openNow"),
        }, False
    except Exception as error:  # noqa: BLE001 - emergency handling has already started
        print(f"Emergency hospital lookup unavailable: {error!r}")
        return {}, True
