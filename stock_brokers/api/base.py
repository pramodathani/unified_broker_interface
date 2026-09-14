import json
from datetime import datetime
from utilities.configurations import *
from utilities.configurations import get_cache, get_mongo_db, get_logger

class BrokerAPIException(Exception):
    """
    BrokerAPIException represents an exception condition related to Broker API calls
    """

    def __init__(self, code=None, message=None):
        """
        BrokerAPIException represents an exception condition related to Broker  API calls
        
        -`code`: (string) error code
        -`message`: (string) error message
        """
        super(BrokerAPIException, self).__init__(code, message)
        self.code = code
        self.message = message

class BrokerAPI:
    """
    Base class for broker REST API implementations.
    """

    def __init__(self, broker_name):
        """
        Initializes the BrokerAPI instance.

        Args:
            broker_name (str): The name of the broker.
        """
        self._broker_name = broker_name
        self._cache = get_cache()
        self._mongo_db = get_mongo_db()
        self._logger = get_logger(broker_name)

        self._settings = self._mongo_db['settings'].find_one({'broker_name': broker_name}, {'_id': 0})
        self._last_login = self._mongo_db['last_login'].find_one({'broker_name': broker_name}, {'_id': 0})
        self._cache.hset('settings', broker_name, json.dumps(self._settings))
        # The login is deliberately not copied into Redis here. Only a login writes the Redis
        # `last_login` hash; see `_current_login` for why a constructor writing it would be a race.

    def _current_login(self):
        """
        The login in force right now, read on every request rather than once at construction.

        Any process that logs a broker in writes the new login to MongoDB and then to the Redis
        `last_login` hash. Reading that hash here, on every request, means a token another process
        has just obtained is used by this object's very next request, rather than a token loaded at
        construction being sent long after it has been replaced.

        Redis is the one place a token is read from, and a login the only thing that writes it.
        Constructors do not copy MongoDB into it, because that would race a login: a process that
        read MongoDB just before another logged in, and wrote Redis just after, would put the old
        token back for everyone.

        The newer of this object's login and Redis's is used, by their `last_login` time. The
        shared login normally wins. This object's own wins only when it is genuinely newer - a
        login this object has just made, or one whose write to Redis failed while its write to
        MongoDB, which this object was built from, succeeded. When either time cannot be read,
        Redis is trusted.

        When Redis holds nothing for the broker, the login is read from MongoDB and written into
        Redis only if that field is still empty, so it can fill the cache but never overwrite a
        login that lands in between. When neither store can be read, the object keeps what it has.

        Returns:
            dict | None: The `last_login` document now in force, also left in `self._last_login`.
        """
        try:
            raw = self._cache.hget('last_login', self._broker_name)
            shared = json.loads(raw) if raw else None
        except Exception:
            shared = None

        if not shared:
            try:
                shared = self._mongo_db['last_login'].find_one({'broker_name': self._broker_name}, {'_id': 0})
            except Exception:
                shared = None
            if shared:
                try:
                    self._cache.hsetnx('last_login', self._broker_name, json.dumps(shared))
                except Exception:
                    pass

        if shared:
            own_moment = self._login_moment(self._last_login)
            shared_moment = self._login_moment(shared)
            if own_moment is None or shared_moment is None or shared_moment >= own_moment:
                self._last_login = shared
        return self._last_login

    @staticmethod
    def _login_moment(document):
        """
        When a login document was made, or None when that cannot be read.

        Brokers stamp `last_login` with local time, some with microseconds and some without.

        Args:
            document (dict | None): A `last_login` document.

        Returns:
            datetime | None: The moment of the login.
        """
        stamp = (document or {}).get('last_login')
        for form in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(str(stamp), form)
            except (TypeError, ValueError):
                continue
        return None

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
        pass

    def get(self, url, params=None, data=None, headers=None, cookies=None, files=None, auth=None, timeout=None, allow_redirects=None, proxies=None, hooks=None, stream=None, verify=None, cert=None, json=None, verbose=False):
        """
        HTTP GET  API call to Broker's API server.
        This queries the Broker's API server for some information. Most responses are JSON encoded. Only a few are CSV encoded.

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
        data = self._request(method="GET", url=url, params=params, data=data, headers=headers, cookies=cookies, files=files, auth=auth, timeout=timeout, allow_redirects=allow_redirects, proxies=proxies, hooks=hooks, stream=stream, verify=verify, cert=cert, json=json)
        return data

    def post(self, url, params=None, data=None, headers=None, cookies=None, files=None, auth=None, timeout=None, allow_redirects=None, proxies=None, hooks=None, stream=None, verify=None, cert=None, json=None, verbose=False):
        """
        HTTP POST  API call to Broker's API server.
        This carries out some action using Broker's API server such as placing an order. Responses are JSON encoded.

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
        data = self._request(method="POST", url=url, params=params, data=data, headers=headers, cookies=cookies, files=files, auth=auth, timeout=timeout, allow_redirects=allow_redirects, proxies=proxies, hooks=hooks, stream=stream, verify=verify, cert=cert, json=json)
        return data

    def put(self, url, params=None, data=None, headers=None, cookies=None, files=None, auth=None, timeout=None, allow_redirects=None, proxies=None, hooks=None, stream=None, verify=None, cert=None, json=None, verbose=False):
        """
        HTTP PUT  API call to Broker's API server.
        This modifies something using Broker's API server such as modifying an order. Responses are JSON encoded.

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
        data = self._request(method="PUT", url=url, params=params, data=data, headers=headers, cookies=cookies, files=files, auth=auth, timeout=timeout, allow_redirects=allow_redirects, proxies=proxies, hooks=hooks, stream=stream, verify=verify, cert=cert, json=json)
        return data
    
    def patch(self, url, params=None, data=None, headers=None, cookies=None, files=None, auth=None, timeout=None, allow_redirects=None, proxies=None, hooks=None, stream=None, verify=None, cert=None, json=None, verbose=False):
        """
        HTTP PATCH  API call to Broker's API server.
        This updates something using Broker's API server such as modifying an order. Responses are JSON encoded.

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
        data = self._request(method="PATCH", url=url, params=params, data=data, headers=headers, cookies=cookies, files=files, auth=auth, timeout=timeout, allow_redirects=allow_redirects, proxies=proxies, hooks=hooks, stream=stream, verify=verify, cert=cert, json=json)
        return data

    def delete(self, url, params=None, data=None, headers=None, cookies=None, files=None, auth=None, timeout=None, allow_redirects=None, proxies=None, hooks=None, stream=None, verify=None, cert=None, json=None, verbose=False):
        """
        HTTP DELETE  API call to Broker's API server.
        This deletes something using Broker's API server such as cancelling an order or invalidating an access token. Responses are JSON encoded.

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
        data = self._request(method="DELETE", url=url, params=params, data=data, headers=headers, cookies=cookies, files=files, auth=auth, timeout=timeout, allow_redirects=allow_redirects, proxies=proxies, hooks=hooks, stream=stream, verify=verify, cert=cert, json=json)
        return data
