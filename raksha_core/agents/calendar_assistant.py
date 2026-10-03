"""Agent: calendar-assistant.

Calendar reads are safe and autonomous. Creating an event is an external write, so the
registry places it in Zone 2 and Step Functions requires caregiver approval first.
No guests are invited automatically; the event is created only on the caregiver's calendar.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

from raksha_common.agent import result, run_tool
from raksha_common.notify import notify_caregiver

CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
CALENDAR_CLIENT_ID = os.environ.get("GOOGLE_CALENDAR_CLIENT_ID", "")
CALENDAR_CLIENT_SECRET = os.environ.get("GOOGLE_CALENDAR_CLIENT_SECRET", "")
CALENDAR_REFRESH_TOKEN = os.environ.get("GOOGLE_CALENDAR_REFRESH_TOKEN", "")
CALENDAR_TOKEN_URI = os.environ.get("GOOGLE_CALENDAR_TOKEN_URI", "https://oauth2.googleapis.com/token")
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]
# Every elder is in India: a time with no offset means IST, never UTC (which would be 5h30m early).
IST = timezone(timedelta(hours=5, minutes=30))


def _service():
    if not all((CALENDAR_CLIENT_ID, CALENDAR_CLIENT_SECRET, CALENDAR_REFRESH_TOKEN)):
        return None
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials(
        token=None,
        refresh_token=CALENDAR_REFRESH_TOKEN,
        token_uri=CALENDAR_TOKEN_URI,
        client_id=CALENDAR_CLIENT_ID,
        client_secret=CALENDAR_CLIENT_SECRET,
        scopes=CALENDAR_SCOPES,
    )
    credentials.refresh(Request())
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _iso(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    return parsed.isoformat()


def list_events(args, event):
    days = max(1, min(int(args.get("days", 7)), 30))
    try:
        service = _service()
        if service is None:
            raise RuntimeError("Google Calendar OAuth is not configured")
        now = datetime.now(timezone.utc)
        data = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=(now + timedelta(days=days)).isoformat(),
            maxResults=10,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = [
            {
                "summary": item.get("summary", "Untitled event"),
                "start": (item.get("start") or {}).get("dateTime") or (item.get("start") or {}).get("date", ""),
                "location": item.get("location", ""),
            }
            for item in data.get("items", [])
        ]
        if not events:
            return result(f"अगले {days} दिनों में कैलेंडर पर कोई कार्यक्रम नहीं है।", {"events": []})
        spoken = "। ".join(
            f"{item['summary']} {item['start']}" + (f", {item['location']}" if item["location"] else "")
            for item in events[:5]
        )
        return result(f"अगले {days} दिनों के कार्यक्रम: {spoken}।", {"events": events})
    except Exception as error:  # noqa: BLE001 - calendar failure must remain conversational
        print(f"Google Calendar read failed, using mock: {error}")
        return result(
            "अभी आपका कैलेंडर नहीं खुल पा रहा है। कृपया थोड़ी देर बाद फिर पूछिए।",
            {"events": []},
            mocked=True,
            mock_reason="Google Calendar OAuth is missing or the Calendar API call failed",
        )


def create_event(args, event):
    summary = args["summary"].strip()
    start = _iso(args["start"])
    start_dt = datetime.fromisoformat(start)
    end = _iso(args["end"]) if args.get("end") else (start_dt + timedelta(hours=1)).isoformat()
    if datetime.fromisoformat(end) <= datetime.fromisoformat(start):
        raise ValueError("event end must be after event start")

    try:
        service = _service()
        if service is None:
            raise RuntimeError("Google Calendar OAuth is not configured")
        body = {
            "summary": summary,
            "description": args.get("description", ""),
            "location": args.get("location", ""),
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }
        created = service.events().insert(calendarId=CALENDAR_ID, body=body, sendUpdates="none").execute()
        return result(
            f"आपका कार्यक्रम कैलेंडर में जोड़ दिया गया है: {summary}।",
            {"event_id": created.get("id", ""), "html_link": created.get("htmlLink", ""), "summary": summary},
        )
    except Exception as error:  # noqa: BLE001 - report failure without inventing success
        print(f"Google Calendar write failed: {error}")
        return result(
            "मैं अभी कैलेंडर में कार्यक्रम नहीं जोड़ पाई। कृपया थोड़ी देर बाद फिर कोशिश करें।",
            {"summary": summary},
            mocked=True,
            mock_reason="Google Calendar OAuth is missing or the Calendar API call failed",
        )


def create_video_call(args, event):
    """Create a caregiver-approved Calendar event with a Google Meet conference."""
    summary = args.get("summary") or f"Raksha family call with {args['recipient']}"
    start = _iso(args["start"])
    start_dt = datetime.fromisoformat(start)
    end = _iso(args["end"]) if args.get("end") else (start_dt + timedelta(minutes=30)).isoformat()
    if datetime.fromisoformat(end) <= start_dt:
        raise ValueError("video call end must be after start")

    try:
        service = _service()
        if service is None:
            raise RuntimeError("Google Calendar OAuth is not configured")
        attendees = [{"email": email} for email in args.get("attendee_emails", []) if "@" in email]
        body = {
            "summary": summary,
            "description": args.get("message", "A family video call arranged with Raksha."),
            "start": {"dateTime": start},
            "end": {"dateTime": end},
            "attendees": attendees,
            "conferenceData": {
                "createRequest": {
                    "requestId": str(uuid.uuid4()),
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            },
        }
        created = service.events().insert(
            calendarId=CALENDAR_ID,
            body=body,
            conferenceDataVersion=1,
            sendUpdates="all" if attendees else "none",
        ).execute()
        conference = created.get("conferenceData", {})
        entry_points = conference.get("entryPoints", [])
        meet_url = next((item.get("uri") for item in entry_points if item.get("entryPointType") == "video"), "")
        if not meet_url:
            raise RuntimeError("Google Calendar did not return a Meet link")
        if not attendees:
            notify_caregiver(
                "Raksha: family video call ready",
                f"A Google Meet call was arranged for {args['recipient']}.\n\nJoin: {meet_url}\n\n"
                "Please share the link with the family member.",
            )
        return result(
            f"आपके परिवार के साथ वीडियो कॉल का लिंक तैयार है। मैंने इसे {summary} के नाम से कैलेंडर में रख दिया है।",
            {"event_id": created.get("id", ""), "meet_url": meet_url, "attendees": [item["email"] for item in attendees]},
        )
    except Exception as error:  # noqa: BLE001 - never claim a call exists when creation failed
        print(f"Google Meet creation failed: {error}")
        return result(
            "मैं अभी वीडियो कॉल का लिंक नहीं बना पाई। कृपया थोड़ी देर बाद फिर कोशिश करें।",
            {"recipient": args.get("recipient", "")},
            mocked=True,
            mock_reason="Google Calendar OAuth or Meet conference creation failed",
        )
TOOLS = {"list_events": list_events, "create_event": create_event, "create_video_call": create_video_call}


def handler(event, context):
    return run_tool("calendar-assistant", TOOLS, event)
