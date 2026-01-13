import socket
import struct
import protocol


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
                udp_sock.bind(('', protocol.UDP_PORT))

                # loop to continue listening if the received message is not appropriate
                while True:
                    # program stops and waits for a UDP message to arrive.
                    # offer_data -> the binary data received in bytes.
                    # addr -> the sender's address (the IP and port of the server that sent the offer).
                    offer_data, addr = udp_sock.recvfrom(protocol.BUFFER_SIZE)

                    # minimum length check to prevent unpack crash
                    if len(offer_data) < 39:
                        continue

                    # convert the received byte sequence into Python variables
                    # '!IbH32s'-> the format string that defines how to read the information
                    # take only the first 39 bytes ([:39]) because this is the expected header size
                    magic, m_type, tcp_port, s_name = struct.unpack('!IbH32s', offer_data[:39])

                    # make sure that the received message is really part of our protocol (and not just network noise)
                    # and that its type is "offer" (OFFER_TYPE).
                    if magic == protocol.MAGIC_COOKIE and m_type == protocol.OFFER_TYPE:
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
            tcp_sock.sendall(
                struct.pack('!IbB32s', protocol.MAGIC_COOKIE, protocol.REQUEST_TYPE, rounds, self.team_name))

            wins = 0
            for r in range(rounds):
                print(f"\n{'=' * 25}\n   ROUND {r + 1} of {rounds}\n{'=' * 25}")
                p_sum, d_sum, is_player_turn, cards_received = 0, 0, True, 0

                while True:
                    # listen for update from the server -> a new card or result of the round
                    data = protocol.recv_all(tcp_sock, 9)
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
                            struct.pack('!Ib5s', protocol.MAGIC_COOKIE, protocol.PAYLOAD_TYPE,
                                        decision.ljust(5).encode()))
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
    BlackjackClient().start()
