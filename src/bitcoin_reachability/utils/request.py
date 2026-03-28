import requests
import json
from enum import Enum


class Method(Enum):
    GET = 1
    POST = 2
    PUT = 3
    DELETE = 4


class Request(object):
    def get(self, url):
        return self.perform(Method.GET, url)

    def post(self, url, json_data=None):
        return self.perform(Method.POST, url, json_data)

    def put(self, url, json_data=None):
        return self.perform(Method.PUT, url, json_data)

    def delete(self, url):
        return self.perform(Method.DELETE, url)

    def perform(self, method, url, json_data=None):
        data = json.dumps(json_data) if json_data else None

        if method == Method.GET:
            r = requests.get(url)
        elif method == Method.POST:
            r = requests.post(url, data=data)
        elif method == Method.PUT:
            r = requests.put(url, data=data)
        elif method == Method.DELETE:
            r = requests.delete(url)

        if r.status_code not in (200, 201):
            raise ConnectionError(
                f'\nCode: {r.status_code}\nResult: {r.text}\nData: {data}'
            )

        return r.text
