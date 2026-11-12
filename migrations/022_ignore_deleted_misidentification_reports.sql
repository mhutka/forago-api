DROP INDEX IF EXISTS ux_find_comments_one_report_per_user;

CREATE UNIQUE INDEX ux_find_comments_one_report_per_user
    ON find_comments(find_id, user_id)
    WHERE is_misidentification_report = TRUE
      AND deleted = FALSE;
