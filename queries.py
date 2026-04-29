from analytics import (
    get_reply_thread,
    get_reply_thread_examples,
    get_reply_trios,
    get_reply_lookup,
    get_stats,
    get_top_hashtags,
    get_top_locations,
    get_top_users,
    get_verified_engagement,
)


def header(title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def counts():
    header("Supplementary: Collection Counts")
    stats = get_stats()
    for collection in ["tweets", "replies", "retweets", "users"]:
        print(f"{collection}: {stats[collection]}")


def reply_thread(screenname="Eurovision", limit_tweets=2, limit_replies=10):
    header("Query 1: Reply Thread")
    items = get_reply_thread(screenname, limit_tweets=limit_tweets, limit_replies=limit_replies)
    if not items:
        print({"screenname": screenname, "message": "No reply threads found for this screenname."})
        print("Suggested screen names with direct replies:")
        for example in get_reply_thread_examples():
            print(example)
        return

    for item in items:
        print({"root_tweet": item["root_tweet"], "reply_count": item["reply_count"]})
        for reply in item["thread"]:
            print(reply)


def most_active_user(limit=10):
    header("Query 3: Most Active User")
    for item in get_top_users(limit):
        print(item)


def most_active_location(limit=10):
    header("Query 2: Most Active Location")
    for item in get_top_locations(limit):
        print(item)


def top_hashtags(limit=25):
    header("Query 4: Top Hashtags")
    for item in get_top_hashtags(limit):
        print(item)


def verified_engagement(limit=20):
    header("Query 6: Nature of Engagement for Verified Users")
    for item in get_verified_engagement(limit):
        print(item)


def reply_trios(limit=10):
    header("Query 5: Reply Trios")
    for trio in get_reply_trios(limit):
        print(trio)


def reply_lookup(limit=20):
    header("Supplementary: Direct Reply Lookup")
    for reply in get_reply_lookup(limit=limit):
        print(reply)


if __name__ == "__main__":
    counts()
    reply_thread()
    most_active_location()
    most_active_user()
    top_hashtags()
    reply_trios()
    verified_engagement()
