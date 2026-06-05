from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from .artwork.app import app as artwork_app
from .browse.app import app as browse_app
from .discover.app import app as discover_app
from .downloader.app import app as downloader_app
from .metadata.app import app as metadata_app
from .tags.app import app as tags_app

app = FastAPI(title="FOMO UI")


@app.get("/")
async def root():
    return RedirectResponse(url="/download/")


@app.get("/browse")
async def browse_redirect():
    return RedirectResponse(url="/browse/")


app.mount("/artwork", artwork_app)
app.mount("/browse", browse_app)
app.mount("/discover", discover_app)
app.mount("/download", downloader_app)
app.mount("/metadata", metadata_app)
app.mount("/tags", tags_app)
