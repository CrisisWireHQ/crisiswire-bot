import os
import tweepy

_client = None


def client() -> tweepy.Client:
    global _client
    if _client is None:
        _client = tweepy.Client(
            consumer_key=os.environ["X_API_KEY"],
            consumer_secret=os.environ["X_API_SECRET"],
            access_token=os.environ["X_ACCESS_TOKEN"],
            access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
        )
    return _client


def post(text: str) -> dict:
    resp = client().create_tweet(text=text)
    return {"id": resp.data["id"], "text": text}
