import os
from sqlalchemy import create_engine, text
from qdrant_client import QdrantClient

client = QdrantClient(url=os.getenv('QDRANT_URL'), api_key=os.getenv('QDRANT_API_KEY'))
info = client.get_collection('sc_judgments')
print(f'Qdrant points: {info.points_count}')

engine = create_engine(os.getenv('DATABASE_URL').replace('+asyncpg', '+psycopg2'))
with engine.connect() as c:
    n = c.execute(text('SELECT COUNT(*) FROM ingested_judgments')).scalar()
    print(f'Supabase rows: {n}')
