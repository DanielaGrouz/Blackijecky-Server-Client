import unittest
import struct
import main  # Imports your main.py file


class TestBlackjackProtocol(unittest.TestCase):

    def setUp(self):
        self.server = main.BlackjackServer()

    def test_magic_cookie_and_constants(self):
        """Verify protocol constants match the requirements."""
        self.assertEqual(main.MAGIC_COOKIE, 0xabcddcba, "Magic Cookie must be 0xabcddcba [cite: 87]")
        self.assertEqual(main.OFFER_TYPE, 0x2, "Offer Type must be 0x2 [cite: 88]")
        self.assertEqual(main.REQUEST_TYPE, 0x3, "Request Type must be 0x3 [cite: 93]")
        self.assertEqual(main.PAYLOAD_TYPE, 0x4, "Payload Type must be 0x4 [cite: 99]")

    def test_packet_structure_offer(self):
        """Verify the Offer packet has the correct size and format."""
        # Format: !IbH32s -> 4 + 1 + 2 + 32 = 39 bytes
        expected_size = struct.calcsize('!IbH32s')
        self.assertEqual(expected_size, 39, "Offer header size must be exactly 39 bytes [cite: 85-90]")

    def test_packet_structure_request(self):
        """Verify the Request packet has the correct size and format."""
        # Format: !IbB32s -> 4 + 1 + 1 + 32 = 38 bytes
        expected_size = struct.calcsize('!IbB32s')
        self.assertEqual(expected_size, 38, "Request header size must be exactly 38 bytes [cite: 91-95]")

    def test_game_logic_card_values(self):
        """Verify card value mapping (2-10, Face=10, Ace=11)."""
        # Numeric cards
        hand_numeric = [(5, 0), (9, 1)]  # 5 + 9
        self.assertEqual(self.server.calculate_value(hand_numeric), 14)

        # Face cards (J, Q, K = 10)
        hand_faces = [(11, 0), (13, 2)]  # Jack + King = 10 + 10
        self.assertEqual(self.server.calculate_value(hand_faces), 20)

    def test_game_logic_soft_ace(self):
        """Verify 'Soft Ace' logic - Ace becomes 1 if total > 21."""
        # Standard case: Ace + 5 = 16
        hand_soft = [(1, 0), (5, 1)]
        self.assertEqual(self.server.calculate_value(hand_soft), 16)

        # Bust adjustment case: Ace + 5 + 10 = 26 -> Becomes 16
        hand_bust_adjusted = [(1, 0), (5, 1), (10, 2)]
        self.assertEqual(self.server.calculate_value(hand_bust_adjusted), 16)

        # Edge case: Two Aces (11+1 = 12)
        hand_two_aces = [(1, 0), (1, 1)]
        self.assertEqual(self.server.calculate_value(hand_two_aces), 12)


if __name__ == '__main__':
    unittest.main()