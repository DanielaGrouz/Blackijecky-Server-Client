import subprocess
import sys
import time

# Configuration
NUM_CLIENTS = 3            # Number of concurrent clients
CLIENT_INPUT = "1\ns\n"    # Input: 1 round, then "Stand" (to finish quickly)

def run_system_test():
    print(f"--- SYSTEM TEST: Concurrency & Stability ({NUM_CLIENTS} Clients) ---")

    # 1. Start the Server
    # Using '-u' (unbuffered) is critical to read output in real-time
    print("[Test] Launching Server...")
    server_process = subprocess.Popen(
        [sys.executable, '-u', 'main.py', 'server'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8' # Important: Supports emojis (UTF-8)
    )

    time.sleep(2) # Allow server time to bind and start broadcasting

    # 2. Launch Clients concurrently
    clients = []
    print(f"[Test] Launching {NUM_CLIENTS} clients simultaneously...")

    for i in range(NUM_CLIENTS):
        p = subprocess.Popen(
            [sys.executable, '-u', 'main.py', 'client'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8'
        )
        clients.append(p)

    # 3. Feed input and verify results
    print("[Test] Clients are playing...")
    success_count = 0

    for i, p in enumerate(clients):
        try:
            # Send input and wait (with timeout)
            # Since the client runs in an infinite loop, we expect a TimeoutExpired exception.
            # However, we will capture whatever output was printed before the timeout.
            try:
                outs, errs = p.communicate(input=CLIENT_INPUT, timeout=10)
            except subprocess.TimeoutExpired as e:
                p.kill() # Kill the client as the test round is over
                # Retrieve captured output
                outs = e.stdout if e.stdout else ""
                errs = e.stderr if e.stderr else ""

            # Verify output content
            if "Address already in use" in errs:
                print(f"❌ Client {i+1}: Failed (Port conflict! Check SO_REUSEPORT)")
            elif "Finished playing" in outs:
                print(f"✅ Client {i+1}: Finished successfully (Stats printed).")
                success_count += 1
            else:
                print(f"⚠️ Client {i+1}: Unknown state.\nLast Output:\n{outs[-200:]}")

        except Exception as ex:
            print(f"❌ Client {i+1}: Crashed - {ex}")

    # 4. Cleanup and Server Shutdown
    print("[Test] Stopping Server...")
    server_process.terminate()
    try:
        server_process.wait(timeout=2)
    except:
        server_process.kill()

    # Final Summary
    print("-" * 30)
    if success_count == NUM_CLIENTS:
        print("🏆 TEST PASSED: All clients played concurrently.")
    else:
        print(f"💥 TEST FAILED: Only {success_count}/{NUM_CLIENTS} clients succeeded.")

if __name__ == "__main__":
    run_system_test()