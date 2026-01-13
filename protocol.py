import socket

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

