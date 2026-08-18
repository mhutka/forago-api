-- Derive the canonical half-month period for legacy records that predate period assignment.

UPDATE finds
SET period = CONCAT(
    CASE EXTRACT(MONTH FROM date)::INTEGER
        WHEN 1 THEN 'JAN'
        WHEN 2 THEN 'FEB'
        WHEN 3 THEN 'MAR'
        WHEN 4 THEN 'APR'
        WHEN 5 THEN 'MAY'
        WHEN 6 THEN 'JUN'
        WHEN 7 THEN 'JUL'
        WHEN 8 THEN 'AUG'
        WHEN 9 THEN 'SEP'
        WHEN 10 THEN 'OCT'
        WHEN 11 THEN 'NOV'
        WHEN 12 THEN 'DEC'
    END,
    CASE WHEN EXTRACT(DAY FROM date)::INTEGER <= 15 THEN '_1' ELSE '_2' END
)
WHERE period IS NULL;