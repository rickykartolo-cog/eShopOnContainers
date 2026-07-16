-- Deterministic SQL Server schema dump for contract freezing.
-- Run with: sqlcmd -d <Database> -i sql_schema_dump.sql -W -s "|" -h -1
SET NOCOUNT ON;

PRINT '== COLUMNS ==';
SELECT
    s.name + '.' + t.name AS [table],
    c.name AS [column],
    ty.name AS [type],
    c.max_length,
    c.precision,
    c.scale,
    c.is_nullable,
    c.is_identity,
    ISNULL(OBJECT_DEFINITION(c.default_object_id), '') AS default_definition
FROM sys.columns c
JOIN sys.tables t ON t.object_id = c.object_id
JOIN sys.schemas s ON s.schema_id = t.schema_id
JOIN sys.types ty ON ty.user_type_id = c.user_type_id
ORDER BY s.name, t.name, c.column_id;

PRINT '== PRIMARY KEYS AND UNIQUE CONSTRAINTS ==';
SELECT
    s.name + '.' + t.name AS [table],
    kc.name AS constraint_name,
    kc.type_desc,
    c.name AS [column],
    ic.key_ordinal
FROM sys.key_constraints kc
JOIN sys.tables t ON t.object_id = kc.parent_object_id
JOIN sys.schemas s ON s.schema_id = t.schema_id
JOIN sys.index_columns ic ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
ORDER BY s.name, t.name, kc.name, ic.key_ordinal;

PRINT '== INDEXES ==';
SELECT
    s.name + '.' + t.name AS [table],
    i.name AS index_name,
    i.type_desc,
    i.is_unique,
    c.name AS [column],
    ic.key_ordinal,
    ic.is_included_column
FROM sys.indexes i
JOIN sys.tables t ON t.object_id = i.object_id
JOIN sys.schemas s ON s.schema_id = t.schema_id
JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
WHERE i.name IS NOT NULL
ORDER BY s.name, t.name, i.name, ic.key_ordinal;

PRINT '== FOREIGN KEYS ==';
SELECT
    fk.name AS fk_name,
    sp.name + '.' + tp.name AS parent_table,
    cp.name AS parent_column,
    sr.name + '.' + tr.name AS referenced_table,
    cr.name AS referenced_column,
    fk.delete_referential_action_desc,
    fk.update_referential_action_desc
FROM sys.foreign_keys fk
JOIN sys.tables tp ON tp.object_id = fk.parent_object_id
JOIN sys.schemas sp ON sp.schema_id = tp.schema_id
JOIN sys.tables tr ON tr.object_id = fk.referenced_object_id
JOIN sys.schemas sr ON sr.schema_id = tr.schema_id
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.columns cp ON cp.object_id = fkc.parent_object_id AND cp.column_id = fkc.parent_column_id
JOIN sys.columns cr ON cr.object_id = fkc.referenced_object_id AND cr.column_id = fkc.referenced_column_id
ORDER BY fk.name, fkc.constraint_column_id;

PRINT '== CHECK AND DEFAULT CONSTRAINTS ==';
SELECT
    s.name + '.' + t.name AS [table],
    cc.name AS constraint_name,
    'CHECK' AS constraint_type,
    cc.definition
FROM sys.check_constraints cc
JOIN sys.tables t ON t.object_id = cc.parent_object_id
JOIN sys.schemas s ON s.schema_id = t.schema_id
ORDER BY s.name, t.name, cc.name;

PRINT '== SEQUENCES (incl. HiLo) ==';
SELECT
    s.name + '.' + seq.name AS [sequence],
    CAST(seq.start_value AS bigint) AS start_value,
    CAST(seq.increment AS bigint) AS increment,
    CAST(seq.minimum_value AS bigint) AS minimum_value,
    seq.is_cycling,
    ty.name AS [type]
FROM sys.sequences seq
JOIN sys.schemas s ON s.schema_id = seq.schema_id
JOIN sys.types ty ON ty.user_type_id = seq.user_type_id
ORDER BY s.name, seq.name;
