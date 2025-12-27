# Database Migrations

This folder contains database migration scripts for schema changes.

## Running Migrations

### Apply Migration
```bash
python migrations/add_sub_topic_column.py
```

### Rollback Migration (if needed)
```bash
python migrations/add_sub_topic_column.py rollback
```

## Migration History

| Date | Script | Description | Status |
|------|--------|-------------|--------|
| 2025-12-27 | `add_sub_topic_column.py` | Adds sub_topic field to question_bank for granular analytics | ✅ Active |

## Creating New Migrations

1. Create a new Python file in this folder
2. Import `engine` from `database`
3. Implement `migrate()` and `rollback()` functions
4. Add entry to this README
5. Test thoroughly before committing

## Best Practices

- ✅ Always check if migration already applied (idempotent)
- ✅ Provide rollback capability when possible
- ✅ Test on development database first
- ✅ Document all schema changes
- ⚠️ SQLite has limited ALTER TABLE support (no DROP COLUMN)
