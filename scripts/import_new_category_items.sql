-- Imports all new category item lists in one run.
--
-- Usage (psql, from any directory):
--   \i c:/Users/Pc/Desktop/FLUTTER/forago_backend/scripts/import_new_category_items.sql
--
-- Each import runs in its own transaction; ON_ERROR_STOP aborts at the first failure.
-- Re-running is safe (idempotent).

\set ON_ERROR_STOP on
\set csv_dir 'C:/Users/Pc/Desktop/FLUTTER/forago/forago'
\set importer 'c:/Users/Pc/Desktop/FLUTTER/forago_backend/scripts/import_category_items_from_csv.sql'

\set category_slug 'herbs'
\set csv_path :csv_dir '/rastliny.csv'
\i :importer

\set category_slug 'birds'
\set csv_path :csv_dir '/vtaky.csv'
\i :importer

\set category_slug 'fish'
\set csv_path :csv_dir '/ryby.csv'
\i :importer

\set category_slug 'wildlife'
\set csv_path :csv_dir '/cicavce.csv'
\i :importer

\set category_slug 'wildlife'
\set csv_path :csv_dir '/zver_plazy_obojzivelniky.csv'
\i :importer

\set category_slug 'insects'
\set csv_path :csv_dir '/hmyz.csv'
\i :importer
