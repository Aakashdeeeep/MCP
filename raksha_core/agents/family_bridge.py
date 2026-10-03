"""Agent: family-bridge (Zone 1). Ask family to call, pass on a message, read the news.

News uses NewsAPI when NEWS_API_KEY is set. Otherwise, or if the call fails, it falls back
to MOCKED headlines. NewsAPI has no Hindi-language feed, so it reads top Indian headlines
(English); Polly's Kajal voice speaks Hinglish.
"""
import os
import urllib.parse

from raksha_common.agent import result, run_tool
from raksha_common.http import request_json
from raksha_common.notify import notify_caregiver

NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "")  # TODO: set in template parameters

MOCK_HEADLINES = [  # MOCKED fallback
    "Monsoon brings relief across several states",
    "Indian cricket team wins series opener",
    "New health scheme announced for senior citizens",
]


def request_call(args, event):
    recipient = args["recipient"]
    notify_caregiver(
        "Raksha: please call back",
        f"Your family member asked Raksha for a call from: {recipient}. Please call them when you can.",
    )
    return result("ठीक है, मैंने संदेश भेज दिया है। वे जल्दी ही आपको फ़ोन करेंगे।", {"recipient": recipient})


def share_update(args, event):
    notify_caregiver("Raksha: message from your family member", args["message"])
    return result("आपका संदेश परिवार को भेज दिया है।", {"message": args["message"]})


def fetch_news(args, event):
    if NEWS_API_KEY:
        try:
            query = {"country": "in", "pageSize": 3, "apiKey": NEWS_API_KEY}
            if args.get("topic"):
                query["q"] = args["topic"]
            data = request_json(
                "https://newsapi.org/v2/top-headlines?" + urllib.parse.urlencode(query),
                headers={"User-Agent": "raksha-os-hackathon"},
            )
            headlines = [a["title"].rsplit(" - ", 1)[0] for a in data.get("articles", [])][:3]
            if not headlines:
                fallback_query = {
                    "q": args.get("topic") or "India",
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 3,
                    "apiKey": NEWS_API_KEY,
                }
                fallback = request_json(
                    "https://newsapi.org/v2/everything?" + urllib.parse.urlencode(fallback_query),
                    headers={"User-Agent": "raksha-os-hackathon"},
                )
                headlines = [a["title"].rsplit(" - ", 1)[0] for a in fallback.get("articles", [])][:3]
            if headlines:
                return result("आज की मुख्य ख़बरें: " + "। ".join(headlines) + "।", {"headlines": headlines})
        except Exception as e:  # noqa: BLE001 - fall back to the mock below
            print(f"NewsAPI failed, using mock: {e}")
    return result(
        "आज की मुख्य ख़बरें: " + "। ".join(MOCK_HEADLINES) + "।",
        {"headlines": MOCK_HEADLINES},
        mocked=True,
        mock_reason="NEWS_API_KEY not set or NewsAPI call failed",
    )


TOOLS = {"request_call": request_call, "share_update": share_update, "fetch_news": fetch_news}


def handler(event, context):
    return run_tool("family-bridge", TOOLS, event)
