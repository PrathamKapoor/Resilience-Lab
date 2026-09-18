"""Set up PostgreSQL for ResilienceLab E2E testing."""

import psycopg


def main():
    # Connect via TCP with trust auth
    conn = psycopg.connect("postgresql://postgres@127.0.0.1:5432/postgres")
    cur = conn.cursor()
    cur.execute("SELECT 1")
    print("TCP trust auth: works")

    # Create user
    cur.execute("SELECT rolname FROM pg_roles WHERE rolname = 'resiliencelab'")
    r = cur.fetchone()
    if r is None:
        cur.execute("CREATE USER resiliencelab WITH PASSWORD 'resiliencelab'")
        print("Created resiliencelab user")
    else:
        print("resiliencelab user exists")
        cur.execute("ALTER USER resiliencelab WITH PASSWORD 'resiliencelab'")
    conn.commit()

    # Create database
    conn.autocommit = True
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'resiliencelab'")
    db = cur.fetchone()
    if db is None:
        cur.execute("CREATE DATABASE resiliencelab OWNER resiliencelab")
        print("Created resiliencelab database")
    else:
        print("resiliencelab database already exists")
    conn.close()

    # Test TCP connection with credentials
    conn2 = psycopg.connect("postgresql://resiliencelab:resiliencelab@127.0.0.1:5432/resiliencelab")
    cur2 = conn2.cursor()
    cur2.execute("SELECT 1")
    print("TCP connection with credentials: works", cur2.fetchone())
    conn2.close()


if __name__ == "__main__":
    main()
