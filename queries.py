import os
from collections import Counter, defaultdict
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv("MONGODB_URI"))
db = client[os.getenv("MONGODB_DB", "twitter_db")]

POST_COLLECTIONS = ["tweets", "replies", "retweets"]


def header(title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def batched(items, size=1000):
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i:i + size]


def counts():
    header("Collection Counts")
    for c in ["tweets", "replies", "retweets", "users"]:
        print(f"{c}: {db[c].count_documents({})}")


def most_active_user(limit=10):
    header("Query 3: Most Active User")

    user_counts = Counter()

    for coll in POST_COLLECTIONS:
        print(f"Scanning {coll}...")
        for doc in db[coll].find({}, {"user_id": 1, "_id": 0}).batch_size(5000):
            if doc.get("user_id"):
                user_counts[doc["user_id"]] += 1

    top_ids = [uid for uid, _ in user_counts.most_common(limit)]
    users = {
        u["user_id"]: u
        for u in db.users.find(
            {"user_id": {"$in": top_ids}},
            {"_id": 0, "user_id": 1, "username": 1, "screenname": 1}
        )
    }

    for uid, count in user_counts.most_common(limit):
        u = users.get(uid, {})
        print({
            "user_id": uid,
            "username": u.get("username"),
            "screenname": u.get("screenname"),
            "total_posts": count
        })


def most_active_location(limit=10):
    header("Query 2: Most Active Location")

    user_counts = Counter()

    for coll in POST_COLLECTIONS:
        print(f"Scanning {coll}...")
        for doc in db[coll].find({}, {"user_id": 1, "_id": 0}).batch_size(5000):
            if doc.get("user_id"):
                user_counts[doc["user_id"]] += 1

    location_counts = Counter()
    user_ids = list(user_counts.keys())

    print("Joining user locations in Python...")
    for batch in batched(user_ids, 1000):
        for user in db.users.find(
            {"user_id": {"$in": batch}},
            {"_id": 0, "user_id": 1, "location": 1}
        ):
            loc = user.get("location")
            if loc:
                location_counts[loc] += user_counts[user["user_id"]]

    for loc, count in location_counts.most_common(limit):
        print({"location": loc, "post_count": count})


def top_hashtags(limit=25):
    header("Query 4: Top Hashtags")

    hashtag_counts = Counter()

    for coll in POST_COLLECTIONS:
        print(f"Scanning {coll}...")
        for doc in db[coll].find({}, {"hashtags": 1, "_id": 0}).batch_size(5000):
            for tag in doc.get("hashtags", []):
                hashtag_counts[tag] += 1

    for tag, count in hashtag_counts.most_common(limit):
        print({"hashtag": tag, "count": count})


def verified_engagement(limit=20):
    header("Query 6: Nature of Engagement for Verified Users")

    verified_users = {
        u["user_id"]: u
        for u in db.users.find(
            {"verified": True},
            {"_id": 0, "user_id": 1, "username": 1, "screenname": 1}
        )
    }

    engagement = defaultdict(Counter)

    print(f"Verified users found: {len(verified_users)}")

    for doc in db.tweets.find({}, {"user_id": 1, "_id": 0}).batch_size(5000):
        uid = doc.get("user_id")
        if uid in verified_users:
            engagement[uid]["plain_tweet"] += 1

    for doc in db.replies.find({}, {"user_id": 1, "_id": 0}).batch_size(5000):
        uid = doc.get("user_id")
        if uid in verified_users:
            engagement[uid]["reply"] += 1

    for doc in db.retweets.find({}, {"user_id": 1, "quote": 1, "_id": 0}).batch_size(5000):
        uid = doc.get("user_id")
        if uid in verified_users:
            if doc.get("quote"):
                engagement[uid]["quote"] += 1
            else:
                engagement[uid]["retweet"] += 1

    ranked = sorted(
        engagement.items(),
        key=lambda x: sum(x[1].values()),
        reverse=True
    )[:limit]

    for uid, type_counts in ranked:
        total = sum(type_counts.values())
        user = verified_users.get(uid, {})

        breakdown = []
        for typ, count in type_counts.items():
            breakdown.append({
                "type": typ,
                "count": count,
                "percentage": round((count / total) * 100, 2)
            })

        print({
            "username": user.get("username"),
            "screenname": user.get("screenname"),
            "total": total,
            "engagement_breakdown": breakdown
        })


def reply_lookup(limit=20):
    header("Query 1: Reply Lookup")

    for reply in db.replies.find(
        {},
        {"_id": 0, "tweet_id": 1, "in_reply_to_id": 1, "user_id": 1, "text": 1}
    ).limit(limit):
        print(reply)


if __name__ == "__main__":
    counts()

    most_active_location()
    most_active_user()
    top_hashtags()
    verified_engagement()

    # Optional demo query
    reply_lookup()