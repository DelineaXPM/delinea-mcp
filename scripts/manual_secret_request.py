import os
import requests
import sys

if len(sys.argv) < 2:
    print("Usage: python test_secret_request.py <Secret_ID>")
    exit(1)

secret_id = sys.argv[1]
password_env_var = f'SECRET_PASSWORD_{secret_id}'
username_env_var = f'SECRET_USERNAME_{secret_id}'
print(f"Using environment variables: {password_env_var}, {username_env_var}")
client_secret = os.getenv(password_env_var)
client_id = os.getenv(username_env_var)
print(f"Using environment variables: {client_secret}, {client_id}")

if not client_secret or not client_id:
    print(f"Required environment variables {password_env_var} and/or {username_env_var} not set.")
    exit(1)

base_url = os.getenv("DELINEA_BASE_URL", "https://localhost/SecretServer")
oauth_url = base_url.rstrip("/") + "/oauth2/token"
data = {"username": client_id, "password": client_secret, "grant_type": "password"}
response = requests.post(oauth_url, data=data)
if response.status_code == 200:
    print(f"OAuth2 token response: {response.json()}")
else:
    print(f"Failed to get OAuth2 token: {response.status_code} {response.text}")
