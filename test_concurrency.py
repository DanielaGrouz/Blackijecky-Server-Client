import subprocess
import sys
import time


def run_stress_test():
    print("--- TESTING CONCURRENCY & SO_REUSEPORT ---")

    # 1. Start Server
    print("Launching Server...")
    server = subprocess.Popen([sys.executable, 'main.py', 'server'],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(2)  # Wait for server startup

    clients = []
    # 2. Launch 3 Clients simultaneously
    # If SO_REUSEPORT is missing/wrong, clients 2 and 3 will crash with "Address already in use"
    for i in range(3):
        print(f"Launching Client {i + 1}...")
        # Automate input: "1 round", then "Stand" (s)
        p = subprocess.Popen([sys.executable, 'main.py', 'client'],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        clients.append(p)

    # 3. Feed input
    for p in clients:
        try:
            out, err = p.communicate(input="1\ns\n", timeout=10)
            if "Address already in use" in err:
                print(f"❌ FAIL: Client {p.pid} failed to bind port (SO_REUSEPORT issue).")
            elif "Game Over" in out:
                print(f"✅ PASS: Client {p.pid} played successfully.")
            else:
                print(f"⚠️ UNKNOWN: Client {p.pid} output:\n{out}\nError:\n{err}")
        except:
            p.kill()
            print(f"❌ Client {p.pid} timed out.")

    # Cleanup
    server.terminate()
    print("Test Complete.")


if __name__ == "__main__":
    run_stress_test()