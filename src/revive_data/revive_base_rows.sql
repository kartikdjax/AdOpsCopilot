-- Revive's own base rows, which the synthetic loader deliberately never
-- writes: the Default manager, the administrator and manager accounts, an
-- `admin` user that can never log in, their account links, and the
-- application variables that report the Revive version and plugins.
-- Taken from a stock Revive 6.0.8 install; contact details are placeholders.

INSERT IGNORE INTO rv_accounts (account_id, account_type, account_name) VALUES
  (1, 'ADMIN', 'Administrator account'),
  (2, 'MANAGER', 'Default manager');

INSERT IGNORE INTO rv_agency (agencyid, name, contact, email, logout_url, updated, account_id, status) VALUES
  (1, 'Default manager', NULL, 'manager@example.com', NULL, UTC_TIMESTAMP(), 2, 0);

INSERT IGNORE INTO rv_users (user_id, contact_name, email_address, username, password, language,
                            default_account_id, comments, active, sso_user_id, date_created, date_last_login, email_updated) VALUES
  (1, 'Administrator', 'admin@example.com', 'admin', '!synthetic-no-login', 'en', 2, NULL, 1, NULL, UTC_TIMESTAMP(), NULL, UTC_TIMESTAMP());

INSERT IGNORE INTO rv_account_user_assoc (account_id, user_id, linked) VALUES
  (1, 1, UTC_TIMESTAMP()),
  (2, 1, UTC_TIMESTAMP());

INSERT IGNORE INTO rv_application_variable (name, value) VALUES
  ('admin_account_id', '1'),
  ('apVideoUI_version', '1.7.10'),
  ('apVideo_version', '1.7.10'),
  ('Client_version', '6.0.9'),
  ('Geo_version', '6.0.9'),
  ('oa_version', '6.0.8'),
  ('oxCacheFile_version', '1.5.8'),
  ('oxDeliveryDataPrepare_version', '1.5.1'),
  ('oxHtml_version', '1.6.7'),
  ('oxInvocationTags_version', '1.8.19'),
  ('oxLogClick_version', '1.5.1'),
  ('oxLogConversion_version', '1.5.1'),
  ('oxLogImpression_version', '1.5.1'),
  ('oxLogRequest_version', '1.5.1'),
  ('oxLogVast_version', '1.15.10'),
  ('oxMemcached_version', '1.5.8'),
  ('oxReportsAdmin_version', '1.6.11'),
  ('oxReportsStandard_version', '1.6.11'),
  ('oxText_version', '1.6.7'),
  ('rvMailerCustomDSN_version', '1.0.8'),
  ('rvMailerMailgun_version', '1.0.8'),
  ('rvMailerMandrill_version', '1.0.8'),
  ('rvMailerSendgrid_version', '1.0.8'),
  ('rvMailerSMTP_version', '1.0.8'),
  ('rvMaxMindGeoIP2Maintenance_version', '1.2.10'),
  ('rvMaxMindGeoIP2_version', '1.2.10'),
  ('Site_version', '6.0.9'),
  ('tables_apVideo', '006'),
  ('tables_core', '628'),
  ('tables_oxDeliveryDataPrepare', '002'),
  ('tables_vastbannertypehtml', '014'),
  ('Time_version', '6.0.9'),
  ('vastInlineBannerTypeHtml_version', '1.15.10'),
  ('vastOverlayBannerTypeHtml_version', '1.15.10'),
  ('vastServeVideoPlayer_version', '1.15.10'),
  ('videoReport_version', '1.15.10');
