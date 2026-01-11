import socket
import struct
import threading
import time
import random
import sys

# constants
MAGIC_COOKIE = 0xabcddcba  # The message is rejected if it does not start with this cookie
OFFER_TYPE = 0x2  # server to client -> broadcast faze
REQUEST_TYPE = 0x3  # client to server -> after tcp connection
PAYLOAD_TYPE = 0x4  # messages client and server during the game
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
            if not packet:
                return None
            # add missing bytes to data
            data.extend(packet)
        except socket.error:
            return None
    return data


class BlackjackServer:
    def __init__(self, team_name="pyjack"):
        # encode first, then pad with Null bytes to exactly 32 bytes
        # ljust -> the protocol expects a string of exactly 32 characters,
        # so if we wrote less, the ljust command adds nulls for padding
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

    def get_local_ip(self):
        """
        Helper to find the actual IP address of the machine's primary network interface.
        This solves the WSL/Virtual Adapter issue by forcing the OS to reveal which
        interface it uses for outbound traffic.
        """

        # AF_INET -> IPv4, SOCK_DGRAM -> UDP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # os will decide which network interface (Wi-Fi/Ethernet) would be used to reach the outside world.
            s.connect(('10.255.255.255', 1))
            # the local IP address of the interface selected by the os
            IP = s.getsockname()[0]
        except Exception:
            # back to localhost if no external network is available
            IP = '127.0.0.1'
        finally:
            # close the socket
            s.close()
        return IP

    def broadcast_offers(self):
        """Sends UDP broadcast offers. Sleeps to avoid busy-waiting."""

        server_ip = self.get_local_ip()
        # create UDP socket
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # We bind to the specific IP to force traffic through the correct interface
        try:
            udp_socket.bind((server_ip, 0))
        except:
            print(f"Warning: Could not bind to {server_ip}, using default.")

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

    def create_deck(self):
        """Creates a deck of 52 cards and shuffles it"""
        deck = [(rank, suit) for rank in range(1, 14) for suit in range(4)]
        random.shuffle(deck)
        return deck

    def format_card(self, card):
        """Turning a card into a read string for the terminal on the server"""
        rank, suit = card
        rank_display = {1: 'A', 11: 'J', 12: 'Q', 13: 'K'}.get(rank, str(rank))
        suit_sym = ["♥", "♦", "♣", "♠"][suit]

        if suit < 2:  # red color
            return f"\033[91m{rank_display}{suit_sym}\033[0m"
        else:  # green color
            return f"\033[92m{rank_display}{suit_sym}\033[0m"


    def calculate_value(self, hand):
        """
        Maps cards 1-13 to values.
        Map card (1-13) to value (Ace=11, Face=10).
        """
        val = 0
        for rank, _ in hand:
            if rank == 1:
                val += 11  # Ace
            elif rank >= 10:
                val += 10  # Face cards
            else:
                val += rank  # Numeric cards

        return val

    def handle_client(self, conn, addr):
        """
        Handles the lifecycle of a single client TCP connection.
        Manages the game rounds and the Blackjack logic.
        """
        c_name = b"Unknown"
        try:
            # prevent hanging on clients
            conn.settimeout(60)  # 1 min timeout (not busy waiting, just idle limit)
            # read message from client
            request_data = recv_all(conn, 38)
            # validation
            if not request_data:
                return

            # Unpack the Request message from client
            magic, m_type, rounds, c_name = struct.unpack('!IbB32s', request_data)
            # validation
            if magic != MAGIC_COOKIE or m_type != REQUEST_TYPE:
                print(f"Invalid request from {addr}")
                return

            print(f"New Game: {c_name.decode().strip()} ({rounds} rounds)")

            for round_idx in range(rounds):
                print(f"\n--- Round {round_idx + 1} of {rounds} ---")
                # Create a new deck for each round
                deck = self.create_deck()

                # Initial deal -> 2 cards to player and 2 cards for dealer.
                p_hand = [deck.pop(), deck.pop()]
                d_hand = [deck.pop(), deck.pop()]

                p_cards_str = ", ".join([self.format_card(c) for c in p_hand])
                print(f"Player initial hand: {p_cards_str} | Total: {self.calculate_value(p_hand)}")
                print(f"Dealer visible card: {self.format_card(d_hand[0])} | Total: {self.calculate_value([d_hand[0]])}")

                # Send initial deal to client (2 player cards, 1 dealer card)
                for card in p_hand + [d_hand[0]]:
                    # Result 0x0 indicates the round is still active
                    # PAYLOAD_TYPE -> indicates game status
                    # send packet to player
                    conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, card[0], 0, card[1]))

                # Player's Turn: Loop until Stand or Bust
                while self.calculate_value(p_hand) < 21:
                    # receive decision from the player
                    # Expecting exactly 10 bytes for decision packet
                    decision_data = recv_all(conn, 10)
                    # validation
                    if not decision_data:
                        break

                    # Unpack the player decision ("Hit" or "Stand")
                    _, _, d_raw = struct.unpack('!Ib5s', decision_data)
                    # Print the player's decision
                    decision = d_raw.decode().strip()
                    print(f"Player decision: {decision}")

                    if b"Hit" in d_raw:
                        # Draw the next card from the shuffled deck
                        new_c = deck.pop()
                        # add card to player
                        p_hand.append(new_c)
                        print(f"Player drew: {self.format_card(new_c)} | New Total: {self.calculate_value(p_hand)}")
                        # inform client of the new card
                        conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, new_c[0], 0, new_c[1]))
                    else:
                        break  # player chooses to stand -> finished his turn

                # Dealer's Turn: Only if player hasn't busted
                p_sum = self.calculate_value(p_hand)
                d_sum = self.calculate_value(d_hand)

                # if player hasn't busted
                if p_sum > 21:
                    print(f"Player BUSTED with {p_sum}!")
                    res = 0x2  # Loss (Player Bust) - Dealer does NOT reveal
                else:
                    print(f"Player stands at {p_sum}. Dealer's turn.")
                    # Dealer reveals hidden card and hits until sum >= 17
                    conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, d_hand[1][0], 0, d_hand[1][1]))
                    print(f"Dealer reveals: {self.format_card(d_hand[1])} | Dealer Total: {d_sum}")

                    # Dealer hits on < 17
                    while d_sum < 17:
                        # Draw the next card from the shuffled deck
                        new_c = deck.pop()
                        # add card to dealer
                        d_hand.append(new_c)
                        # calculate new sun of the dealers hand
                        d_sum = self.calculate_value(d_hand)
                        print(f"Dealer hits and draws: {self.format_card(new_c)} | Dealer Total: {d_sum}")
                        # reveal each dealer draw to client
                        conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, 0x0, new_c[0], 0, new_c[1]))

                    # Winner Determination
                    if d_sum > 21:
                        print(f"Dealer BUSTED with {d_sum}!")
                        res = 0x3  # Dealer Bust (Win)
                    elif p_sum == d_sum:
                        res = 0x1  # Tie
                    elif p_sum > d_sum:
                        res = 0x3  # Player Win
                    else:
                        res = 0x2  # Player Loss

                # Print the result on the server
                result_map = {0x3: "Player Wins", 0x2: "Dealer Wins", 0x1: "Tie"}
                print(f"Round Result: {result_map[res]}")
                # send the final packet for the round with the final result
                conn.sendall(struct.pack('!IbB2bB', MAGIC_COOKIE, PAYLOAD_TYPE, res, 0, 0, 0))

        # error handling
        except socket.timeout:
            print(f"Connection timed out for {c_name.decode().strip()} at {addr}")
        except Exception as e:
            print(f"Session Error with {c_name.decode().strip()} ({addr}): {e}")
        finally:
            conn.close()  # close session after all rounds or on error
            print(f"Connection with {c_name.decode().strip()} closed.")

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
    def __init__(self, team_name="pyjack-client"):
        self.current_rounds = 0
        # encode first, then pad with Null bytes to exactly 32 bytes
        self.team_name = team_name.encode().ljust(32, b'\x00')[:32]

    def format_card(self, rank, suit):
        """Turning a card into a read string for the terminal on the client"""
        rank_display = {1: 'A', 11: 'J', 12: 'Q', 13: 'K'}.get(rank, str(rank))
        suit_sym = ["♥", "♦", "♣", "♠"][suit]

        if suit < 2:  # red color
            return f"\033[91m{rank_display}{suit_sym}\033[0m"
        else:  # green color
            return f"\033[92m{rank_display}{suit_sym}\033[0m"

    def start(self):
        """Runs the client connection loop indefinitely."""
        while True:

            # Input handling loop -> request user for game settings
            self.current_rounds = 0
            rounds_input = ""
            # make sure valid input
            while True:
                rounds_input = input("How many rounds would you like to play? ").strip()
                # Checks that it is a number and that it is greater than 0
                if rounds_input.isdigit() and int(rounds_input) > 0:
                    self.current_rounds = int(rounds_input)
                    break
                print("Please enter a valid number of rounds (at least 1).")

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

                # loop to continue listening if the received message is not appropriate
                while True:
                    # program stops and waits for a UDP message to arrive.
                    # offer_data -> the binary data received in bytes.
                    # addr -> the sender's address (the IP and port of the server that sent the offer).
                    offer_data, addr = udp_sock.recvfrom(BUFFER_SIZE)

                    # minimum length check to prevent unpack crash
                    if len(offer_data) < 39:
                        continue

                    # convert the received byte sequence into Python variables
                    # '!IbH32s'-> the format string that defines how to read the information
                    # take only the first 39 bytes ([:39]) because this is the expected header size
                    magic, m_type, tcp_port, s_name = struct.unpack('!IbH32s', offer_data[:39])

                    # make sure that the received message is really part of our protocol (and not just network noise)
                    # and that its type is "offer" (OFFER_TYPE).
                    if magic == MAGIC_COOKIE and m_type == OFFER_TYPE:
                        # server name sanitization (removing NULL bytes)
                        server_name_str = s_name.decode().strip('\x00').strip()
                        print(f"Received offer from {addr[0]} ({server_name_str})")

                        # server filtering (to avoid connecting to other people's servers)
                        if server_name_str != "pyjack":
                            print(f"Server name '{server_name_str}' does not match, ignoring...")
                            continue

                        # closes the UDP socket. During the game phase we switch to TCP communication,
                        # so we don't need to listen to UDP right now.
                        udp_sock.close()

                        # call another function in the class that is responsible for opening a TCP connection
                        # to the server (according to the IP and port we received in the message) and managing
                        # the game itself.
                        self.play_game(addr[0], tcp_port, self.current_rounds)
                        break

            except Exception as e:
                print(f"Connection/Game Error: {e}")
            finally:
                try:
                    # close socket
                    udp_sock.close()
                except:
                    pass

    def play_game(self, ip, port, rounds):
        """Handles the TCP game logic and player input."""
        try:
            # SOCK_STREAM -> TCP for reliable connection
            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Preventing hangs if the server is not responding
            tcp_sock.settimeout(15)
            # create the physical connection to the server (according to the IP and port
            # we received in the previous start function).
            # this is the TCP "handshake" (three-way handshake).
            tcp_sock.connect((ip, port))

            # send initial Request packet
            tcp_sock.sendall(struct.pack('!IbB32s', MAGIC_COOKIE, REQUEST_TYPE, rounds, self.team_name))

            wins = 0
            for r in range(rounds):
                print(f"\n{'=' * 25}\n   ROUND {r + 1} of {rounds}\n{'=' * 25}")
                p_sum, d_sum, is_player_turn, cards_received = 0, 0, True, 0

                while True:
                    # listen for update from the server -> a new card or result of the round
                    data = recv_all(tcp_sock, 9)
                    if not data:
                        print("Error: Server disconnected unexpectedly.")
                        return

                    # unpack
                    _, _, result, rank, _, suit = struct.unpack('!IbB2bB', data)

                    if rank > 0:  # if a card was received
                        cards_received += 1
                        # calculate following the rules of the game
                        val = 11 if rank == 1 else (10 if rank >= 10 else rank)

                        card_str = self.format_card(rank, suit)

                        # Logic to distinguish Player vs Dealer cards for display
                        if cards_received <= 2:
                            p_sum += val
                            # Basic client-side soft ace adjustment for display
                            print(f"[YOU] Drawn: {card_str} | Total: {p_sum}")
                            if p_sum >= 21: is_player_turn = False
                        elif cards_received == 3:
                            d_sum += val
                            print(f"[DEALER] Visible card: {card_str} | Total: {d_sum}")
                        elif is_player_turn:
                            p_sum += val
                            print(f"[YOU] Hit card: {card_str} | Total: {p_sum}")
                            if p_sum >= 21:
                                is_player_turn = False
                        else:
                            d_sum += val
                            print(f"[DEALER] Card revealed: {card_str} | Total: {d_sum}")

                    if result != 0x0:  # round is over
                        status = {
                            0x3: "\033[1;92mWINNER! 🥳\033[0m",
                            0x2: "\033[1;91mLOSER 💀\033[0m",
                            0x1: "\033[1;93mTIE 🤝\033[0m"
                        }
                        print(f"Result: {status.get(result, '')}")

                        if result == 0x3:
                            wins += 1
                        break  # to finish the game\to start a new round

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
                            struct.pack('!Ib5s', MAGIC_COOKIE, PAYLOAD_TYPE, decision.ljust(5).encode()))
                        if action == 's':
                            is_player_turn = False

            win_rate = (wins / rounds) * 100 if rounds > 0 else 0
            print(f"\nFinished playing {rounds} rounds, win rate: {win_rate}")
            tcp_sock.close()  # close tcp socket

        except socket.timeout:
            print("\n[!] Error: Server is not responding (Timeout).")
        except ConnectionRefusedError:
            print(f"\n[!] Error: Could not connect to server at {ip}:{port}.")
        except Exception as e:
            print(f"\n[!] Gameplay Error: {e}")
        finally:
            tcp_sock.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python main.py [server|client]")
    else:
        mode = sys.argv[1].lower()
        if mode == "server":
            BlackjackServer().start()
        elif mode == "client":
            BlackjackClient().start()
