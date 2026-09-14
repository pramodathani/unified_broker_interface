import base64
import hashlib
import pyotp
import requests
import time
import json as json_lib
from datetime import datetime
from urllib.parse import urlparse, parse_qs

from stock_brokers.api.base import BrokerAPI, BrokerAPIException

class FyersAPIException(BrokerAPIException):
    """Raised for Fyers broker API errors."""

class FyersAPI(BrokerAPI):
    """
    Fyers API class
    """

    def __init__(self):
        """
        Fyers API class
        """
        super().__init__(broker_name="fyers")

        try:
            self.get(url="https://api-t1.fyers.in/api/v3/profile")
        except Exception as e:
            app_id = self._settings["app_id"]
            app_name, app_type = app_id.split("-") if "-" in app_id else (app_id, "100")
            fy_id = self._settings["fy_id"]
            redirect_uri = self._settings.get("redirect_uri", "https://localhost")
            vagator_headers = {"Accept": "application/json", "Content-Type": "text/plain"}

            # Step 1: request a login OTP for the Fyers ID.
            response = requests.post(url="https://api-t2.fyers.in/vagator/v2/send_login_otp_v2", json={"fy_id": base64.b64encode(fy_id.encode()).decode(), "app_id": "2"}, headers=vagator_headers)
            if response.status_code != 200 or response.json().get("request_key") is None:
                raise FyersAPIException(code=response.status_code, message=f"Cannot send login OTP to Fyers trading platform: {response.text}")
            request_key = response.json()["request_key"]

            # Step 2: verify the OTP using the account's TOTP secret. Fyers returns
            # -2 when the code is verified too close to the 30-second boundary, so
            # pause past the boundary if needed before generating the TOTP.
            seconds_until_boundary = 30 - (datetime.now().second % 30)
            if seconds_until_boundary <= 3:
                time.sleep(seconds_until_boundary + 1)
            response = requests.post(url="https://api-t2.fyers.in/vagator/v2/verify_otp", json={"otp": pyotp.TOTP(self._settings["totp_secret"]).now(), "request_key": request_key}, headers=vagator_headers)
            if response.status_code != 200 or response.json().get("request_key") is None:
                raise FyersAPIException(code=response.status_code, message=f"Cannot verify OTP on Fyers trading platform: {response.text}")
            request_key = response.json()["request_key"]

            # Step 3: verify the login PIN.
            response = requests.post(url="https://api-t2.fyers.in/vagator/v2/verify_pin_v2", json={"identifier": base64.b64encode(self._settings["pin"].encode()).decode(), "identity_type": "pin", "request_key": request_key}, headers=vagator_headers)
            if response.status_code != 200 or response.json().get("data", {}).get("access_token") is None:
                raise FyersAPIException(code=response.status_code, message=f"Cannot verify PIN on Fyers trading platform: {response.text}")
            session_token = response.json()["data"]["access_token"]

            # Step 4: authorize the OAuth auth code. Fyers returns it either as a
            # 308 redirect with the auth code in the redirect URL's query string,
            # or directly in the response body as data.auth.
            vagator_headers["Authorization"] = f"Bearer {session_token}"
            response = requests.post(url="https://api-t1.fyers.in/api/v3/token", json={
                "fyers_id": fy_id,
                "app_id": app_name,
                "redirect_uri": redirect_uri,
                "appType": app_type,
                "code_challenge": "",
                "state": "None",
                "scope": "",
                "nonce": "",
                "response_type": "code",
                "create_cookie": True
            }, headers=vagator_headers)
            content = response.json() if response.content else {}
            auth_code = None
            if response.status_code in (200, 308):
                data = content.get("data") if isinstance(content, dict) else None
                if isinstance(data, dict):
                    auth_code = data.get("auth")
                if auth_code is None:
                    auth_code = parse_qs(urlparse(content.get("Url", "")).query).get("auth_code", [None])[0]
            if auth_code is None:
                raise FyersAPIException(code=response.status_code, message=f"Cannot get auth code from Fyers trading platform: {response.text}")

            # Step 5: exchange the auth code for the day's access token.
            response = requests.post(url="https://api-t1.fyers.in/api/v3/validate-authcode", json={
                "grant_type": "authorization_code",
                "appIdHash": hashlib.sha256(f"{app_id}:{self._settings['secret_key']}".encode()).hexdigest(),
                "code": auth_code
            }, headers=vagator_headers)
            if response.status_code != 200:
                raise FyersAPIException(code=response.status_code, message=f"Cannot validate auth code on Fyers trading platform: {response.text}")
            access_token = response.json().get("access_token")
            if access_token is None:
                raise FyersAPIException(code="500", message=f"No access_token in Fyers validate-authcode response: {response.text}")

            last_login = {
                "broker_name": "fyers",
                "access_token": access_token,
                "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self._mongo_db["last_login"].replace_one({"broker_name": "fyers"}, last_login, upsert=True)
            self._cache.hset("last_login", "fyers", json_lib.dumps(last_login))
            self._last_login = last_login

    def _request(self, method, url, params=None, data=None, headers=None, cookies=None, files=None, auth=None, timeout=None, allow_redirects=None, proxies=None, hooks=None, stream=None, verify=None, cert=None, json=None, verbose=False):
        """
        Private generic REST API request to Broker API server.
        This is specialized into GET, POST, PUT, PATCH and DELETE by public methods.

        - `method`: HTTP method to use for the request.
        - `url`: URL of the API endpoint.
        - `params`: Dictionary of parameters to be sent as part of the request.
        - `data`: Dictionary, bytes, or file-like object to send in the body of the request.
        - `headers`: Dictionary of HTTP headers to be sent with the request.
        - `cookies`: Dictionary of cookies to be sent with the request.
        - `files`: Dictionary of files to be sent with the request.
        - `auth`: Authentication tuple or object to be sent with the request.
        - `timeout`: Timeout value for the request.
        - `allow_redirects`: Boolean value indicating whether redirects should be allowed.
        - `proxies`: Dictionary of proxy settings for the request.
        - `hooks`: Dictionary of hooks to be called during the request lifecycle.
        - `stream`: Boolean value indicating whether response content should be streamed.
        - `verify`: Boolean value indicating whether SSL certificate verification should be performed.
        - `cert`: Certificate file or tuple containing certificate and key files for client-side SSL certificate verification.
        - `json`: JSON data to send in the body of the request.
        - `verbose`: If set to True, the request and response are logged.
        """
        self._current_login()
        if headers is None:
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f"{self._settings['app_id']}:{self._last_login['access_token']}"
            }
        
        rest_api_message = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S:%f')} - requests.request(method='{method}', url='{url}', params={params}, data={data}, headers={headers}, cookies={cookies}, files={files}, auth={auth}, timeout={timeout}, allow_redirects={allow_redirects}, proxies={proxies}, hooks={hooks}, stream={stream}, verify={verify}, cert={cert}, json={json})"
        if verbose == True:
            self._logger.info(rest_api_message)
            self._cache.rpush('broker_api_calls', rest_api_message)
                        
        response = requests.request(method=method, url=url, params=params, data=data, headers=headers, cookies=cookies, files=files, auth=auth, timeout=timeout, allow_redirects=allow_redirects, proxies=proxies, hooks=hooks, stream=stream, verify=verify, cert=cert, json=json)
        
        if response.status_code < 300:
            content = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                "status": "success",
                "code": response.status_code
            }
            
            if "json" in response.headers["Content-Type"]:
                if "data" in response.json():
                    content["data"] = response.json()["data"]
                else:
                    content["data"] = response.json()
            elif "text" in response.headers["Content-Type"]:
                try:
                    json_content = json_lib.loads(response.content.decode("utf-8").strip())
                    if "data" in json_content:
                        content["data"] = json_content["data"]
                    else:
                        content["data"] = json_content
                except json_lib.JSONDecodeError:
                    content["data"] = response.content.decode("utf-8").strip()
            else:
                content["data"] = response.content.decode("utf-8").strip()
            return content
        else:
            if "json" in response.headers["Content-Type"]:
                json_content = response.json()
                if "message" in json_content and "code" in json_content:
                    raise FyersAPIException(code=json_content["code"], message=json_content["message"])
                else:
                    raise FyersAPIException(code=response.status_code, message=json_content)
            elif "text" in response.headers["Content-Type"]:
                try:
                    json_content = json_lib.loads(response.content.decode("utf-8").strip())
                    if "message" in json_content and "code" in json_content:
                        raise FyersAPIException(code=json_content["code"], message=json_content["message"])
                    else:
                        raise FyersAPIException(code=response.status_code, message=json_content)
                except json_lib.JSONDecodeError:
                    raise FyersAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())
            else:
                raise FyersAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())
