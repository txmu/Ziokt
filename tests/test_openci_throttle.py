"""Bounded HTTP throttle recovery preserves the original authenticated request."""
from email.message import Message
import io
import json
from unittest.mock import Mock
from urllib.error import HTTPError
import unittest
from openci.client import Client
from openci.state import Error


class ThrottleTests(unittest.TestCase):
    def failure(self,retry='0',retryable=True):
        headers=Message();headers['Retry-After']=retry
        return HTTPError('http://127.0.0.1',429,'rate limit',headers,io.BytesIO(json.dumps({'error':{'code':'RATE_LIMIT','message':'rate limit','retryable':retryable}}).encode()))

    def test_throttle_retries_the_same_request_and_has_a_finite_budget(self):
        client=Client('http://127.0.0.1','scoped-token')
        client.opener=Mock();client.opener.open.side_effect=[self.failure(),io.BytesIO(b'{"accepted":true}')]
        self.assertEqual(client.request('POST','/v1/objects/begin',{'upload':'stable'}),{'accepted':True})
        self.assertIs(client.opener.open.call_args_list[0].args[0],client.opener.open.call_args_list[1].args[0])
        client.opener.open.side_effect=[self.failure(),self.failure(),self.failure()]
        with self.assertRaises(Error):client.request('POST','/v1/objects/begin',{'upload':'stable'})

    def test_invalid_or_excessive_retry_headers_are_not_waited_out(self):
        for retry in ('-1','999999','NaN','1.5',''):
            client=Client('http://127.0.0.1','scoped-token');client.opener=Mock();client.opener.open.side_effect=self.failure(retry)
            with self.subTest(retry=retry),self.assertRaises(Error):client.request('GET','/v1/status')
            self.assertEqual(client.opener.open.call_count,1)
