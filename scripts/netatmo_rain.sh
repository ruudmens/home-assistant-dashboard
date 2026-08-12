#!/usr/bin/env bash
# /config/netatmo_rain.sh
# Fetches rain_24h from a public Netatmo weather station near your home.
# Output: a single float (mm) or the string "unavailable"
#
# First-time setup:
#   1. Create a Netatmo developer app at https://dev.netatmo.com/apps
#      to get a CLIENT_ID and CLIENT_SECRET.
#   2. Complete the OAuth2 authorization flow once to obtain a
#      REFRESH_TOKEN (Netatmo's docs walk through this).
#   3. Fill in the placeholders below.
#   4. chmod +x /config/netatmo_rain.sh
#   5. bash /config/netatmo_rain.sh   (test manually in the HA terminal)
#
# You don't need to own a Netatmo station yourself — the public data API
# returns readings from any nearby public station, so this also works if a
# neighbor has one.

# ── Credentials — replace the values below with your own ──────────────────
CLIENT_ID="<YOUR_NETATMO_CLIENT_ID>"
CLIENT_SECRET="<YOUR_NETATMO_CLIENT_SECRET>"
REFRESH_TOKEN="<YOUR_NETATMO_REFRESH_TOKEN>"
# ─────────────────────────────────────────────────────────────────────────

# MAC addresses of the specific station + rain module to read from. Find
# these by first calling getpublicdata without a filter and inspecting the
# response, or via the Netatmo app if it's your own station.
STATION_MAC="<STATION_MAC_ADDRESS>"
RAIN_MODULE_MAC="<RAIN_MODULE_MAC_ADDRESS>"

# Step 1: Get a fresh access token via the refresh token flow
TOKEN_RESPONSE=$(curl -s --max-time 15 -X POST "https://api.netatmo.com/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=refresh_token&client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}&refresh_token=${REFRESH_TOKEN}")

# Parse the token — python3 as primary method, jq as fallback
ACCESS_TOKEN=""
if command -v python3 &>/dev/null; then
  ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('access_token', ''))
except Exception:
    print('')
" 2>/dev/null)
fi

if [ -z "$ACCESS_TOKEN" ] && command -v jq &>/dev/null; then
  ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token // empty' 2>/dev/null)
fi

if [ -z "$ACCESS_TOKEN" ]; then
  echo "unavailable"
  exit 0
fi

# Step 2: Fetch public rain data for the bounding box around your location.
# Replace with a small box (roughly 0.01-0.02 degrees per side) centered on
# your own coordinates.
DATA_RESPONSE=$(curl -s --max-time 15 \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  "https://api.netatmo.com/api/getpublicdata?lat_ne=<LAT_NE>&lon_ne=<LON_NE>&lat_sw=<LAT_SW>&lon_sw=<LON_SW>&required_data=rain")

# Step 3: Extract rain_24h for the configured station and module
RAIN_VALUE=""
if command -v python3 &>/dev/null; then
  RAIN_VALUE=$(echo "$DATA_RESPONSE" | python3 -c "
import sys, json

station_mac = '${STATION_MAC}'.lower()
module_mac  = '${RAIN_MODULE_MAC}'.lower()

try:
    data = json.load(sys.stdin)
    for station in data.get('body', []):
        if station.get('_id', '').lower() == station_mac:
            measures = station.get('measures', {})
            for key, val in measures.items():
                if key.lower() == module_mac:
                    rain = val.get('rain_24h')
                    if rain is not None:
                        print(rain)
                        sys.exit(0)
    print('unavailable')
except Exception:
    print('unavailable')
" 2>/dev/null)
fi

# Fallback to jq if python3 isn't available or returned nothing
if [ -z "$RAIN_VALUE" ] && command -v jq &>/dev/null; then
  RAIN_VALUE=$(echo "$DATA_RESPONSE" | jq -r \
    --arg s "${STATION_MAC}" --arg m "${RAIN_MODULE_MAC}" \
    '.body[]? | select(.["_id"] == $s) | .measures[$m].rain_24h // "unavailable"' \
    2>/dev/null | head -1)
fi

echo "${RAIN_VALUE:-unavailable}"
