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
from sync_logic import sync_city_for_date, wait_for_job_completion
import requests
import json
import threading
import uuid as uuidlib
import logging
import time
from datetime import datetime, timedelta

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
CITIES_FILE = 'cities.json'
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
  max-width: 700px;
  margin: 40px auto;
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
  max-height: 500px;
  overflow: auto;
  margin-bottom: 24px;
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

def load_cities():
    if not os.path.exists(CITIES_FILE):
        return []
    with open(CITIES_FILE, 'r') as f:
        return json.load(f)

def save_cities(cities):
    with cities_lock:
        with open(CITIES_FILE, 'w') as f:
            json.dump(cities, f, indent=2)

def threaded_sync(city, dates, sync_id):
    total = len(dates)
    errors = []
    logging.info(f"Starting sync for {city['city']} ({city['country']}) for {total} days: {dates[0]} to {dates[-1]}")
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
            # Use the new callback and polling interval
            from datetime import datetime as dt
            date_obj = dt.strptime(date, "%Y-%m-%d")
            payload = build_sync_payload(city, date_obj, date_obj)
            response = make_api_request("movement/job/pings", data=payload)
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
                    # Poll for up to 100 minutes, every 1 minute
                    data_sync_progress[sync_id]['veraset_status'] = 'Polling Veraset job status...'
                    status_result = wait_for_job_completion(job_id, max_attempts=100, poll_interval=60, status_callback=status_callback)
                    if not status_result or 'error' in status_result:
                        status = 'failed'
                        error_msg = status_result.get('error', 'Unknown error during job status polling')
                        logging.error(f"Sync failed for {city['city']} on {date}: {error_msg}")
                    else:
                        # S3 sync step
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
            # Wait a moment so UI can show the S3 sync status
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
            'status': status,
            'done': i + 1 == total,
            'errors': errors.copy()
        })
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
    if request.method == 'POST' and 'sync_time' in request.form:
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
        </form>
        <table border=1 cellpadding=5>
            <tr><th>Country</th><th>State/Province</th><th>City</th><th>Latitude</th><th>Longitude</th><th>Email</th><th>Actions</th></tr>
            {% for city in cities %}
            <tr>
                <td>{{city['country']}}</td>
                <td>{{city.get('state_province','')}}</td>
                <td>{{city['city']}}</td>
                <td>{{city['latitude']}}</td>
                <td>{{city['longitude']}}</td>
                <td>{{city.get('notification_email','')}}</td>
                <td>
                    <a href="{{ url_for('edit_city', city_id=city['city_id']) }}">Edit</a> |
                    <a href="{{ url_for('delete_city', city_id=city['city_id']) }}" onclick="return confirm('Delete this city?')">Delete</a> |
                    <a href="{{ url_for('sync_city', city_id=city['city_id']) }}">Sync</a>
                </td>
            </tr>
            {% endfor %}
        </table>
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
            'notification_email': request.form['notification_email']
        }
        logging.info(f"Adding city: {data}")
        cities.append(data)
        save_cities(cities)
        return redirect(url_for('index'))
    return render_template_string(APPLE_STYLE + '''
        <div class="container">
        <h2>Add City</h2>
        <form method="post" id="cityForm">
            Country: <select name="country" id="country" required></select><br>
            State/Province: <select name="state_province" id="state_province"></select><br>
            City: <input name="city" id="city"><br>
            Latitude: <input name="latitude" id="latitude"><br>
            Longitude: <input name="longitude" id="longitude"><br>
            <button type="button" onclick="geocodeCity()">Auto-populate Lat/Lon</button><br>
            Notification Email: <input name="notification_email"><br>
            <input type="submit" value="Add">
        </form>
        <a href="{{ url_for('index') }}">Back</a>
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
                    } else {
                        alert('Could not find coordinates.');
                    }
                });
        }
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
        logging.info(f"Editing city: {city}")
        save_cities(cities)
        return redirect(url_for('index'))
    return render_template_string(APPLE_STYLE + '''
        <div class="container">
        <h2>Edit City</h2>
        <form method="post" id="cityForm">
            Country: <select name="country" id="country" required></select><br>
            State/Province: <select name="state_province" id="state_province"></select><br>
            City: <input name="city" id="city" value="{{city['city']}}"><br>
            Latitude: <input name="latitude" id="latitude" value="{{city['latitude']}}"><br>
            Longitude: <input name="longitude" id="longitude" value="{{city['longitude']}}"><br>
            <button type="button" onclick="geocodeCity()">Auto-populate Lat/Lon</button><br>
            Notification Email: <input name="notification_email" value="{{city['notification_email']}}"><br>
            <input type="submit" value="Save">
        </form>
        <a href="{{ url_for('index') }}">Back</a>
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
                    } else {
                        alert('Could not find coordinates.');
                    }
                });
        }
        </script>
        </div>
    ''', city=city)

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
    if request.method == 'POST':
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        from datetime import datetime, timedelta
        d1 = datetime.strptime(start_date, '%Y-%m-%d')
        d2 = datetime.strptime(end_date, '%Y-%m-%d')
        delta = d2 - d1
        dates = [(d1 + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(delta.days + 1)]
        sync_id = str(uuidlib.uuid4())
        data_sync_progress[sync_id] = {
            'current': 0,
            'total': len(dates),
            'date': '',
            'status': 'pending',
            'done': False,
            'city': city['city'],
            'country': city['country'],
            'state_province': city.get('state_province', ''),
            'date_range': f"{start_date} to {end_date}"
        }
        threading.Thread(target=threaded_sync, args=(city, dates, sync_id), daemon=True).start()
        return render_template_string(APPLE_STYLE + '''
            <div class="container">
            <h2>Sync Progress for {{city['city']}}</h2>
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
            poll();
            </script>
            </div>
        ''', city=city, sync_id=sync_id)
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
        <pre id="logbox" style="background:#222;color:#eee;padding:1em;max-height:500px;overflow:auto;font-size:13px;">{{logs}}</pre>
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

# Helper to build payload as in scripts
def build_sync_payload(city, from_date, to_date):
    return {
        "date_range": {
            "from_date": from_date.strftime("%Y-%m-%d"),
            "to_date": to_date.strftime("%Y-%m-%d")
        },
        "schema_type": "FULL",
        "geo_radius": [{
            "poi_id": f"{city['city'].lower()}_center",
            "latitude": float(city['latitude']),
            "longitude": float(city['longitude']),
            "distance_in_meters": 50000
        }]
    }

def make_api_request(endpoint, method="POST", data=None):
    url = f"{API_ENDPOINT}/v1/{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": VERASET_API_KEY
    }
    try:
        resp = requests.request(method, url, headers=headers, json=data)
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            logging.error(f"Non-JSON response: {resp.text}")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"API request error: {e}")
        raise

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
            jobs.append({'sync_id': k, 'job_date': job_date, **v})
    # Sort by job_date descending
    jobs.sort(key=lambda j: j['job_date'], reverse=True)
    return render_template_string(APPLE_STYLE + '''
        <div class="container">
        <h2>All Sync Jobs Progress (Last 30 Days)</h2>
        <table border=1 cellpadding=5>
            <tr><th>Sync ID</th><th>Date</th><th>Status</th><th>Current</th><th>Total</th><th>Veraset Status</th><th>Done</th><th>Errors</th><th>View</th></tr>
            {% for job in jobs %}
            <tr>
                <td style="font-size:0.9em">{{job.sync_id}}</td>
                <td>{{job.date}}</td>
                <td>{{job.status}}</td>
                <td>{{job.current}}</td>
                <td>{{job.total}}</td>
                <td>{{job.get('veraset_status','')}}</td>
                <td>{{'Yes' if job.done else 'No'}}</td>
                <td style="color:#c00">{{job.errors|join(', ')}}</td>
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
        return render_template_string(APPLE_STYLE + '''<div class="container"><h2>Sync Not Found</h2><a href="{{ url_for('sync_jobs') }}">Back to Sync Jobs</a></div>''')
    # Reuse the progress bar UI
    return render_template_string(APPLE_STYLE + '''
        <div class="container">
        <h2>Sync Progress (ID: {{sync_id}})</h2>
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
        poll();
        </script>
        </div>
    ''', sync_id=sync_id, prog=prog)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=True) 