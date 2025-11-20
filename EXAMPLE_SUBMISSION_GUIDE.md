# Example GIS Data Submission for City Administrators

This document explains the example submission template demonstrating the standardized format all cities should follow.

---

## Required Data Categories for Submission

### Complete Data Package Requirements

Cities should provide data for these essential categories to ensure comprehensive spatial analysis:

*The examples listed under the Public Open Spaces, Public Sporting Facilities, Cultural Sites, and Recreation Facilities layers below are illustrative only, and it is ultimately up to you as a city to define the sites to be included. However, it is important to only include publicly accessible facilities and sites that contribute to the city's cultural and recreational life (for example, gyms and hotels would not typically fall under this category).*

**Please ensure that all files are submitted as GIS shapefiles with polygon geometries.**

### 1. Admin Boundary
**File:** `[CityName]_[Country]_Admin_Boundary.shp`  
**Description:** Official city administrative boundaries that define the city limits and jurisdictional areas.  
**Geometry:** Polygon | **Priority:** REQUIRED

### 2. Subdivision Boundaries
**File:** `[CityName]_[Country]_Subdivisions.shp`  
**Description:** Add the most commonly-used subdivision boundary. This should be the subdivision used in question 3 of your survey (i.e. zones, districts or neighborhoods).  
**Geometry:** Polygon | **Priority:** RECOMMENDED

### 3. Public Open Spaces
**File:** `[CityName]_[Country]_Public_Spaces.shp`  
**Description:** Parks, green spaces, town squares, public gathering places, promenades, picnic areas, public beaches, and recreational areas accessible to the public.  
**Geometry:** Polygon | **Priority:** REQUIRED

### 4. Public Sport Facilities
**File:** `[CityName]_[Country]_Sport_Facilities.shp`  
**Description:** Sports fields, sporting clubs, playgrounds, walking and jogging tracks, cycling paths, etc.  
**Geometry:** Polygon | **Priority:** REQUIRED

### 5. Recreational Facilities
**File:** `[CityName]_[Country]_Recreation.shp`  
**Description:** Art galleries, community centers, amusement parks, waterfront promenades, picnic areas, public beaches, theaters, museums, zoological gardens, theme parks, music venues, community centres, libraries etc.  
**Geometry:** Polygon | **Priority:** REQUIRED

### 6. Cultural Sites
**File:** `[CityName]_[Country]_Cultural_Sites.shp`  
**Description:** Museums, heritage sites, art galleries, libraries, community centres and cultural landmarks within the city.  
**Geometry:** Polygon | **Priority:** REQUIRED

---

## Best Practices

✅ **Clean Organization**: Files directly in GIS SHP folder (no confusing nested directories)  
✅ **Complete Data**: Boundary, neighborhood, and POI files provided  
✅ **Proper Components**: All required shapefile components (.shp, .shx, .dbf, .prj, .cpg)  
✅ **Reasonable Size**: Manageable file sizes (boundary: 42KB, neighborhoods: 18KB, POI: 85KB)  
✅ **Geometry**: Polygon boundaries only  
✅ **Good Naming**: Clear, descriptive file names with category suffixes
