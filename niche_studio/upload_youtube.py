"""Upload to your YouTube channel with the official Data API (OAuth).

One-time setup: Google Cloud console -> same project as your API key -> enable "YouTube Data API v3"
-> OAuth consent screen (External, add yourself as a test user) -> Credentials -> OAuth client ID
-> Desktop app -> download JSON as secrets/client_secret.json. First upload opens a browser to sign in.

Note: until Google audits your API project, videos uploaded through the API are locked to Private.
You can still make them public by hand in YouTube Studio, or apply for an audit
(https://support.google.com/youtube/contact/yt_api_form).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]


def _service(cfg: dict):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    root = cfg["_root"]
    yc = cfg.get("youtube", {})
    token = root / yc.get("oauth_token", "secrets/youtube_token.json")
    secret = root / yc.get("oauth_client_secret", "secrets/client_secret.json")
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not secret.exists():
                raise FileNotFoundError(f"Missing {secret}. See upload_youtube.py header for setup.")
            creds = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES).run_local_server(port=0)
        token.parent.mkdir(parents=True, exist_ok=True)
        token.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds)


def upload(cfg: dict, video: Path, idea: dict, publish_at: datetime | None = None, privacy: str | None = None,
           log=print) -> str:
    from googleapiclient.http import MediaFileUpload

    yc = cfg.get("youtube", {})
    yt = _service(cfg)
    title = idea["title"][:100]
    tags = [h.lstrip("#") for h in idea.get("hashtags", [])][:15]
    desc = idea.get("youtube_description", "")
    if idea.get("format") == "short" and "#shorts" not in desc.lower():
        desc += "\n\n#Shorts"
    desc += "\n" + " ".join(idea.get("hashtags", [])[:5])
    status = {"privacyStatus": privacy or yc.get("privacy", "private"),
              "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}
    if publish_at:
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at.astimezone().isoformat()
    body = {"snippet": {"title": title, "description": desc[:4900], "tags": tags,
                        "categoryId": str(yc.get("category_id", 23)),  # 23 = Comedy, 24 = Entertainment
                        "defaultLanguage": yc.get("upload_language", "en")},
            "status": status}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True))
    resp = None
    while resp is None:
        st, resp = req.next_chunk()
        if st:
            log(f"  YouTube upload {int(st.progress() * 100)}%")
    vid = resp["id"]
    thumb = video.with_name("thumbnail.jpg")
    if thumb.exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb))).execute()
        except Exception as e:  # needs a phone-verified channel
            log(f"  thumbnail not set: {e}")
    log(f"  YouTube: https://youtu.be/{vid} ({status['privacyStatus']})")
    return vid
