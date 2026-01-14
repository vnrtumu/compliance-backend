from app.core.db import SessionLocal, engine
from app.models.upload import Upload
from sqlalchemy import inspect

def test_db():
    try:
        # Check connection
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print(f"Tables in DB: {tables}")

        if "uploads" not in tables:
            print("Error: 'uploads' table does not exist!")
            return

        db = SessionLocal()
        try:
            uploads = db.query(Upload).all()
            print(f"Found {len(uploads)} uploads in database.")
            for u in uploads:
                print(f" - {u.filename} ({u.id})")
        except Exception as e:
            print(f"Error querying database: {e}")
        finally:
            db.close()
    except Exception as e:
        print(f"Error connecting to database: {e}")

if __name__ == "__main__":
    test_db()
