import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import bot as bot_module
from bot import compose


class ComposeContractTests(unittest.TestCase):
    def test_compose_returns_required_shape_for_merchant_trigger(self):
        category = {
            "slug": "dentists",
            "voice": {"tone": "peer_clinical", "taboos": ["guaranteed"]},
            "offer_catalog": [{"title": "Dental Cleaning @ ₹299"}],
        }
        merchant = {
            "merchant_id": "m_001",
            "identity": {
                "name": "Dr. Meera's Dental Clinic",
                "owner_first_name": "Meera",
                "languages": ["en", "hi"],
            },
            "offers": [{"title": "Dental Cleaning @ ₹299", "status": "active"}],
        }
        trigger = {
            "id": "trg_1",
            "scope": "merchant",
            "kind": "research_digest",
            "suppression_key": "research:test",
            "payload": {
                "top_item": {
                    "title": "3-month fluoride recall cuts caries recurrence",
                    "source": "JIDA Oct 2026",
                    "trial_n": 2100,
                }
            },
        }

        result = compose(category, merchant, trigger, None)

        self.assertEqual(
            {"body", "cta", "send_as", "suppression_key", "rationale"},
            set(result.keys()),
        )
        self.assertEqual(result["send_as"], "vera")
        self.assertEqual(result["suppression_key"], "research:test")
        self.assertNotIn("http", result["body"].lower())
        self.assertTrue(len(result["body"]) > 0)

    def test_compose_customer_facing_uses_merchant_on_behalf(self):
        category = {"slug": "dentists", "voice": {"tone": "peer_clinical"}}
        merchant = {
            "merchant_id": "m_001",
            "identity": {"name": "Dr. Meera's Dental Clinic", "owner_first_name": "Meera"},
            "offers": [{"title": "Dental Cleaning @ ₹299", "status": "active"}],
        }
        trigger = {
            "id": "trg_2",
            "scope": "customer",
            "kind": "recall_due",
            "suppression_key": "recall:test",
            "payload": {},
        }
        customer = {"identity": {"name": "Priya"}}

        result = compose(category, merchant, trigger, customer)

        self.assertEqual(result["send_as"], "merchant_on_behalf")
        self.assertIn("Priya", result["body"])


class EndpointContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(bot_module.app)
        bot_module.contexts.clear()
        bot_module.conversations.clear()
        bot_module.suppressed_keys.clear()

    def test_metadata_endpoint_matches_documented_contract(self):
        response = self.client.get("/v1/metadata")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "team_name": "Team Nucleya",
            "team_members": ["Aman", "Shruti"],
            "model": "claude fable 5",
            "approach": "single-prompt composer with retrieval over digest items + dispatch by trigger.kind",
            "contact_email": "team@example.com",
            "version": "1.2.0",
            "submitted_at": "2026-04-26T08:00:00Z",
        })

    def test_context_repeated_version_returns_conflict(self):
        payload = {
            "scope": "merchant",
            "context_id": "m_001_drmeera",
            "version": 1,
            "payload": {"merchant_id": "m_001_drmeera"},
            "delivered_at": "2026-04-26T09:45:00Z",
        }

        first_response = self.client.post("/v1/context", json=payload)
        second_response = self.client.post("/v1/context", json=payload)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.json()["accepted"], True)
        self.assertEqual(second_response.status_code, 409)
        self.assertEqual(second_response.json(), {
            "accepted": False,
            "reason": "stale_version",
            "current_version": 1,
        })

    def test_reply_without_gemini_client_uses_deterministic_fallback(self):
        with patch.dict(bot_module.os.environ, {"GEMINI_API_KEY": ""}, clear=False):
            response = self.client.post(
                "/v1/reply",
                json={
                    "conversation_id": "conv_1",
                    "merchant_id": "m_001",
                    "customer_id": None,
                    "from_role": "merchant",
                    "message": "Yes, please draft the next step.",
                    "received_at": "2026-04-26T10:45:00Z",
                    "turn_number": 2,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["action"], "send")
        self.assertIn("next step", payload["body"].lower())


if __name__ == "__main__":
    unittest.main()
