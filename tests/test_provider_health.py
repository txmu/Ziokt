"""Fresh challenge proof is separate from application/peer readiness."""
import time
import unittest
from unittest.mock import patch

from ziokt.client import NativeClient
from ziokt.protocol import ProtocolError


class ProviderHealthTests(unittest.TestCase):
    def setUp(self):
        self.provider={"native_project":"corium","provider_id":"corium-test"}
        self.client=NativeClient("federation-test",self.provider)

    def reply(self,challenge):
        return {"schema":"ziokt.provider-health.v1","challenge":challenge,
                "native_project":"corium","provider_id":"corium-test",
                "federation_id":"federation-test","enabled":True,
                "observed_at_ms":time.time_ns()//1_000_000,
                "checks":{"pinned_process_rpc":"passed"}}

    def test_native_challenge_is_fresh_and_does_not_claim_peer_readiness(self):
        with patch("ziokt.client.exchange",side_effect=lambda provider,request,**kwargs:self.reply(request["params"]["challenge"])):
            result=self.client.health()
        self.assertEqual(result["checks"]["pinned_process_rpc"],"passed")
        self.assertNotIn("external_peer",result["checks"])

    def test_replayed_or_misbinding_health_reply_is_rejected(self):
        with patch("ziokt.client.exchange",return_value=self.reply("0"*32)):
            with self.assertRaises(ProtocolError) as error:self.client.health()
        self.assertEqual(error.exception.code,"INVALID_HEALTH_PROOF")

    def test_stale_health_reply_is_rejected(self):
        def stale(provider,request,**kwargs):
            result=self.reply(request["params"]["challenge"]);result["observed_at_ms"]-=6000
            return result
        with patch("ziokt.client.exchange",side_effect=stale):
            with self.assertRaises(ProtocolError) as error:self.client.health()
        self.assertEqual(error.exception.code,"INVALID_HEALTH_PROOF")


if __name__=="__main__":unittest.main()
