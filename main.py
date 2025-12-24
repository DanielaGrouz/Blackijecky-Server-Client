import socket
import struct
import threading
import time
import random
import sys
import traceback

# constants
MAGIC_COOKIE = 0xabcddcba # The message is rejected if it doesn’t start with this cookie
OFFER_TYPE = 0x2 # server to client -> broadcast faze
REQUEST_TYPE = 0x3 # client to server -> after tcp connection
PAYLOAD_TYPE = 0x4 # messages client and server during the game
UDP_PORT = 13122  # hardcoded as per instructions
BUFFER_SIZE = 1024

def recv_all(sock, n):
    """
    Ensures exactly n bytes are read from the stream.
    Prevents data corruption due to network fragmentation.
    """
    data = bytearray()
    while len(data) < n:
        try:
            # read the missing bytes
            packet = sock.recv(n - len(data))
            # connection closed
            if not packet: return None
            # add missing bytes to data
            data.extend(packet)
        except socket.error:
            return None
    return data


class BlackjackServer:
    def __init__(self, team_name="pyjack"):
        # encode first, then pad with Null bytes to exactly 32 bytes
        # ljust -> the protocol expects a string of exactly 32 characters,
        # so if we wrote less, the ljust command adds spaces for padding
        self.team_name = team_name.encode().ljust(32, b'\x00')[:32]

        # setup TCP socket to listen for incoming connections
        # AF_INET -> use of Ipv4
        # SOCK_STREAM -> tcp protocol
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # instruct the operating system to allow the server to rebind to the same port immediately after it is closed,
        # bypassing the waiting mechanism (TIME_WAIT) and preventing an "Address already in use" error upon restart.
        # -> allows restarting server immediately on the same port
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # '' -> listen on all network interfaces of the computer.
        # bind to a random available port
        self.tcp_socket.bind(('', 0))
        # tcp_port -> save the allocated port
        self.tcp_port = self.tcp_socket.getsockname()[1]
        # size of the waiting clients queue is 15
        self.tcp_socket.listen(15)

    def broadcast_offers(self):
        """Sends UDP broadcast offers. Sleeps to avoid busy-waiting."""
        # create UCP socket
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # allow the socket to send broadcast messages
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # pack the offer message using network byte order
        packet = struct.pack('!IbH32s', MAGIC_COOKIE, OFFER_TYPE, self.tcp_port, self.team_name)

        print(f"Server started, listening on TCP port {self.tcp_port}")

        while True:
            try:
                # send broadcast message to all computers in the same network
                udp_socket.sendto(packet, ('<broadcast>', UDP_PORT))
                # send once every second -> Broadcasting once per second is frequent enough
                # for clients to find the server quickly, but does not overload the traffic.
                time.sleep(1)  # no busy waiting
            except Exception as e:
                # problem sending message OR network disconnected
                print(f"Broadcast warning: {e}")
                time.sleep(1)


    def get_card(self):
        """Generates a random card rank (1-13) and suit (0-3)."""
        return random.randint(1, 13), random.randint(0, 3)

    def calculate_value(self, hand):
        """
        Maps cards 1-13 to values.
        Map card (1-13) to value (Ace=11/1, Face=10).
        """
        val = 0
        aces = 0
        for rank, _ in hand:
            if rank == 1:
                aces += 1
                val += 11 # Ace
            elif rank >= 10:
                val += 10 # Face cards
            else:
                val += rank # Numeric cards

        # Soft Hand adjustment
        while val > 21 and aces > 0:
            val -= 10
            aces -= 1
        return val

    def handle_client(self, conn, addr):
        """
        Handles the lifecycle of a single client TCP connection.
        Manages the game rounds and the Blackjack logic.
        """
        try:
            # prevent hanging on clients
            conn.settimeout(600)  # 10 min timeout (not busy waiting, just idle limit)
            # read message from client
            request_data = recv_all(conn, 38)
            # validation
            if not request_data:
                return

            # Unpack the Request message from client
            magic, m_type, rounds, c_name = struct.unpack('!IbB32s', request_data)
            # validation
            if magic != MAGIC_COOKIE or m_type != REQUEST_TYPE:
                return

            print(f"New Game: {c_name.decode().strip()} ({rounds} rounds)")

            for _ in range(rounds):
                # Round Setup: Initial deal -> 2 cards to player and
                # 2 cards for dealer.
                p_hand = [self.get_card(), self.get_card()]
                d_hand = [self.get_card(), self.get_card()]

                # Send initial deal to client (2 player cards, 1 dealer card)
                for card in p_hand + [d_hand[0]]:
                    # Result 0x0 indicates the round is still active
                    # PAYLOAD_TYPE -> indicates game status
                    # send packet to player
                    conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, card[0], 0, card[1]))

                # Player's Turn: Loop until Stand or Bust
                while self.calculate_value(p_hand) < 21:
                    # receive decision from the player
                    # Expecting exactly 11 bytes for decision packet
                    decision_data = recv_all(conn, 11)
                    # validation
                    if not decision_data:
                        break

                    # Unpack the player decision ("Hittt" or "Stand")
                    _, _, _, d_raw = struct.unpack('!IbB5s', decision_data)

                    if b"Hittt" in d_raw:
                        # generate new card
                        new_c = self.get_card()
                        # add card to player
                        p_hand.append(new_c)
                        # inform client of the new card
                        conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, new_c[0], 0, new_c[1]))
                    else:
                        break  # player chooses to stand -> finished his turn

                # Dealer's Turn: Only if player hasn't busted
                p_sum = self.calculate_value(p_hand)
                d_sum = self.calculate_value(d_hand)

                # if player hasn't busted
                if p_sum > 21:
                    res = 0x2  # Loss (Player Bust) - Dealer does NOT reveal
                else:
                    # Dealer reveals hidden card and hits until sum >= 17
                    conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, d_hand[1][0], 0, d_hand[1][1]))

                    # Dealer hits on < 17
                    while d_sum < 17:
                        # generate new card
                        new_c = self.get_card()
                        # add card to dealer
                        d_hand.append(new_c)
                        # calculate new sun of the dealers hand
                        d_sum = self.calculate_value(d_hand)
                        # reveal each dealer draw to client
                        conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, new_c[0], 0, new_c[1]))

                    # Winner Determination
                    if d_sum > 21:
                        res = 0x3 # Dealer Bust (Win)
                    elif p_sum == d_sum:
                        res = 0x1 # Tie
                    elif p_sum > d_sum:
                        res = 0x3 # Player Win
                    else:
                        res = 0x2 # Player Loss

                # send the final packet for the round with the final result
                conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, res, 0, 0, 0))

        except Exception as e:
            print(f"Session Error with {addr}: {e}")  # error handling
        finally:
            conn.close()  # close session after all rounds or on error

    def start(self):
        """Starts the server broadcast thread and the main TCP acceptance loop."""
        # create a new thread and start background UDP broadcast
        # daemon -> if the main program terminates (the user closes the
        # server), this thread will automatically be killed along with it and
        # will not continue to run in the background and take up memory
        threading.Thread(target=self.broadcast_offers, daemon=True).start()
        print("Server is running forever. Press Ctrl+C to stop.")
        while True:
            try:
                # accept() blocks until a client connects, preventing busy-waiting
                # conn -> new socket which is dedicated to talking to that specific client.
                # The original socket (self.tcp_socket) remains free to listen to additional new clients.
                # addr -> port and ip of the new client
                conn, addr = self.tcp_socket.accept()
                # new thread for every new client
                # args -> pass the func the new socket
                threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()
            except Exception as e:
                print(f"Accept Error: {e}")


class BlackjackClient:
    def __init__(self, team_name="pyjack"):
        # encode first, then pad with Null bytes to exactly 32 bytes
        self.team_name = team_name.encode().ljust(32, b'\x00')[:32]

    def start(self):
        """Runs the client connection loop indefinitely."""
        while True:
            print("Client started, listening for offer requests...")
            # create new socket, SOCK_DGRAM -> UDP for Broadcast
            udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # allows multiple programs (or runs of the same program) to listen on
            # the same port simultaneously on the same computer.
            udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # if os supports SO_REUSEPORT -> enable to prevent conflicts when listening on the same port.
            if hasattr(socket, 'SO_REUSEPORT'):
                udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

            try:
                # '' -> listen on all network interfaces of the computer.
                # UDP_PORT -> The number of the port on which to expect offers
                udp_sock.bind(('', UDP_PORT))

                # program stops and waits for a UDP message to arrive.
                # offer_data -> the binary data received in bytes.
                # addr -> the sender's address (the IP and port of the server that sent the offer).
                offer_data, addr = udp_sock.recvfrom(BUFFER_SIZE)
                # convert the received byte sequence into Python variables
                # '!IbH32s'-> the format string that defines how to read the information
                # take only the first 39 bytes ([:39]) because this is the expected header size
                magic, m_type, tcp_port, s_name = struct.unpack('!IbH32s', offer_data[:39])
                # make sure that the received message is really part of our protocol (and not just network noise)
                # and that its type is "offer" (OFFER_TYPE).
                if magic == MAGIC_COOKIE and m_type == OFFER_TYPE:
                    print(f"Received offer from {addr[0]} ({s_name.decode().strip()})")
                    # closes the UDP socket. During the game phase we switch to TCP communication,
                    # so we don't need to listen to UDP right now.
                    udp_sock.close()
                    # call another function in the class that is responsible for opening a TCP connection
                    # to the server (according to the IP and port we received in the message) and managing
                    # the game itself.
                    self.play_game(addr[0], tcp_port)
            except Exception as e:
                print(f"Connection/Game Error: {e}")
            finally:
                try:
                    # close socket
                    udp_sock.close()
                except:
                    pass

    def play_game(self, ip, port):
        """Handles the TCP game logic and player input."""
        try:
            # SOCK_STREAM -> TCP for reliable connection
            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # create the physical connection to the server (according to the IP and port
            # we received in the previous start function).
            # this is the TCP "handshake" (three-way handshake).
            tcp_sock.connect((ip, port))

            # Input handling loop -> request user for game settings
            rounds_input = ""
            # make sure valid input
            while not rounds_input.isdigit():
                rounds_input = input("How many rounds would you like to play? ").strip()
            rounds = int(rounds_input)

            # send initial Request packet
            tcp_sock.sendall(struct.pack('!IbB32s', MAGIC_COOKIE, REQUEST_TYPE, rounds, self.team_name))

            wins = 0
            for r in range(rounds):
                print(f"\n{'=' * 25}\n   ROUND {r + 1} of {rounds}\n{'=' * 25}")
                p_sum, is_player_turn, cards_received = 0, True, 0

                while True:
                    # listen for update from the server -> a new card or result of the round
                    data = recv_all(tcp_sock, 9)
                    if not data:
                        print("Server disconnected.")
                        return

                    # unpack
                    _, _, result, rank, _, suit = struct.unpack('!IbB2bB', data)

                    if rank > 0:  # if a card was received
                        cards_received += 1
                        # calculate following the rules of the game
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

                    if result != 0x0: # round is over
                        status = {0x3: "WINNER! 🥳", 0x2: "LOSER 💀", 0x1: "TIE 🤝"}.get(result, "")
                        if result == 0x3: wins += 1
                        print(f"Result: {status}");
                        break # to finish the game\to start a new round

                    if cards_received >= 3 and is_player_turn and p_sum < 21:
                        action = ""
                        # make sure valid input
                        while action not in ['h', 's']:
                            action = input("(H)it or (S)tand? ").lower().strip()

                        decision = "Hittt" if action == 'h' else "Stand"
                        # send decision to server
                        # ljust -> the protocol expects a string of exactly 5 characters,
                        # so if we wrote less, the ljust command adds spaces for padding

                        tcp_sock.sendall(
                            struct.pack('!IbB5s', MAGIC_COOKIE, PAYLOAD_TYPE, 0, decision.ljust(5).encode()))
                        if action == 's':
                            is_player_turn = False

            print(f"\nGame Over: {wins}/{rounds} wins")
            tcp_sock.close() # close tcp socket
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
