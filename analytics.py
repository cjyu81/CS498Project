import os
import json
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


def _top_users_pipeline(limit: int):
    return [
        {"$project": {"_id": 0, "user_id": 1}},
        {"$unionWith": {"coll": "replies", "pipeline": [{"$project": {"_id": 0, "user_id": 1}}]}},
        {"$unionWith": {"coll": "retweets", "pipeline": [{"$project": {"_id": 0, "user_id": 1}}]}},
        {"$match": {"user_id": {"$ne": None}}},
        {"$group": {"_id": "$user_id", "total_posts": {"$sum": 1}}},
        {"$sort": {"total_posts": -1}},
        {"$limit": limit},
        {"$lookup": {"from": "users", "localField": "_id", "foreignField": "user_id", "as": "user"}},
        {"$unwind": {"path": "$user", "preserveNullAndEmptyArrays": True}},
        {
            "$project": {
                "_id": 0,
                "user_id": "$_id",
                "username": "$user.username",
                "screenname": "$user.screenname",
                "verified": "$user.verified",
                "location": "$user.location",
                "total_posts": 1,
            }
        },
    ]


def _top_hashtags_pipeline(limit: int):
    return [
        {"$project": {"_id": 0, "hashtags": 1}},
        {"$unionWith": {"coll": "replies", "pipeline": [{"$project": {"_id": 0, "hashtags": 1}}]}},
        {"$unionWith": {"coll": "retweets", "pipeline": [{"$project": {"_id": 0, "hashtags": 1}}]}},
        {"$unwind": "$hashtags"},
        {"$match": {"hashtags": {"$ne": None, "$ne": ""}}},
        {"$group": {"_id": "$hashtags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "hashtag": "$_id", "count": 1}},
    ]


def _run_pipeline(pipeline):
    return list(db.tweets.aggregate(pipeline, allowDiskUse=True, maxTimeMS=120000))


def _run_replies_pipeline(pipeline):
    return list(db.replies.aggregate(pipeline, allowDiskUse=True, maxTimeMS=120000))


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
        items = _run_pipeline(_top_users_pipeline(limit))
        return [
            {
                "rank": index,
                **item,
                "verified": bool(item.get("verified")),
            }
            for index, item in enumerate(items, start=1)
        ]

    return _with_cache(key, 600, compute)


def get_top_locations(limit=20):
    limit = _normalize_limit(limit, 20, 100)
    key = _cache_key("top_locations", limit)

    def compute():
        items = list(
            db.tweets.aggregate(
                [
                    {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "user_id", "as": "user"}},
                    {"$unwind": "$user"},
                    {"$match": {"user.location": {"$nin": [None, ""]}}},
                    {"$group": {"_id": "$user.location", "tweet_count": {"$sum": 1}}},
                    {"$sort": {"tweet_count": -1}},
                    {"$limit": limit},
                    {"$project": {"_id": 0, "location": "$_id", "tweet_count": 1}},
                ],
                allowDiskUse=True,
                maxTimeMS=120000,
            )
        )
        return [
            {
                "rank": index,
                "location": item["location"],
                "post_count": item["tweet_count"],
            }
            for index, item in enumerate(items, start=1)
        ]

    return _with_cache(key, 600, compute)


def get_top_hashtags(limit=50):
    limit = _normalize_limit(limit, 50, 200)
    key = _cache_key("top_hashtags", limit)

    def compute():
        items = _run_pipeline(_top_hashtags_pipeline(limit))
        return [
            {
                "rank": index,
                **item,
            }
            for index, item in enumerate(items, start=1)
        ]

    return _with_cache(key, 600, compute)


def get_query_demonstrations():
    key = _cache_key("query_demonstrations")

    def compute():
        top_users_limit = 5
        top_hashtags_limit = 5

        top_users_pipeline = _top_users_pipeline(top_users_limit)
        top_hashtags_pipeline = _top_hashtags_pipeline(top_hashtags_limit)

        return [
            {
                "id": "most-active-users",
                "title": "Query 3: Most Active User",
                "summary": "MongoDB aggregates three post collections, groups by user_id, sorts by post volume, and joins user profile data.",
                "execution_model": "MongoDB aggregation pipeline",
                "endpoint": f"/api/top-users?limit={top_users_limit}",
                "pipeline": top_users_pipeline,
                "pipeline_pretty": "tweets\n-> unionWith(replies)\n-> unionWith(retweets)\n-> group by user_id\n-> sort by total_posts desc\n-> limit 5\n-> lookup users\n-> project username, screenname, total_posts",
                "results": get_top_users(top_users_limit),
            },
            {
                "id": "top-hashtags",
                "title": "Query 4: Top Hashtags",
                "summary": "MongoDB unions hashtags from tweets, replies, and retweets, unwinds the arrays, groups counts, and returns the most frequent tags.",
                "execution_model": "MongoDB aggregation pipeline",
                "endpoint": f"/api/top-hashtags?limit={top_hashtags_limit}",
                "pipeline": top_hashtags_pipeline,
                "pipeline_pretty": "tweets\n-> unionWith(replies)\n-> unionWith(retweets)\n-> unwind hashtags\n-> group by hashtag\n-> sort by count desc\n-> limit 5\n-> project hashtag, count",
                "results": get_top_hashtags(top_hashtags_limit),
            },
        ]

    return _with_cache(key, 600, compute)


def get_reply_thread(screenname: str, limit_tweets=3, limit_replies=50):
    limit_tweets = _normalize_limit(limit_tweets, 3, 10)
    limit_replies = _normalize_limit(limit_replies, 50, 200)
    if not screenname:
        return []

    pipeline = [
        {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "user_id", "as": "user"}},
        {"$unwind": "$user"},
        {"$match": {"user.screenname": {"$regex": f"^{screenname}$", "$options": "i"}}},
        {"$sort": {"created_at": 1}},
        {"$limit": limit_tweets},
        {
            "$graphLookup": {
                "from": "replies",
                "startWith": "$tweet_id",
                "connectFromField": "tweet_id",
                "connectToField": "in_reply_to_id",
                "as": "thread_replies",
                "depthField": "depth",
                "maxDepth": 8,
            }
        },
        {
            "$project": {
                "_id": 0,
                "tweet_id": 1,
                "created_at": 1,
                "text": 1,
                "user_id": 1,
                "screenname": "$user.screenname",
                "username": "$user.username",
                "thread_replies": 1,
            }
        },
    ]

    threads = _run_pipeline(pipeline)
    user_ids = set()
    for thread in threads:
        for reply in thread.get("thread_replies", []):
            if reply.get("user_id"):
                user_ids.add(reply["user_id"])

    users = {
        user["user_id"]: user
        for user in db.users.find(
            {"user_id": {"$in": list(user_ids)}},
            {"_id": 0, "user_id": 1, "username": 1, "screenname": 1},
        )
    }

    output = []
    for thread in threads:
        ordered_replies = sorted(thread.get("thread_replies", []), key=lambda reply: reply.get("created_at", ""))
        replies = []
        for reply in ordered_replies[:limit_replies]:
            user = users.get(reply.get("user_id"), {})
            replies.append(
                {
                    "tweet_id": reply.get("tweet_id"),
                    "in_reply_to_id": reply.get("in_reply_to_id"),
                    "created_at": reply.get("created_at"),
                    "text": reply.get("text"),
                    "user_id": reply.get("user_id"),
                    "username": user.get("username"),
                    "screenname": user.get("screenname"),
                    "depth": reply.get("depth", 0),
                }
            )

        output.append(
            {
                "root_tweet": {
                    "tweet_id": thread.get("tweet_id"),
                    "created_at": thread.get("created_at"),
                    "text": thread.get("text"),
                    "user_id": thread.get("user_id"),
                    "username": thread.get("username"),
                    "screenname": thread.get("screenname"),
                },
                "reply_count": len(thread.get("thread_replies", [])),
                "thread": replies,
            }
        )

    return output


def get_reply_thread_examples(limit=5):
    limit = _normalize_limit(limit, 5, 20)
    key = _cache_key("reply_thread_examples", limit)

    def compute():
        pipeline = [
            {"$match": {"in_reply_to_id": {"$ne": None}, "in_reply_to_screen_name": {"$nin": [None, ""]}}},
            {"$group": {"_id": {"tweet_id": "$in_reply_to_id", "screenname": "$in_reply_to_screen_name"}, "direct_reply_count": {"$sum": 1}}},
            {"$sort": {"direct_reply_count": -1}},
            {"$limit": limit},
            {"$project": {"_id": 0, "screenname": "$_id.screenname", "tweet_id": "$_id.tweet_id", "direct_reply_count": 1}},
        ]
        return _run_replies_pipeline(pipeline)

    return _with_cache(key, 600, compute)


def get_reply_trios(limit=20):
    limit = _normalize_limit(limit, 20, 100)
    key = _cache_key("reply_trios", limit)

    def compute():
        edges = _run_replies_pipeline(
            [
                {
                    "$match": {
                        "user_id": {"$ne": None},
                        "in_reply_to_user_id": {"$ne": None},
                        "$expr": {"$ne": ["$user_id", "$in_reply_to_user_id"]},
                    }
                },
                {"$group": {"_id": {"replier": "$user_id", "replied_to": "$in_reply_to_user_id"}}},
                {"$project": {"_id": 0, "replier": "$_id.replier", "replied_to": "$_id.replied_to"}},
            ]
        )

        directed = {(edge["replier"], edge["replied_to"]) for edge in edges}
        mutual_pairs = set()
        for replier, replied_to in directed:
            if (replied_to, replier) in directed:
                pair = tuple(sorted((replier, replied_to)))
                mutual_pairs.add(pair)

        adjacency = defaultdict(set)
        for user_a, user_b in mutual_pairs:
            adjacency[user_a].add(user_b)
            adjacency[user_b].add(user_a)

        trio_ids = []
        for user_a in sorted(adjacency):
            for user_b in sorted(candidate for candidate in adjacency[user_a] if candidate > user_a):
                common = sorted(candidate for candidate in adjacency[user_a].intersection(adjacency[user_b]) if candidate > user_b)
                for user_c in common:
                    trio_ids.append((user_a, user_b, user_c))
                    if len(trio_ids) >= limit:
                        break
                if len(trio_ids) >= limit:
                    break
            if len(trio_ids) >= limit:
                break

        user_ids = {user_id for trio in trio_ids for user_id in trio}
        users = {
            user["user_id"]: user
            for user in db.users.find(
                {"user_id": {"$in": list(user_ids)}},
                {"_id": 0, "user_id": 1, "username": 1, "screenname": 1},
            )
        }

        return [
            {
                "rank": index,
                "userA": users.get(user_a, {}).get("screenname"),
                "userB": users.get(user_b, {}).get("screenname"),
                "userC": users.get(user_c, {}).get("screenname"),
                "userA_id": user_a,
                "userB_id": user_b,
                "userC_id": user_c,
            }
            for index, (user_a, user_b, user_c) in enumerate(trio_ids, start=1)
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
