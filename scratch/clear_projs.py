import psycopg2, os
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()
cur.execute("DELETE FROM bug_projects WHERE name != 'The Fertile Crescent'")
conn.commit()
print("Deleted other projects")
