import pyotp
import hashlib
import requests
import json as json_lib
from datetime import datetime
from urllib.parse import urlparse, parse_qs

from stock_brokers.api.base import BrokerAPI, BrokerAPIException

class FlattradeAPIException(BrokerAPIException):
    """Raised for Flattrade broker API errors."""

class FlattradeAPI(BrokerAPI):
    """
    Flattrade API class
    """

    def __init__(self):
        """
        Flattrade API class
        """
        super().__init__(broker_name="flattrade")

        try:
            # Noren refuses a dead session inside an HTTP 200, which the request raises nothing for, so the
            # body is checked too: without it a dead token would never lead to a login.
            details = (self.post(url="https://piconnect.flattrade.in/PiConnectAPI/UserDetails") or {}).get("data")
            if not isinstance(details, dict) or str(details.get("stat", "")).lower() != "ok":
                raise FlattradeAPIException(code="Not_Ok", message=f"UserDetails refused the session: {str(details)[:200]}")
        except Exception as e:
            headers = {
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.5",
                "Host": "authapi.flattrade.in",
                "Origin": "https://auth.flattrade.in",
                "Referer": "https://auth.flattrade.in/",
            }
            
            response = requests.post("https://auth.flattrade.in/auth/session", headers=headers)
            if response.status_code != 200:
                raise FlattradeAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())

            sid = response.text
            json_data = {
                "UserName": self._settings["username"],
                "Password": hashlib.sha256(self._settings["password"].encode()).hexdigest(),
                "App":"",
                "ClientID":"",
                "Key":"",
                "APIKey": self._settings["api_key"],
                "PAN_DOB": pyotp.TOTP(self._settings["totp_secret"]).now(),
                "Sid" : sid,
                "Override": ""
            }

            response = requests.post("https://auth.flattrade.in/ftauth", json=json_data, headers=headers)
            if response.status_code != 200:
                raise FlattradeAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())

            response_data = response.json()
            redirect_url = response_data.get("RedirectURL", "")
            query_params = parse_qs(urlparse(redirect_url).query)
            if "code" not in query_params:
                emsg = response_data.get("emsg") or response_data.get("stat")
                if emsg:
                    raise FlattradeAPIException(
                        code=emsg,
                        message=f"Flattrade login blocked: {emsg} (no request token issued).",
                    )
                raise FlattradeAPIException(code="500", message="Cannot get request token from Flattrade REST API server.")

            code = query_params["code"][0]
            api_secret = {
                "api_key": self._settings["api_key"],
                "request_code": code,
                "api_secret": hashlib.sha256((self._settings["api_key"] + code + self._settings['api_secret']).encode('utf-8')).hexdigest()
            }

            response = requests.post("https://authapi.flattrade.in/trade/apitoken", json=api_secret, headers=headers)
            if response.status_code != 200:
                raise FlattradeAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())

            token_data = response.json()
            token = token_data.get("token", "")

            last_login = {
                "broker_name": "flattrade",
                "access_token": token, 
                "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self._mongo_db["last_login"].replace_one({"broker_name": "flattrade"}, last_login, upsert=True)
            self._cache.hset("last_login", "flattrade", json_lib.dumps(last_login))
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
        if data is None:
            data = {
                "uid": self._settings["username"]
            }
            # Escaped as a JSON \u0026 rather than left literal: Noren splits this body on the
            # ampersand before it parses the JSON, so a trading symbol containing one - ARE&M,
            # M&M, L&T - ends the jData field early and comes back as "jData is not valid json
            # object". Percent-encoding the field instead is refused: Noren does not decode it.
            data = json_lib.dumps(data).replace("&", "\\u0026")
            data = "jData=" + data
            data += f"&jKey={self._last_login['access_token']}"
        elif isinstance(data, dict):
            data["uid"] = self._settings["username"]
            # Escaped as a JSON \u0026 rather than left literal: Noren splits this body on the
            # ampersand before it parses the JSON, so a trading symbol containing one - ARE&M,
            # M&M, L&T - ends the jData field early and comes back as "jData is not valid json
            # object". Percent-encoding the field instead is refused: Noren does not decode it.
            data = json_lib.dumps(data).replace("&", "\\u0026")
            data = "jData=" + data
            data += f"&jKey={self._last_login['access_token']}"        

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
                content["data"] = response.json()
            elif "text" in response.headers["Content-Type"]:
                try:
                    json_content = json_lib.loads(response.content.decode("utf-8").strip())
                    content["data"] = json_content
                except json_lib.JSONDecodeError:
                    content["data"] = response.content.decode("utf-8").strip()
            else:
                content["data"] = response.content.decode("utf-8").strip()
            return content
        else:
            if "json" in response.headers["Content-Type"]:
                json_content = response.json()
                if "stat" in json_content and "emsg" in json_content:
                    raise FlattradeAPIException(code=json_content["stat"], message=json_content["emsg"])
                else:
                    raise FlattradeAPIException(code=response.status_code, message=json_content)
            elif "text" in response.headers["Content-Type"]:
                try:
                    json_content = json_lib.loads(response.content.decode("utf-8").strip())
                    if "stat" in json_content and "emsg" in json_content:
                        raise FlattradeAPIException(code=json_content["stat"], message=json_content["emsg"])
                    else:
                        raise FlattradeAPIException(code=response.status_code, message=json_content)
                except json_lib.JSONDecodeError:
                    raise FlattradeAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())
            else:
                raise FlattradeAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())
