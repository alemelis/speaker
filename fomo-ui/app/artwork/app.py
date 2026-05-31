from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from core.owntone import OwnToneClient

app = FastAPI(title="Artwork Proxy")
_client = OwnToneClient()


@app.get("/")
def proxy_artwork(u: str):
    if not u.startswith("/"):
        raise HTTPException(status_code=400, detail="Only relative OwnTone paths are allowed.")
    resp = _client.fetch_artwork(u)
    if resp.status_code != 200:
        raise HTTPException(status_code=404, detail="Artwork not found.")
    content_type = resp.headers.get("Content-Type", "image/jpeg")
    return StreamingResponse(resp.iter_content(chunk_size=8192), media_type=content_type)
