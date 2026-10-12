"""Regression coverage for the PawaPay v2 lookup envelope and callback outcome."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException
from app.services.pawapay_adapter import PawaPayProvider, PawaPayAPIError
from app.routers import payments


class PawaPayDepositStatusTests(unittest.TestCase):
    def setUp(self):
        self.deposit_id = str(uuid4())
        self.provider = PawaPayProvider()

    def envelope(self, status):
        return {"status": "FOUND", "data": {"depositId": self.deposit_id,
                "status": status, "amount": "1500", "currency": "UGX"}}

    def test_callback_uses_authoritative_nested_outcome(self):
        for status, expected in [("COMPLETED", "SUCCESSFUL"), ("FAILED", "FAILED")]:
            with self.subTest(status=status):
                request = AsyncMock()
                request.json.return_value = {"depositId": self.deposit_id, "status": "COMPLETED"}
                request.headers = {}
                handler = AsyncMock(return_value={"received": True})
                with patch.object(self.provider, "_request", return_value=self.envelope(status)), \
                     patch.object(payments.payment_providers, "get", return_value=self.provider), \
                     patch.object(payments, "provider_webhook", handler):
                    asyncio.run(payments.pawapay_deposit_callback.__wrapped__(request=request, db=object()))
                payload = handler.call_args.args[1]
                self.assertEqual(payload.status, expected)
                self.assertEqual(payload.amount_ugx, 1500)
                self.assertEqual(payload.provider_reference, self.deposit_id)

    def test_nonfinal_state_is_preserved(self):
        with patch.object(self.provider, "_request", return_value=self.envelope("SUBMITTED")):
            self.assertEqual(self.provider.get_deposit_status(self.deposit_id)["status"], "SUBMITTED")

    def test_invalid_lookup_does_not_confirm_payment(self):
        malformed = self.envelope("COMPLETED")
        malformed["data"]["depositId"] = str(uuid4())
        for response in [{"status": "NOT_FOUND"}, {"status": "FOUND"},
                         {"status": "FOUND", "data": []}, malformed]:
            with self.subTest(response=response), patch.object(self.provider, "_request", return_value=response):
                with self.assertRaises(PawaPayAPIError):
                    self.provider.get_deposit_status(self.deposit_id)

    def test_callback_keeps_amount_validation(self):
        response = self.envelope("COMPLETED")
        response["data"]["currency"] = "USD"
        request = AsyncMock()
        request.json.return_value = {"depositId": self.deposit_id, "status": "COMPLETED"}
        request.headers = {}
        with patch.object(self.provider, "_request", return_value=response), \
             patch.object(payments.payment_providers, "get", return_value=self.provider), \
             patch.object(payments, "provider_webhook", AsyncMock()) as handler:
            with self.assertRaises(HTTPException) as error:
                asyncio.run(payments.pawapay_deposit_callback.__wrapped__(request=request, db=object()))
            self.assertEqual(error.exception.status_code, 422)
            handler.assert_not_called()
