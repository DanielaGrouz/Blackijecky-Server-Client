import socket
import struct
import threading
import time
import random
import sys

# --- PROTOCOL CONSTANTS ---
MAGIC_COOKIE = 0xabcddcba
OFFER_TYPE = 0x2
REQUEST_TYPE = 0x3
PAYLOAD_TYPE = 0x4
UDP_PORT = 13122  # Hardcoded UDP port
BUFFER_SIZE = 1024

class BlackjackClient:
    """
    Client class that listens for server offers and engages in Blackjack games.
    """

    def __init__(self, team_name="Joker"):
        # ensure team name is exactly 32 bytes
        self.team_name = team_name.ljust(32)[:32].encode()

    def start(self):
        """Runs the client connection loop indefinitely."""
        while True:
            print("Client started, listening for offer requests...")
            udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, 'SO_REUSEPORT'):
                udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

            udp_sock.bind(('', UDP_PORT))

            try:
                offer_data, addr = udp_sock.recvfrom(BUFFER_SIZE)
                magic, m_type, tcp_port, s_name = struct.unpack('!IbH32s', offer_data[:39])

                if magic == MAGIC_COOKIE and m_type == OFFER_TYPE:
                    print(f"Received offer from {addr[0]} ({s_name.decode().strip()})")
                    udp_sock.close()
                    self.play_game(addr[0], tcp_port)
            except Exception as e:
                print(f"Client error: {e}")
                udp_sock.close()
    def play_game(self, server_ip, server_port):
        """Handles the TCP game logic and player input."""
        try:
            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_sock.connect((server_ip, server_port))

            # request user for game settings
            rounds_input = ""
            while not rounds_input.isdigit():
                rounds_input = input("How many rounds would you like to play? ").strip()
            rounds = int(rounds_input)

            # send initial Request packet
            request = struct.pack('!IbB32s', MAGIC_COOKIE, 0x3, rounds, self.team_name)
            tcp_sock.send(request)

            wins = 0
            for r in range(rounds):
                print(f"\n--- Round {r + 1} ---")
                current_sum = 0

                while True:
                    # listen for Payload updates (cards or results)
                    data = tcp_sock.recv(BUFFER_SIZE)
                    if not data: break

                    # Unpack: Magic (4), Type (1), Result (1), Rank (2), Suit (1)
                    _, _, result, rank, _, suit = struct.unpack('!IbB2bB', data[:9])

                    if rank > 0:  # if a card was received
                        value = 11 if rank == 1 else (10 if rank >= 10 else rank)
                        current_sum += value
                        suit_name = ["Heart", "Diamond", "Club", "Spade"][suit]
                        print(f"Drawn: {rank} of {suit_name}. Current hand value: {current_sum}")

                    if result != 0x0:  # Round is over
                        if result == 0x3:
                            wins += 1
                            print("Result: WIN! 🥳")
                        elif result == 0x2:
                            print("Result: LOSS 💀")
                        else:
                            print("Result: TIE 🤝")
                        break

                    # if still active, ask for user decision
                    if current_sum < 21:
                        action = ""
                        while action.lower() not in ['h', 's']:
                            action = input("(H)it or (S)tand? ").lower().strip()
                        if action.lower() == 'h':
                            decision_str = "Hittt"
                        else:
                            decision_str = "Stand"
                        # send decision to server
                        payload = struct.pack('!IbB5s', MAGIC_COOKIE, 0x4, 0, decision_str.ljust(5).encode())
                        tcp_sock.send(payload)
                        if action.lower != 'h': break  # wait for dealer to finish

            # print session statistics
            win_rate = (wins / rounds * 100) if rounds > 0 else 0
            print(f"\nFinished playing {rounds} rounds, win rate: {win_rate:.1f}%")
            tcp_sock.close()

        except Exception as e:
            print(f"Game error: {e}")


if __name__ == "__main__":
    client = BlackjackClient()
    client.start()