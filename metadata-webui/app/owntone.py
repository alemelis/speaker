import os

import requests


def _candidate_endpoints(base_url: str) -> list[str]:
    if base_url.endswith("/api"):
        return [
            f"{base_url}/update",
            f"{base_url}/rescan",
        ]

    return [
        f"{base_url}/api/update",
        f"{base_url}/api/rescan",
    ]


def trigger_rescan() -> dict[str, str | bool]:
    base_url = os.getenv("OWNTONE_BASE", "http://owntone:3689").rstrip("/")
    endpoints = _candidate_endpoints(base_url)
    errors: list[str] = []

    for endpoint in endpoints:
        try:
            response = requests.put(endpoint, timeout=10)
            response.raise_for_status()
            return {
                "ok": True,
                "endpoint": endpoint,
                "message": "Owntone rescan triggered.",
            }
        except requests.RequestException as exc:
            errors.append(f"{endpoint}: {exc}")

    return {
        "ok": False,
        "endpoint": endpoints[0],
        "message": " | ".join(errors),
    }
