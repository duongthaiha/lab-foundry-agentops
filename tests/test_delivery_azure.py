import unittest
from unittest.mock import Mock, patch

from azure.core import MatchConditions
from azure.core.exceptions import ResourceModifiedError

from agentops.contracts import LabError, canonical
from agentops.delivery_azure import BlobJournal, NoRedirect, ensure


class AzureBoundaryTests(unittest.TestCase):
    def test_credential_redirects_are_never_followed(self):
        with self.assertRaisesRegex(LabError, "Redirect refused"):
            NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://untrusted.invalid")

    def test_create_only_readback_and_drift(self):
        http = Mock()
        desired = {"name": "resource"}
        http.request.side_effect = [None, {}, {"name": "resource", "server_field": "ignored"}]
        ensure(http, "/resources/item", desired)
        self.assertEqual(http.request.call_args_list[1].kwargs["headers"], {"If-None-Match": "*"})
        http.reset_mock()
        http.request.side_effect = [{"name": "foreign"}]
        with self.assertRaisesRegex(LabError, "read-back drift"):
            ensure(http, "/resources/item", desired)
        self.assertEqual(http.request.call_count, 1)

    def test_known_service_normalization_is_excluded_only_from_readback(self):
        http = Mock()
        desired = {"properties": {"target": "https://unit.invalid", "isSharedToAll": True}}
        expected = {"properties": {"target": "https://unit.invalid"}}
        http.request.side_effect = [None, {}, {"properties": {"target": "https://unit.invalid", "isSharedToAll": False}}]
        ensure(http, "/resources/item", desired, expected)
        self.assertEqual(http.request.call_args_list[1].args[2], desired)
        http.reset_mock()
        http.request.side_effect = [{"properties": {"target": "https://other.invalid", "isSharedToAll": True}}]
        with self.assertRaisesRegex(LabError, "read-back drift"):
            ensure(http, "/resources/item", desired, expected)

    def test_journal_requires_lease_and_expected_etag(self):
        with patch("azure.storage.blob.BlobClient") as client:
            blob = client.return_value
            blob.download_blob.return_value.readall.return_value = canonical({"schema_version": 1})
            blob.download_blob.return_value.properties.etag = "old-etag"
            blob.upload_blob.return_value = {"etag": "new-etag"}
            journal = BlobJournal("https://example.blob.core.windows.net", Mock())
            with journal.locked() as state:
                journal.save(state)
                call = blob.upload_blob.call_args.kwargs
                self.assertEqual(call["etag"], "old-etag")
                self.assertEqual(call["match_condition"], MatchConditions.IfNotModified)
                self.assertIs(call["lease"], journal.lease)
            blob.acquire_lease.return_value.release.assert_called_once()
            blob.close.assert_called_once()

    def test_lost_lease_blocks_state_write_and_closes_client(self):
        with patch("azure.storage.blob.BlobClient") as client:
            blob = client.return_value
            blob.download_blob.return_value.readall.return_value = canonical({"schema_version": 1})
            blob.acquire_lease.return_value.renew.side_effect = ResourceModifiedError("lost lease")
            journal = BlobJournal("https://example.blob.core.windows.net", Mock())
            with self.assertRaisesRegex(LabError, "lease lost"):
                with journal.locked() as state:
                    journal.save(state)
            self.assertEqual(blob.upload_blob.call_count, 1)
            blob.close.assert_called_once()
        with patch("azure.storage.blob.BlobClient") as client:
            client.return_value.acquire_lease.side_effect = ResourceModifiedError("busy")
            with self.assertRaises(ResourceModifiedError):
                with BlobJournal("https://example.blob.core.windows.net", Mock()).locked():
                    self.fail("Must not enter without a lease")
            client.return_value.close.assert_called_once()
