import multiprocessing
import subprocess
import time


def run_client():
    """
    Launches a single client instance.
    This simulates a real team connecting during the hackathon.
    """
    # Using 'input' simulation to automate the 'number of rounds' prompt
    # This sends '3' as the number of rounds and then plays a few hits
    process = subprocess.Popen(
        ['python', 'main.py', 'client'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    # Simulate user input: 3 rounds, then 's' (stand) for every prompt
    try:
        output, errors = process.communicate(input="3\ns\ns\ns\ns\ns\ns\n", timeout=30)
        print(f"Client Instance Finished.\nFinal Stats Output: {output.splitlines()[-1]}")
    except Exception as e:
        print(f"Client instance error: {e}")


if __name__ == "__main__":
    print("--- Starting Stress Test: Launching 10 Concurrent Clients ---")

    processes = []
    for i in range(10):
        p = multiprocessing.Process(target=run_client)
        processes.append(p)
        p.start()
        print(f"Launched Client #{i + 1}")

    for p in processes:
        p.join()

    print("--- Stress Test Complete ---")