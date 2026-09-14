import pyotp
import requests
import json as json_lib
from datetime import datetime

from stock_brokers.api.base import BrokerAPI, BrokerAPIException

class KotakAPIException(BrokerAPIException):
    """Raised for Kotak broker API errors."""

class KotakAPI(BrokerAPI):
    """
    Kotak API class.

    Kotak assigns each session its own API host and returns it as `baseUrl` in the Login Validate
    response - `e21`, `e22`, `e43` and so on. A call made to any other host is refused with
    stCode 200032, "Invalid URL. Please verify the 'baseUrl' in the Login Validate API response",
    even when the token is perfectly valid. So no host is hard coded: `base_url` reads the one the
    login stored and `url()` builds every request path on top of it.

    The order update feed, `bin/kotak/order_updates`, does the same thing with the same stored value.
    """

    # Only a starting point for the first probe on an account that has never logged in and so has
    # no stored host yet. A wrong guess here costs nothing: the probe fails, the login runs, and
    # the host Kotak actually assigned is stored and used from then on.
    _FALLBACK_BASE_URL = "https://gw-napi.kotaksecurities.com"

    @staticmethod
    def normalize_base_url(base_url):
        """
        A stored `baseUrl` as an origin with no trailing slash.

        Kotak has returned this value with and without a scheme and with and without a trailing
        slash, so it is normalized on the way in and on the way out rather than trusted.

        - `base_url` is the value from the Login Validate response.
        """
        base_url = str(base_url).strip().rstrip("/")
        if not base_url.startswith(("http://", "https://")):
            base_url = f"https://{base_url}"
        return base_url

    @property
    def base_url(self):
        """
        The API host this session must use, from the stored login.
        """
        stored = (self._last_login or {}).get("base_url")
        if not stored or stored == "None":
            return self._FALLBACK_BASE_URL
        return self.normalize_base_url(stored)

    def url(self, path):
        """
        Absolute URL for a Kotak API path, on the host this session was assigned.

        - `path` is the path part, with or without a leading slash.
        """
        return f"{self.base_url}/{str(path).lstrip('/')}"

    def __init__(self):
        """
        Kotak API class
        """
        super().__init__(broker_name="kotak")

        # The Login Validate response's `data`, when this object logged in; None when the stored session was
        # still good. Besides the tokens it carries the account's profile, which Kotak serves nowhere else.
        self.login_response = None

        try:
            self.get(url=self.url("/quick/user/positions"))
        except Exception as e:
            headers = {
                "Authorization": f"{self._settings['api_key']}",
                "neo-fin-key": "neotradeapi",
                "Content-Type": "application/json"
            }
            data = {
                "mobileNumber": f"{self._settings['mobile_number']}",
                "ucc": f"{self._settings['ucc_code']}",
                "totp": pyotp.TOTP(f"{self._settings['totp_secret']}").now()
            }

            data = requests.post(url="https://mis.kotaksecurities.com/login/1.0/tradeApiLogin", headers=headers, data=json_lib.dumps(data))
            if data.status_code != 200:
                raise KotakAPIException(code=data.status_code, message="Cannot get access token from Kotak REST API server.")
            
            if "json" in data.headers.get("Content-Type", ""):
                data = data.json()
                if "data" not in data:
                    raise KotakAPIException(code="500", message="Cannot get access token from Kotak REST API server.")
                data = data["data"]
            elif "text" in data.headers.get("Content-Type", ""):
                try:
                    data = json_lib.loads(data.content.decode("utf-8").strip())
                    if "data" not in data:
                        raise KotakAPIException(code="500", message="Cannot get access token from Kotak REST API server.")
                    data = data["data"]
                except json_lib.JSONDecodeError:
                    raise KotakAPIException(code="500", message="Cannot get access token from Kotak REST API server.")
            else:
                raise KotakAPIException(code="500", message="Cannot get access token from Kotak REST API server.")

            headers = {
                "Authorization": f"{self._settings['api_key']}",
                "neo-fin-key": "neotradeapi",
                "Content-Type": "application/json",
                "Auth": data["token"],
                "sid": data["sid"]
            }

            data = {
                "mpin": self._settings['mpin']
            }

            data = self.post(url="https://mis.kotaksecurities.com/login/1.0/tradeApiValidate", headers=headers, data=json_lib.dumps(data))

            if "data" not in data:
                raise KotakAPIException(code="500", message="Cannot get access token from Kotak REST API server.")
            data = data["data"]

            if "token" not in data:
                raise KotakAPIException(code="500", message="Cannot get access token from Kotak REST API server.")

            # Without this host every later call is refused with stCode 200032, so its absence is
            # a failed login rather than a detail to shrug off.
            if not data.get("baseUrl"):
                raise KotakAPIException(
                    code="500",
                    message="Kotak's Login Validate response carried no baseUrl, so there is no "
                            "host to send API calls to.")

            last_login = {
                "broker_name": "kotak",
                "access_token": data["token"],
                "sid": data["sid"],
                "base_url": self.normalize_base_url(data["baseUrl"]),
                "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            }
            self._mongo_db["last_login"].replace_one({"broker_name": "kotak"}, last_login, upsert=True)
            self._cache.hset("last_login", "kotak", json_lib.dumps(last_login))
            self._last_login = last_login
            self.login_response = data

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
                "neo-fin-key": "neotradeapi",
                "Auth": self._last_login['access_token'],
                "Sid": self._last_login['sid']
            }        
        
        if verbose == True:
            rest_api_message = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S:%f')} - requests.request(method='{method}', url='{url}', params={params}, data={data}, headers={headers}, cookies={cookies}, files={files}, auth={auth}, timeout={timeout}, allow_redirects={allow_redirects}, proxies={proxies}, hooks={hooks}, stream={stream}, verify={verify}, cert={cert}, json={json})"
            self._cache.rpush('broker_api_calls', rest_api_message)
            self._logger.info(rest_api_message)        

        response = requests.request(method=method, url=url, params=params, data=data, headers=headers, json=json)
        
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
                if "errorCode" in json_content and "message" in json_content:
                    raise KotakAPIException(code=json_content["errorCode"], message=json_content["message"])
                else:
                    raise KotakAPIException(code=response.status_code, message=json_content)
            elif "text" in response.headers["Content-Type"]:
                try:
                    json_content = json_lib.loads(response.content.decode("utf-8").strip())
                    if "errorCode" in json_content and "message" in json_content:
                        raise KotakAPIException(code=json_content["errorCode"], message=json_content["message"])
                    else:
                        raise KotakAPIException(code=response.status_code, message=json_content)
                except json_lib.JSONDecodeError:
                    raise KotakAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())
            else:
                raise KotakAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())
