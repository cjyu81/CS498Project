# Eurovision Twitter Analytics Dashboard

This project is a CS498 cloud data management prototype built on top of a MongoDB Atlas dataset derived from the Kaggle dataset "Twitter Data from 2018 Eurovision Final."

It includes:

- a MongoDB loader for the Kaggle JSON files
- reusable Python analytics functions
- a FastAPI backend
- a browser dashboard for exploring activity, hashtags, locations, verified-user engagement, and replies

## Project Structure

- [load_twitter_kaggle.py] loads a quota-safe subset into MongoDB Atlas
- [queries.py] runs the analytics in script form
- [analytics.py] contains reusable query logic and lightweight caching
- [app.py] serves the FastAPI API and dashboard
- [templates/index.html] is the dashboard UI
- [static/styles.css] contains the dashboard styling
- [static/favicon.svg] provides the browser favicon

## Requirements

- Python 3.10+
- A Conda environment with the required packages installed
- MongoDB Atlas connection info in `.env`
- Internet access to reach your Atlas cluster

Expected `.env` values:

```env
MONGODB_URI=...
MONGODB_DB=twitter_db
```

## How To Run

From the project folder:

```powershell
cd CS498Project
```

Activate your Conda environment first. Example:

```powershell
conda activate mongo
```

Install dependencies if needed:

```powershell
pip install -r requirements.txt
```

Start the dashboard:

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8010
```

Then open:

- [http://127.0.0.1:8010](http://127.0.0.1:8010) for the dashboard
- [http://127.0.0.1:8010/docs](http://127.0.0.1:8010/docs) for FastAPI interactive API docs

If port `8010` is busy on your machine, choose another port such as `8081`:

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8081
```

## Basic Usage

When the app loads, it automatically fetches live data from MongoDB and renders:

- overview cards for tweets, replies, retweets, and users
- a post-mix chart
- a top-hashtag chart
- most active users and top locations tables
- verified-user engagement summaries

The dashboard also includes three search tools:

1. Search by screenname
   Returns matching user documents from the `users` collection.
2. Search by hashtag
   Returns matching posts from `tweets`, `replies`, and `retweets`.
3. Reply lookup
   Returns reply records tied to a given `tweet_id`, or sample replies if left blank.

## API Endpoints

All analytics routes are available under `/api`.

- `GET /api/stats`
- `GET /api/top-users?limit=20`
- `GET /api/top-locations?limit=20`
- `GET /api/top-hashtags?limit=50`
- `GET /api/verified-engagement?limit=20`
- `GET /api/reply-lookup?tweet_id=...&limit=20`
- `GET /api/search-user?screenname=...`
- `GET /api/search-hashtag?tag=...`

Examples:

```text
GET /api/top-users?limit=10
GET /api/search-user?screenname=eurovision
GET /api/search-hashtag?tag=%23eurovision
GET /api/reply-lookup?tweet_id=9876543210
```

## Running The Original Scripts

To run the analytics script directly:

```powershell
python queries.py
```

To rerun the data loader:

```powershell
python load_twitter_kaggle.py
```

Note: the loader drops and rebuilds the database before loading the subset again.

## Notes

- Atlas free tier can be slow for large aggregations, so the analytics are implemented as Python-side streaming queries.
- The dashboard uses lightweight in-memory caching in `analytics.py` to avoid rerunning the heaviest scans on every request.
- If the home page loads but data does not appear, check `.env`, Atlas IP access settings, and whether the `mongo` environment has `pymongo`, `fastapi`, `jinja2`, and `uvicorn` installed.
