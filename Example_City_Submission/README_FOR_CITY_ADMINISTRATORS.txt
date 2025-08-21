===============================================================================
                    STANDARDIZED GIS DATA SUBMISSION GUIDE
                         UN Mobility Experiment Project
===============================================================================

This folder contains an EXAMPLE of the standardized format for submitting 
GIS boundary data to the UN Mobility Experiment data lifecycle system.

EXAMPLE CITY: Santiago, Chile
FILES INCLUDED: Urban Boundary + Neighborhoods + Cultural POI

===============================================================================
                              FILE STRUCTURE
===============================================================================

Your submission ZIP file should contain files named exactly like this:

BOUNDARY FILES (REQUIRED):
✓ [CityName]_[Country]_Urban_Boundary.shp    <- Main geometry file
✓ [CityName]_[Country]_Urban_Boundary.shx    <- Spatial index (REQUIRED)
✓ [CityName]_[Country]_Urban_Boundary.dbf    <- Attribute table (REQUIRED)
✓ [CityName]_[Country]_Urban_Boundary.prj    <- Coordinate system (HIGHLY RECOMMENDED)
✓ [CityName]_[Country]_Urban_Boundary.cpg    <- Character encoding (optional)

NEIGHBORHOOD FILES (RECOMMENDED):
✓ [CityName]_[Country]_Neighborhoods.shp     <- Main geometry file
✓ [CityName]_[Country]_Neighborhoods.shx     <- Spatial index (REQUIRED)
✓ [CityName]_[Country]_Neighborhoods.dbf     <- Attribute table (REQUIRED)
✓ [CityName]_[Country]_Neighborhoods.prj     <- Coordinate system (HIGHLY RECOMMENDED)
✓ [CityName]_[Country]_Neighborhoods.cpg     <- Character encoding (optional)

ADDITIONAL DATA FILES (OPTIONAL BUT RECOMMENDED):
✓ [CityName]_[Country]_Public_Spaces.shp     <- Parks and green spaces
✓ [CityName]_[Country]_Cultural_Sites.shp    <- Museums, heritage sites (Point locations)
✓ [CityName]_[Country]_Recreation.shp        <- Sports facilities, community venues
Each category requires: .shp, .shx, .dbf, .prj, .cpg files

===============================================================================
                              NAMING RULES
===============================================================================

1. CITY NAME: Use official English name, no abbreviations
   ✓ Good: Santiago_Chile, Buenos_Aires_Argentina
   ✗ Bad: Stgo_Chile, BA_Argentina

2. COUNTRY: Use common English country name or ISO code
   ✓ Good: Chile, Argentina, KSA, Turkey
   ✗ Bad: República_de_Chile

3. NO SPACES: Use underscores instead of spaces
   ✓ Good: New_York_USA_Urban_Boundary.shp
   ✗ Bad: New York USA Urban Boundary.shp

4. NO SPECIAL CHARACTERS: Only letters, numbers, underscores
   ✓ Good: Sao_Paulo_Brazil_Urban_Boundary.shp
   ✗ Bad: São_Paulo_Brazil_Urban_Boundary.shp

===============================================================================
                           TECHNICAL REQUIREMENTS
===============================================================================

COORDINATE SYSTEM: 
- MUST be WGS84 (EPSG:4326)
- Latitude/Longitude in decimal degrees
- If your data is in a different projection, convert it before submission

GEOMETRY TYPE:
- Boundary files: Polygon or PolygonZ
- Neighborhood files: Polygon or PolygonZ
- POI files: Point (specific facility locations)

FILE FORMAT:
- Submit as ZIP file only (no RAR, 7z, or other formats)
- ZIP filename: [CityName]_[Country]_Boundaries.zip

REQUIRED DATA CATEGORIES FOR COMPREHENSIVE SUBMISSION:

1. ADMIN BOUNDARY (REQUIRED):
   File: [CityName]_[Country]_Admin_Boundary.shp
   Description: Official city administrative boundaries that define city limits
   Geometry: Polygon

2. SUBDIVISION BOUNDARIES (RECOMMENDED):
   File: [CityName]_[Country]_Subdivisions.shp
   Description: Zones, districts, neighborhoods for detailed spatial analysis
   Geometry: Polygon

3. PUBLIC OPEN SPACES (RECOMMENDED):
   File: [CityName]_[Country]_Public_Spaces.shp
   Description: Parks, green spaces, recreational areas accessible to public
   Geometry: Polygon or Point

4. CULTURAL SITES (OPTIONAL):
   File: [CityName]_[Country]_Cultural_Sites.shp
   Description: Museums, heritage sites, cultural landmarks within the city
   Geometry: Point (preferred) or Polygon

5. RECREATIONAL FACILITIES (OPTIONAL):
   File: [CityName]_[Country]_Recreation.shp
   Description: Public sports facilities and venues for community use
   Geometry: Point (preferred) or Polygon

QUALITY CHECKS:
□ All required files included (.shp, .shx, .dbf)
□ Files open correctly in GIS software (QGIS, ArcGIS)
□ Coordinate system is WGS84 (EPSG:4326)
□ No gaps or overlaps in geometry
□ File names follow naming convention
□ ZIP file is not corrupted

===============================================================================
                              SUBMISSION STEPS
===============================================================================

1. PREPARE YOUR DATA:
   - Ensure coordinate system is WGS84 (EPSG:4326)
   - Check geometry is valid (no self-intersections)
   - Name files according to convention

2. CREATE ZIP FILE:
   - Include all required shapefile components
   - Name ZIP file: [CityName]_[Country]_Boundaries.zip
   - Test that ZIP file opens correctly

3. SUBMIT VIA WEB INTERFACE:
   - Log into the UN Mobility Experiment system
   - Navigate to your city's page
   - Use the boundary upload feature
   - Upload your ZIP file

4. VERIFY UPLOAD:
   - Check that boundaries display correctly on the map
   - Verify all layers are visible and properly positioned

===============================================================================
                                SUPPORT
===============================================================================

If you encounter issues:
1. Check this README file for common problems
2. Verify your files meet all technical requirements
3. Test your ZIP file on a different computer
4. Contact technical support with specific error messages

COMMON ISSUES:
- Missing .shx or .dbf files → Include all shapefile components
- Wrong coordinate system → Convert to WGS84 (EPSG:4326)
- Special characters in names → Use only ASCII characters
- Large file sizes → Consider simplifying geometry if >50MB

===============================================================================

This example demonstrates the correct format. Replace "Santiago_Chile" with 
your city's name and country, following the same pattern.

Last updated: December 2024
