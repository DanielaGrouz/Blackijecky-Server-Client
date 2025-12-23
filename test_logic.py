import unittest
from main import BlackjackServer

class TestBlackjackLogic(unittest.TestCase):
    def setUp(self):
        # Initialize server (binds to a random port, which is fine for testing)
        self.server = BlackjackServer()

    def test_numeric_cards(self):
        """Check simple sum of number cards."""
        hand = [(2, 0), (5, 1)] # 2 of Hearts, 5 of Diamonds
        self.assertEqual(self.server.calculate_value(hand), 7)

    def test_face_cards(self):
        """Check that J, Q, K count as 10."""
        hand = [(11, 0), (12, 1)] # Jack, Queen
        self.assertEqual(self.server.calculate_value(hand), 20)

    def test_ace_soft(self):
        """Check Ace counts as 11 when total < 21."""
        hand = [(1, 0), (5, 1)] # Ace, 5
        self.assertEqual(self.server.calculate_value(hand), 16)

    def test_ace_hard(self):
        """Check Ace reduces to 1 when total would otherwise bust."""
        # King (10), 5 (5), Ace (11 -> 1) = 16
        hand = [(13, 0), (5, 1), (1, 2)]
        self.assertEqual(self.server.calculate_value(hand), 16)

    def test_multiple_aces(self):
        """Check two Aces: One stays 11, one becomes 1."""
        # Ace (11), Ace (1) = 12
        hand = [(1, 0), (1, 1)]
        self.assertEqual(self.server.calculate_value(hand), 12)

    def test_blackjack(self):
        """Check natural Blackjack (21)."""
        hand = [(1, 0), (13, 1)] # Ace, King
        self.assertEqual(self.server.calculate_value(hand), 21)

    def test_bust(self):
        """Check calculation for a busted hand."""
        hand = [(10, 0), (10, 1), (5, 2)] # 10 + 10 + 5 = 25
        self.assertEqual(self.server.calculate_value(hand), 25)

if __name__ == '__main__':
    print("Running Game Logic Tests...")
    unittest.main()

import subprocess
import sys
import time


def run_stress_test():
    print("--- TESTING CONCURRENCY & SO_REUSEPORT ---")

    # 1. Start Server
    print("Launching Server...")
    server = subprocess.Popen([sys.executable, 'main.py', 'server'],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(2)  # Wait for server startup

    clients = []
    # 2. Launch 3 Clients simultaneously
    # If SO_REUSEPORT is missing/wrong, clients 2 and 3 will crash with "Address already in use"
    for i in range(3):
        print(f"Launching Client {i + 1}...")
        # Automate input: "1 round", then "Stand" (s)
        p = subprocess.Popen([sys.executable, 'main.py', 'client'],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        clients.append(p)

    # 3. Feed input
    for p in clients:
        try:
            out, err = p.communicate(input="1\ns\n", timeout=10)
            if "Address already in use" in err:
                print(f"❌ FAIL: Client {p.pid} failed to bind port (SO_REUSEPORT issue).")
            elif "Game Over" in out:
                print(f"✅ PASS: Client {p.pid} played successfully.")
            else:
                print(f"⚠️ UNKNOWN: Client {p.pid} output:\n{out}\nError:\n{err}")
        except:
            p.kill()
            print(f"❌ Client {p.pid} timed out.")

    # Cleanup
    server.terminate()
    print("Test Complete.")


if __name__ == "__main__":
    run_stress_test()

import unittest
from main import BlackjackServer


class TestCardMapping(unittest.TestCase):
    def setUp(self):
        self.server = BlackjackServer()

    def test_numeric_mapping(self):
        # Test 2 through 9
        for i in range(2, 10):
            hand = [(i, 0)]  # Suit doesn't matter for value
            self.assertEqual(self.server.calculate_value(hand), i, f"Failed on card {i}")

    def test_face_mapping(self):
        # 10, Jack(11), Queen(12), King(13) should all be 10
        for i in range(10, 14):
            hand = [(i, 0)]
            self.assertEqual(self.server.calculate_value(hand), 10, f"Failed on face card {i}")

    def test_ace_logic(self):
        # Soft Ace
        hand_soft = [(1, 0), (5, 0)]  # Ace + 5 = 16
        self.assertEqual(self.server.calculate_value(hand_soft), 16)

        # Hard Ace (Bust prevention)
        hand_hard = [(1, 0), (10, 0), (5, 0)]  # Ace + 10 + 5 = 16 (not 26)
        self.assertEqual(self.server.calculate_value(hand_hard), 16)

        # Blackjack
        hand_bj = [(1, 0), (13, 0)]  # Ace + King = 21
        self.assertEqual(self.server.calculate_value(hand_bj), 21)


if __name__ == '__main__':
    unittest.main()