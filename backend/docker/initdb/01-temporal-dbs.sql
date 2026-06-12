-- Pre-create Temporal's databases so auto-setup can run with SKIP_DB_CREATE=true.
-- Avoids a race in auto-setup's create-database step against a just-started Postgres.
-- (The app DB `orderpilot` is created by the image via POSTGRES_DB.)
CREATE DATABASE temporal;
CREATE DATABASE temporal_visibility;
