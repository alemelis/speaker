"""Shared FastAPI helpers. SPAStaticFiles was previously copy-pasted 6 times."""

from typing import Any

from fastapi.staticfiles import StaticFiles


class SPAStaticFiles(StaticFiles):
    """Static handler that falls back to index.html for SPA client-side routes."""

    async def get_response(self, path: str, scope: dict[str, Any]):  # type: ignore[override]
        response = await super().get_response(path, scope)
        if response.status_code == 404:
            response = await super().get_response("index.html", scope)
        response.headers["Cache-Control"] = "no-store"
        return response
