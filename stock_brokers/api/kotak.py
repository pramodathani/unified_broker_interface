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
    even when the token is perfectly valid. So no host is hard coded: `url()` reads the one the
    login stored and builds every request path on top of it.

    The order update feed, `bin/kotak/orders/websocket_order_details`, does the same thing with the same stored value.

    Kotak also has no profile endpoint. The account's profile arrives only in the Login Validate response, so a login here keeps it on `login_response` and writes it to the Redis key `kotak:user:details` through `_store_profile`, in the shape the other brokers' `user/details` scripts write. `_PROFILE_FIELDS` names the fields Kotak's Totp_validate documentation describes, rather than filtering the response, so a token Kotak adds to it later can never land in the profile.
    """

    # Only a starting point for the first probe on an account that has never logged in and so has
    # no stored host yet. A wrong guess here costs nothing: the probe fails, the login runs, and
    # the host Kotak actually assigned is stored and used from then on.
    _FALLBACK_BASE_URL = "https://gw-napi.kotaksecurities.com"

    _PROFILE_REDIS_KEY = "kotak:user:details"

    _PROFILE_FIELDS = (
        "ucc",
        "greetingName",
        "clientType",
        "isNRI",
        "isTrialAccount",
        "dormancyStatus",
        "mfAccess",
        "asbaStatus",
        "clientGroup",
        "kId",
        "isUserPwdExpired",
        "derivativesRiskDisclosure",
        "incRange",
        "incUpdFlag",
    )

    def url(self, path):
        """Builds the absolute URL for a Kotak API path, on the host this session was assigned.

        The host is the `base_url` of the stored login. Kotak has returned it with and without a scheme and with and without a trailing slash, so it is normalized here as well as when the login stores it, rather than trusted. An account that has never logged in has no stored host yet and gets `_FALLBACK_BASE_URL`.

        This stays a separate method because the Kotak scripts in `bin/kotak/`, `bin/check-broker-connections` and the Kotak quote source build their request URLs with it.

        Args:
            path (str): The path part, with or without a leading slash.

        Returns:
            str: The absolute URL.
        """
        base_url = (self._last_login or {}).get("base_url")
        if not base_url or base_url == "None":
            base_url = self._FALLBACK_BASE_URL
        else:
            base_url = str(base_url).strip().rstrip("/")
            if not base_url.startswith(("http://", "https://")):
                base_url = f"https://{base_url}"
        return f"{base_url}/{str(path).lstrip('/')}"

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

            base_url = str(data["baseUrl"]).strip().rstrip("/")
            if not base_url.startswith(("http://", "https://")):
                base_url = f"https://{base_url}"

            last_login = {
                "broker_name": "kotak",
                "access_token": data["token"],
                "sid": data["sid"],
                "base_url": base_url,
                "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            }
            self._mongo_db["last_login"].replace_one({"broker_name": "kotak"}, last_login, upsert=True)
            self._cache.hset("last_login", "kotak", json_lib.dumps(last_login))
            self._last_login = last_login
            self.login_response = data
            self._store_profile(data)

    def _store_profile(self, login_data):
        """Stores the account's profile from a Login Validate response in Redis.

        Kotak serves the profile nowhere else. It arrives once, beside the tokens, in the answer to Login Validate, so every process that logs in writes `kotak:user:details` itself rather than leaving it to the one script that happens to be a session script. The value has the shape the other brokers' `user/details` scripts write, with `timestamp`, `status`, `code` and the profile under `data`, and holds only the fields named in `_PROFILE_FIELDS`.

        A failed write is logged and then ignored, because the login itself succeeded and the caller's session is usable without the profile.

        Args:
            login_data (dict): The `data` object of the Login Validate response.

        Returns:
            None: Nothing is returned; the profile is written to Redis.
        """
        account = {}
        for field in self._PROFILE_FIELDS:
            account[field] = login_data.get(field)
        profile = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "status": "success",
            "code": 200,
            "data": account,
        }
        try:
            self._cache.set(self._PROFILE_REDIS_KEY, json_lib.dumps(profile))
        except Exception as exception:
            self._logger.warning(f"Could not write {self._PROFILE_REDIS_KEY}: "
                                 f"{type(exception).__name__}: {exception}")
        else:
            self._logger.info(f"Wrote the profile of {account.get('ucc')} to {self._PROFILE_REDIS_KEY}")

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
