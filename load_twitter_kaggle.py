import os
import json
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv
from pymongo import MongoClient, WriteConcern
from pymongo.errors import BulkWriteError, OperationFailure

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("MONGODB_DB", "twitter_db")

if not MONGODB_URI:
    raise ValueError("Missing MONGODB_URI in .env")

DATASET_DIR = Path("raw_data/dataset")

# Atlas free tier is 512 MB. Stop before that so indexes can still fit.
MAX_STORAGE_MB_BEFORE_INDEXES = 360

# Smaller batches reduce chance of suddenly jumping over quota.
BATCH_SIZE = 1000

client = MongoClient(MONGODB_URI)
db = client[DB_NAME].with_options(write_concern=WriteConcern(w=1))


def get_db_size_mb() -> float:
    try:
        stats = db.command("dbStats")
        storage = stats.get("storageSize", 0)
        indexes = stats.get("indexSize", 0)
        return (storage + indexes) / (1024 * 1024)
    except Exception:
        return 0.0


def should_stop_loading() -> bool:
    size_mb = get_db_size_mb()
    return size_mb >= MAX_STORAGE_MB_BEFORE_INDEXES


def chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def iter_json_objects(file_path: Path) -> Iterable[dict[str, Any]]:
    text = file_path.read_text(encoding="utf-8", errors="ignore").strip()

    if not text:
        return

    try:
        parsed = json.loads(text)

        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    yield item
            return

        if isinstance(parsed, dict):
            yield parsed
            return

    except json.JSONDecodeError:
        pass

    with file_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    yield obj
            except json.JSONDecodeError:
                continue


def get_nested(d: dict, *keys, default=None):
    cur = d

    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]

    return cur


def extract_hashtags(tweet: dict) -> list[str]:
    hashtags = get_nested(tweet, "entities", "hashtags", default=[])
    out = []

    if isinstance(hashtags, list):
        for h in hashtags:
            if isinstance(h, dict):
                text = h.get("text")
                if text:
                    out.append(str(text).lower())
            elif isinstance(h, str):
                out.append(h.lower())

    return out


def normalize_user(tweet: dict) -> dict | None:
    user = tweet.get("user")

    if not isinstance(user, dict):
        return None

    user_id = user.get("id") or user.get("id_str")

    if user_id is None:
        return None

    return {
        "user_id": str(user_id),
        "username": user.get("name"),
        "screenname": user.get("screen_name"),
        "location": user.get("location"),
        "verified": bool(user.get("verified", False)),
        "followers_count": user.get("followers_count"),
        "friends_count": user.get("friends_count"),
        "statuses_count": user.get("statuses_count"),
    }


def normalize_base_fields(tweet: dict) -> dict:
    tweet_id = tweet.get("id") or tweet.get("id_str")
    user_id = get_nested(tweet, "user", "id") or get_nested(tweet, "user", "id_str")

    return {
        "tweet_id": str(tweet_id) if tweet_id is not None else None,
        "created_at": tweet.get("created_at"),
        "text": tweet.get("full_text") or tweet.get("text"),
        "user_id": str(user_id) if user_id is not None else None,
        "hashtags": extract_hashtags(tweet),
        "lang": tweet.get("lang"),
        "favorite_count": tweet.get("favorite_count"),
        "retweet_count": tweet.get("retweet_count"),
    }


def classify_tweet(tweet: dict) -> tuple[str | None, dict | None]:
    base = normalize_base_fields(tweet)

    if not base["tweet_id"] or not base["user_id"]:
        return None, None

    if "retweeted_status" in tweet:
        retweeted = tweet.get("retweeted_status", {})
        retweet_id = None

        if isinstance(retweeted, dict):
            retweet_id = retweeted.get("id") or retweeted.get("id_str")

        quoted_status = tweet.get("quoted_status")
        quote_text = None

        if isinstance(quoted_status, dict):
            quote_text = quoted_status.get("full_text") or quoted_status.get("text")

        return "retweets", {
            **base,
            "retweet_id": str(retweet_id) if retweet_id is not None else None,
            "quote": bool(tweet.get("is_quote_status", False)),
            "quoteText": quote_text,
        }

    in_reply_to_id = tweet.get("in_reply_to_status_id") or tweet.get("in_reply_to_status_id_str")

    if in_reply_to_id is not None:
        reply_user_id = tweet.get("in_reply_to_user_id") or tweet.get("in_reply_to_user_id_str")

        return "replies", {
            **base,
            "in_reply_to_id": str(in_reply_to_id),
            "in_reply_to_screen_name": tweet.get("in_reply_to_screen_name"),
            "in_reply_to_user_id": str(reply_user_id) if reply_user_id is not None else None,
        }

    return "tweets", base


def safe_insert_many(collection, docs):
    if not docs:
        return True

    try:
        collection.insert_many(docs, ordered=False)
        return True

    except BulkWriteError as e:
        errors = e.details.get("writeErrors", [])
        non_duplicate_errors = [err for err in errors if err.get("code") != 11000]

        if non_duplicate_errors:
            print(f"Non-duplicate write error in {collection.name}:")
            print(non_duplicate_errors[:3])
            return False

        return True

    except OperationFailure as e:
        print(f"\nMongoDB operation failed while writing {collection.name}:")
        print(e)
        return False


def flush_batches(batches):
    for collection_name, docs in batches.items():
        if docs:
            ok = safe_insert_many(db[collection_name], docs)
            docs.clear()
            if not ok:
                return False
    return True


def create_indexes():
    print("\nCreating minimal indexes...")

    # Keep only indexes needed for your project queries.
    db.users.create_index("user_id")
    db.users.create_index("screenname")

    db.tweets.create_index("user_id")

    db.replies.create_index("user_id")
    db.replies.create_index("in_reply_to_id")

    db.retweets.create_index("user_id")

    print("Indexes created.")


def main():
    if not DATASET_DIR.exists():
        raise FileNotFoundError(f"Dataset folder not found: {DATASET_DIR.resolve()}")

    print("Dropping old database...")
    client.drop_database(DB_NAME)

    files = sorted(DATASET_DIR.rglob("*.json"))

    if not files:
        raise FileNotFoundError("No .json files found under raw_data/dataset")

    print(f"Found {len(files)} JSON files")
    print(f"Target max storage before indexes: {MAX_STORAGE_MB_BEFORE_INDEXES} MB\n")

    batches = {
        "tweets": [],
        "replies": [],
        "retweets": [],
        "users": [],
    }

    seen_users = set()

    total_raw_seen = 0
    total_loaded_posts = 0
    skipped = 0

    counts = {
        "tweets": 0,
        "replies": 0,
        "retweets": 0,
        "users": 0,
    }

    stop = False

    for file_path in files:
        if stop:
            break

        print(f"Processing {file_path.name}")

        for raw in iter_json_objects(file_path):
            total_raw_seen += 1

            user_doc = normalize_user(raw)
            if user_doc and user_doc["user_id"] not in seen_users:
                seen_users.add(user_doc["user_id"])
                batches["users"].append(user_doc)
                counts["users"] += 1

            collection_name, tweet_doc = classify_tweet(raw)

            if not tweet_doc:
                skipped += 1
                continue

            batches[collection_name].append(tweet_doc)
            counts[collection_name] += 1
            total_loaded_posts += 1

            batch_full = any(len(docs) >= BATCH_SIZE for docs in batches.values())

            if batch_full:
                if not flush_batches(batches):
                    stop = True
                    break

                if total_loaded_posts % 25000 < BATCH_SIZE:
                    size_mb = get_db_size_mb()
                    print(
                        f"Loaded posts: {total_loaded_posts:,} | "
                        f"users: {counts['users']:,} | "
                        f"DB size: {size_mb:.1f} MB"
                    )

                if should_stop_loading():
                    print("\nReached storage target. Stopping load safely.")
                    stop = True
                    break

    flush_batches(batches)

    print("\nCreating indexes after subset load...")
    try:
        create_indexes()
    except OperationFailure as e:
        print("\nIndex creation failed, likely due to storage quota.")
        print("Lower MAX_STORAGE_MB_BEFORE_INDEXES to 320 and rerun.")
        print(e)

    print("\nFinal loaded subset summary:")
    print("raw records scanned:", total_raw_seen)
    print("loaded plain tweets:", db.tweets.count_documents({}))
    print("loaded replies:", db.replies.count_documents({}))
    print("loaded retweets:", db.retweets.count_documents({}))
    print("loaded users:", db.users.count_documents({}))
    print("skipped records:", skipped)
    print(f"final DB size estimate: {get_db_size_mb():.1f} MB")

    print("\nSample tweet:")
    print(db.tweets.find_one())

    print("\nSample reply:")
    print(db.replies.find_one())

    print("\nSample retweet:")
    print(db.retweets.find_one())

    print("\nSample user:")
    print(db.users.find_one())


if __name__ == "__main__":
    main()