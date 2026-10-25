-- Runs once, on the first start of an empty data volume.
-- POSTGRES_DB is `postgres`, so the three databases are created here.
CREATE DATABASE ihsp OWNER ihsp;
CREATE DATABASE ihsp_test OWNER ihsp;
CREATE DATABASE hydra OWNER ihsp;
