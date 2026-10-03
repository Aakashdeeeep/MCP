"""Agent: care-coordinator (Zone 1). Medicine adherence logging, adherence summary, and
weather-aware activity advice.

Weather uses OpenWeatherMap when OPENWEATHER_API_KEY is set, otherwise a MOCKED
"rain" response.
"""
import os
import urllib.parse
from datetime import datetime, timezone

import boto3

from raksha_common.adherence import adherence_summary
from raksha_common.agent import HOME_LAT, HOME_LNG, PATIENT_ID, result, run_tool
from raksha_common.http import request_json

dynamodb = boto3.resource("dynamodb")
# TODO: set once AWS account exists (SAM injects these from template.yaml)
adherence_table = dynamodb.Table(os.environ.get("ADHERENCE_TABLE", "AdherenceLog-TODO"))
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")

BAD_WEATHER = {"Rain", "Drizzle", "Thunderstorm", "Snow"}


def log_dose(args, event):
    adherence_table.put_item(
        Item={
            "patient_id": PATIENT_ID,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "medicine": args["medicine"],
            "taken": bool(args["taken"]),
            "plan_id": event.get("plan_id", ""),
        }
    )
    if args["taken"]:
        return result(f"बहुत अच्छे! {args['medicine']} लेना दर्ज कर लिया है।", {"logged": True})
    return result(f"ठीक है, {args['medicine']} नहीं ली, यह लिख लिया है। कोशिश कीजिए अगली बार समय पर लें।", {"logged": True})


def get_adherence(args, event):
    summary = adherence_summary(PATIENT_ID, args.get("days") or 7)
    if summary is None:
        return result("अभी डॉक्टर की दवाइयों की सूची नहीं मिली है।", {})
    return result(
        f"पिछले {summary['days']} दिनों में आपने {summary['taken']} खुराक ली हैं और {summary['missed']} छूट गई हैं।",
        summary,
    )


def current_weather():
    """Returns (condition, temp_c, mocked)."""
    if OPENWEATHER_API_KEY:
        try:
            query = urllib.parse.urlencode(
                {"lat": HOME_LAT, "lon": HOME_LNG, "appid": OPENWEATHER_API_KEY, "units": "metric"}
            )
            data = request_json(f"https://api.openweathermap.org/data/2.5/weather?{query}")
            return data["weather"][0]["main"], data["main"]["temp"], False
        except Exception as e:  # noqa: BLE001 - fall back to the mock below
            print(f"OpenWeatherMap failed, using mock: {e}")
    return "Rain", 27.0, True  # MOCKED


def check_weather(args, event):
    condition, temp, mocked = current_weather()
    activity = args.get("activity") or "walk"
    if condition in BAD_WEATHER:
        reply = "आज बारिश का मौसम है, आज घर के अंदर ही टहल लीजिए।"
    elif temp >= 38:
        reply = "आज बहुत गर्मी है। बाहर जाना हो तो सुबह जल्दी या शाम को जाइए और पानी पीते रहिए।"
    else:
        reply = "आज मौसम ठीक है, आप आराम से टहलने जा सकते हैं।"
    return result(
        reply,
        {"condition": condition, "temp_c": temp, "activity": activity},
        mocked=mocked,
        mock_reason="OPENWEATHER_API_KEY not set or OpenWeatherMap call failed" if mocked else None,
    )


TOOLS = {"log_dose": log_dose, "get_adherence": get_adherence, "check_weather": check_weather}


def handler(event, context):
    return run_tool("care-coordinator", TOOLS, event)
