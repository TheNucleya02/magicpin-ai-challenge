import unittest

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


if __name__ == "__main__":
    unittest.main()
