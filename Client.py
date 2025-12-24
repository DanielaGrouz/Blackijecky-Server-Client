import socket
import struct
import threading
import time
import random
import sys

# constants
MAGIC_COOKIE = 0xabcddcba # The message is rejected if it doesn’t start with this cookie
OFFER_TYPE = 0x2 # server to client -> broadcast faze
REQUEST_TYPE = 0x3 # client to server -> after tcp connection
PAYLOAD_TYPE = 0x4 # messages client and server during the game
UDP_PORT = 13122  # hardcoded as per instructions
BUFFER_SIZE = 1024


class BlackjackClient:
    """
    Client class that listens for server offers and engages in Blackjack games.
    """

    def __init__(self, team_name="Joker"): #default name = Joker
        # ensure team name is exactly 32 bytes
        self.team_name = team_name.ljust(32)[:32].encode()

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

            # '' -> listen on all network interfaces of the computer.
            # UDP_PORT -> The number of the port on which to expect offers
            udp_sock.bind(('', UDP_PORT))

            try:
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
                print(f"Client error: {e}")
                # close socket due to an error
                udp_sock.close()
    def play_game(self, server_ip, server_port):
        """Handles the TCP game logic and player input."""
        try:
            # SOCK_STREAM -> TCP for reliable connection
            tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # create the physical connection to the server (according to the IP and port
            # we received in the previous start function).
            # this is the TCP "handshake" (three-way handshake).
            tcp_sock.connect((server_ip, server_port))

            # request user for game settings
            rounds_input = ""
            # make sure valid input
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
                    # listen for update from the server -> a new card or result of the round
                    data = tcp_sock.recv(BUFFER_SIZE)
                    if not data: break

                    # unpack
                    _, _, result, rank, _, suit = struct.unpack('!IbB2bB', data[:9])

                    if rank > 0:  # if a card was received
                        # calculate following the rules of the game
                        value = 11 if rank == 1 else (10 if rank >= 10 else rank)
                        current_sum += value
                        suit_name = ["Heart", "Diamond", "Club", "Spade"][suit]
                        print(f"Drawn: {rank} of {suit_name}. Current hand value: {current_sum}")

                    if result != 0x0:  # round is over
                        if result == 0x3:
                            wins += 1
                            print("Result: WIN! 🥳")
                        elif result == 0x2:
                            print("Result: LOSS 💀")
                        else:
                            print("Result: TIE 🤝")
                        break # to finish the game\to start a new round

                    # if still active, ask for user decision
                    if current_sum < 21:
                        action = ""
                        # make sure valid input
                        while action.lower() not in ['h', 's']:
                            action = input("(H)it or (S)tand? ").lower().strip()
                        if action.lower() == 'h':
                            decision_str = "Hittt"
                        else:
                            decision_str = "Stand"
                        # send decision to server
                        # ljust -> the protocol expects a string of exactly 5 characters,
                        # so if we wrote less, the ljust command adds spaces for padding
                        payload = struct.pack('!IbB5s', MAGIC_COOKIE, 0x4, 0, decision_str.ljust(5).encode())
                        tcp_sock.send(payload)
                        if action.lower() != 'h': break  # wait for dealer to finish

            # calculate and print session statistics
            win_rate = (wins / rounds * 100) if rounds > 0 else 0
            print(f"\nFinished playing {rounds} rounds, win rate: {win_rate:.1f}%")
            # close tcp socket
            tcp_sock.close()

        except Exception as e:
            print(f"Game error: {e}")


if __name__ == "__main__":
    client = BlackjackClient()
    client.start()