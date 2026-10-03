"""Agent: location-finder (Zone 1). Find useful nearby destinations with Google Places API and
look up pincodes with the India Post pincode API (free, no key).

Both fall back to MOCKED responses when a key is missing or a call fails.
"""
import math
import os

from raksha_common.agent import HOME_LAT, HOME_LNG, result, run_tool
from raksha_common.http import request_json
from raksha_common.notify import notify_caregiver

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")  # TODO: set in template parameters

PLACE_TYPES = {
    "hospital": "hospital",
    "pharmacy": "pharmacy",
    "restaurant": "restaurant",
    "cafe": "cafe",
    "library": "library",
    "temple": "hindu_temple",
    "park": "park",
}
PLACE_NAMES_HI = {
    "hospital": "अस्पताल",
    "pharmacy": "दवाई की दुकान",
    "restaurant": "रेस्तराँ",
    "cafe": "कैफ़े",
    "library": "पुस्तकालय",
    "temple": "मंदिर",
    "park": "पार्क",
}
MOCK_PLACES = {  # MOCKED fallback
    "hospital": {"name": "Apollo Hospital", "address": "Jubilee Hills, Hyderabad 500033", "distance_km": 2.3},
    "pharmacy": {"name": "MedPlus Pharmacy", "address": "Road No. 36, Hyderabad 500033", "distance_km": 0.8},
    "restaurant": {"name": "Sarvi Restaurant", "address": "Banjara Hills, Hyderabad", "distance_km": 1.4, "rating": 4.2, "user_rating_count": 860},
    "cafe": {"name": "Roastery Coffee House", "address": "Jubilee Hills, Hyderabad", "distance_km": 1.1, "rating": 4.4, "user_rating_count": 520},
    "library": {"name": "City Central Library", "address": "Himayat Nagar, Hyderabad", "distance_km": 2.0},
    "temple": {"name": "Sri Venkateswara Temple", "address": "Jubilee Hills, Hyderabad", "distance_km": 1.7},
    "park": {"name": "Kasu Brahmananda Reddy National Park", "address": "Banjara Hills, Hyderabad", "distance_km": 2.5},
}


def distance_km(lat1, lng1, lat2, lng2):
    """Haversine distance."""
    r = 6371.0
    dlat, dlng = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 1)


def nearest_from_google(place_type):
    data = request_json(
        "https://places.googleapis.com/v1/places:searchNearby",
        method="POST",
        headers={
            "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location,places.nationalPhoneNumber,places.currentOpeningHours,places.rating,places.userRatingCount,places.googleMapsUri,places.websiteUri",
        },
        body={
            "includedTypes": [PLACE_TYPES[place_type]],
            "maxResultCount": 1,
            "rankPreference": "DISTANCE",
            "locationRestriction": {"circle": {"center": {"latitude": HOME_LAT, "longitude": HOME_LNG}, "radius": 10000}},
        },
    )
    place = data["places"][0]
    loc = place["location"]
    opening = place.get("currentOpeningHours") or {}
    return {
        "name": place["displayName"]["text"],
        "address": place["formattedAddress"],
        "distance_km": distance_km(HOME_LAT, HOME_LNG, loc["latitude"], loc["longitude"]),
        "phone": place.get("nationalPhoneNumber", ""),
        "open_now": opening.get("openNow"),
        "rating": place.get("rating"),
        "user_rating_count": place.get("userRatingCount"),
        "maps_url": place.get("googleMapsUri", ""),
        "website": place.get("websiteUri", ""),
    }


def find_nearest(args, event):
    place_type = args["place_type"] if args["place_type"] in PLACE_TYPES else "hospital"
    mocked = True
    place = MOCK_PLACES[place_type]
    if GOOGLE_MAPS_API_KEY:
        try:
            place, mocked = nearest_from_google(place_type), False
        except Exception as e:  # noqa: BLE001 - fall back to the mock
            print(f"Google Places failed, using mock: {e}")

    reply = f"सबसे पास का {PLACE_NAMES_HI[place_type]} {place['name']} है, जो {place['distance_km']} किलोमीटर दूर है।"
    if place.get("open_now") is True:
        reply += " यह अभी खुला हुआ दिख रहा है।"
    elif place.get("open_now") is False:
        reply += " यह अभी बंद दिख रहा है, जाने से पहले फ़ोन कर लें।"
    if place.get("phone"):
        reply += f" फ़ोन नंबर {place['phone']} है।"
    if place.get("rating") is not None:
        review_count = place.get("user_rating_count")
        review_text = f" {review_count} लोगों की राय के आधार पर" if review_count else ""
        reply += f" Google पर रेटिंग {place['rating']} स्टार है{review_text}।"
    if args.get("share_with_family"):
        notify_caregiver(
            f"Raksha: trusted destination - {place_type}",
            f"Your family member asked for the nearest {place_type}.\n\n"
            f"{place['name']}\n{place['address']}\n"
            f"Distance: {place['distance_km']} km\n"
            f"Phone: {place.get('phone') or 'not listed'}\n"
            f"Google rating: {place.get('rating') or 'not listed'} ({place.get('user_rating_count') or 0} ratings)\n"
            f"Map: {place.get('maps_url') or 'not listed'}\n"
            f"Open now: {place.get('open_now') if place.get('open_now') is not None else 'unknown'}\n\n"
            "Please confirm the destination suits them and that they have company if needed.",
        )
        reply += " मैंने पता और जानकारी आपके परिवार को भेज दी है। अगर आप चाहें तो उनसे साथ चलने को कहिए।"
    data = dict(place)
    if place.get("open_now") is False:
        # Tells the state machine this answer may not help: it may spend its one read-only
        # re-plan on an alternative (a closed pharmacy -> a hospital with a pharmacy).
        data["needs_alternative"] = f"The nearest {place_type}, {place['name']}, is closed right now."
    return result(reply, data, mocked=mocked, mock_reason="GOOGLE_MAPS_API_KEY not set or Places call failed" if mocked else None)


def lookup_pincode(args, event):
    pincode = "".join(ch for ch in args["pincode"] if ch.isdigit())
    if len(pincode) != 6:
        return result("यह पिनकोड सही नहीं लग रहा। कृपया छह अंकों का पिनकोड बताइए।", {"pincode": pincode})
    try:
        data = request_json(f"https://api.postalpincode.in/pincode/{pincode}")
        office = data[0]["PostOffice"][0]
        info = {"pincode": pincode, "area": office["Name"], "district": office["District"], "state": office["State"]}
        mocked = False
    except Exception as e:  # noqa: BLE001 - fall back to the mock
        print(f"Pincode API failed, using mock: {e}")
        info = {"pincode": pincode, "area": "Jubilee Hills", "district": "Hyderabad", "state": "Telangana"}
        mocked = True
    return result(
        f"पिनकोड {pincode} {info['area']}, {info['district']}, {info['state']} का है।",
        info,
        mocked=mocked,
        mock_reason="pincode API call failed" if mocked else None,
    )


TOOLS = {"find_nearest": find_nearest, "lookup_pincode": lookup_pincode}


def handler(event, context):
    return run_tool("location-finder", TOOLS, event)
