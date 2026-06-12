import os
import ssl
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool
from dotenv import load_dotenv

load_dotenv()

raw_db_url = os.environ.get("DATABASE_URL")

if not raw_db_url:
    print("\n❌ Error: DATABASE_URL environment variable is not set!")
    print("Please set it in your environment or create a '.env' file containing:")
    print("DATABASE_URL=your_neon_connection_string_here\n")
    exit(1)

raw_db_url = raw_db_url.strip()
print(f"Testing DATABASE_URL connection...")
print(f"Original length: {len(raw_db_url)}")

try:
    url_obj = make_url(raw_db_url)
    print(f"Parsed Host: {url_obj.host}")
    print(f"Parsed Username: {url_obj.username}")
    print(f"Parsed DB Name: {url_obj.database}")
    print(f"Password length: {len(url_obj.password or '')}")
    
    # Process for pg8000
    url_obj = url_obj.set(drivername="postgresql+pg8000")
    url_obj = url_obj.set(query={})
    db_url = str(url_obj)
    
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    
    engine = create_engine(
        db_url,
        poolclass=NullPool,
        connect_args={
            "ssl_context": ssl_ctx,
        }
    )
    
    print("\nConnecting to database...")
    with engine.connect() as conn:
        res = conn.execute(text("SELECT 1")).scalar()
        if res == 1:
            print("\n✅ Success! Database connected successfully using pg8000.")
        else:
            print(f"\n⚠️ Connected but query returned unexpected value: {res}")
            
except Exception as e:
    print("\n❌ Connection Failed!")
    print(f"Error Details: {e}")
    print("\nCommon Troubleshooting:")
    print("1. If it says 'password authentication failed', your database password or username is incorrect.")
    print("2. Make sure you copied the connection string correctly from the Neon Console.")
    print("3. Check if your password contains special characters that might need URL-encoding (e.g. '@' becomes '%40', '#' becomes '%23').")
    print("4. Try using the Direct connection string (without '-pooler' in the host name) to verify.")
