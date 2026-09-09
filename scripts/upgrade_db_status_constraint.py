import sqlite3

def upgrade():
    conn = sqlite3.connect('greenshift.db')
    cursor = conn.cursor()
    cursor.execute('PRAGMA foreign_keys=OFF;')
    cursor.execute('BEGIN TRANSACTION;')

    sql = cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()[0]
    old_constraint = "CHECK (status IN ('SUBMITTED', 'SCHEDULED', 'PENDING_APPROVAL', 'APPROVED', 'DECLINED', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED'))"
    new_constraint = "CHECK (status IN ('SUBMITTED', 'VALIDATED', 'SCHEDULED', 'PENDING_APPROVAL', 'APPROVED', 'DECLINED', 'REJECTED', 'QUEUED', 'DISPATCHING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED'))"
    
    if old_constraint in sql:
        new_sql = sql.replace(old_constraint, new_constraint)
        new_sql = new_sql.replace('CREATE TABLE "jobs"', 'CREATE TABLE "jobs_new"')
        cursor.execute(new_sql)
        cursor.execute('INSERT INTO jobs_new SELECT * FROM jobs;')
        cursor.execute('DROP TABLE jobs;')
        cursor.execute('ALTER TABLE jobs_new RENAME TO jobs;')

        # Recreate indexes
        cursor.execute('CREATE INDEX IF NOT EXISTS ix_jobs_team_status ON jobs (team_id, status);')
        cursor.execute('CREATE INDEX IF NOT EXISTS ix_jobs_status_created ON jobs (status, created_at);')
        cursor.execute('CREATE INDEX IF NOT EXISTS ix_jobs_submitted_at ON jobs (submitted_at);')
        cursor.execute('CREATE INDEX IF NOT EXISTS ix_jobs_deadline ON jobs (deadline);')
        cursor.execute('CREATE INDEX IF NOT EXISTS ix_jobs_region ON jobs (region);')
        cursor.execute('CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs (status);')
        cursor.execute('CREATE INDEX IF NOT EXISTS ix_jobs_team_id ON jobs (team_id);')

        conn.commit()
        print('Successfully upgraded SQLite jobs table constraint!')
    else:
        print('Constraint already updated or not found!')

    cursor.execute('PRAGMA foreign_keys=ON;')
    conn.close()

if __name__ == '__main__':
    upgrade()
