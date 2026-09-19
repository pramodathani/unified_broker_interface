import pyotp
import requests
import json as json_lib
from datetime import datetime

from stock_brokers.api.base import BrokerAPI, BrokerAPIException

class INDMoneyAPIException(BrokerAPIException):
    """Raised for INDMoney broker API errors."""

class INDMoneyAPI(BrokerAPI):
    """
    INDMoneyAPI class
    """

    quote_api_calls = []
    historical_api_calls = []
    order_api_calls = []
    other_api_calls = []

    def __init__(self):
        """
        INDMoneyAPI class
        """
        super().__init__(broker_name="indmoney")

        try:
            self.get(url="https://api.indstocks.com/user/profile")
        except Exception as e:
            response = requests.post(
                url="https://api.indstocks.com/generate/token", 
                headers={
                    "x-api-key": self._settings["client_id"],
                    "Content-Type": "application/json"
                }, 
                json={
                    "mpin": self._settings["mpin"],
                    "totp": pyotp.TOTP(self._settings["totp_secret"]).now()
                }
            )
            if response.status_code != 200:
                raise INDMoneyAPIException(code=response.status_code, message=f"Cannot generate access token from INDstocks API: {response.text}")

            access_token = response.json().get("token")
            if access_token is None:
                raise INDMoneyAPIException(code="500", message="No token in INDstocks generate/token response.")

            last_login = {
                "broker_name": "indmoney",
                "access_token": access_token,
                "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self._mongo_db["last_login"].replace_one({"broker_name": "indmoney"}, last_login, upsert=True)
            self._cache.hset("last_login", "indmoney", json_lib.dumps(last_login))
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
                'Authorization': self._last_login['access_token']
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
            # IND Money's error body carries `error_type` (live-confirmed: e.g.
            # {"status":"error","message":"...","error_type":"RequestValidationException"}),
            # NOT `error_code`. Some older paths may still use `error_code`, so both
            # are accepted as the exception code; the message comes from `message`.
            if "json" in response.headers["Content-Type"]:
                json_content = response.json()
                error_code = json_content.get("error_type") or json_content.get("error_code")
                if error_code is not None and "message" in json_content:
                    raise INDMoneyAPIException(code=error_code, message=json_content["message"])
                else:
                    raise INDMoneyAPIException(code=response.status_code, message=json_content)
            elif "text" in response.headers["Content-Type"]:
                try:
                    json_content = json_lib.loads(response.content.decode("utf-8").strip())
                    error_code = json_content.get("error_type") or json_content.get("error_code")
                    if error_code is not None and "message" in json_content:
                        raise INDMoneyAPIException(code=error_code, message=json_content["message"])
                    else:
                        raise INDMoneyAPIException(code=response.status_code, message=json_content)
                except json_lib.JSONDecodeError:
                    raise INDMoneyAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())
            else:
                raise INDMoneyAPIException(code=response.status_code, message=response.content.decode("utf-8").strip())
