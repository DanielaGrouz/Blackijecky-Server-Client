import subprocess
import sys
import time
import os

# --- CONFIGURATION ---
NUM_CLIENTS = 5  # How many clients to run at once
ROUNDS_TO_PLAY = 2  # How many rounds each client plays
CLIENT_INPUT = "2\ns\ns\n"  # Input: "2 rounds" -> "Stand" (round 1) -> "Stand" (round 2)


def run_test():
    print(f"--- STARTING STRESS TEST ({NUM_CLIENTS} Clients) ---")

    # 1. Start the Server
    print("[Test] Launching Server...")
    server_process = subprocess.Popen(
        [sys.executable, 'main.py', 'server'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Give server a moment to bind ports
    time.sleep(2)

    # 2. Launch Clients concurrently
    clients = []
    print(f"[Test] Launching {NUM_CLIENTS} clients simultaneously...")

    for i in range(NUM_CLIENTS):
        # We start the client and pipe the predefined inputs to it
        p = subprocess.Popen(
            [sys.executable, 'main.py', 'client'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        clients.append(p)

    # 3. Feed input to clients and wait for them to finish
    print("[Test] Clients are playing...")
    active_clients = clients[:]

    start_time = time.time()

    # Send inputs to all clients
    for p in clients:
        try:
            # This sends the "2\ns\ns\n" string to the client's input()
            outs, errs = p.communicate(input=CLIENT_INPUT, timeout=15)
            if p.returncode == 0:
                print(f"✅ Client {p.pid} finished successfully.")
            else:
                print(f"❌ Client {p.pid} crashed! Error:\n{errs}")
        except subprocess.TimeoutExpired:
            p.kill()
            print(f"❌ Client {p.pid} timed out.")

    # 4. Cleanup
    print("[Test] Stopping Server...")
    server_process.terminate()
    try:
        server_process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        server_process.kill()

    print("\n--- TEST SUMMARY ---")
    print(f"Test completed in {time.time() - start_time:.2f} seconds.")
    print("If you see 'Finished successfully' for all clients, your concurrency works!")


if __name__ == "__main__":
    run_test()