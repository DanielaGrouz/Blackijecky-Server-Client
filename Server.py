import socket
import struct
import threading
import time
import random

# Protocol Constants
MAGIC_COOKIE = 0xabcddcba
OFFER_TYPE = 0x2
REQUEST_TYPE = 0x3
PAYLOAD_TYPE = 0x4
UDP_PORT = 13122  # hardcoded as per instructions
BUFFER_SIZE = 1024


class BlackjackServer:
    """
    Main Server class to handle UDP broadcasting and TCP game sessions.
    The server is designed to run forever and handle multiple clients using threads.
    """

    def __init__(self, team_name="CyberSharks"):
        # format team name to exactly 32 bytes
        self.team_name = team_name.ljust(32)[:32].encode()

        # setup TCP socket to listen for incoming connections
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket.bind(('', 0))  # bind to any available port
        self.tcp_port = self.tcp_socket.getsockname()[1]
        self.tcp_socket.listen(10)

    def broadcast_offers(self):
        """
        Continuously broadcasts UDP offer messages every second.
        Packet Format: Magic Cookie (4), Type (1), TCP Port (2), Server Name (32).
        """
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # pack the offer message using network byte order
        offer_packet = struct.pack('!IbH32s', MAGIC_COOKIE, OFFER_TYPE, self.tcp_port, self.team_name)

        print(f"Server started, listening on IP address {socket.gethostbyname(socket.gethostname())}")
        while True:
            try:
                udp_socket.sendto(offer_packet, ('<broadcast>', UDP_PORT))
                time.sleep(1)  # send once every second
            except Exception as e:
                print(f"Broadcast error: {e}")

    def get_card(self):
        """Generates a random card rank (1-13) and suit (0-3)."""
        return random.randint(1, 13), random.randint(0, 3)

    def calculate_value(self, hand):
        """
        calculates hand value based on Simplified Blackjack rules.
        numbers 2-10 are face value, J/Q/K are 10, Ace is 11.
        """
        total = 0
        for rank, _ in hand:
            if rank >= 10:
                total += 10  # Face cards
            elif rank == 1:
                total += 11  # Ace
            else:
                total += rank  # Numeric cards
        return total

    def handle_client(self, conn, addr):
        """
        Handles the lifecycle of a single client TCP connection.
        Manages the game rounds and the Blackjack logic.
        """
        try:
            conn.settimeout(15)  # prevent hanging on idle clients
            data = conn.recv(BUFFER_SIZE)
            if not data or len(data) < 38: return

            # Unpack the Request message from client
            magic, m_type, num_rounds, client_name = struct.unpack('!IbB32s', data[:38])
            if magic != MAGIC_COOKIE or m_type != REQUEST_TYPE:
                return

            print(f"New session: {client_name.decode().strip()} wants {num_rounds} rounds.")

            for _ in range(num_rounds):
                # Round Setup: Initial deal
                player_hand = [self.get_card(), self.get_card()]
                dealer_hand = [self.get_card(), self.get_card()]

                # Send initial deal to client (2 player cards, 1 dealer card)
                for card in player_hand + [dealer_hand[0]]:
                    # Result 0x0 indicates the round is still active
                    packet = struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, card[0], 0, card[1])
                    conn.send(packet)

                # Player's Turn: Loop until Stand or Bust
                while self.calculate_value(player_hand) < 21:
                    decision_data = conn.recv(BUFFER_SIZE)
                    if not decision_data: break

                    # Unpack the player decision ("Hittt" or "Stand")
                    _, _, _, decision_raw = struct.unpack('!IbB5s', decision_data[:10])
                    decision = decision_raw.decode().strip()

                    if "Hittt" in decision:
                        new_card = self.get_card()
                        player_hand.append(new_card)
                        # Inform client of the new card
                        conn.send(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, new_card[0], 0, new_card[1]))
                    else:
                        break  # Player chooses to Stand

                # Dealer's Turn: Only if player hasn't busted
                p_sum = self.calculate_value(player_hand)
                d_sum = self.calculate_value(dealer_hand)

                if p_sum <= 21:
                    # Dealer reveals hidden card and hits until sum >= 17
                    while d_sum < 17:
                        new_card = self.get_card()
                        dealer_hand.append(new_card)
                        d_sum = self.calculate_value(dealer_hand)
                        # Reveal each dealer draw to client
                        conn.send(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, new_card[0], 0, new_card[1]))

                # Winner Determination
                res = 0x1  # Default to Tie
                if p_sum > 21:
                    res = 0x2  # Player Bust (Loss)
                elif d_sum > 21:
                    res = 0x3  # Dealer Bust (Win)
                elif p_sum > d_sum:
                    res = 0x3  # Win
                elif d_sum > p_sum:
                    res = 0x2  # Loss

                # Final packet for the round with the final result
                conn.send(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, res, 0, 0, 0))

        except Exception as e:
            print(f"TCP session error with {addr}: {e}")
        finally:
            conn.close()  # Close session after all rounds or on error

    def run(self):
        """Starts the server broadcast thread and the main TCP acceptance loop."""
        # Start background UDP broadcast
        threading.Thread(target=self.broadcast_offers, daemon=True).start()
        while True:
            # accept() blocks until a client connects, preventing busy-waiting
            conn, addr = self.tcp_socket.accept()
            threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    server = BlackjackServer()
    server.run()