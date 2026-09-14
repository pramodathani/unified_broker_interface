import pyotp
import requests
import json as json_lib
from datetime import datetime

from stock_brokers.api.base import BrokerAPI, BrokerAPIException

class DhanAPIException(BrokerAPIException):
    """Raised for Dhan broker API errors."""

class DhanAPI(BrokerAPI):
    """
    DhanAPI class
    """

    def __init__(self):
        """
        DhanAPI class
        """        
        super().__init__(broker_name="dhan")

        try:
            self.get(url="https://api.dhan.co/v2/profile")
        except Exception as exc:
            params = {
                "dhanClientId": self._settings['client_id'],
                "pin": self._settings['pin'],
                "totp": pyotp.TOTP(self._settings['totp_secret']).now()
            }
            
            data = self.post(url="https://auth.dhan.co/app/generateAccessToken", params=params, headers={'Content-Type': 'application/json'})
            if "data" not in data:
                raise DhanAPIException(code="500", message="Cannot get access token from Dhan REST API server.")
            data = data["data"]

            if "accessToken" not in data:
                raise DhanAPIException(code="500", message="Cannot get access token from Dhan REST API server.")

            last_login = {
                "broker_name": "dhan",
                "access_token": data["accessToken"], 
                "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self._mongo_db["last_login"].replace_one({"broker_name": "dhan"}, last_login, upsert=True)
            self._cache.hset("last_login", "dhan", json_lib.dumps(last_login))
            self._last_login = last_login
 
    def _request(self, method, url, params=None, data=None, headers=None, cookies=None, files=None, auth=None, timeout=None, allow_redirects=None, proxies=None, hooks=None, stream=None, verify=None, cert=None, json=None, verbose=False):
        """
        Private generic REST API request to Broker API server.
        This is specialized into GET, POST, PUT, PATCH and DELETE by public methods.

        - `method`: HTTP method to use for the request.
        - `url`: URL of the API endpoint excluding the base url.   
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
                'access-token': self._last_login['access_token']
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
                content["data"] = response.json()
            else:
                content["data"] = response.content.decode("utf-8").strip()
            return content
        else:
            if "json" in response.headers["Content-Type"]:
                json_content = response.json()
                if "errorType" in json_content and "errorMessage" in json_content:
                    raise DhanAPIException(code=json_content["errorType"], message=json_content["errorMessage"])
            raise DhanAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())
