import os
import time
import requests
from urllib.parse import urlencode

MAPILLARY_API = "https://graph.mapillary.com"

def nominatim_geocode(address: str, retries: int = 3, delay: float = 1.0):
    """Return (lat, lon, label) or (None, None, None) if not found."""
    if not address:
        return None, None, None
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": address, "format": "json", "limit": 1}
    headers = {"User-Agent": "MapExplorer/1.0 (educational-demo)"}
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=20)
            r.raise_for_status()
            data = r.json()
            if data:
                lat, lon = float(data[0]["lat"]), float(data[0]["lon"])
                label = data[0].get("display_name", address)
                return lat, lon, label
            return None, None, None
        except Exception:
            if attempt == retries - 1:
                return None, None, None
            time.sleep(delay)

def mapillary_nearest_image(lat: float, lon: float, token: str, radius_m: int = 150):
    """
    Robust image lookup with debug info.
    Returns dict {id, thumb_url, lat, lon, captured_at, debug} or None.
    """
    import math, requests

    def _extract_first(data):
        if data.get("data"):
            img = data["data"][0]
            geom = img.get("computed_geometry", {})
            coords = geom.get("coordinates") if isinstance(geom, dict) else None
            return {
                "id": img.get("id"),
                "thumb_url": img.get("thumb_1024_url"),
                "lat": coords[1] if coords else None,
                "lon": coords[0] if coords else None,
                "captured_at": img.get("captured_at"),
            }
        return None

    if not token or not token.startswith("MLY|"):
        return {"debug": "Missing or malformed Mapillary token (should start with MLY|)"}

    API = "https://graph.mapillary.com/images"
    fields = "id,thumb_1024_url,computed_geometry,captured_at,is_pano"

    # 1️⃣ Primary: closeto
    try:
        params = {
            "access_token": token,
            "fields": fields,
            "closeto": f"{lon},{lat}",
            "limit": 1,
        }
        r = requests.get(API, params=params, timeout=15)
        j = r.json()
        hit = _extract_first(j)
        if hit:
            hit["debug"] = f"closeto OK (HTTP {r.status_code})"
            return hit
        first_try_note = f"closeto returned no data (HTTP {r.status_code})"
    except Exception as e:
        first_try_note = f"closeto error: {e}"

    # 2️⃣ Fallback: bbox search around the point
    try:
        dlat = radius_m / 111_320.0
        dlon = radius_m / (111_320.0 * max(0.1, math.cos(math.radians(lat))))
        bbox = f"{lon-dlon},{lat-dlat},{lon+dlon},{lat+dlat}"
        params = {
            "access_token": token,
            "fields": fields,
            "bbox": bbox,
            "limit": 1,
        }
        r = requests.get(API, params=params, timeout=15)
        j = r.json()
        hit = _extract_first(j)
        if hit:
            hit["debug"] = f"bbox OK (HTTP {r.status_code})"
            return hit
        second_try_note = f"bbox returned no data (HTTP {r.status_code})"
    except Exception as e:
        second_try_note = f"bbox error: {e}"

    # 3️⃣ Larger bbox retry (double radius)
    try:
        dlat *= 2
        dlon *= 2
        bbox = f"{lon-dlon},{lat-dlat},{lon+dlon},{lat+dlat}"
        params = {
            "access_token": token,
            "fields": fields,
            "bbox": bbox,
            "limit": 1,
        }
        r = requests.get(API, params=params, timeout=15)
        j = r.json()
        hit = _extract_first(j)
        if hit:
            hit["debug"] = f"bbox x2 OK (HTTP {r.status_code})"
            return hit
        third_try_note = f"bbox x2 returned no data (HTTP {r.status_code})"
    except Exception as e:
        third_try_note = f"bbox x2 error: {e}"

    return {
        "debug": "No image found",
        "closeto": first_try_note,
        "bbox": second_try_note,
        "bbox_x2": third_try_note,
    }

def google_streetview_embed_url(lat: float, lon: float, api_key: str, fov: int = 80):
    """
    Returns an embeddable Google Street View iframe URL (Embed API v1).
    Note: requires a valid Google Maps API key with Embed/Street View enabled.
    """
    if not api_key:
        return None
    base = "https://www.google.com/maps/embed/v1/streetview"
    qs = urlencode({"key": api_key, "location": f"{lat},{lon}", "fov": fov})
    return f"{base}?{qs}"

def mapillary_image_deeplink(image_id: str):
    # Mapillary web deeplink (works with image "id" in modern Graph API)
    if not image_id:
        return None
    return f"https://www.mapillary.com/app/?focus=photo&pKey={image_id}"
