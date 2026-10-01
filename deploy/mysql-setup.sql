-- One-time MySQL setup for the Copilot. Run as MySQL root on the server,
-- after replacing both CHANGE_ME values with new passwords:
--   mysql -u root -p < deploy/mysql-setup.sql
-- Then put the same passwords in deploy/.env. Root credentials never go there.

CREATE DATABASE IF NOT EXISTS copilot_revive;

-- The app only reads. Declared for both localhost and 127.0.0.1: the
-- containers connect over TCP to 127.0.0.1.
CREATE USER IF NOT EXISTS 'copilot_app'@'localhost' IDENTIFIED BY 'CHANGE_ME_APP_PASSWORD';
CREATE USER IF NOT EXISTS 'copilot_app'@'127.0.0.1' IDENTIFIED BY 'CHANGE_ME_APP_PASSWORD';
GRANT SELECT ON copilot_revive.* TO 'copilot_app'@'localhost', 'copilot_app'@'127.0.0.1';

-- Setup and the scheduler create tables and replace synthetic data, in this database only.
CREATE USER IF NOT EXISTS 'copilot_loader'@'localhost' IDENTIFIED BY 'CHANGE_ME_LOADER_PASSWORD';
CREATE USER IF NOT EXISTS 'copilot_loader'@'127.0.0.1' IDENTIFIED BY 'CHANGE_ME_LOADER_PASSWORD';
GRANT ALL PRIVILEGES ON copilot_revive.* TO 'copilot_loader'@'localhost', 'copilot_loader'@'127.0.0.1';

FLUSH PRIVILEGES;
