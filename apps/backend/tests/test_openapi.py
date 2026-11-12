"""Swagger at /docs: the spec is generated from the routes and tells the truth."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app.main import create_app


class OpenApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with mock.patch.dict(os.environ, {"STARK_DOCS": "1"}):
            cls.client = TestClient(create_app())
        cls.spec = cls.client.get("/docs/openapi.json").json()

    def test_swagger_ui_is_served(self):
        response = self.client.get("/docs")
        self.assertEqual(response.status_code, 200)
        self.assertIn("swagger-ui", response.text)

    def test_every_contract_route_is_documented(self):
        documented = {f"{method.upper()} {path}"
                      for path, operations in self.spec["paths"].items()
                      for method in operations}
        for route in ("GET /v1/state", "POST /v1/bills", "PATCH /v1/bills/{bill_id}",
                      "POST /v1/payments", "GET /v1/plans", "PATCH /v1/limits",
                      "POST /v1/wallet/topup", "POST /v1/voice", "GET /v1/speak/stream",
                      "POST /v1/tg/webhook", "POST /v1/link/code"):
            self.assertIn(route, documented)
        # A test seam, not part of the product.
        self.assertNotIn("POST /v1/_stub/reset", documented)

    def test_no_route_claims_a_422(self):
        for path, operations in self.spec["paths"].items():
            for method, operation in operations.items():
                self.assertNotIn("422", operation["responses"], f"{method} {path}")
        self.assertNotIn("HTTPValidationError", self.spec["components"]["schemas"])

    def test_errors_are_documented_with_their_codes(self):
        payment = self.spec["paths"]["/v1/payments"]["post"]["responses"]
        self.assertIn("over_cap", payment["409"]["description"])
        self.assertIn("unauthorized", payment["401"]["description"])
        self.assertEqual(payment["409"]["content"]["application/json"]["schema"]["$ref"],
                         "#/components/schemas/ErrorDto")

    def test_swagger_does_not_keep_the_token(self):
        self.assertNotIn("persistAuthorization", self.client.get("/docs").text)

    def test_bearer_auth_is_offered(self):
        schemes = self.spec["components"]["securitySchemes"]
        self.assertEqual(schemes["HTTPBearer"]["scheme"], "bearer")


class DocsOffTest(unittest.TestCase):
    """Production: no docs, no spec, and `/` does not list the routes."""

    @classmethod
    def setUpClass(cls):
        with mock.patch.dict(os.environ, {"STARK_DOCS": "0"}):
            cls.app = create_app()
        cls.client = TestClient(cls.app)

    def test_docs_and_spec_are_not_served(self):
        for path in ("/docs", "/redoc", "/docs/openapi.json"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_the_index_names_the_service_only(self):
        body = self.client.get("/").json()
        self.assertEqual(body["service"], "stark-api")
        self.assertNotIn("routes", body)

    def test_the_spec_still_builds_in_process(self):
        self.assertIn("/v1/speak/ticket", self.app.openapi()["paths"])


if __name__ == "__main__":
    unittest.main()
