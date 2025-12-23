import socket
import struct
import threading
import time
import random
import sys
import traceback  # Added for server-side error logging

# --- PROTOCOL CONSTANTS ---
MAGIC_COOKIE = 0xabcddcba
OFFER_TYPE = 0x2
REQUEST_TYPE = 0x3
PAYLOAD_TYPE = 0x4
UDP_PORT = 13122
BUFFER_SIZE = 1024


def recv_all(sock, n):
    """Ensures exactly n bytes are read from the stream."""
    data = bytearray()
    while len(data) < n:
        try:
            packet = sock.recv(n - len(data))
            if not packet: return None
            data.extend(packet)
        except:
            return None
    return data


class BlackjackServer:
    def __init__(self, team_name="CyberSharks"):
        self.team_name = team_name.ljust(32)[:32].encode()
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_socket.bind(('', 0))
        self.tcp_port = self.tcp_socket.getsockname()[1]
        self.tcp_socket.listen(15)

    def broadcast_offers(self):
        """Sends UDP broadcast offers."""
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        packet = struct.pack('!IbH32s', MAGIC_COOKIE, OFFER_TYPE, self.tcp_port, self.team_name)
        print(f"Server started, listening on TCP port {self.tcp_port}")
        while True:
            try:
                udp_socket.sendto(packet, ('<broadcast>', UDP_PORT))
                time.sleep(1)
            except:
                pass

    def calculate_value(self, hand):
        """Calculates hand value."""
        total = 0
        for rank, _ in hand:
            total += 10 if rank >= 10 else (11 if rank == 1 else rank)
        return total

    def handle_client(self, conn, addr):
        """Manages the game session."""
        try:
            conn.settimeout(10)
            request_data = recv_all(conn, 38)
            if not request_data: return
            magic, m_type, rounds, c_name = struct.unpack('!IbB32s', request_data)
            if magic != MAGIC_COOKIE or m_type != REQUEST_TYPE: return

            print(f"New Game: {c_name.decode().strip()} ({rounds} rounds)")

            for _ in range(rounds):
                p_hand = [(random.randint(1, 13), random.randint(0, 3)), (random.randint(1, 13), random.randint(0, 3))]
                d_hand = [(random.randint(1, 13), random.randint(0, 3)), (random.randint(1, 13), random.randint(0, 3))]

                # Initial deal
                for card in p_hand + [d_hand[0]]:
                    conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, card[0], 0, card[1]))

                # Player Turn
                while self.calculate_value(p_hand) < 21:
                    # FIX: Read exactly 11 bytes to match client's struct.pack('!IbB5s')
                    decision_data = recv_all(conn, 11)
                    if not decision_data: break
                    _, _, _, d_raw = struct.unpack('!IbB5s', decision_data)
                    if b"Hittt" in d_raw:
                        new_c = (random.randint(1, 13), random.randint(0, 3))
                        p_hand.append(new_c)
                        conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, new_c[0], 0, new_c[1]))
                    else:
                        break

                # Dealer Turn
                p_sum, d_sum = self.calculate_value(p_hand), self.calculate_value(d_hand)
                if p_sum <= 21:
                    # Reveal dealer's hidden card
                    conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, d_hand[1][0], 0, d_hand[1][1]))

                    # Dealer hits until 17
                    while d_sum < 17:
                        new_c = (random.randint(1, 13), random.randint(0, 3))
                        d_hand.append(new_c)
                        d_sum = self.calculate_value(d_hand)
                        conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, new_c[0], 0, new_c[1]))

                    # Determine winner
                    if d_sum > 21:
                        res = 0x3  # Dealer Bust
                    elif p_sum == d_sum:
                        res = 0x1  # Tie
                    elif p_sum > d_sum:
                        res = 0x3  # Player Win
                    else:
                        res = 0x2  # Dealer Win
                else:
                    res = 0x2  # Player Bust (Loss)

                # Send result
                conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, res, 0, 0, 0))
        except Exception:
            traceback.print_exc()  # Print server errors instead of crashing silently
        finally:
            conn.close()

    def start(self):
        threading.Thread(target=self.broadcast_offers, daemon=True).start()
        while True:
            conn, addr = self.tcp_socket.accept()
            threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()


class BlackjackClient:
    def __init__(self, team_name="Joker"):
        self.team_name = team_name.ljust(32)[:32].encode()

    def start(self):
        while True:
            print("Client started, listening for offer requests...")
            udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, 'SO_REUSEPORT'): udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            try:
                udp_sock.bind(('', UDP_PORT))
                offer_data, addr = udp_sock.recvfrom(BUFFER_SIZE)
                magic, m_type, tcp_port, s_name = struct.unpack('!IbH32s', offer_data[:39])
                if magic == MAGIC_COOKIE and m_type == OFFER_TYPE:
                    print(f"Received offer from {addr[0]} ({s_name.decode().strip()})")
                    udp_sock.close()
                    self.play_game(addr[0], tcp_port)
            except:
                udp_sock.close()

    def play_game(self, ip, port):
        try:
            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_sock.connect((ip, port))
            rounds_input = input("How many rounds would you like to play? ").strip()
            rounds = int(rounds_input) if rounds_input.isdigit() else 1
            tcp_sock.sendall(struct.pack('!IbB32s', MAGIC_COOKIE, REQUEST_TYPE, rounds, self.team_name))

            wins = 0
            for r in range(rounds):
                print(f"\n{'=' * 25}\n   ROUND {r + 1} of {rounds}\n{'=' * 25}")
                p_sum, is_player_turn, cards_received = 0, True, 0

                while True:
                    data = recv_all(tcp_sock, 9)
                    if not data:
                        print("Error: Connection lost.");
                        return

                    _, _, result, rank, _, suit = struct.unpack('!IbB2bB', data)

                    if rank > 0:
                        cards_received += 1
                        val = 11 if rank == 1 else (10 if rank >= 10 else rank)
                        suit_sym = ["♥", "♦", "♣", "♠"][suit]

                        # Client-side Logic for display:
                        if cards_received <= 2:
                            p_sum += val
                            print(f"[YOU] Drawn: {rank}{suit_sym} | Hand: {p_sum}")
                            if p_sum >= 21: is_player_turn = False  # Auto stand on 21/Bust
                        elif cards_received == 3:
                            # 3rd card is ALWAYS the dealer's first visible card
                            print(f"[DEALER] Visible card: {rank}{suit_sym}")
                        elif is_player_turn:
                            p_sum += val
                            print(f"[YOU] Hit card: {rank}{suit_sym} | Total: {p_sum}")
                            if p_sum >= 21: is_player_turn = False
                        else:
                            print(f"[DEALER] Card revealed: {rank}{suit_sym}")

                    if result != 0x0:
                        status = {0x3: "WINNER! 🥳", 0x2: "LOSER 💀", 0x1: "PUSH 🤝"}.get(result, "")
                        if result == 0x3: wins += 1
                        print(f"Result: {status}");
                        break

                    # Input Logic
                    if cards_received >= 3 and is_player_turn and p_sum < 21:
                        action = input("(H)it or (S)tand? ").lower().strip()
                        decision = "Hittt" if action == 'h' else "Stand"
                        # This packs exactly 11 bytes (4+1+1+5)
                        tcp_sock.sendall(
                            struct.pack('!IbB5s', MAGIC_COOKIE, PAYLOAD_TYPE, 0, decision.ljust(5).encode()))
                        if action == 's': is_player_turn = False

            print(f"\nGame Over: {wins}/{rounds} wins")
            tcp_sock.close()
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python main.py [server|client]")
    else:
        mode = sys.argv[1].lower()
        if mode == "server":
            BlackjackServer().start()
        elif mode == "client":
            BlackjackClient().start()