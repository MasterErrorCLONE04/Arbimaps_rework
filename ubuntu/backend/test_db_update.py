import psycopg2
from core.db.connection import get_db_params

def main():
    params = get_db_params()
    params['dbname'] = 'neiva'
    conn = psycopg2.connect(**params)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE arbimaps_app.users SET password_hash = %s",
                ("pbkdf2_sha256$100000$741bcb3eb2b9248bc31fcd7cd57a905c$0fe6f6281384e299886cbd97a3a7d5fab8c8199d0585f6cd5f3dfb151e05a9ad",)
            )
            print("Updated rows:", cur.rowcount)
        conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    main()
