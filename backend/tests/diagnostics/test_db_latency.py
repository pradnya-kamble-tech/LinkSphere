import time
import psycopg

def measure_rtt(host, port, iterations=500):
    conn_str = f"host={host} port={port} dbname=linksphere_test user=linksphere_user password=linksphere_dev_password"
    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            # Warm up
            cur.execute("SELECT 1;")
            start = time.perf_counter()
            for _ in range(iterations):
                cur.execute("SELECT 1;")
                cur.fetchone()
            total_time = time.perf_counter() - start
            avg_ms = (total_time / iterations) * 1000
            return avg_ms

if __name__ == "__main__":
    ms_localhost = measure_rtt("localhost", 5434)
    ms_127 = measure_rtt("127.0.0.1", 5434)
    print(f"localhost:5434: {ms_localhost:.3f} ms per round-trip")
    print(f"127.0.0.1:5434: {ms_127:.3f} ms per round-trip")
