import socket
import struct
import threading
import time
import random
import sys
import traceback

# --- PROTOCOL CONSTANTS ---
MAGIC_COOKIE = 0xabcddcba
OFFER_TYPE = 0x2
REQUEST_TYPE = 0x3
PAYLOAD_TYPE = 0x4
UDP_PORT = 13122
BUFFER_SIZE = 1024


def recv_all(sock, n):
    """
    Ensures exactly n bytes are read from the stream.
    Prevents data corruption due to network fragmentation.
    """
    data = bytearray()
    while len(data) < n:
        try:
            packet = sock.recv(n - len(data))
            if not packet: return None  # Connection closed remotely
            data.extend(packet)
        except socket.error:
            return None
    return data


class BlackjackServer:
    def __init__(self, team_name="WinError21"):  # Creative Name Guideline
        # Ensure name is exactly 32 bytes
        self.team_name = team_name.ljust(32)[:32].encode()
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Allows restarting server immediately on the same port
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_socket.bind(('', 0))  # Listen on random available port
        self.tcp_port = self.tcp_socket.getsockname()[1]
        self.tcp_socket.listen(15)

    def broadcast_offers(self):
        """Sends UDP broadcast offers. Sleeps to avoid busy-waiting."""
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        packet = struct.pack('!IbH32s', MAGIC_COOKIE, OFFER_TYPE, self.tcp_port, self.team_name)

        print(f"Server started, listening on TCP port {self.tcp_port}")

        while True:
            try:
                udp_socket.sendto(packet, ('<broadcast>', UDP_PORT))
                time.sleep(1)  # Guideline: No busy waiting
            except Exception as e:
                print(f"Broadcast warning: {e}")
                time.sleep(1)

    def calculate_value(self, hand):
        """
        Maps cards 1-13 to values.
        Guideline: Map card (1-13) to value (Ace=11/1, Face=10).
        """
        val = 0
        aces = 0
        for rank, _ in hand:
            if rank == 1:
                aces += 1
                val += 11
            elif rank >= 10:
                val += 10
            else:
                val += rank

        # Soft Hand adjustment
        while val > 21 and aces > 0:
            val -= 10
            aces -= 1
        return val

    def handle_client(self, conn, addr):
        """Manages a single client session."""
        try:
            conn.settimeout(600)  # 10 min timeout (not busy waiting, just idle limit)

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
                    # Expecting exactly 11 bytes for decision packet
                    decision_data = recv_all(conn, 11)
                    if not decision_data: break
                    _, _, _, d_raw = struct.unpack('!IbB5s', decision_data)

                    if b"Hittt" in d_raw:
                        new_c = (random.randint(1, 13), random.randint(0, 3))
                        p_hand.append(new_c)
                        conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, new_c[0], 0, new_c[1]))
                    else:
                        break  # Stand

                # Dealer Logic
                p_sum = self.calculate_value(p_hand)
                d_sum = self.calculate_value(d_hand)
                res = 0x0

                if p_sum > 21:
                    res = 0x2  # Loss (Player Bust) - Dealer does NOT reveal
                else:
                    # Reveal hidden card
                    conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, d_hand[1][0], 0, d_hand[1][1]))

                    # Dealer hits on < 17
                    while d_sum < 17:
                        new_c = (random.randint(1, 13), random.randint(0, 3))
                        d_hand.append(new_c)
                        d_sum = self.calculate_value(d_hand)
                        conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, new_c[0], 0, new_c[1]))

                    # Compare
                    if d_sum > 21:
                        res = 0x3
                    elif p_sum == d_sum:
                        res = 0x1
                    elif p_sum > d_sum:
                        res = 0x3
                    else:
                        res = 0x2

                # Final Result
                conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, res, 0, 0, 0))

        except Exception as e:
            print(f"Session Error with {addr}: {e}")  # Guideline: Error handling
        finally:
            conn.close()

    def start(self):
        # Daemon thread ensures broadcast stops when main thread dies
        threading.Thread(target=self.broadcast_offers, daemon=True).start()
        print("Server is running forever. Press Ctrl+C to stop.")
        while True:
            try:
                # accept() blocks, preventing busy-waiting
                conn, addr = self.tcp_socket.accept()
                threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()
            except Exception as e:
                print(f"Accept Error: {e}")


class BlackjackClient:
    def __init__(self, team_name="WinError21"):
        self.team_name = team_name.ljust(32)[:32].encode()

    def start(self):
        # Guideline: Client runs forever until manual quit
        while True:
            print("Client started, listening for offer requests...")
            udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Guideline: SO_REUSEPORT for running multiple clients on one machine
            if hasattr(socket, 'SO_REUSEPORT'):
                udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

            try:
                # Guideline: Listen on hardcoded port 13122
                udp_sock.bind(('', UDP_PORT))

                # Blocking call - no busy waiting
                offer_data, addr = udp_sock.recvfrom(BUFFER_SIZE)

                magic, m_type, tcp_port, s_name = struct.unpack('!IbH32s', offer_data[:39])
                if magic == MAGIC_COOKIE and m_type == OFFER_TYPE:
                    print(f"Received offer from {addr[0]} ({s_name.decode().strip()})")
                    udp_sock.close()
                    self.play_game(addr[0], tcp_port)
            except Exception as e:
                print(f"Connection/Game Error: {e}")
            finally:
                try:
                    udp_sock.close()
                except:
                    pass

    def play_game(self, ip, port):
        try:
            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            tcp_sock.connect((ip, port))

            # Input handling loop
            rounds_input = ""
            while not rounds_input.isdigit():
                rounds_input = input("How many rounds would you like to play? ").strip()
            rounds = int(rounds_input)

            tcp_sock.sendall(struct.pack('!IbB32s', MAGIC_COOKIE, REQUEST_TYPE, rounds, self.team_name))

            wins = 0
            for r in range(rounds):
                print(f"\n{'=' * 25}\n   ROUND {r + 1} of {rounds}\n{'=' * 25}")
                p_sum, is_player_turn, cards_received = 0, True, 0

                while True:
                    data = recv_all(tcp_sock, 9)
                    if not data:
                        print("Server disconnected.");
                        return

                    _, _, result, rank, _, suit = struct.unpack('!IbB2bB', data)

                    if rank > 0:
                        cards_received += 1
                        val = 11 if rank == 1 else (10 if rank >= 10 else rank)
                        suit_sym = ["♥", "♦", "♣", "♠"][suit]

                        # Logic to distinguish Player vs Dealer cards for display
                        if cards_received <= 2:
                            p_sum += val
                            # Basic client-side soft ace adjustment for display
                            if p_sum > 21 and rank == 1: p_sum -= 10
                            print(f"[YOU] Drawn: {rank}{suit_sym} | Hand: {p_sum}")
                            if p_sum >= 21: is_player_turn = False
                        elif cards_received == 3:
                            print(f"[DEALER] Visible card: {rank}{suit_sym}")
                        elif is_player_turn:
                            p_sum += val
                            if p_sum > 21 and rank == 1: p_sum -= 10
                            print(f"[YOU] Hit card: {rank}{suit_sym} | Total: {p_sum}")
                            if p_sum >= 21: is_player_turn = False
                        else:
                            print(f"[DEALER] Card revealed: {rank}{suit_sym}")

                    if result != 0x0:
                        status = {0x3: "WINNER! 🥳", 0x2: "LOSER 💀", 0x1: "PUSH 🤝"}.get(result, "")
                        if result == 0x3: wins += 1
                        print(f"Result: {status}");
                        break

                    if cards_received >= 3 and is_player_turn and p_sum < 21:
                        action = ""
                        while action not in ['h', 's']:
                            action = input("(H)it or (S)tand? ").lower().strip()

                        decision = "Hittt" if action == 'h' else "Stand"
                        tcp_sock.sendall(
                            struct.pack('!IbB5s', MAGIC_COOKIE, PAYLOAD_TYPE, 0, decision.ljust(5).encode()))
                        if action == 's': is_player_turn = False

            print(f"\nGame Over: {wins}/{rounds} wins")
            tcp_sock.close()
        except Exception as e:
            print(f"Gameplay Error: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python main.py [server|client]")
    else:
        mode = sys.argv[1].lower()
        if mode == "server":
            BlackjackServer().start()
        elif mode == "client":
            BlackjackClient().start()

# import socket
# import struct
# import threading
# import time
# import random
# import sys
# import traceback
#
# # --- PROTOCOL CONSTANTS ---
# MAGIC_COOKIE = 0xabcddcba
# OFFER_TYPE = 0x2
# REQUEST_TYPE = 0x3
# PAYLOAD_TYPE = 0x4
# UDP_PORT = 13122
# BUFFER_SIZE = 1024
#
#
# def recv_all(sock, n):
#     """Ensures exactly n bytes are read from the stream."""
#     data = bytearray()
#     while len(data) < n:
#         try:
#             packet = sock.recv(n - len(data))
#             if not packet: return None
#             data.extend(packet)
#         except:
#             return None
#     return data
#
#
# class BlackjackServer:
#     def __init__(self, team_name="CyberSharks"):
#         self.team_name = team_name.ljust(32)[:32].encode()
#         self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#         self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
#         self.tcp_socket.bind(('', 0))
#         self.tcp_port = self.tcp_socket.getsockname()[1]
#         self.tcp_socket.listen(15)
#
#     def broadcast_offers(self):
#         """Sends UDP broadcast offers."""
#         udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
#         udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
#         packet = struct.pack('!IbH32s', MAGIC_COOKIE, OFFER_TYPE, self.tcp_port, self.team_name)
#         print(f"Server started, listening on TCP port {self.tcp_port}")
#         while True:
#             try:
#                 udp_socket.sendto(packet, ('<broadcast>', UDP_PORT))
#                 time.sleep(1)
#             except:
#                 pass
#
#     def calculate_value(self, hand):
#         """Calculates hand value with correct Ace logic (Soft/Hard)."""
#         val = 0
#         aces = 0
#         for rank, _ in hand:
#             if rank == 1:
#                 aces += 1
#                 val += 11
#             elif rank >= 10:
#                 val += 10
#             else:
#                 val += rank
#
#         # Convert Aces from 11 to 1 if bust
#         while val > 21 and aces > 0:
#             val -= 10
#             aces -= 1
#         return val
#
#     def handle_client(self, conn, addr):
#         """Manages the game session."""
#         try:
#             # NOT Busy Waiting: The thread sleeps until data arrives or 600s pass.
#             conn.settimeout(600)
#
#             request_data = recv_all(conn, 38)
#             if not request_data: return
#             magic, m_type, rounds, c_name = struct.unpack('!IbB32s', request_data)
#             if magic != MAGIC_COOKIE or m_type != REQUEST_TYPE: return
#
#             print(f"New Game: {c_name.decode().strip()} ({rounds} rounds)")
#
#             for _ in range(rounds):
#                 p_hand = [(random.randint(1, 13), random.randint(0, 3)), (random.randint(1, 13), random.randint(0, 3))]
#                 d_hand = [(random.randint(1, 13), random.randint(0, 3)), (random.randint(1, 13), random.randint(0, 3))]
#
#                 # Initial deal
#                 for card in p_hand + [d_hand[0]]:
#                     conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, card[0], 0, card[1]))
#
#                 # --- Player Turn Loop ---
#                 while self.calculate_value(p_hand) < 21:
#                     # FIX: Read exactly 11 bytes (Magic 4 + Type 1 + Placeholder 1 + Decision 5)
#                     decision_data = recv_all(conn, 11)
#                     if not decision_data: break
#                     _, _, _, d_raw = struct.unpack('!IbB5s', decision_data)
#                     if b"Hittt" in d_raw:
#                         new_c = (random.randint(1, 13), random.randint(0, 3))
#                         p_hand.append(new_c)
#                         conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, new_c[0], 0, new_c[1]))
#                     else:
#                         break  # Player stands
#
#                 # --- Dealer Turn Logic (Strict Rule Adherence) ---
#                 #
#                 p_sum = self.calculate_value(p_hand)
#                 d_sum = self.calculate_value(d_hand)
#                 res = 0x0
#
#                 if p_sum > 21:
#                     # RULE: If client busts, they IMMEDIATELY lose.
#                     # Dealer does NOT reveal hidden card. Dealer does NOT draw.
#                     res = 0x2  # Loss
#                 else:
#                     # RULE: If client did NOT bust:
#                     # 1. Reveal hidden second card
#                     conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, d_hand[1][0], 0, d_hand[1][1]))
#
#                     # 2. Dealer draws until 17 or more
#                     while d_sum < 17:
#                         new_c = (random.randint(1, 13), random.randint(0, 3))
#                         d_hand.append(new_c)
#                         d_sum = self.calculate_value(d_hand)
#                         conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, new_c[0], 0, new_c[1]))
#
#                     # 3. Determine winner
#                     if d_sum > 21:
#                         res = 0x3  # Dealer Bust -> Win
#                     elif p_sum == d_sum:
#                         res = 0x1  # Tie
#                     elif p_sum > d_sum:
#                         res = 0x3  # Player Higher -> Win
#                     else:
#                         res = 0x2  # Dealer Higher -> Loss
#
#                 # Send Final Result
#                 conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, res, 0, 0, 0))
#         except Exception:
#             traceback.print_exc()
#         finally:
#             conn.close()
#
#     def start(self):
#         threading.Thread(target=self.broadcast_offers, daemon=True).start()
#         while True:
#             # accept() blocks, waiting for connection. This is efficient event-driven IO.
#             conn, addr = self.tcp_socket.accept()
#             threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()
#
#
# class BlackjackClient:
#     def __init__(self, team_name="Joker"):
#         self.team_name = team_name.ljust(32)[:32].encode()
#
#     def start(self):
#         while True:
#             print("Client started, listening for offer requests...")
#             udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
#             udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
#             if hasattr(socket, 'SO_REUSEPORT'): udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
#             try:
#                 udp_sock.bind(('', UDP_PORT))
#                 offer_data, addr = udp_sock.recvfrom(BUFFER_SIZE)
#                 magic, m_type, tcp_port, s_name = struct.unpack('!IbH32s', offer_data[:39])
#                 if magic == MAGIC_COOKIE and m_type == OFFER_TYPE:
#                     print(f"Received offer from {addr[0]} ({s_name.decode().strip()})")
#                     udp_sock.close()
#                     self.play_game(addr[0], tcp_port)
#             except:
#                 udp_sock.close()
#
#     def play_game(self, ip, port):
#         try:
#             tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#             tcp_sock.connect((ip, port))
#             rounds_input = input("How many rounds would you like to play? ").strip()
#             rounds = int(rounds_input) if rounds_input.isdigit() else 1
#             tcp_sock.sendall(struct.pack('!IbB32s', MAGIC_COOKIE, REQUEST_TYPE, rounds, self.team_name))
#
#             wins = 0
#             for r in range(rounds):
#                 print(f"\n{'=' * 25}\n   ROUND {r + 1} of {rounds}\n{'=' * 25}")
#                 p_sum, is_player_turn, cards_received = 0, True, 0
#
#                 while True:
#                     data = recv_all(tcp_sock, 9)
#                     if not data:
#                         print("Error: Connection lost.");
#                         return
#
#                     _, _, result, rank, _, suit = struct.unpack('!IbB2bB', data)
#
#                     if rank > 0:
#                         cards_received += 1
#                         val = 11 if rank == 1 else (10 if rank >= 10 else rank)
#                         suit_sym = ["♥", "♦", "♣", "♠"][suit]
#
#                         if cards_received <= 2:
#                             p_sum += val
#                             if p_sum > 21 and rank == 1: p_sum -= 10
#                             print(f"[YOU] Drawn: {rank}{suit_sym} | Hand: {p_sum}")
#                             if p_sum >= 21: is_player_turn = False
#                         elif cards_received == 3:
#                             print(f"[DEALER] Visible card: {rank}{suit_sym}")
#                         elif is_player_turn:
#                             p_sum += val
#                             if p_sum > 21 and rank == 1: p_sum -= 10
#                             print(f"[YOU] Hit card: {rank}{suit_sym} | Total: {p_sum}")
#                             if p_sum >= 21: is_player_turn = False
#                         else:
#                             print(f"[DEALER] Card revealed: {rank}{suit_sym}")
#
#                     if result != 0x0:
#                         status = {0x3: "WINNER! 🥳", 0x2: "LOSER 💀", 0x1: "PUSH 🤝"}.get(result, "")
#                         if result == 0x3: wins += 1
#                         print(f"Result: {status}");
#                         break
#
#                     if cards_received >= 3 and is_player_turn and p_sum < 21:
#                         action = input("(H)it or (S)tand? ").lower().strip()
#                         decision = "Hittt" if action == 'h' else "Stand"
#                         tcp_sock.sendall(
#                             struct.pack('!IbB5s', MAGIC_COOKIE, PAYLOAD_TYPE, 0, decision.ljust(5).encode()))
#                         if action == 's': is_player_turn = False
#
#             print(f"\nGame Over: {wins}/{rounds} wins")
#             tcp_sock.close()
#         except Exception as e:
#             print(f"Error: {e}")
#
#
# if __name__ == "__main__":
#     if len(sys.argv) < 2:
#         print("Usage: python main.py [server|client]")
#     else:
#         mode = sys.argv[1].lower()
#         if mode == "server":
#             BlackjackServer().start()
#         elif mode == "client":
#             BlackjackClient().start()