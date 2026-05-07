# 🧭 Intelligent Urban Visualization Tool

A Streamlit application that provides instant urban information for any address in France:  
cadastral parcel, PLU zoning, official regulation PDF, Mapillary imagery, and Google Street View fallback.

---

##  Overview

This tool offers a complete, interactive analysis of any location:

- Address geocoding (Nominatim / OSM)
- Cadastral parcel retrieval and map display (IGN WFS)
- PLU zoning via the national Urbanism Geoportal (GPU)
- Direct link to the official PLU regulation PDF
- Street-level imagery (Mapillary 360° panorama + Google Street View fallback)
- Automatic summary sheet of all key information

Ideal for urban planners, architects, real-estate professionals, local authorities, and students.

---

##  Features

### 1. Address Geocoding (Nominatim)
- Converts an address into GPS coordinates
- Displays the full standardized label from OpenStreetMap

### 2. Cadastral Parcel (IGN Parcellaire Express)
- Automatic WFS request to IGN data services
- Parcel boundary rendered on an interactive Folium map
- Parcel area in m² when provided by IGN attributes

### 3. PLU Zoning (Urbanism Geoportal – GPU)
- Automated zoning retrieval through GPU WFS API
- Displays zoning code and description
- Direct link to the official regulation PDF

### 4. Street-Level Imagery (Mapillary + Google)
- Mapillary nearest-image search with multi-radius fallback
- High-resolution thumbnails + immersive 360° panorama (Pannellum viewer)
- Seamless fallback to Google Street View if Mapillary is unavailable

### 5. Summary Sheet
- Address  
- GPS coordinates  
- Parcel area  
- PLU zoning  
- Regulation PDF  
- Street-level imagery  

---

##  Tech Stack

- **Python 3+**
- **Streamlit** for the UI
- **Folium** for mapping
- **Pannellum** for 360° panoramas
- **PyPDF2** for extracting PLU PDF information
- **APIs used**:
  - Nominatim (OpenStreetMap)
  - IGN WFS (Cadastral Parcellaire Express)
  - Géoportail de l’Urbanisme (PLU WFS)
  - Mapillary Graph API
  - Google Maps API (Street View)

---
