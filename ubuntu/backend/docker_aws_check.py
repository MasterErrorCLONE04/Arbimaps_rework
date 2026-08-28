import psycopg2, os, sys

print("=== DIRECT TEST OF AWS RDS REMOTE ENDPOINT ===")
aws_host = 'arbimapps.c3c0imwimaws.us-east-2.rds.amazonaws.com'
aws_db = 'programacion'

credentials = [
    ('ArbitriumSAS', 'Ru6T9s4yN5z!2026'),
    ('postgres', 'Arbitrium2026_test_pwd'),
    ('postgres', 'Arbitrium2026!'),
    ('ArbitriumSAS', 'Arbitrium2026!')
]

for user, pwd in credentials:
    print(f"\nAttempting AWS connection with User: '{user}'...")
    for ssl_mode in ['require', 'prefer']:
        try:
            conn = psycopg2.connect(
                host=aws_host,
                port=5432,
                dbname=aws_db,
                user=user,
                password=pwd,
                sslmode=ssl_mode,
                connect_timeout=5
            )
            cur = conn.cursor()
            cur.execute("SELECT version();")
            ver = cur.fetchone()[0]
            print(f"SUCCESS! AWS RDS Connected with user='{user}' and sslmode='{ssl_mode}'!")
            print("AWS PostgreSQL Version:", ver[:70])
            cur.close()
            conn.close()
            sys.exit(0)
        except Exception as e:
            print(f"Failed (ssl={ssl_mode}): {repr(e)}")
