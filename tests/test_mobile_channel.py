"""Tests for source/services/integrations/mobile_channel.py canonical sender handling."""

from source.services.integrations.mobile_channel import canonical_sender_id


class TestMobileChannelServiceCanonicalization:
    def test_whatsapp_sender_id_strips_device_suffix(self):
        canonical = canonical_sender_id("whatsapp", "15551234567:12@s.whatsapp.net")

        assert canonical == "15551234567@s.whatsapp.net"

    def test_non_whatsapp_sender_id_unchanged(self):
        canonical = canonical_sender_id("telegram", "123456789")

        assert canonical == "123456789"
