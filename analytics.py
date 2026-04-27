import os
import time
from collections import Counter, defaultdict
from threading import Lock

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

POST_COLLECTIONS = ("tweets", "replies", "retweets")
COMMON_POST_FIELDS = {
    "_id": 0,
    "tweet_id": 1,
    "created_at": 1,
    "text": 1,
    "user_id": 1,
    "hashtags": 1,
    "lang": 1,
    "favorite_count": 1,
    "retweet_count": 1,
}

_cache = {}
_cache_lock = Lock()

client = MongoClient(os.getenv("MONGODB_URI"))
db = client[os.getenv("MONGODB_DB", "twitter_db")]


def _normalize_limit(limit: int, default: int, maximum: int) -> int:
    if limit is None:
        return default
    return max(1, min(int(limit), maximum))


def _cache_key(name: str, *parts):
    return (name, *parts)


def _with_cache(key, ttl_seconds: int, compute):
    now = time.time()

    with _cache_lock:
        cached = _cache.get(key)
        if cached and cached["expires_at"] > now:
            return cached["value"]

    value = compute()

    with _cache_lock:
        _cache[key] = {
            "value": value,
            "expires_at": now + ttl_seconds,
        }

    return value


def _top_user_counts():
    user_counts = Counter()

    for coll in POST_COLLECTIONS:
        for doc in db[coll].find({}, {"_id": 0, "user_id": 1}).batch_size(5000):
            user_id = doc.get("user_id")
            if user_id:
                user_counts[user_id] += 1

    return user_counts


def get_stats():
    key = _cache_key("stats")

    def compute():
        tweets = db.tweets.count_documents({})
        replies = db.replies.count_documents({})
        retweets = db.retweets.count_documents({})
        users = db.users.count_documents({})

        return {
            "tweets": tweets,
            "replies": replies,
            "retweets": retweets,
            "users": users,
            "total_posts": tweets + replies + retweets,
        }

    return _with_cache(key, 300, compute)


def get_top_users(limit=20):
    limit = _normalize_limit(limit, 20, 100)
    key = _cache_key("top_users", limit)

    def compute():
        user_counts = _top_user_counts()
        top_ids = [user_id for user_id, _ in user_counts.most_common(limit)]
        users = {
            user["user_id"]: user
            for user in db.users.find(
                {"user_id": {"$in": top_ids}},
                {"_id": 0, "user_id": 1, "username": 1, "screenname": 1, "verified": 1, "location": 1},
            )
        }

        return [
            {
                "rank": index,
                "user_id": user_id,
                "username": users.get(user_id, {}).get("username"),
                "screenname": users.get(user_id, {}).get("screenname"),
                "verified": bool(users.get(user_id, {}).get("verified")),
                "location": users.get(user_id, {}).get("location"),
                "total_posts": count,
            }
            for index, (user_id, count) in enumerate(user_counts.most_common(limit), start=1)
        ]

    return _with_cache(key, 600, compute)


def get_top_locations(limit=20):
    limit = _normalize_limit(limit, 20, 100)
    key = _cache_key("top_locations", limit)

    def compute():
        user_counts = _top_user_counts()
        location_counts = Counter()
        user_ids = list(user_counts.keys())

        for start in range(0, len(user_ids), 1000):
            batch = user_ids[start : start + 1000]
            for user in db.users.find(
                {"user_id": {"$in": batch}},
                {"_id": 0, "user_id": 1, "location": 1},
            ):
                location = user.get("location")
                if location:
                    location_counts[location] += user_counts[user["user_id"]]

        return [
            {
                "rank": index,
                "location": location,
                "post_count": count,
            }
            for index, (location, count) in enumerate(location_counts.most_common(limit), start=1)
        ]

    return _with_cache(key, 600, compute)


def get_top_hashtags(limit=50):
    limit = _normalize_limit(limit, 50, 200)
    key = _cache_key("top_hashtags", limit)

    def compute():
        hashtag_counts = Counter()

        for coll in POST_COLLECTIONS:
            for doc in db[coll].find({}, {"_id": 0, "hashtags": 1}).batch_size(5000):
                for tag in doc.get("hashtags", []):
                    if tag:
                        hashtag_counts[tag] += 1

        return [
            {
                "rank": index,
                "hashtag": tag,
                "count": count,
            }
            for index, (tag, count) in enumerate(hashtag_counts.most_common(limit), start=1)
        ]

    return _with_cache(key, 600, compute)


def get_verified_engagement(limit=20):
    limit = _normalize_limit(limit, 20, 100)
    key = _cache_key("verified_engagement", limit)

    def compute():
        verified_users = {
            user["user_id"]: user
            for user in db.users.find(
                {"verified": True},
                {"_id": 0, "user_id": 1, "username": 1, "screenname": 1},
            )
        }

        engagement = defaultdict(Counter)

        for doc in db.tweets.find({}, {"_id": 0, "user_id": 1}).batch_size(5000):
            user_id = doc.get("user_id")
            if user_id in verified_users:
                engagement[user_id]["plain_tweet"] += 1

        for doc in db.replies.find({}, {"_id": 0, "user_id": 1}).batch_size(5000):
            user_id = doc.get("user_id")
            if user_id in verified_users:
                engagement[user_id]["reply"] += 1

        for doc in db.retweets.find({}, {"_id": 0, "user_id": 1, "quote": 1}).batch_size(5000):
            user_id = doc.get("user_id")
            if user_id in verified_users:
                if doc.get("quote"):
                    engagement[user_id]["quote"] += 1
                else:
                    engagement[user_id]["retweet"] += 1

        ranked = sorted(
            engagement.items(),
            key=lambda item: sum(item[1].values()),
            reverse=True,
        )[:limit]

        output = []
        for index, (user_id, counts) in enumerate(ranked, start=1):
            total = sum(counts.values())
            user = verified_users.get(user_id, {})
            breakdown = []

            for entry_type in ("plain_tweet", "reply", "retweet", "quote"):
                count = counts.get(entry_type, 0)
                breakdown.append(
                    {
                        "type": entry_type,
                        "count": count,
                        "percentage": round((count / total) * 100, 2) if total else 0,
                    }
                )

            output.append(
                {
                    "rank": index,
                    "user_id": user_id,
                    "username": user.get("username"),
                    "screenname": user.get("screenname"),
                    "total": total,
                    "engagement_breakdown": breakdown,
                }
            )

        return output

    return _with_cache(key, 600, compute)


def get_reply_lookup(tweet_id=None, limit=20):
    limit = _normalize_limit(limit, 20, 100)
    query = {}
    sort = None

    if tweet_id:
        query["$or"] = [
            {"tweet_id": str(tweet_id)},
            {"in_reply_to_id": str(tweet_id)},
        ]
        sort = [("created_at", 1)]

    cursor = db.replies.find(
        query,
        {
            **COMMON_POST_FIELDS,
            "in_reply_to_id": 1,
            "in_reply_to_screen_name": 1,
            "in_reply_to_user_id": 1,
        },
    )

    if sort:
        cursor = cursor.sort(sort)

    return list(cursor.limit(limit))


def search_user(screenname: str, limit=20):
    limit = _normalize_limit(limit, 20, 50)
    if not screenname:
        return []

    query = {"screenname": {"$regex": screenname, "$options": "i"}}
    return list(
        db.users.find(
            query,
            {
                "_id": 0,
                "user_id": 1,
                "username": 1,
                "screenname": 1,
                "location": 1,
                "verified": 1,
                "followers_count": 1,
                "friends_count": 1,
                "statuses_count": 1,
            },
        ).limit(limit)
    )


def search_hashtag(tag: str, limit=20):
    limit = _normalize_limit(limit, 20, 50)
    if not tag:
        return []

    normalized = tag.lower().lstrip("#")
    results = []

    for coll in POST_COLLECTIONS:
        cursor = db[coll].find(
            {"hashtags": normalized},
            COMMON_POST_FIELDS,
        ).limit(limit)

        for doc in cursor:
            results.append({"collection": coll, **doc})
            if len(results) >= limit:
                return results

    return results
