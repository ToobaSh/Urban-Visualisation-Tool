import os
import math
import json
import base64
from datetime import datetime

import requests
import streamlit as st
from dotenv import load_dotenv
from streamlit_folium import st_folium
import folium

# utils.py must provide at least these:
from utils import (
    nominatim_geocode,
    google_streetview_embed_url,
)

# ======================================
# Config & secrets
# ======================================

st.set_page_config(
    page_title="Intelligent Urban Visualization Tool",
    page_icon="🧭",
    layout="wide",
)

load_dotenv()

MAPILLARY_TOKEN = os.getenv("MAPILLARY_TOKEN", "")
GOOGLE_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

# ======================================
# Mapillary helpers (from your first app)
# ======================================

MAP_FIELDS = "id,computed_geometry,thumb_1024_url,thumb_2048_url,captured_at,is_pano"


def _deg_for_meters(lat_deg: float, meters: float):
    """Approximate latitude/longitude offsets in degrees for a distance in meters."""
    dlat = meters / 111_320.0
    dlon = dlat * math.cos(math.radians(lat_deg))
    return dlat, dlon


def _haversine_m(lat1, lon1, lat2, lon2):
    """Distance in meters between two lat/lon points using the Haversine formula."""
    from math import radians, sin, cos, asin, sqrt

    R = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 2 * R * asin(sqrt(a))


def mapillary_find_best(
    lat: float,
    lon: float,
    token: str,
    radii_m=None,
    require_pano: bool = False,
):
    """
    Find the best Mapillary image near a point.

    - If require_pano=True: prefer panoramic images (is_pano=True).
    - radii_m: list of radii (in meters) to search with a bbox fallback.

    Returns:
        (thumb_url, meta_dict) or (None, None) if nothing found.
    """
    if not token or not token.startswith("MLY|"):
        return None, None

    if radii_m is None:
        radii_m = (150, 300, 600, 1200, 3000, 6000, 10000)

    base = "https://graph.mapillary.com/images"

    def rank_items(items):
        """
        Rank images:
        - panoramic images first
        - then by distance (closest first)
        """
        ranked = []
        for it in items:
            geom = (it.get("computed_geometry") or {}).get("coordinates")
            if isinstance(geom, (list, tuple)) and len(geom) == 2:
                dist = _haversine_m(lat, lon, geom[1], geom[0])
            else:
                dist = float("inf")
            ranked.append((bool(it.get("is_pano")), dist, it))
        ranked.sort(key=lambda x: (-int(x[0]), x[1]))  # pano first, then distance
        return ranked

    # 1) First try with 'closeto'
    try:
        r = requests.get(
            base,
            params={
                "access_token": token,
                "fields": MAP_FIELDS,
                "limit": 20,
                "closeto": f"{lat},{lon}",
            },
            timeout=20,
        )
        r.raise_for_status()
        items = r.json().get("data", [])
        if items:
            ranked = rank_items(items)
            if require_pano:
                panos = [t for t in ranked if t[0]]
                if panos:
                    it = panos[0][2]
                    return (
                        it.get("thumb_1024_url") or it.get("thumb_2048_url"),
                        it,
                    )
            it = ranked[0][2]
            return it.get("thumb_1024_url") or it.get("thumb_2048_url"), it
    except Exception:
        pass

    # 2) Fallback: use bbox searches with multiple radii
    for radius in radii_m:
        dlat, dlon = _deg_for_meters(lat, radius)
        bbox = f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}"
        try:
            r = requests.get(
                base,
                params={
                    "access_token": token,
                    "fields": MAP_FIELDS,
                    "limit": 50,
                    "bbox": bbox,
                },
                timeout=20,
            )
            r.raise_for_status()
            items = r.json().get("data", [])
            if not items:
                continue
            ranked = rank_items(items)
            if require_pano:
                panos = [t for t in ranked if t[0]]
                if panos:
                    it = panos[0][2]
                    return (
                        it.get("thumb_1024_url") or it.get("thumb_2048_url"),
                        it,
                    )
            it = ranked[0][2]
            return it.get("thumb_1024_url") or it.get("thumb_2048_url"), it
        except Exception:
            continue

    return None, None


def _fmt_date(value) -> str:
    """Convert Mapillary date or timestamp to an ISO date string when possible."""
    if not value:
        return ""
    if isinstance(value, (int, float)):
        try:
            # If > 1e12 it is likely in milliseconds
            if value > 1e12:
                value /= 1000.0
            return datetime.utcfromtimestamp(value).date().isoformat()
        except Exception:
            return ""
    if isinstance(value, str):
        try:
            return (
                datetime.fromisoformat(value.replace("Z", "+00:00"))
                .date()
                .isoformat()
            )
        except Exception:
            return value[:10]
    return str(value)


def pannellum_html_from_image_bytes(img_bytes: bytes, height_px: int = 480) -> str:
    """
    Build an HTML block that uses Pannellum to render a 360° panorama from JPEG bytes.
    """
    data_uri = "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode(
        "ascii"
    )
    cfg = {
        "type": "equirectangular",
        "panorama": data_uri,
        "autoLoad": True,
        "autoRotate": -2,
        "showZoomCtrl": True,
        "hfov": 90,
    }
    return f"""
    <div id="pano" style="width:100%; height:{int(height_px)}px; border-radius:10px; overflow:hidden;"></div>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/pannellum/build/pannellum.css">
    <script src="https://cdn.jsdelivr.net/npm/pannellum/build/pannellum.js"></script>
    <script>
      (function(){{
        var cfg = {json.dumps(cfg)};
        function init(){{ window.pannellum && pannellum.viewer("pano", cfg); }}
        if (document.readyState === "complete") init(); else window.addEventListener("load", init);
      }})();
    </script>
    """


# ======================================
# Geocoding + WFS helpers (cadastre & PLU)
# ======================================

@st.cache_data(ttl=3600)
def cached_geocode(addr: str):
    """
    Small wrapper around nominatim_geocode provided in utils.py.
    Expected return format: (lat, lon, label)
    """
    return nominatim_geocode(addr)


@st.cache_data(ttl=1800)
def get_cadastre_parcel_from_wfs(lat, lon, bbox_deg=0.001, max_features=10):
    """
    Query IGN WFS (Parcellaire Express) around a point and return
    the *closest* parcel as a small dictionary:

    {
        "coords": [[lat, lon], ...],   # polygon for Folium
        "area_m2": float | None,      # parcel area if available
        "properties": dict            # raw WFS attributes (debug)
    }

    Returns None if nothing is found.
    """
    wfs_url = "https://data.geopf.fr/wfs/ows"

    min_lon = lon - bbox_deg
    min_lat = lat - bbox_deg
    max_lon = lon + bbox_deg
    max_lat = lat + bbox_deg

    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": "CADASTRALPARCELS.PARCELLAIRE_EXPRESS:parcelle",
        "SRSNAME": "EPSG:4326",
        "BBOX": f"{min_lon},{min_lat},{max_lon},{max_lat},EPSG:4326",
        "OUTPUTFORMAT": "application/json",
        "COUNT": str(max_features),
    }

    try:
        r = requests.get(wfs_url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print("IGN WFS error:", e)
        return None

    features = data.get("features", [])
    if not features:
        return None

    best_coords = None
    best_d2 = None
    best_props = None

    for feat in features:
        geom = feat.get("geometry")
        if not geom:
            continue

        gtype = geom.get("type")
        coords = geom.get("coordinates")

        ring = None
        if gtype == "Polygon":
            if coords and coords[0]:
                ring = coords[0]
        elif gtype == "MultiPolygon":
            try:
                ring = coords[0][0]
            except Exception:
                ring = None

        if not ring:
            continue

        # Compute centroid
        sum_lon = sum(pt[0] for pt in ring)
        sum_lat = sum(pt[1] for pt in ring)
        n = len(ring)
        if n == 0:
            continue

        centroid_lon = sum_lon / n
        centroid_lat = sum_lat / n

        dx = centroid_lon - lon
        dy = centroid_lat - lat
        d2 = dx * dx + dy * dy

        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best_coords = [[pt[1], pt[0]] for pt in ring]
            best_props = feat.get("properties", {})

    if not best_coords:
        return None

    # Try to extract surface/area from attributes
    area_m2 = None
    if best_props:
        for key in best_props.keys():
            lk = key.lower()
            if "contenance" in lk or "surface" in lk:
                val = best_props.get(key)
                try:
                    area_m2 = float(str(val).replace(",", "."))
                except Exception:
                    pass
                if area_m2 is not None:
                    break

    return {
        "coords": best_coords,
        "area_m2": area_m2,
        "properties": best_props or {},
    }

def format_plu_info(props: dict) -> dict:
    """Convert raw GPU PLU fields into user-friendly labels."""

    if not props:
        return {}

    readable = {
        "Zone code": props.get("libelle"),
        "Zone type": props.get("typezone"),
        "Zone description": props.get("libelong"),
        "Validation date": props.get("datvalid"),
        "Regulation file": props.get("nomfic"),
        "Authorized uses": props.get("destoui"),
        "Prohibited uses": props.get("destnon"),
    }

    # Remove empty/null ones
    return {k: v for k, v in readable.items() if v not in (None, "", "NULL")}

@st.cache_data(ttl=600)
def get_plu_zone_from_wfs(lat, lon, bbox_deg=0.002, max_features=10):
    """
    Simple PLU zoning lookup using GPU WFS (zone_urba layer).

    Returns:
        {
            "zone_code": str | None,
            "zone_label": str | None,
            "raw_properties": dict
        }
    """
    wfs_url = "https://data.geopf.fr/wfs/ows"

    min_lon = lon - bbox_deg
    min_lat = lat - bbox_deg
    max_lon = lon + bbox_deg
    max_lat = lat + bbox_deg

    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": "wfs_du:zone_urba",
        "SRSNAME": "EPSG:4326",
        "BBOX": f"{min_lon},{min_lat},{max_lon},{max_lat},EPSG:4326",
        "OUTPUTFORMAT": "application/json",
        "COUNT": str(max_features),
    }

    try:
        r = requests.get(wfs_url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print("IGN WFS PLU error:", e)
        return None

    features = data.get("features", [])
    if not features:
        return None

    feat = features[0]
    props = feat.get("properties", {})

    zone_code = (
        props.get("libelle")
        or props.get("LIBELLE")
        or props.get("ZONE")
        or props.get("zone")
        or props.get("CODE_ZONE")
        or props.get("code_zone")
        or props.get("CODEZONE")
        or props.get("codezone")
        or props.get("typezone")
    )

    zone_label = (
        props.get("libelong")
        or props.get("LIBELLE_LONG")
        or props.get("LIBELLELONG")
        or props.get("LIBELLE")
        or props.get("libelle")
        or props.get("LIB_ZONE")
        or props.get("LIBELLE_ZONE")
        or props.get("NOM_ZONE")
        or props.get("nom_zone")
    )

    # Fallback: if no zone_code, try any field containing "zone"
    if not zone_code:
        for k, v in props.items():
            if "zone" in k.lower() and isinstance(v, str) and len(v) <= 10:
                zone_code = v
                break

    return {
        "zone_code": zone_code,
        "zone_label": zone_label,
        "raw_properties": props,
    }


def build_plu_pdf_url_from_properties(props: dict) -> str | None:
    """
    Build the PLU regulation PDF URL from GPU zone_urba properties.

    We use:
      - gpu_doc_id : document ID in GPU
      - nomfic     : PDF filename of the regulation
    """
    if not props:
        return None

    doc_id = props.get("gpu_doc_id") or props.get("id")
    filename = props.get("nomfic")

    if not doc_id or not filename:
        return None

    # GPU API pattern:
    # /api/document/{id}/download-file/{fileName}
    return f"https://www.geoportail-urbanisme.gouv.fr/api/document/{doc_id}/download-file/{filename}"


# ======================================
# Session state
# ======================================

if "geo_result" not in st.session_state:
    st.session_state.geo_result = None

# ======================================
# UI – Header & sidebar
# ======================================

st.title("🧭 Intelligent Urban Visualization Tool")
st.markdown(
    "Address ➜ **map**, **cadastral parcel**, **Street View** (Google / Mapillary), "
    "**PLU zoning** and link to the official **regulation**."
)
st.markdown("---")

with st.sidebar:
    st.markdown("## Settings")

    provider = st.selectbox(
        "Street imagery provider",
        ["Auto", "Mapillary", "Google"],
        help="Auto: try Mapillary first, then Google if needed.",
    )

    radius = st.slider(
        "Mapillary search radius (meters)",
        50,
        1000,
        150,
        step=50,
        help="Controls how far the app searches for nearby Mapillary images.",
    )

    pano_first = st.checkbox(
        "Prefer panoramic Mapillary images", value=True
    )

    st.markdown("---")
    st.markdown("### API keys")
    st.caption(
        "API keys are configured server-side (not visible to the user)."
    )

# ======================================
# UI – Address + geocoding
# ======================================

st.markdown("### Address")

address = st.text_input(
    "Enter an address:",
    value="",
    placeholder="e.g. Eiffel Tower, Paris",
)

col_search, _ = st.columns([1, 3])
with col_search:
    search = st.button("Geocode & display")

if search:
    if not address.strip():
        st.warning("Please enter an address.")
        st.stop()

    geo = cached_geocode(address.strip())
    # cached_geocode is expected to return (lat, lon, label) or None
    if not geo or not geo[0]:
        st.error("Address not found. Please try another query.")
        st.session_state.geo_result = None
    else:
        lat, lon, label = geo
        st.session_state.geo_result = {
            "lat": lat,
            "lon": lon,
            "label": label,
        }

geo = st.session_state.geo_result

if not geo:
    st.info("Enter an address and click **Geocode & display**.")
    st.stop()

lat = geo["lat"]
lon = geo["lon"]
label = geo["label"]

st.success(
    f"Geocoding successful → **{label}**  \n"
    f"Coordinates: `{lat:.6f}, {lon:.6f}`"
)

# ======================================
# PLU info & parcel
# ======================================

plu_info = get_plu_zone_from_wfs(lat, lon)
props = plu_info.get("raw_properties", {}) if plu_info else {}
pdf_url = build_plu_pdf_url_from_properties(props) if plu_info else None

# Cadastral parcel (coords + area)
parcel = get_cadastre_parcel_from_wfs(lat, lon)

# ======================================
# Summary sheet
# ======================================

st.markdown("### Summary sheet")

col_a, col_b, col_c, col_d = st.columns([2, 1, 1, 1])

with col_a:
    st.markdown("**Searched address:**")
    st.markdown(label)

with col_b:
    st.markdown("**PLU zone:**")
    if plu_info and plu_info.get("zone_code"):
        st.markdown(f"`{plu_info['zone_code']}`")
    else:
        st.markdown("_Unknown_")

with col_c:
    st.markdown("**Regulation:**")
    if pdf_url:
        st.markdown(f"[📄 Open regulation (PDF)]({pdf_url})")
    else:
        st.markdown("_Not available_")

with col_d:
    st.markdown("**Parcel area:**")
    if parcel and parcel.get("area_m2"):
        st.markdown(f"≈ {parcel['area_m2']:.0f} m²")
    else:
        st.markdown("_Not available_")

st.markdown("---")

# ======================================
# Tabs
# ======================================

tab_carte, tab_plu, tab_street, tab_brut = st.tabs(
    ["🗺️ Map & parcel", "📑 PLU / Zoning", "🚶 Street view", "🧩 Raw data"]
)

# ---------------------- Map & parcel ---------------------- #
with tab_carte:
    st.subheader("Map & cadastral parcel")

    m = folium.Map(location=[lat, lon], zoom_start=18, control_scale=True)
    folium.Marker([lat, lon], tooltip=label, popup=label).add_to(m)

    if parcel and parcel.get("coords"):
        folium.Polygon(
            locations=parcel["coords"],
            color="red",
            weight=2,
            fill=True,
            fill_opacity=0.2,
            tooltip="Parcel (IGN Parcellaire Express)",
        ).add_to(m)
    else:
        offset = 0.0003
        fake_polygon_coords = [
            [lat - offset, lon - offset],
            [lat - offset, lon + offset],
            [lat + offset, lon + offset],
            [lat + offset, lon - offset],
        ]
        folium.Polygon(
            locations=fake_polygon_coords,
            color="orange",
            weight=2,
            fill=True,
            fill_opacity=0.1,
            tooltip="Parcel (demo, no cadastre found)",
        ).add_to(m)

    st_folium(m, height=450, use_container_width=True)

# ---------------------- PLU / Zoning ---------------------- #
# ---------------------- PLU / Zoning ---------------------- #
with tab_plu:
    st.subheader("PLU / Zoning")

    if plu_info:
        st.success("Zoning information retrieved from the Urbanism Geoportal (GPU).")

        zone_code = plu_info.get("zone_code")
        zone_label = plu_info.get("zone_label")
        props = plu_info.get("raw_properties", {})
        pdf_url = build_plu_pdf_url_from_properties(props)

        # --- Human-friendly zoning display ---
        st.markdown("### Zoning summary")

        if zone_code:
            st.write(f"**Zone code:** {zone_code}")

        if zone_label:
            st.write(f"**Zone description:** {zone_label}")

        zone_type = props.get("typezone")
        if zone_type:
            st.write(f"**Zone type:** {zone_type}")

        last_update = props.get("gpu_timestamp")
        if last_update:
            st.write(f"**Last update:** {last_update[:10]}")

        if pdf_url:
            st.markdown(f" **Regulation PDF:** [Open document]({pdf_url})")
        else:
            st.info("No regulation PDF available for this zone.")

        # --- Optional: show a cleaned dictionary ---
        st.markdown("### Details (simplified)")
        simplified = {
            "Zone code": zone_code,
            "Zone type": zone_type,
            "Zone description": zone_label,
            "Regulation file": props.get("nomfic"),
            "Last update": last_update[:10] if last_update else None,
            "PLU reference": props.get("idurba"),
        }
        st.json(simplified)

        # --- Full raw properties (hidden by default) ---
        with st.expander("Full raw PLU data (advanced)"):
            st.json(props)
    else:
        st.info("No PLU zoning found at this location.")


# ---------------------- Street View / Panoramic ---------------------- #
with tab_street:
    st.subheader("Street-level view (Mapillary / Google)")

    chosen_provider = provider
    selected_thumb = None
    selected_meta = None

    # Radius list for Mapillary (based on the slider)
    radii = (
        radius,
        max(radius * 2, 300),
        600,
        1200,
        3000,
        6000,
        10000,
    )

    # Auto mode: Mapillary first, then Google
    if provider == "Auto":
        if MAPILLARY_TOKEN:
            thumb, meta = mapillary_find_best(
                lat, lon, MAPILLARY_TOKEN, radii_m=radii, require_pano=pano_first
            )
            # If pano requested but not found, try again without pano constraint
            if pano_first and (not thumb or not isinstance(meta, dict)):
                thumb, meta = mapillary_find_best(
                    lat, lon, MAPILLARY_TOKEN, radii_m=radii, require_pano=False
                )

            if thumb and isinstance(meta, dict):
                chosen_provider = "Mapillary"
                selected_thumb = thumb
                selected_meta = meta

        if (not selected_thumb) and GOOGLE_KEY:
            chosen_provider = "Google"

    # ---- Mapillary ---- #
    if chosen_provider == "Mapillary":
        if not MAPILLARY_TOKEN:
            st.warning(
                "Please configure MAPILLARY_TOKEN to use Mapillary imagery."
            )
        else:
            if not selected_thumb or not selected_meta:
                thumb, meta = mapillary_find_best(
                    lat, lon, MAPILLARY_TOKEN, radii_m=radii, require_pano=pano_first
                )
                if pano_first and (not thumb or not isinstance(meta, dict)):
                    st.info(
                        "No panoramic image found nearby — searching for the closest available image."
                    )
                    thumb, meta = mapillary_find_best(
                        lat,
                        lon,
                        MAPILLARY_TOKEN,
                        radii_m=radii,
                        require_pano=False,
                    )
            else:
                thumb, meta = selected_thumb, selected_meta

            if not thumb or not isinstance(meta, dict):
                st.error("No Mapillary imagery found near this point.")
            else:
                static_url = meta.get("thumb_1024_url") or thumb

                # Static preview
                try:
                    img_resp = requests.get(static_url, timeout=20)
                    img_resp.raise_for_status()
                    st.image(
                        img_resp.content,
                        caption="Mapillary static preview",
                        use_column_width=True,
                    )
                except Exception as e:
                    st.warning(f"Error loading static image: {e}")

                is_pano = bool(meta.get("is_pano"))
                date_str = _fmt_date(meta.get("captured_at", ""))

                if is_pano:
                    st.markdown("##### Mapillary panoramic view (Pannellum)")
                    pano_url = meta.get("thumb_2048_url") or static_url
                    try:
                        pbytes = requests.get(pano_url, timeout=30)
                        pbytes.raise_for_status()
                        html_block = pannellum_html_from_image_bytes(
                            pbytes.content, height_px=480
                        )
                        st.components.v1.html(
                            html_block, height=520, scrolling=False
                        )
                    except Exception as e:
                        st.warning(
                            f"Error loading panorama (showing static image only): {e}"
                        )
                else:
                    st.info(
                        "This image is not panoramic (standard street-level photo)."
                    )

                pid = str(meta.get("id", ""))
                footer = f"ID: `{pid}`"
                if date_str:
                    footer += f" — Capture date: {date_str}"
                st.caption(footer)

    # ---- Google Street View ---- #
    elif chosen_provider == "Google":
        if not GOOGLE_KEY:
            st.warning(
                "Please configure GOOGLE_MAPS_API_KEY to use Google Street View."
            )
        else:
            url = google_streetview_embed_url(lat, lon, GOOGLE_KEY)
            if url:
                st.markdown(f"[Open Street View in a new tab ↗]({url})")
                st.components.v1.iframe(url, height=450, scrolling=False)
            else:
                st.info("Could not build Google Street View embed URL.")

    # ---- No provider available ---- #
    else:
        st.info(
            "No street imagery provider is available, or no image was found near this location."
        )

# ---------------------- Raw data ---------------------- #
with tab_brut:
    st.subheader("Raw data / debug")

    st.markdown("#### Coordinates & address")
    st.write({"lat": lat, "lon": lon, "label": label})

    st.markdown("#### PLU (WFS properties)")
    if plu_info:
        st.json(plu_info.get("raw_properties", {}))
    else:
        st.info("No PLU information available for this location.")

    st.markdown("#### Cadastral parcel (WFS properties)")
    if parcel and parcel.get("properties"):
        st.json(parcel["properties"])
    else:
        st.info("No parcel found or no attributes available.")
