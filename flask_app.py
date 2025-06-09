"""
Flask app for managing mobility cities and triggering data syncs.

How to run:
1. Ensure .env is present with admin_user and admin_password
2. Install requirements: pip install flask boto3 python-dotenv requests
3. Run: python flask_app.py
4. Access via SSH tunnel: ssh -i salman-dev.pem -L 5000:localhost:5000 ec2-user@<EC2_PUBLIC_IP>
5. Open http://localhost:5000 in your browser
"""
import os
import uuid
from flask import Flask, render_template_string, request, redirect, url_for, session, flash, send_from_directory, jsonify
import boto3
from dotenv import load_dotenv, set_key
from sync_logic import sync_city_for_date, wait_for_job_completion, sync_data_to_bucket, build_sync_payload, make_api_request
import requests
import json
import threading
import uuid as uuidlib
import logging
import time
from datetime import datetime, timedelta
import shutil
from glob import glob
from utils import load_cities, save_cities

# Load credentials
load_dotenv()
ADMIN_USER = os.getenv('admin_user')
ADMIN_PASSWORD = os.getenv('admin_password')
VERASET_API_KEY = os.environ.get('VERASET_API_KEY')
API_ENDPOINT = "https://platform.prd.veraset.tech"

# Ensure AWS credentials from .env are set in os.environ for subprocesses and boto3
os.environ['AWS_ACCESS_KEY_ID'] = os.getenv('AWS_ACCESS_KEY_ID', '')
os.environ['AWS_SECRET_ACCESS_KEY'] = os.getenv('AWS_SECRET_ACCESS_KEY', '')

REGION = 'us-west-2'
TABLE_NAME = 'mobility_cities'
CITIES_FILE = os.path.join('db', 'cities.json')
cities_lock = threading.Lock()

# Global sync progress tracking
data_sync_progress = {}

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Logging setup
LOG_FILE = 'app.log'
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)

# Apple-inspired global style
APPLE_STYLE = '''<style>
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  background: #f8f8fa;
  color: #222;
  margin: 0;
  padding: 0;
}
.container {
  max-width: 1200px;
  margin: 40px 0 20px 10vw;
  background: #fff;
  border-radius: 18px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.07);
  padding: 32px 36px 28px 36px;
}
h2 {
  font-weight: 600;
  letter-spacing: -0.02em;
  margin-top: 0;
  color: #111;
}
input, select, button, textarea {
  font-family: inherit;
  font-size: 1rem;
  border-radius: 10px;
  border: 1px solid #d1d1d6;
  padding: 10px 12px;
  margin: 6px 0 16px 0;
  background: #f5f5f7;
  transition: border 0.2s, box-shadow 0.2s;
  outline: none;
}
input:focus, select:focus, textarea:focus {
  border: 1.5px solid #007aff;
  box-shadow: 0 0 0 2px #007aff22;
}
button {
  background: linear-gradient(90deg, #007aff 80%, #0051a8 100%);
  color: #fff;
  border: none;
  font-weight: 600;
  padding: 10px 24px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(0,122,255,0.07);
  margin-right: 8px;
  margin-bottom: 8px;
  transition: background 0.2s, box-shadow 0.2s;
}
button:hover {
  background: #0051a8;
}
table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  background: #fff;
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  margin-bottom: 24px;
}
th, td {
  padding: 12px 16px;
  text-align: left;
}
th {
  background: #f5f5f7;
  font-weight: 600;
  color: #444;
}
tr:not(:last-child) td {
  border-bottom: 1px solid #ececec;
}
a {
  color: #007aff;
  text-decoration: none;
  font-weight: 500;
  transition: color 0.2s;
}
a:hover {
  color: #0051a8;
  text-decoration: underline;
}
pre#logbox {
  background: #111;
  color: #eee;
  border-radius: 12px;
  padding: 1.2em;
  font-size: 14px;
  max-height: 1000px;
  width: 100%;
  min-width: 1800px;
  max-width: 2800px;
  overflow: auto;
  margin-bottom: 24px;
  margin-left: auto;
  margin-right: auto;
  display: block;
}
#progress-bar {
  width: 100%;
  background: #e5e5ea;
  border-radius: 12px;
  border: 1px solid #d1d1d6;
  height: 32px;
  margin-bottom: 12px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
#bar {
  height: 100%;
  width: 0;
  background: linear-gradient(90deg, #007aff 80%, #0051a8 100%);
  border-radius: 12px;
  text-align: center;
  color: #fff;
  font-weight: 600;
  font-size: 1.1em;
  transition: width 0.4s;
  display: flex;
  align-items: center;
  justify-content: center;
}
#error, .error, #errors {
  color: #c00;
  font-weight: 500;
  margin-top: 1em;
}
::-webkit-input-placeholder { color: #aaa; }
::-moz-placeholder { color: #aaa; }
:-ms-input-placeholder { color: #aaa; }
::placeholder { color: #aaa; }
</style>'''

SYNC_TIME_ENV_KEY = 'SYNC_TIME'
def get_sync_time():
    sync_time = os.getenv(SYNC_TIME_ENV_KEY)
    if sync_time and ':' in sync_time:
        hour, minute = sync_time.split(':')
        return int(hour), int(minute)
    return 2, 0  # Default 2:00am

def set_sync_time(hour, minute):
    time_str = f"{int(hour):02d}:{int(minute):02d}"
    set_key('.env', SYNC_TIME_ENV_KEY, time_str)
    os.environ[SYNC_TIME_ENV_KEY] = time_str
    # Fix permissions after update
    try:
        os.system('chown ec2-user:ec2-user /home/ec2-user/mobility-data-lifecycle-manager/.env')
        os.system('chmod 600 /home/ec2-user/mobility-data-lifecycle-manager/.env')
    except Exception as e:
        print(f"Warning: Could not fix .env permissions: {e}")
    update_crontab_for_sync_time(time_str)

def update_crontab_for_sync_time(time_str):
    import subprocess
    hour, minute = time_str.split(':')
    cron_line = f"{int(minute)} {int(hour)} * * * cd /home/ec2-user/mobility-data-lifecycle-manager && source venv/bin/activate && python daily_sync.py >> /home/ec2-user/mobility-data-lifecycle-manager/app.log 2>&1"
    # Remove any existing daily_sync.py cron jobs, then add the new one
    try:
        crontab = subprocess.check_output(['sudo', 'crontab', '-u', 'ec2-user', '-l'], text=True)
        lines = [l for l in crontab.splitlines() if 'daily_sync.py' not in l]
    except subprocess.CalledProcessError:
        lines = []
    lines.append(cron_line.strip())
    new_crontab = '\n'.join(lines) + '\n'
    subprocess.run(['sudo', 'crontab', '-u', 'ec2-user', '-'], input=new_crontab, text=True, check=True)

def get_dynamodb():
    return boto3.resource('dynamodb', region_name=REGION)

def get_table():
    return get_dynamodb().Table(TABLE_NAME)

def is_logged_in():
    return session.get('logged_in')

def threaded_sync(city, dates, sync_id):
    total = len(dates)
    errors = []
    logging.info(f"Starting sync for {city['city']} ({city['country']}) for {total} days: {dates[0]} to {dates[-1]}")
    quota_error_flag = False
    for i, date in enumerate(dates):
        logging.info(f"Syncing {city['city']} on {date}")
        error_msg = None
        veraset_status = {'status': 'pending'}
        def status_callback(status, attempt):
            if status and 'data' in status and 'status' in status['data']:
                data_sync_progress[sync_id]['veraset_status'] = f"Veraset job status: {status['data']['status']} (attempt {attempt+1})"
            else:
                data_sync_progress[sync_id]['veraset_status'] = f"Polling Veraset job status... (attempt {attempt+1})"
        try:
            from datetime import datetime as dt
            date_obj = dt.strptime(date, "%Y-%m-%d")
            payload = build_sync_payload(city, date_obj, date_obj)
            response = make_api_request("movement/job/pings", data=payload)
            # Check for quota exceeded error
            if response and isinstance(response, dict):
                error_message = response.get('error_message') or response.get('error', '')
                if error_message and 'Monthly Job Quota exceeded' in error_message:
                    logging.error("Monthly Job Quota exceeded. Please contact support for inquiry.")
                    error_msg = "Monthly Job Quota exceeded. Please contact support for inquiry."
                    quota_error_flag = True
                    # Add to errors and update progress immediately
                    errors.append(f"{date}: {error_msg}")
                    data_sync_progress[sync_id].update({
                        'current': i + 1,
                        'total': total,
                        'date': date,
                        'status': 'quota_exceeded',
                        'done': i + 1 == total,
                        'errors': errors.copy()
                    })
                    # Show in GUI via flash if possible
                    from flask import has_request_context, flash
                    if has_request_context():
                        flash("Monthly Job Quota exceeded. Please contact support for inquiry.", 'error')
                    break
            if not response or 'error' in response:
                status = 'failed'
                error_msg = response.get('error', 'No response from API')
                logging.error(f"Sync failed for {city['city']} on {date}: {error_msg}")
            else:
                job_id = response.get("data", {}).get("job_id")
                if not job_id:
                    status = 'failed'
                    error_msg = f"No job_id received from Veraset API"
                    logging.error(f"Sync failed for {city['city']} on {date}: {error_msg}")
                else:
                    data_sync_progress[sync_id]['veraset_status'] = 'Polling Veraset job status...'
                    status_result = wait_for_job_completion(job_id, max_attempts=100, poll_interval=60, status_callback=status_callback)
                    if not status_result or 'error' in status_result:
                        status = 'failed'
                        error_msg = status_result.get('error', 'Unknown error during job status polling')
                        logging.error(f"Sync failed for {city['city']} on {date}: {error_msg}")
                    else:
                        sync_result = sync_city_for_date(city, date)
                        if not sync_result.get('success'):
                            status = 'failed'
                            error_msg = sync_result.get('error', 'Unknown error during S3 sync')
                            logging.error(f"Sync failed for {city['city']} on {date}: {error_msg}")
                        else:
                            status = 'success'
                            logging.info(f"Sync result for {city['city']} on {date}: success")
                            data_sync_progress[sync_id]['status'] = 's3_syncing'
                            data_sync_progress[sync_id]['s3_sync'] = f"S3 sync complete for {date}."
            time.sleep(0.5)
        except Exception as e:
            status = 'error'
            error_msg = str(e)
            logging.error(f"Exception during sync for {city['city']} on {date}: {e}", exc_info=True)
        if error_msg:
            errors.append(f"{date}: {error_msg}")
        data_sync_progress[sync_id].update({
            'current': i + 1,
            'total': total,
            'date': date,
            'status': status if error_msg else 'success',
            'done': i + 1 == total,
            'errors': errors.copy()
        })
    # After loop, ensure quota error is present if detected
    if quota_error_flag and not any('Monthly Job Quota exceeded' in e for e in errors):
        errors.append("Monthly Job Quota exceeded. Please contact support for inquiry.")
        data_sync_progress[sync_id]['errors'] = errors.copy()
        data_sync_progress[sync_id]['status'] = 'quota_exceeded'
    data_sync_progress[sync_id]['done'] = True
    logging.info(f"Sync complete for {city['city']} ({city['country']})")

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form['username']
        pw = request.form['password']
        logging.info(f"Login attempt for user: {user}")
        if user == ADMIN_USER and pw == ADMIN_PASSWORD:
            session['logged_in'] = True
            logging.info(f"Login successful for user: {user}")
            return redirect(url_for('index'))
        else:
            logging.warning(f"Login failed for user: {user}")
            flash('Invalid credentials')
    return render_template_string(APPLE_STYLE + '''
        <div class="container">
        <h2>Login</h2>
        <form method="post">
            <input name="username" placeholder="Username"><br>
            <input name="password" type="password" placeholder="Password"><br>
            <input type="submit" value="Login">
        </form>
        </div>
    ''')

@app.route('/logout')
def logout():
    logging.info("User logged out")
    session.clear()
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
def index():
    if not is_logged_in():
        return redirect(url_for('login'))
    sync_hour, sync_minute = get_sync_time()
    if request.method == 'POST':
        if 'disable_sync' in request.form:
            # Remove the cron job for daily_sync.py
            import subprocess
            try:
                crontab = subprocess.check_output(['sudo', 'crontab', '-u', 'ec2-user', '-l'], text=True)
                lines = [l for l in crontab.splitlines() if 'daily_sync.py' not in l]
            except subprocess.CalledProcessError:
                lines = []
            new_crontab = '\n'.join(lines) + '\n'
            subprocess.run(['sudo', 'crontab', '-u', 'ec2-user', '-'], input=new_crontab, text=True, check=True)
            flash("Daily sync has been disabled (cron job removed).")
            return redirect(url_for('index'))
        if 'sync_time' in request.form:
            new_time = request.form['sync_time']
            if ':' in new_time:
                hour, minute = new_time.split(':')
                set_sync_time(hour, minute)
                flash(f"Sync time updated to {hour}:{minute} (24h)")
            return redirect(url_for('index'))
    cities = load_cities()
    return render_template_string(APPLE_STYLE + '''
        <div class="container">
        <h2>Mobility Cities</h2>
        <form method="post" style="margin-bottom:2em;">
            <label>Daily Sync Time (24h, UTC):
                <input type="time" name="sync_time" value="{{'%02d:%02d' % (sync_hour, sync_minute)}}">
            </label>
            <input type="submit" value="Update Sync Time">
            <button type="submit" name="disable_sync" value="1" style="background:#ccc;color:#222;">Disable Daily Sync</button>
        </form>
        <div style="margin-bottom:1em;color:#555;font-size:0.98em;">
            <b>Note:</b> Each daily sync downloads data for <b>one day, 7 days prior</b> to the current UTC date.
        </div>
        <form action="{{ url_for('sync_all') }}" method="post" style="margin-bottom:1em;display:flex;align-items:center;gap:10px;">
            <label>Start Date: <input name="start_date" type="date" required></label>
            <label>End Date: <input name="end_date" type="date" required></label>
            <label>Schema Type:
                <select name="schema_type">
                    <option value="FULL" selected>FULL</option>
                    <option value="TRIPS">TRIPS</option>
                </select>
            </label>
            <button type="submit">Sync All Cities</button>
        </form>
        <div style="overflow-x:auto;">
          <table border=1 cellpadding=5>
              <tr><th>Country</th><th>State/Province</th><th>City</th><th>Latitude</th><th>Longitude</th><th>Email</th><th>Radius (m)</th><th>Actions</th></tr>
              {% for city in cities %}
              <tr>
                  <td>{{city['country']}}</td>
                  <td>{{city.get('state_province','')}}</td>
                  <td>{{city['city']}}</td>
                  <td>{{city['latitude']}}</td>
                  <td>{{city['longitude']}}</td>
                  <td>{{city.get('notification_email','')}}</td>
                  <td>{{city.get('radius_meters', 50000)}}</td>
                  <td>
                      <a href="{{ url_for('edit_city', city_id=city['city_id']) }}">Edit</a> |
                      <a href="{{ url_for('delete_city', city_id=city['city_id']) }}" onclick="return confirm('Delete this city?')">Delete</a> |
                      <a href="{{ url_for('sync_city', city_id=city['city_id']) }}">Sync</a>
                  </td>
              </tr>
              {% endfor %}
          </table>
        </div>
        <br><a href="{{ url_for('add_city') }}">Add City</a>
        <br><a href="{{ url_for('view_logs') }}">View Logs</a>
        <br><a href="{{ url_for('sync_jobs') }}">View Sync Jobs Progress</a>
        </div>
    ''', cities=cities, sync_hour=sync_hour, sync_minute=sync_minute)

@app.route('/add', methods=['GET', 'POST'])
def add_city():
    if not is_logged_in():
        logging.debug("Add city: user not logged in.")
        return redirect(url_for('login'))
    if request.method == 'POST':
        cities = load_cities()
        data = {
            'city_id': str(uuid.uuid4()),
            'country': request.form['country'],
            'state_province': request.form.get('state_province', ''),
            'city': request.form['city'],
            'latitude': request.form['latitude'],
            'longitude': request.form['longitude'],
            'notification_email': request.form['notification_email'],
        }
        aoi_type = request.form.get('aoi_type')
        if aoi_type == 'radius':
            data['radius_meters'] = float(request.form['radius_meters'])
        elif aoi_type == 'polygon':
            import json as _json
            data['polygon_geojson'] = _json.loads(request.form['polygon_geojson'])
        else:
            flash('You must define an AOI (radius or polygon).')
            return redirect(url_for('add_city'))
        # Remove the other AOI type if present
        if aoi_type == 'radius':
            data.pop('polygon_geojson', None)
        if aoi_type == 'polygon':
            data.pop('radius_meters', None)
        logging.info(f"Adding city: {data}")
        cities.append(data)
        save_cities(cities)
        return redirect(url_for('index'))
    return render_template_string(APPLE_STYLE + '''
        <div class="container">
        <h2>Add City</h2>
        <form method="post" id="cityForm" onsubmit="return prepareAOI()">
            Country: <select name="country" id="country" required></select><br>
            State/Province: <select name="state_province" id="state_province"></select><br>
            City: <input name="city" id="city"><br>
            Latitude: <input name="latitude" id="latitude"><br>
            Longitude: <input name="longitude" id="longitude"><br>
            <button type="button" onclick="geocodeCity()">Auto-populate Lat/Lon</button><br>
            Notification Email: <input name="notification_email"><br>
            <div style="margin:1em 0;">
                <b>Area of Interest (AOI):</b><br>
                <label><input type="radio" name="aoi_type" value="radius" checked onchange="toggleAOI()"> Radius</label>
                <label><input type="radio" name="aoi_type" value="polygon" onchange="toggleAOI()"> Polygon</label>
            </div>
            <div id="radiusControls">
                Radius Meters: <input name="radius_meters" id="radius_meters" type="number" value="10000" min="1" step="1" onchange="updateRadius()"><br>
            </div>
            <div id="polygonControls" style="display:none;">
                <span>Draw a polygon on the map below.</span>
                <input type="hidden" name="polygon_geojson" id="polygon_geojson">
            </div>
            <div id="map" style="height:400px;margin:1em 0;"></div>
            <input type="submit" value="Add">
        </form>
        <a href="{{ url_for('index') }}">Back</a>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <link rel="stylesheet" href="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css" />
        <script src="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js"></script>
        <script>
        let countriesData = [];
        function populateCountries() {
            fetch('/countries_states.json')
                .then(r => r.json())
                .then(data => {
                    countriesData = data;
                    const countrySelect = document.getElementById('country');
                    countrySelect.innerHTML = '<option value="">Select Country</option>';
                    data.forEach(c => {
                        countrySelect.innerHTML += `<option value="${c.name}">${c.name}</option>`;
                    });
                });
        }
        function populateStates() {
            const country = document.getElementById('country').value;
            const stateSelect = document.getElementById('state_province');
            stateSelect.innerHTML = '<option value="">Select State/Province</option>';
            const countryObj = countriesData.find(c => c.name === country);
            if (countryObj && countryObj.states) {
                countryObj.states.forEach(s => {
                    stateSelect.innerHTML += `<option value="${s.name}">${s.name}</option>`;
                });
            }
        }
        document.addEventListener('DOMContentLoaded', function() {
            populateCountries();
            document.getElementById('country').addEventListener('change', populateStates);
        });
        function geocodeCity() {
            const city = document.getElementById('city').value;
            const country = document.getElementById('country').value;
            const state = document.getElementById('state_province').value;
            fetch(`/geocode_city?city=${encodeURIComponent(city)}&country=${encodeURIComponent(country)}&state=${encodeURIComponent(state)}`)
                .then(r => r.json())
                .then(data => {
                    if (data.lat && data.lon) {
                        document.getElementById('latitude').value = data.lat;
                        document.getElementById('longitude').value = data.lon;
                        setMapCenter(parseFloat(data.lat), parseFloat(data.lon));
                    } else {
                        alert('Could not find coordinates.');
                    }
                });
        }
        // --- Leaflet Map and AOI Logic ---
        let map, marker, circle, drawnItems, drawControl;
        let currentAOI = 'radius';
        function setMapCenter(lat, lon) {
            if (map) {
                map.setView([lat, lon], 12);
                if (marker) marker.setLatLng([lat, lon]);
                if (circle && currentAOI === 'radius') circle.setLatLng([lat, lon]);
            }
        }
        function toggleAOI() {
            const aoiType = document.querySelector('input[name="aoi_type"]:checked').value;
            currentAOI = aoiType;
            document.getElementById('radiusControls').style.display = aoiType === 'radius' ? '' : 'none';
            document.getElementById('polygonControls').style.display = aoiType === 'polygon' ? '' : 'none';
            if (aoiType === 'radius') {
                if (drawnItems) drawnItems.clearLayers();
                if (circle) circle.addTo(map);
                if (marker) marker.addTo(map);
            } else {
                if (circle) map.removeLayer(circle);
                if (marker) map.removeLayer(marker);
            }
        }
        function updateRadius() {
            if (!circle) return;
            const r = parseFloat(document.getElementById('radius_meters').value);
            circle.setRadius(r);
        }
        function prepareAOI() {
            const aoiType = document.querySelector('input[name="aoi_type"]:checked').value;
            if (aoiType === 'polygon') {
                if (!drawnItems || drawnItems.getLayers().length === 0) {
                    alert('Please draw a polygon on the map.');
                    return false;
                }
                const geojson = drawnItems.getLayers()[0].toGeoJSON();
                document.getElementById('polygon_geojson').value = JSON.stringify(geojson);
            }
            if (aoiType === 'radius') {
                if (!circle) {
                    alert('Please set a radius on the map.');
                    return false;
                }
                document.getElementById('radius_meters').value = circle.getRadius();
            }
            return true;
        }
        document.addEventListener('DOMContentLoaded', function() {
            // Initialize map
            const lat = parseFloat(document.getElementById('latitude').value) || 43.7;
            const lon = parseFloat(document.getElementById('longitude').value) || -79.4;
            map = L.map('map').setView([lat, lon], 12);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
                attribution: '© OpenStreetMap'
            }).addTo(map);
            marker = L.marker([lat, lon], {draggable:true}).addTo(map);
            marker.on('dragend', function(e) {
                const pos = marker.getLatLng();
                document.getElementById('latitude').value = pos.lat;
                document.getElementById('longitude').value = pos.lng;
                if (circle) circle.setLatLng(pos);
            });
            circle = L.circle([lat, lon], {radius: parseFloat(document.getElementById('radius_meters').value) || 10000, color:'#3388ff'}).addTo(map);
            circle.on('edit', function(e) {
                document.getElementById('radius_meters').value = circle.getRadius();
            });
            map.on('click', function(e) {
                marker.setLatLng(e.latlng);
                document.getElementById('latitude').value = e.latlng.lat;
                document.getElementById('longitude').value = e.latlng.lng;
                if (circle) circle.setLatLng(e.latlng);
            });
            // Leaflet Draw for polygon
            drawnItems = new L.FeatureGroup();
            map.addLayer(drawnItems);
            drawControl = new L.Control.Draw({
                draw: {
                    polygon: true,
                    polyline: false,
                    rectangle: false,
                    circle: false,
                    marker: false,
                    circlemarker: false
                },
                edit: {
                    featureGroup: drawnItems,
                    remove: true
                }
            });
            map.addControl(drawControl);
            map.on(L.Draw.Event.CREATED, function (e) {
                drawnItems.clearLayers();
                drawnItems.addLayer(e.layer);
            });
            map.on(L.Draw.Event.DELETED, function (e) {
                // nothing needed
            });
            // AOI toggle
            document.querySelectorAll('input[name="aoi_type"]').forEach(r => r.addEventListener('change', toggleAOI));
        });
        </script>
        </div>
    ''')

@app.route('/edit/<city_id>', methods=['GET', 'POST'])
def edit_city(city_id):
    if not is_logged_in():
        logging.debug("Edit city: user not logged in.")
        return redirect(url_for('login'))
    cities = load_cities()
    city = next((c for c in cities if c['city_id'] == city_id), None)
    if not city:
        logging.warning(f"Edit city: city_id {city_id} not found.")
        return 'City not found', 404
    if request.method == 'POST':
        for field in ['country', 'state_province', 'city', 'latitude', 'longitude', 'notification_email']:
            city[field] = request.form.get(field, '')
        aoi_type = request.form.get('aoi_type')
        if aoi_type == 'radius':
            city['radius_meters'] = float(request.form['radius_meters'])
            city.pop('polygon_geojson', None)
        elif aoi_type == 'polygon':
            import json as _json
            city['polygon_geojson'] = _json.loads(request.form['polygon_geojson'])
            city.pop('radius_meters', None)
        else:
            flash('You must define an AOI (radius or polygon).')
            return redirect(url_for('edit_city', city_id=city_id))
        logging.info(f"Editing city: {city}")
        save_cities(cities)
        return redirect(url_for('index'))
    # Determine AOI type for UI
    aoi_type = 'polygon' if 'polygon_geojson' in city else 'radius'
    radius_val = city.get('radius_meters', 10000)
    polygon_geojson = city.get('polygon_geojson', None)
    return render_template_string(APPLE_STYLE + '''
        <div class="container">
        <h2>Edit City</h2>
        <form method="post" id="cityForm" onsubmit="return prepareAOI()">
            Country: <select name="country" id="country" required></select><br>
            State/Province: <select name="state_province" id="state_province"></select><br>
            City: <input name="city" id="city" value="{{city['city']}}"><br>
            Latitude: <input name="latitude" id="latitude" value="{{city['latitude']}}"><br>
            Longitude: <input name="longitude" id="longitude" value="{{city['longitude']}}"><br>
            <button type="button" onclick="geocodeCity()">Auto-populate Lat/Lon</button><br>
            Notification Email: <input name="notification_email" value="{{city['notification_email']}}"><br>
            <div style="margin:1em 0;">
                <b>Area of Interest (AOI):</b><br>
                <label><input type="radio" name="aoi_type" value="radius" {% if aoi_type == 'radius' %}checked{% endif %} onchange="toggleAOI()"> Radius</label>
                <label><input type="radio" name="aoi_type" value="polygon" {% if aoi_type == 'polygon' %}checked{% endif %} onchange="toggleAOI()"> Polygon</label>
            </div>
            <div id="radiusControls" style="display:{% if aoi_type == 'radius' %}block{% else %}none{% endif %};">
                Radius Meters: <input name="radius_meters" id="radius_meters" type="number" value="{{radius_val}}" min="1" step="1" onchange="updateRadius()"><br>
            </div>
            <div id="polygonControls" style="display:{% if aoi_type == 'polygon' %}block{% else %}none{% endif %};">
                <span>Draw a polygon on the map below.</span>
                <input type="hidden" name="polygon_geojson" id="polygon_geojson">
            </div>
            <div id="map" style="height:400px;margin:1em 0;"></div>
            <input type="submit" value="Save">
        </form>
        <a href="{{ url_for('index') }}">Back</a>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <link rel="stylesheet" href="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css" />
        <script src="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js"></script>
        <script>
        let countriesData = [];
        function populateCountries(selectedCountry) {
            fetch('/countries_states.json')
                .then(r => r.json())
                .then(data => {
                    countriesData = data;
                    const countrySelect = document.getElementById('country');
                    countrySelect.innerHTML = '<option value="">Select Country</option>';
                    data.forEach(c => {
                        countrySelect.innerHTML += `<option value="${c.name}">${c.name}</option>`;
                    });
                    if (selectedCountry) {
                        countrySelect.value = selectedCountry;
                        populateStates(selectedCountry, '{{city.get('state_province', '')}}');
                    }
                });
        }
        function populateStates(selectedCountry, selectedState) {
            const country = selectedCountry || document.getElementById('country').value;
            const stateSelect = document.getElementById('state_province');
            stateSelect.innerHTML = '<option value="">Select State/Province</option>';
            const countryObj = countriesData.find(c => c.name === country);
            if (countryObj && countryObj.states) {
                countryObj.states.forEach(s => {
                    stateSelect.innerHTML += `<option value="${s.name}">${s.name}</option>`;
                });
                if (selectedState) {
                    stateSelect.value = selectedState;
                }
            }
        }
        document.addEventListener('DOMContentLoaded', function() {
            populateCountries('{{city['country']}}');
            document.getElementById('country').addEventListener('change', function() {
                populateStates(this.value);
            });
        });
        function geocodeCity() {
            const city = document.getElementById('city').value;
            const country = document.getElementById('country').value;
            const state = document.getElementById('state_province').value;
            fetch(`/geocode_city?city=${encodeURIComponent(city)}&country=${encodeURIComponent(country)}&state=${encodeURIComponent(state)}`)
                .then(r => r.json())
                .then(data => {
                    if (data.lat && data.lon) {
                        document.getElementById('latitude').value = data.lat;
                        document.getElementById('longitude').value = data.lon;
                        setMapCenter(parseFloat(data.lat), parseFloat(data.lon));
                    } else {
                        alert('Could not find coordinates.');
                    }
                });
        }
        // --- Leaflet Map and AOI Logic ---
        let map, marker, circle, drawnItems, drawControl;
        let currentAOI = '{{aoi_type}}';
        function setMapCenter(lat, lon) {
            if (map) {
                map.setView([lat, lon], 12);
                if (marker) marker.setLatLng([lat, lon]);
                if (circle && currentAOI === 'radius') circle.setLatLng([lat, lon]);
            }
        }
        function toggleAOI() {
            const aoiType = document.querySelector('input[name="aoi_type"]:checked').value;
            currentAOI = aoiType;
            document.getElementById('radiusControls').style.display = aoiType === 'radius' ? '' : 'none';
            document.getElementById('polygonControls').style.display = aoiType === 'polygon' ? '' : 'none';
            if (aoiType === 'radius') {
                if (drawnItems) drawnItems.clearLayers();
                if (circle) circle.addTo(map);
                if (marker) marker.addTo(map);
            } else {
                if (circle) map.removeLayer(circle);
                if (marker) map.removeLayer(marker);
            }
        }
        function updateRadius() {
            if (!circle) return;
            const r = parseFloat(document.getElementById('radius_meters').value);
            circle.setRadius(r);
        }
        function prepareAOI() {
            const aoiType = document.querySelector('input[name="aoi_type"]:checked').value;
            if (aoiType === 'polygon') {
                if (!drawnItems || drawnItems.getLayers().length === 0) {
                    alert('Please draw a polygon on the map.');
                    return false;
                }
                const geojson = drawnItems.getLayers()[0].toGeoJSON();
                document.getElementById('polygon_geojson').value = JSON.stringify(geojson);
            }
            if (aoiType === 'radius') {
                if (!circle) {
                    alert('Please set a radius on the map.');
                    return false;
                }
                document.getElementById('radius_meters').value = circle.getRadius();
            }
            return true;
        }
        document.addEventListener('DOMContentLoaded', function() {
            // Initialize map
            const lat = parseFloat(document.getElementById('latitude').value) || 43.7;
            const lon = parseFloat(document.getElementById('longitude').value) || -79.4;
            map = L.map('map').setView([lat, lon], 12);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
                attribution: '© OpenStreetMap'
            }).addTo(map);
            marker = L.marker([lat, lon], {draggable:true}).addTo(map);
            marker.on('dragend', function(e) {
                const pos = marker.getLatLng();
                document.getElementById('latitude').value = pos.lat;
                document.getElementById('longitude').value = pos.lng;
                if (circle) circle.setLatLng(pos);
            });
            circle = L.circle([lat, lon], {radius: parseFloat(document.getElementById('radius_meters').value) || 10000, color:'#3388ff'});
            if (currentAOI === 'radius') circle.addTo(map);
            circle.on('edit', function(e) {
                document.getElementById('radius_meters').value = circle.getRadius();
            });
            map.on('click', function(e) {
                marker.setLatLng(e.latlng);
                document.getElementById('latitude').value = e.latlng.lat;
                document.getElementById('longitude').value = e.latlng.lng;
                if (circle) circle.setLatLng(e.latlng);
            });
            // Leaflet Draw for polygon
            drawnItems = new L.FeatureGroup();
            map.addLayer(drawnItems);
            drawControl = new L.Control.Draw({
                draw: {
                    polygon: true,
                    polyline: false,
                    rectangle: false,
                    circle: false,
                    marker: false,
                    circlemarker: false
                },
                edit: {
                    featureGroup: drawnItems,
                    remove: true
                }
            });
            map.addControl(drawControl);
            map.on(L.Draw.Event.CREATED, function (e) {
                drawnItems.clearLayers();
                drawnItems.addLayer(e.layer);
            });
            map.on(L.Draw.Event.DELETED, function (e) {
                // nothing needed
            });
            // Load existing AOI if present
            {% if aoi_type == 'polygon' and polygon_geojson %}
            setTimeout(function() {
                var geojson = {{ polygon_geojson|tojson }};
                var layer = L.geoJSON(geojson).getLayers()[0];
                drawnItems.clearLayers();
                drawnItems.addLayer(layer);
                map.fitBounds(layer.getBounds());
            }, 300);
            {% elif aoi_type == 'radius' and radius_val %}
            setTimeout(function() {
                if (circle) circle.setRadius({{radius_val}});
            }, 300);
            {% endif %}
            // AOI toggle
            document.querySelectorAll('input[name="aoi_type"]').forEach(r => r.addEventListener('change', toggleAOI));
        });
        </script>
        </div>
    ''', city=city, aoi_type=aoi_type, radius_val=radius_val, polygon_geojson=polygon_geojson)

@app.route('/delete/<city_id>')
def delete_city(city_id):
    if not is_logged_in():
        logging.debug("Delete city: user not logged in.")
        return redirect(url_for('login'))
    cities = load_cities()
    city = next((c for c in cities if c['city_id'] == city_id), None)
    if city:
        logging.info(f"Deleting city: {city}")
    else:
        logging.warning(f"Delete city: city_id {city_id} not found.")
    cities = [c for c in cities if c['city_id'] != city_id]
    save_cities(cities)
    return redirect(url_for('index'))

@app.route('/sync/<city_id>', methods=['GET', 'POST'])
def sync_city(city_id):
    if not is_logged_in():
        return redirect(url_for('login'))
    cities = load_cities()
    city = next((c for c in cities if c['city_id'] == city_id), None)
    if not city:
        return 'City not found', 404
    error_message = None
    if request.method == 'POST':
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        from datetime import datetime, timedelta
        d1 = datetime.strptime(start_date, '%Y-%m-%d')
        d2 = datetime.strptime(end_date, '%Y-%m-%d')
        delta = d2 - d1
        dates = [(d1 + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(delta.days + 1)]
        sync_id = str(uuidlib.uuid4())
        aoi_info = None
        if 'radius_meters' in city:
            aoi_info = {'type': 'radius', 'radius_meters': city['radius_meters']}
        elif 'polygon_geojson' in city:
            aoi_info = {'type': 'polygon', 'polygon': 'defined'}
        data_sync_progress[sync_id] = {
            'current': 0,
            'total': len(dates),
            'date': '',
            'status': 'pending',
            'done': False,
            'city': city['city'],
            'country': city['country'],
            'state_province': city.get('state_province', ''),
            'date_range': f"{start_date} to {end_date}",
            'aoi': aoi_info
        }
        # Run sync in thread and check for quota error
        def sync_and_check():
            threaded_sync(city, dates, sync_id)
            # After sync, check for quota error in progress
            prog = data_sync_progress.get(sync_id, {})
            for err in prog.get('errors', []):
                if 'Monthly Job Quota exceeded' in err:
                    nonlocal error_message
                    error_message = 'Monthly Job Quota exceeded. Please contact support for inquiry.'
        threading.Thread(target=sync_and_check, daemon=True).start()
        return render_template_string(APPLE_STYLE + '''
            <div class="container">
            <h2>Sync Progress for {{city['city']}}</h2>
            {% if error_message %}
            <div style="color:#c00;font-weight:bold;margin-bottom:1em;">{{ error_message }}</div>
            {% endif %}
            <div><b>City:</b> {{city['city']}}<br>
            <b>Country:</b> {{city['country']}}<br>
            <b>State/Province:</b> {{city.get('state_province', '')}}<br>
            <b>Date Range:</b> {{city['date_range']}}</div>
            <div id="progress-bar" style="width: 100%; background: #eee; border: 1px solid #ccc; height: 30px; margin-top: 1em;">
              <div id="bar" style="height: 100%; width: 0; background: #4caf50; text-align: center; color: white;"></div>
            </div>
            <div id="status"></div>
            <div id="veraset_status" style="color:#007aff;margin-top:1em;"></div>
            <div id="errors" style="color: #c00; margin-top: 1em;"></div>
            <a href="{{ url_for('index') }}">Back</a>
            <script>
            function poll() {
              fetch('/sync_progress/{{sync_id}}').then(r => r.json()).then(data => {
                let percent = Math.round(100 * data.current / data.total);
                document.getElementById('bar').style.width = percent + '%';
                document.getElementById('bar').textContent = percent + '%';
                document.getElementById('status').textContent = `Syncing date: ${data.date} (${data.current}/${data.total}) Status: ${data.status}`;
                if (data.veraset_status) {
                  document.getElementById('veraset_status').textContent = data.veraset_status;
                } else {
                  document.getElementById('veraset_status').textContent = '';
                }
                // Always update quota error at top if present
                let quotaError = data.errors && data.errors.some(e => e.includes('Monthly Job Quota exceeded'));
                let quotaDiv = document.getElementById('quota_error');
                if (quotaDiv) {
                  quotaDiv.remove(); // Always remove before possibly adding
                }
                if (quotaError) {
                  quotaDiv = document.createElement('div');
                  quotaDiv.id = 'quota_error';
                  quotaDiv.style = 'color:#c00;font-weight:bold;margin-bottom:1em;';
                  quotaDiv.textContent = 'Monthly Job Quota exceeded. Please contact support for inquiry.';
                  let container = document.querySelector('.container');
                  if (container) {
                    container.insertBefore(quotaDiv, container.children[1]);
                  }
                }
                if (data.errors && data.errors.length > 0) {
                  document.getElementById('errors').innerHTML = '<b>Errors:</b><br>' + data.errors.map(e => `<div>${e}</div>`).join('');
                } else {
                  document.getElementById('errors').innerHTML = '';
                }
                if (!data.done) setTimeout(poll, 1000);
                else document.getElementById('status').textContent += ' (Done)';
                if (data.s3_sync) {
                  document.getElementById('status').textContent += '\n' + data.s3_sync;
                }
              });
            }
            document.addEventListener('DOMContentLoaded', poll);
            </script>
            </div>
        ''', city=city, sync_id=sync_id, error_message=error_message)
    return render_template_string(APPLE_STYLE + '''
        <div class="container">
        <h2>Sync City: {{city['city']}}</h2>
        <form method="post">
            Start Date: <input name="start_date" type="date" required><br>
            End Date: <input name="end_date" type="date" required><br>
            <input type="submit" value="Sync">
        </form>
        <a href="{{ url_for('index') }}">Back</a>
        </div>
    ''', city=city)

@app.route('/sync_progress/<sync_id>')
def sync_progress(sync_id):
    prog = data_sync_progress.get(sync_id, {'current': 0, 'total': 1, 'date': '', 'status': 'pending', 'done': True, 'errors': []})
    return jsonify(prog)

@app.route('/countries_states.json')
def countries_states():
    return send_from_directory('.', 'countries_states.json', mimetype='application/json')

@app.route('/geocode_city')
def geocode_city():
    city = request.args.get('city')
    country = request.args.get('country')
    state = request.args.get('state')
    logging.debug(f"Geocoding request: city={city}, country={country}, state={state}")
    if not city or not country:
        logging.warning("Geocoding failed: city and country required.")
        return {'error': 'city and country required'}, 400
    query = f"{city}, {state+', ' if state else ''}{country}"
    url = f"https://nominatim.openstreetmap.org/search"
    params = {'q': query, 'format': 'json', 'limit': 1}
    headers = {'User-Agent': 'mobility-app/1.0'}
    resp = requests.get(url, params=params, headers=headers)
    if resp.status_code != 200 or not resp.json():
        logging.warning(f"Geocoding failed for {query}: {resp.status_code} {resp.text}")
        return {'error': 'not found'}, 404
    data = resp.json()[0]
    logging.info(f"Geocoding result for {query}: lat={data['lat']}, lon={data['lon']}")
    return {'lat': data['lat'], 'lon': data['lon']}

@app.route('/view_logs')
def view_logs():
    if not is_logged_in():
        return redirect(url_for('login'))
    try:
        with open(LOG_FILE, 'r') as f:
            lines = f.readlines()[-1000:]
    except Exception as e:
        lines = [f"Error reading log: {e}"]
    # If AJAX, just return logs as plain text
    if request.args.get('ajax') == '1':
        return ''.join(lines), 200, {'Content-Type': 'text/plain'}
    return render_template_string(APPLE_STYLE + '''
        <div class="container">
        <h2>Application Logs (last 1000 lines)</h2>
        <button id="pauseBtn" onclick="togglePause()">Pause</button>
        <button onclick="refreshLogs()">Refresh</button>
        <pre id="logbox" style="background:#111;color:#eee;padding:1em;max-height:1000px;max-width:1400px;overflow:auto;font-size:13px;">{{logs}}</pre>
        <a href="{{ url_for('index') }}">Back</a>
        <script>
        let paused = false;
        function refreshLogs() {
            fetch('/view_logs?ajax=1').then(r => r.text()).then(txt => {
                if (!paused) {
                    const logbox = document.getElementById('logbox');
                    logbox.textContent = txt;
                    logbox.scrollTop = logbox.scrollHeight;
                }
            });
        }
        function pollLogs() {
            if (!paused) refreshLogs();
            setTimeout(pollLogs, 2000);
        }
        function togglePause() {
            paused = !paused;
            document.getElementById('pauseBtn').textContent = paused ? 'Resume' : 'Pause';
        }
        pollLogs();
        </script>
        </div>
    ''', logs=''.join(lines))

def get_job_status(job_id):
    return make_api_request(f"job/{job_id}", method="GET")

@app.route('/sync_jobs')
def sync_jobs():
    if not is_logged_in():
        return redirect(url_for('login'))
    # Only show jobs from the last 30 days, sorted most recent first
    now = datetime.utcnow()
    jobs = []
    for k, v in data_sync_progress.items():
        # Try to parse the date field
        try:
            job_date = datetime.strptime(str(v.get('date', '')), '%Y-%m-%d')
        except Exception:
            job_date = now  # If missing or invalid, treat as now
        if (now - job_date).days <= 30:
            # Check for quota error
            quota_error = any('Monthly Job Quota exceeded' in e for e in v.get('errors', []))
            jobs.append({'sync_id': k, 'job_date': job_date, 'quota_error': quota_error, **v})
    # Sort by job_date descending
    jobs.sort(key=lambda j: j['job_date'], reverse=True)
    return render_template_string(APPLE_STYLE + '''
        <div class="container">
        <h2>All Sync Jobs Progress (Last 30 Days)</h2>
        <table border=1 cellpadding=5>
            <tr><th>Sync ID</th><th>City</th><th>Date Range</th><th>Date</th><th>Status</th><th>Current</th><th>Total</th><th>Veraset Status</th><th>Done</th><th>Errors</th><th>Quota Exceeded</th><th>View</th></tr>
            {% for job in jobs %}
            <tr>
                <td style="font-size:0.9em">{{job.sync_id}}</td>
                <td>{{job.get('city','')}}</td>
                <td>{{job.get('date_range','')}}</td>
                <td>{{job.date}}</td>
                <td>{{job.status}}</td>
                <td>{{job.current}}</td>
                <td>{{job.total}}</td>
                <td>{{job.get('veraset_status','')}}</td>
                <td>{{'Yes' if job.done else 'No'}}</td>
                <td style="color:#c00">{{job.errors|join(', ')}}</td>
                <td>{% if job.quota_error %}<span style="color:#c00;font-weight:bold;">Quota Exceeded</span>{% else %}-{% endif %}</td>
                <td><a href="{{ url_for('sync_progress_page', sync_id=job.sync_id) }}">View</a></td>
            </tr>
            {% endfor %}
        </table>
        <a href="{{ url_for('index') }}">Back</a>
        </div>
    ''', jobs=jobs)

@app.route('/sync/<sync_id>', methods=['GET'])
def sync_progress_page(sync_id):
    # Show the progress page for a given sync_id (GET)
    prog = data_sync_progress.get(sync_id)
    if not prog:
        return render_template_string(APPLE_STYLE + """
            <div class='container'><h2>Sync Not Found</h2><a href='{{ url_for('index') }}'>Back</a></div>
        """)
    # Check for quota error in errors
    quota_error = any('Monthly Job Quota exceeded' in e for e in prog.get('errors', []))
    # Reuse the progress bar UI
    return render_template_string(APPLE_STYLE + '''
        <div class="container">
        <h2>Sync Progress (ID: {{sync_id}})</h2>
        {% if quota_error %}
        <div style="color:#c00;font-weight:bold;margin-bottom:1em;">Monthly Job Quota exceeded. Please contact support for inquiry.</div>
        {% endif %}
        <div><b>City:</b> {{prog.city}}<br>
        <b>Country:</b> {{prog.country}}<br>
        <b>State/Province:</b> {{prog.state_province}}<br>
        <b>Date Range:</b> {{prog.date_range}}</div>
        <div id="progress-bar" style="width: 100%; background: #eee; border: 1px solid #ccc; height: 30px; margin-top: 1em;">
          <div id="bar" style="height: 100%; width: 0; background: #4caf50; text-align: center; color: white;"></div>
        </div>
        <div id="status"></div>
        <div id="veraset_status" style="color:#007aff;margin-top:1em;"></div>
        <div id="errors" style="color: #c00; margin-top: 1em;"></div>
        <a href="{{ url_for('sync_jobs') }}">Back to Sync Jobs</a>
        <script>
        function poll() {
          fetch('/sync_progress/{{sync_id}}').then(r => r.json()).then(data => {
            let percent = Math.round(100 * data.current / data.total);
            document.getElementById('bar').style.width = percent + '%';
            document.getElementById('bar').textContent = percent + '%';
            document.getElementById('status').textContent = `Syncing date: ${data.date} (${data.current}/${data.total}) Status: ${data.status}`;
            if (data.veraset_status) {
              document.getElementById('veraset_status').textContent = data.veraset_status;
            } else {
              document.getElementById('veraset_status').textContent = '';
            }
            // Always update quota error at top if present
            let quotaError = data.errors && data.errors.some(e => e.includes('Monthly Job Quota exceeded'));
            let quotaDiv = document.getElementById('quota_error');
            if (quotaDiv) {
              quotaDiv.remove(); // Always remove before possibly adding
            }
            if (quotaError) {
              quotaDiv = document.createElement('div');
              quotaDiv.id = 'quota_error';
              quotaDiv.style = 'color:#c00;font-weight:bold;margin-bottom:1em;';
              quotaDiv.textContent = 'Monthly Job Quota exceeded. Please contact support for inquiry.';
              let container = document.querySelector('.container');
              if (container) {
                container.insertBefore(quotaDiv, container.children[1]);
              }
            }
            if (data.errors && data.errors.length > 0) {
              document.getElementById('errors').innerHTML = '<b>Errors:</b><br>' + data.errors.map(e => `<div>${e}</div>`).join('');
            } else {
              document.getElementById('errors').innerHTML = '';
            }
            if (!data.done) setTimeout(poll, 1000);
            else document.getElementById('status').textContent += ' (Done)';
            if (data.s3_sync) {
              document.getElementById('status').textContent += '\n' + data.s3_sync;
            }
          });
        }
        document.addEventListener('DOMContentLoaded', poll);
        </script>
        </div>
    ''', sync_id=sync_id, prog=prog, quota_error=quota_error)

@app.route('/sync_all', methods=['GET', 'POST'])
def sync_all():
    if not is_logged_in():
        return redirect(url_for('login'))
    error_message = None
    if request.method == 'POST':
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        schema_type = request.form.get('schema_type', 'TRIPS')
        cities = load_cities()
        sync_id = str(uuidlib.uuid4())
        data_sync_progress[sync_id] = {
            'current': 0,
            'total': len(cities),
            'date': '',
            'status': 'pending',
            'done': False,
            'city': 'ALL',
            'country': '',
            'state_province': '',
            'date_range': f"{start_date} to {end_date}",
            'errors': []
        }
        def sync_all_thread():
            errors = []
            geo_radius = []
            geo_json = []
            for city in cities:
                if 'radius_meters' in city:
                    geo_radius.append({
                        "poi_id": f"{city['city'].lower()}_center",
                        "latitude": float(city['latitude']),
                        "longitude": float(city['longitude']),
                        "distance_in_meters": float(city.get('radius_meters', 50000))
                    })
                elif 'polygon_geojson' in city:
                    geo_json.append({
                        "poi_id": f"{city['city'].lower()}_polygon",
                        "geo_json": city['polygon_geojson']['geometry'] if 'geometry' in city['polygon_geojson'] else city['polygon_geojson']
                    })
            payload = {
                "date_range": {
                    "from_date": start_date,
                    "to_date": end_date
                },
                "schema_type": schema_type
            }
            if geo_radius:
                payload["geo_radius"] = geo_radius
            if geo_json:
                payload["geo_json"] = geo_json
            api_key = os.environ.get('VERASET_API_KEY')
            logging.info(f"[Sync All] Starting sync for ALL cities from {start_date} to {end_date}")
            logging.debug(f"[Sync All] VERASET_API_KEY: {api_key}")
            logging.debug(f"[Sync All] Payload: {payload}")
            data_sync_progress[sync_id]['date'] = f"ALL ({len(cities)} cities)"
            data_sync_progress[sync_id]['status'] = f"syncing all cities"
            try:
                response = make_api_request("movement/job/pings", data=payload)
                if not response or 'error' in response:
                    errors.append(response.get('error', 'No response from API'))
                else:
                    request_id = response.get("request_id")
                    job_id = response.get("data", {}).get("job_id")
                    if not request_id or not job_id:
                        errors.append(f"No request_id or job_id in response: {response}")
                    else:
                        status = wait_for_job_completion(job_id)
                        if not status or 'error' in status:
                            errors.append(status.get('error', 'Unknown error during job status polling'))
                        else:
                            # S3 sync step
                            for city in cities:
                                sync_result = sync_data_to_bucket(city, start_date, status.get('s3_location'))
                                if not sync_result.get('success'):
                                    errors.append(sync_result.get('error', 'Unknown error during S3 sync'))
            except Exception as e:
                errors.append(str(e))
            data_sync_progress[sync_id]['done'] = True
            data_sync_progress[sync_id]['errors'] = errors
        threading.Thread(target=sync_all_thread, daemon=True).start()
        return redirect(url_for('sync_all_progress', sync_id=sync_id))
    # GET: show form
    return render_template_string(APPLE_STYLE + '''
        <div class="container">
        <h2>Sync All Cities</h2>
        <form method="post">
            Start Date: <input name="start_date" type="date" required><br>
            End Date: <input name="end_date" type="date" required><br>
            <input type="submit" value="Sync All Cities">
        </form>
        <a href="{{ url_for('index') }}">Back</a>
        </div>
    ''')

@app.route('/sync_all_progress/<sync_id>')
def sync_all_progress(sync_id):
    prog = data_sync_progress.get(sync_id)
    if not prog:
        return render_template_string(APPLE_STYLE + """
            <div class='container'><h2>Sync Not Found</h2><a href='{{ url_for('index') }}'>Back</a></div>
        """)
    return render_template_string(APPLE_STYLE + '''
        <div class="container">
        <h2>Sync Progress: All Cities</h2>
        <div><b>Date Range:</b> {{prog.date_range}}</div>
        <div id="progress-bar" style="width: 100%; background: #eee; border: 1px solid #ccc; height: 30px; margin-top: 1em;">
          <div id="bar" style="height: 100%; width: 0; background: #4caf50; text-align: center; color: white;"></div>
        </div>
        <div id="status"></div>
        <div id="errors" style="color: #c00; margin-top: 1em;"></div>
        <a href="{{ url_for('index') }}">Back</a>
        <script>
        function poll() {
          fetch('/sync_progress/{{sync_id}}').then(r => r.json()).then(data => {
            let percent = Math.round(100 * data.current / data.total);
            document.getElementById('bar').style.width = percent + '%';
            document.getElementById('bar').textContent = percent + '%';
            document.getElementById('status').textContent = `Syncing city: ${data.date} (${data.current}/${data.total}) Status: ${data.status}`;
            if (data.errors && data.errors.length > 0) {
              document.getElementById('errors').innerHTML = '<b>Errors:</b><br>' + data.errors.map(e => `<div>${e}</div>`).join('');
            } else {
              document.getElementById('errors').innerHTML = '';
            }
            if (!data.done) setTimeout(poll, 1000);
            else document.getElementById('status').textContent += ' (Done)';
          });
        }
        document.addEventListener('DOMContentLoaded', poll);
        </script>
        </div>
    ''', prog=prog, sync_id=sync_id)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=True) 

