import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client

LABELS = ("positive", "complaint", "unsubscribe", "other")

def classify(reply: str) -> str:
    """Returns one of: positive | complaint | unsubscribe | other"""
    response = _get_client().chat.completions.create(
        model="gpt-4o-mini",  # ponytail: cheapest, fast, overkill for 1-label task
        max_tokens=10,
        messages=[
            {
                "role": "system",
                "content": (
                    "You classify customer WhatsApp replies to a review request. "
                    f"Reply with exactly one word from: {', '.join(LABELS)}.\n"
                    "positive = happy, will leave review, thanks\n"
                    "complaint = unhappy, bad experience, problem\n"
                    "unsubscribe = stop, remove me, don't message\n"
                    "other = anything else"
                )
            },
            {"role": "user", "content": reply}
        ],
    )
    label = response.choices[0].message.content.strip().lower()
    return label if label in LABELS else "other"


if __name__ == "__main__":
    tests = [
        ("Great service, will definitely leave a review!", "positive"),
        ("The technician was rude and the job was done poorly", "complaint"),
        ("Please stop messaging me", "unsubscribe"),
        ("Hello", "other"),
        ("Okay thanks", "positive"),
        ("I had a terrible experience", "complaint"),
    ]
    for text, expected in tests:
        result = classify(text)
        status = "✅" if result == expected else "❌"
        print(f"{status} '{text[:40]}' → {result} (expected {expected})")