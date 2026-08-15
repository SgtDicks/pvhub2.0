# Sidecar container for capture_headers.py. Build with:
#   docker build -t pvhub-auth-helper .
#
# Two delivery modes -- pick one (or pass both sets of flags together):
#
# Push -- sends fresh headers straight into Home Assistant via the
# pvhub.update_auth_headers service. No shared filesystem needed, but
# the HA token is account-wide:
#   docker run -d --name pvhub-auth-helper \
#     -e PVHUB_USERNAME=you@example.com \
#     -e PVHUB_PASSWORD=yourpassword \
#     -e HA_TOKEN=your-long-lived-access-token \
#     pvhub-auth-helper \
#     --login-url "https://www.pv-hub.com/login" \
#     --plant-url "https://www.pv-hub.com/v2/plants/analysis?GROUPID=YOUR_PLANT_ID" \
#     --ha-url "http://homeassistant.local:8123" \
#     --plant-id "YOUR_PLANT_ID" \
#     --loop-interval 1500
#
# File -- writes to a JSON file Home Assistant re-reads. No HA credential
# needed, but requires a shared filesystem path:
#   docker run -d --name pvhub-auth-helper \
#     -e PVHUB_USERNAME=you@example.com \
#     -e PVHUB_PASSWORD=yourpassword \
#     -v /path/on/host/shared:/shared \
#     pvhub-auth-helper \
#     --login-url "https://www.pv-hub.com/login" \
#     --plant-url "https://www.pv-hub.com/v2/plants/analysis?GROUPID=YOUR_PLANT_ID" \
#     --output /shared/pvhub_auth.json \
#     --loop-interval 1500

FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

WORKDIR /app
COPY capture_headers.py /app/capture_headers.py
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

ENTRYPOINT ["python", "/app/capture_headers.py"]
