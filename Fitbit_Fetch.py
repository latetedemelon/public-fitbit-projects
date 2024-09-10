import base64, requests, schedule, time, json, pytz, logging, os, sys
from requests.exceptions import ConnectionError
from datetime import datetime, timedelta

# Variables
FITBIT_LOG_FILE_PATH = os.environ.get("FITBIT_LOG_FILE_PATH") or "your/expected/log/file/location/path"
TOKEN_FILE_PATH = os.environ.get("TOKEN_FILE_PATH") or "your/expected/token/file/location/path"
OVERWRITE_LOG_FILE = True
FITBIT_LANGUAGE = 'en_US'
VICTORIA_METRICS_URL = os.environ.get("VICTORIA_METRICS_URL") or "http://your_victoriametrics_url_here/api/v1/import"  # VictoriaMetrics endpoint
client_id = os.environ.get("CLIENT_ID") or "your_application_client_ID"
client_secret = os.environ.get("CLIENT_SECRET") or "your_application_client_secret"
DEVICENAME = os.environ.get("DEVICENAME") or "Your_Device_Name"
ACCESS_TOKEN = ""
AUTO_DATE_RANGE = True
auto_update_date_range = 1
LOCAL_TIMEZONE = os.environ.get("LOCAL_TIMEZONE") or "Automatic"
SCHEDULE_AUTO_UPDATE = True if AUTO_DATE_RANGE else False
SERVER_ERROR_MAX_RETRY = 3
EXPIRED_TOKEN_MAX_RETRY = 5
SKIP_REQUEST_ON_SERVER_ERROR = True

# Logging setup
if OVERWRITE_LOG_FILE:
    with open(FITBIT_LOG_FILE_PATH, "w"): pass

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(FITBIT_LOG_FILE_PATH, mode='a'),
        logging.StreamHandler(sys.stdout)
    ]
)

# VictoriaMetrics Data Write Function
def write_points_to_victoria_metrics(points):
    try:
        headers = {
            'Content-Type': 'text/plain'
        }
        # Prepare data in line protocol format for VictoriaMetrics
        lines = []
        for point in points:
            measurement = point['measurement']
            time = point['time']
            fields = ",".join([f"{k}={v}" for k, v in point['fields'].items()])
            tags = ",".join([f"{k}={v}" for k, v in point['tags'].items()])
            line = f"{measurement},{tags} {fields} {int(datetime.fromisoformat(time).timestamp() * 1e9)}"
            lines.append(line)

        data = "\n".join(lines)
        response = requests.post(VICTORIA_METRICS_URL, headers=headers, data=data)

        if response.status_code == 200:
            logging.info("Successfully updated VictoriaMetrics database with new points")
        else:
            logging.error(f"VictoriaMetrics connection failed with status code {response.status_code}: {response.text}")
    except Exception as err:
        logging.error(f"Error while writing points to VictoriaMetrics: {err}")
        print(f"VictoriaMetrics connection failed: {err}")

# API Request Function
def request_data_from_fitbit(url, headers={}, params={}, data={}, request_type="get"):
    global ACCESS_TOKEN
    retry_attempts = 0
    logging.debug("Requesting data from fitbit via Url : " + url)
    while True:
        if request_type == "get":
            headers = {
                "Authorization": f"Bearer {ACCESS_TOKEN}",
                "Accept": "application/json",
                'Accept-Language': FITBIT_LANGUAGE
            }
        try:
            if request_type == "get":
                response = requests.get(url, headers=headers, params=params, data=data)
            elif request_type == "post":
                response = requests.post(url, headers=headers, params=params, data=data)
            else:
                raise Exception("Invalid request type " + str(request_type))
        
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                retry_after = int(response.headers["Retry-After"]) + 300
                logging.warning("Fitbit API limit reached. Retrying in " + str(retry_after) + " seconds")
                time.sleep(retry_after)
            elif response.status_code == 401:
                ACCESS_TOKEN = Get_New_Access_Token(client_id, client_secret)
                time.sleep(30)
                if retry_attempts > EXPIRED_TOKEN_MAX_RETRY:
                    raise Exception("Unable to solve the 401 Error. " + response.text)
            elif response.status_code in [500, 502, 503, 504]:
                logging.warning("Server Error encountered. Retrying after 120 seconds....")
                time.sleep(120)
                if retry_attempts > SERVER_ERROR_MAX_RETRY:
                    logging.error("Unable to solve the server Error. Retry limit exceeded.")
                    if SKIP_REQUEST_ON_SERVER_ERROR:
                        return None
            else:
                logging.error("Fitbit API request failed. Status code: " + str(response.status_code) + " " + str(response.text))
                response.raise_for_status()
                return None

        except ConnectionError as e:
            logging.error("Failed to connect to the internet: " + str(e))
        retry_attempts += 1
        time.sleep(30)

# Token management functions
def refresh_fitbit_tokens(client_id, client_secret, refresh_token):
    logging.info("Attempting to refresh tokens...")
    url = "https://api.fitbit.com/oauth2/token"
    headers = {
        "Authorization": "Basic " + base64.b64encode((client_id + ":" + client_secret).encode()).decode(),
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    json_data = request_data_from_fitbit(url, headers=headers, data=data, request_type="post")
    access_token = json_data["access_token"]
    new_refresh_token = json_data["refresh_token"]
    tokens = {
        "access_token": access_token,
        "refresh_token": new_refresh_token
    }
    with open(TOKEN_FILE_PATH, "w") as file:
        json.dump(tokens, file)
    return access_token, new_refresh_token

def load_tokens_from_file():
    with open(TOKEN_FILE_PATH, "r") as file:
        tokens = json.load(file)
        return tokens.get("access_token"), tokens.get("refresh_token")

def Get_New_Access_Token(client_id, client_secret):
    try:
        access_token, refresh_token = load_tokens_from_file()
    except FileNotFoundError:
        refresh_token = input("No token file found. Please enter a valid refresh token : ")
    access_token, refresh_token = refresh_fitbit_tokens(client_id, client_secret, refresh_token)
    return access_token

ACCESS_TOKEN = Get_New_Access_Token(client_id, client_secret)

# Fitbit Data Retrieval Functions
def get_battery_level():
    device = request_data_from_fitbit("https://api.fitbit.com/1/user/-/devices.json")[0]
    if device:
        collected_records.append({
            "measurement": "DeviceBatteryLevel",
            "time": LOCAL_TIMEZONE.localize(datetime.fromisoformat(device['lastSyncTime'])).astimezone(pytz.utc).isoformat(),
            "fields": {"value": float(device['batteryLevel'])},
            "tags": {"Device": DEVICENAME}
        })

def get_intraday_data_limit_1d(date_str, measurement_list):
    for measurement in measurement_list:
        data = request_data_from_fitbit(f'https://api.fitbit.com/1/user/-/activities/{measurement[0]}/date/{date_str}/1d/{measurement[2]}.json')["activities-" + measurement[0] + "-intraday"]['dataset']
        if data:
            for value in data:
                log_time = datetime.fromisoformat(date_str + "T" + value['time'])
                utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
                collected_records.append({
                    "measurement": measurement[1],
                    "time": utc_time,
                    "tags": {"Device": DEVICENAME},
                    "fields": {"value": int(value['value'])}
                })

def get_daily_data_limit_30d(start_date_str, end_date_str):
    hrv_data_list = request_data_from_fitbit(f'https://api.fitbit.com/1/user/-/hrv/date/{start_date_str}/{end_date_str}.json')['hrv']
    if hrv_data_list:
        for data in hrv_data_list:
            log_time = datetime.fromisoformat(data["dateTime"] + "T" + "00:00:00")
            utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
            collected_records.append({
                "measurement": "HRV",
                "time": utc_time,
                "tags": {"Device": DEVICENAME},
                "fields": {
                    "dailyRmssd": data["value"]["dailyRmssd"],
                    "deepRmssd": data["value"]["deepRmssd"]
                }
            })

def get_daily_data_limit_100d(start_date_str, end_date_str):
    sleep_data = request_data_from_fitbit(f'https://api.fitbit.com/1.2/user/-/sleep/date/{start_date_str}/{end_date_str}.json')["sleep"]
    if sleep_data:
        for record in sleep_data:
            log_time = datetime.fromisoformat(record["startTime"])
            utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
            collected_records.append({
                "measurement": "Sleep Summary",
                "time": utc_time,
                "tags": {"Device": DEVICENAME, "isMainSleep": record["isMainSleep"]},
                "fields": {
                    'efficiency': record["efficiency"],
                    'minutesAfterWakeup': record['minutesAfterWakeup'],
                    'minutesAsleep': record['minutesAsleep'],
                    'minutesToFallAsleep': record['minutesToFallAsleep'],
                    'minutesInBed': record['timeInBed'],
                    'minutesAwake': record['minutesAwake']
                }
            })

def get_daily_data_limit_365d(start_date_str, end_date_str):
    activity_minutes_list = ["minutesSedentary", "minutesLightlyActive", "minutesFairlyActive", "minutesVeryActive"]
    for activity_type in activity_minutes_list:
        activity_minutes_data_list = request_data_from_fitbit(f'https://api.fitbit.com/1/user/-/activities/tracker/{activity_type}/date/{start_date_str}/{end_date_str}.json')["activities-tracker-"+activity_type]
        if activity_minutes_data_list:
            for data in activity_minutes_data_list:
                log_time = datetime.fromisoformat(data["dateTime"] + "T" + "00:00:00")
                utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
                collected_records.append({
                    "measurement": "Activity Minutes",
                    "time": utc_time,
                    "tags": {"Device": DEVICENAME},
                    "fields": {activity_type: int(data["value"])}
                })

def get_daily_data_limit_none(start_date_str, end_date_str):
    data_list = request_data_from_fitbit(f'https://api.fitbit.com/1/user/-/spo2/date/{start_date_str}/{end_date_str}.json')
    if data_list:
        for data in data_list:
            log_time = datetime.fromisoformat(data["dateTime"] + "T" + "00:00:00")
            utc_time = LOCAL_TIMEZONE.localize(log_time).astimezone(pytz.utc).isoformat()
            collected_records.append({
                "measurement": "SPO2",
                "time": utc_time,
                "tags": {"Device": DEVICENAME},
                "fields": {
                    "avg": data["value"]["avg"],
                    "max": data["value"]["max"],
                    "min": data["value"]["min"]
                }
            })

def fetch_latest_activities(end_date_str):
    recent_activities_data = request_data_from_fitbit('https://api.fitbit.com/1/user/-/activities/list.json', params={'beforeDate': end_date_str, 'sort':'desc', 'limit':50, 'offset':0})
    if recent_activities_data:
        for activity in recent_activities_data['activities']:
            fields = {}
            if 'activeDuration' in activity:
                fields['ActiveDuration'] = int(activity['activeDuration'])
            if 'averageHeartRate' in activity:
                fields['AverageHeartRate'] = int(activity['averageHeartRate'])
            if 'calories' in activity:
                fields['calories'] = int(activity['calories'])
            if 'duration' in activity:
                fields['duration'] = int(activity['duration'])
            if 'distance' in activity:
                fields['distance'] = float(activity['distance'])
            if 'steps' in activity:
                fields['steps'] = int(activity['steps'])
            starttime = datetime.fromisoformat(activity['startTime'].strip("Z"))
            utc_time = starttime.astimezone(pytz.utc).isoformat()
            collected_records.append({
                "measurement": "Activity Records",
                "time": utc_time,
                "tags": {"ActivityName": activity['activityName']},
                "fields": fields
            })

# Scheduler for continuous updates
if SCHEDULE_AUTO_UPDATE:
    schedule.every(1).hours.do(lambda : Get_New_Access_Token(client_id, client_secret))
    schedule.every(3).minutes.do(lambda : get_intraday_data_limit_1d(end_date_str, [('heart','HeartRate_Intraday','1sec'),('steps','Steps_Intraday','1min')]))
    schedule.every(1).hours.do(lambda : get_intraday_data_limit_1d((datetime.strptime(end_date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"), [('heart','HeartRate_Intraday','1sec'),('steps','Steps_Intraday','1min')]))
    schedule.every(20).minutes.do(get_battery_level)
    schedule.every(3).hours.do(lambda : get_daily_data_limit_30d(start_date_str, end_date_str))
    schedule.every(4).hours.do(lambda : get_daily_data_limit_100d(start_date_str, end_date_str))
    schedule.every(6).hours.do(lambda : get_daily_data_limit_365d(start_date_str, end_date_str))
    schedule.every(6).hours.do(lambda : get_daily_data_limit_none(start_date_str, end_date_str))
    schedule.every(1).hours.do(lambda : fetch_latest_activities(end_date_str))

    while True:
        schedule.run_pending()
        if collected_records:
            write_points_to_victoria_metrics(collected_records)
            collected_records = []
        time.sleep(30)
