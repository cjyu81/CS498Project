from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from analytics import (
    db,
    get_query_demonstrations,
    get_reply_thread,
    get_reply_thread_examples,
    get_reply_trios,
    get_reply_lookup,
    get_stats,
    get_top_hashtags,
    get_top_locations,
    get_top_users,
    get_verified_engagement,
    search_hashtag,
    search_user,
)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="Eurovision Twitter Analytics",
    description="Dashboard and API for exploring the 2018 Eurovision Final Twitter dataset in MongoDB.",
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(BASE_DIR / "static" / "favicon.svg", media_type="image/svg+xml")


@app.get("/health")
def health():
    try:
        db.command("ping")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc
    return {"status": "ok"}


@app.get("/api/stats")
def stats():
    return get_stats()


@app.get("/api/top-users")
def top_users(limit: int = Query(default=20, ge=1, le=100)):
    return {"items": get_top_users(limit)}


@app.get("/api/top-locations")
def top_locations(limit: int = Query(default=20, ge=1, le=100)):
    return {"items": get_top_locations(limit)}


@app.get("/api/most-active-country")
def most_active_country(limit: int = Query(default=20, ge=1, le=100)):
    return {"items": get_top_locations(limit)}


@app.get("/api/top-hashtags")
def top_hashtags(limit: int = Query(default=50, ge=1, le=200)):
    return {"items": get_top_hashtags(limit)}


@app.get("/api/query-demonstrations")
def query_demonstrations():
    return {"items": get_query_demonstrations()}


@app.get("/api/verified-engagement")
def verified_engagement(limit: int = Query(default=20, ge=1, le=100)):
    return {"items": get_verified_engagement(limit)}


@app.get("/api/reply-thread")
def reply_thread(
    screenname: str = Query(..., min_length=1),
    limit_tweets: int = Query(default=3, ge=1, le=10),
    limit_replies: int = Query(default=50, ge=1, le=200),
):
    return {"items": get_reply_thread(screenname, limit_tweets=limit_tweets, limit_replies=limit_replies)}


@app.get("/api/reply-thread-examples")
def reply_thread_examples(limit: int = Query(default=5, ge=1, le=20)):
    return {"items": get_reply_thread_examples(limit)}


@app.get("/api/reply-lookup")
def reply_lookup(tweet_id: str | None = None, limit: int = Query(default=20, ge=1, le=100)):
    return {"items": get_reply_lookup(tweet_id=tweet_id, limit=limit)}


@app.get("/api/reply-trios")
def reply_trios(limit: int = Query(default=20, ge=1, le=100)):
    return {"items": get_reply_trios(limit)}


@app.get("/api/search-user")
def user_search(screenname: str = Query(..., min_length=1), limit: int = Query(default=20, ge=1, le=50)):
    return {"items": search_user(screenname, limit)}


@app.get("/api/search-hashtag")
def hashtag_search(tag: str = Query(..., min_length=1), limit: int = Query(default=20, ge=1, le=50)):
    return {"items": search_hashtag(tag, limit)}
