-- Revive Adserver 6.0.8 tables the Copilot reads or loads, as created by a
-- stock Revive 6.0.8 install (SHOW CREATE TABLE, structure only, no data).
-- Used by `python -m src.deploy.setup` to bootstrap an empty database.

CREATE TABLE IF NOT EXISTS `rv_account_user_assoc` (
  `account_id` mediumint NOT NULL,
  `user_id` mediumint NOT NULL,
  `linked` datetime NOT NULL,
  PRIMARY KEY (`account_id`,`user_id`),
  KEY `rv_account_user_assoc_user_id` (`user_id`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3;

CREATE TABLE IF NOT EXISTS `rv_accounts` (
  `account_id` mediumint NOT NULL AUTO_INCREMENT,
  `account_type` varchar(16) NOT NULL DEFAULT '',
  `account_name` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`account_id`),
  KEY `rv_accounts_account_type` (`account_type`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3;

CREATE TABLE IF NOT EXISTS `rv_acls` (
  `bannerid` mediumint NOT NULL DEFAULT '0',
  `logical` varchar(3) NOT NULL DEFAULT 'and',
  `type` varchar(255) NOT NULL DEFAULT '',
  `comparison` char(2) NOT NULL DEFAULT '==',
  `data` text NOT NULL,
  `executionorder` int unsigned NOT NULL DEFAULT '0',
  PRIMARY KEY (`bannerid`,`executionorder`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3;

CREATE TABLE IF NOT EXISTS `rv_ad_zone_assoc` (
  `ad_zone_assoc_id` mediumint NOT NULL AUTO_INCREMENT,
  `zone_id` mediumint DEFAULT NULL,
  `ad_id` mediumint DEFAULT NULL,
  `priority` double DEFAULT '0',
  `link_type` smallint NOT NULL DEFAULT '1',
  `priority_factor` double DEFAULT '0',
  `to_be_delivered` tinyint(1) NOT NULL DEFAULT '1',
  PRIMARY KEY (`ad_zone_assoc_id`),
  KEY `rv_ad_zone_assoc_zone_id` (`zone_id`),
  KEY `rv_ad_zone_assoc_ad_id` (`ad_id`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3;

CREATE TABLE IF NOT EXISTS `rv_affiliates` (
  `affiliateid` mediumint NOT NULL AUTO_INCREMENT,
  `agencyid` mediumint NOT NULL DEFAULT '0',
  `name` varchar(255) NOT NULL DEFAULT '',
  `mnemonic` varchar(5) NOT NULL DEFAULT '',
  `comments` text,
  `contact` varchar(255) DEFAULT NULL,
  `email` varchar(64) NOT NULL DEFAULT '',
  `website` varchar(255) DEFAULT NULL,
  `updated` datetime NOT NULL,
  `oac_country_code` char(2) NOT NULL DEFAULT '',
  `oac_language_id` int DEFAULT NULL,
  `oac_category_id` int DEFAULT NULL,
  `account_id` mediumint DEFAULT NULL,
  PRIMARY KEY (`affiliateid`),
  UNIQUE KEY `rv_affiliates_account_id` (`account_id`),
  KEY `rv_affiliates_agencyid` (`agencyid`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3;

CREATE TABLE IF NOT EXISTS `rv_agency` (
  `agencyid` mediumint NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL DEFAULT '',
  `contact` varchar(255) DEFAULT NULL,
  `email` varchar(64) NOT NULL DEFAULT '',
  `logout_url` varchar(255) DEFAULT NULL,
  `updated` datetime NOT NULL,
  `account_id` mediumint DEFAULT NULL,
  `status` smallint NOT NULL DEFAULT '0',
  PRIMARY KEY (`agencyid`),
  UNIQUE KEY `rv_agency_account_id` (`account_id`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3;

CREATE TABLE IF NOT EXISTS `rv_application_variable` (
  `name` varchar(250) NOT NULL DEFAULT '',
  `value` text NOT NULL,
  PRIMARY KEY (`name`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3;

CREATE TABLE IF NOT EXISTS `rv_audit` (
  `auditid` mediumint NOT NULL AUTO_INCREMENT,
  `actionid` mediumint NOT NULL,
  `context` varchar(200) NOT NULL DEFAULT '',
  `contextid` mediumint DEFAULT NULL,
  `parentid` mediumint DEFAULT NULL,
  `details` text NOT NULL,
  `userid` mediumint NOT NULL DEFAULT '0',
  `username` varchar(64) DEFAULT NULL,
  `usertype` tinyint NOT NULL DEFAULT '0',
  `updated` datetime DEFAULT NULL,
  `account_id` mediumint NOT NULL,
  `advertiser_account_id` mediumint DEFAULT NULL,
  `website_account_id` mediumint DEFAULT NULL,
  PRIMARY KEY (`auditid`),
  KEY `rv_audit_parentid_contextid` (`parentid`,`contextid`),
  KEY `rv_audit_updated` (`updated`),
  KEY `rv_audit_usertype` (`usertype`),
  KEY `rv_audit_username` (`username`),
  KEY `rv_audit_context_actionid` (`context`,`actionid`),
  KEY `rv_audit_account_id` (`account_id`),
  KEY `rv_audit_advertiser_account_id` (`advertiser_account_id`),
  KEY `rv_audit_website_account_id` (`website_account_id`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3;

CREATE TABLE IF NOT EXISTS `rv_banners` (
  `bannerid` mediumint NOT NULL AUTO_INCREMENT,
  `campaignid` mediumint NOT NULL DEFAULT '0',
  `contenttype` varchar(8) NOT NULL DEFAULT 'gif',
  `pluginversion` mediumint NOT NULL DEFAULT '0',
  `storagetype` varchar(16) NOT NULL DEFAULT 'sql',
  `filename` varchar(255) NOT NULL DEFAULT '',
  `imageurl` varchar(255) NOT NULL DEFAULT '',
  `htmltemplate` mediumtext NOT NULL,
  `htmlcache` mediumtext NOT NULL,
  `width` smallint NOT NULL DEFAULT '0',
  `height` smallint NOT NULL DEFAULT '0',
  `weight` tinyint NOT NULL DEFAULT '1',
  `seq` tinyint NOT NULL DEFAULT '0',
  `target` varchar(16) NOT NULL DEFAULT '',
  `url` text NOT NULL,
  `alt` varchar(255) NOT NULL DEFAULT '',
  `statustext` varchar(255) NOT NULL DEFAULT '',
  `bannertext` text NOT NULL,
  `description` varchar(255) NOT NULL DEFAULT '',
  `adserver` varchar(255) NOT NULL DEFAULT '',
  `block` int NOT NULL DEFAULT '0',
  `capping` int NOT NULL DEFAULT '0',
  `session_capping` int NOT NULL DEFAULT '0',
  `compiledlimitation` text NOT NULL,
  `acl_plugins` text,
  `append` text NOT NULL,
  `bannertype` tinyint NOT NULL DEFAULT '0',
  `alt_filename` varchar(255) NOT NULL DEFAULT '',
  `alt_imageurl` varchar(255) NOT NULL DEFAULT '',
  `alt_contenttype` varchar(8) NOT NULL DEFAULT 'gif',
  `comments` text,
  `updated` datetime NOT NULL,
  `acls_updated` datetime NOT NULL DEFAULT '0000-00-00 00:00:00',
  `keyword` varchar(255) NOT NULL DEFAULT '',
  `transparent` tinyint(1) NOT NULL DEFAULT '0',
  `parameters` text,
  `status` int NOT NULL DEFAULT '0',
  `ext_bannertype` varchar(255) DEFAULT NULL,
  `prepend` text NOT NULL,
  `iframe_friendly` tinyint(1) NOT NULL DEFAULT '1',
  PRIMARY KEY (`bannerid`),
  KEY `rv_banners_campaignid` (`campaignid`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3;

CREATE TABLE IF NOT EXISTS `rv_campaigns` (
  `campaignid` mediumint NOT NULL AUTO_INCREMENT,
  `campaignname` varchar(255) NOT NULL DEFAULT '',
  `clientid` mediumint NOT NULL DEFAULT '0',
  `views` int DEFAULT '-1',
  `clicks` int DEFAULT '-1',
  `conversions` int DEFAULT '-1',
  `priority` int NOT NULL DEFAULT '0',
  `weight` tinyint NOT NULL DEFAULT '1',
  `target_impression` int NOT NULL DEFAULT '0',
  `target_click` int NOT NULL DEFAULT '0',
  `target_conversion` int NOT NULL DEFAULT '0',
  `anonymous` enum('t','f') NOT NULL DEFAULT 'f',
  `companion` smallint DEFAULT '0',
  `comments` text,
  `revenue` decimal(10,4) DEFAULT NULL,
  `revenue_type` smallint DEFAULT NULL,
  `updated` datetime NOT NULL,
  `block` int NOT NULL DEFAULT '0',
  `capping` int NOT NULL DEFAULT '0',
  `session_capping` int NOT NULL DEFAULT '0',
  `status` int NOT NULL DEFAULT '0',
  `hosted_views` int NOT NULL DEFAULT '0',
  `hosted_clicks` int NOT NULL DEFAULT '0',
  `viewwindow` mediumint NOT NULL DEFAULT '0',
  `clickwindow` mediumint NOT NULL DEFAULT '0',
  `ecpm` decimal(10,4) DEFAULT NULL,
  `min_impressions` int NOT NULL DEFAULT '0',
  `ecpm_enabled` tinyint NOT NULL DEFAULT '0',
  `activate_time` datetime DEFAULT NULL,
  `expire_time` datetime DEFAULT NULL,
  `type` tinyint NOT NULL DEFAULT '0',
  `show_capped_no_cookie` tinyint NOT NULL DEFAULT '0',
  PRIMARY KEY (`campaignid`),
  KEY `rv_campaigns_clientid` (`clientid`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3;

CREATE TABLE IF NOT EXISTS `rv_clients` (
  `clientid` mediumint NOT NULL AUTO_INCREMENT,
  `agencyid` mediumint NOT NULL DEFAULT '0',
  `clientname` varchar(255) NOT NULL DEFAULT '',
  `contact` varchar(255) DEFAULT NULL,
  `email` varchar(64) NOT NULL DEFAULT '',
  `report` enum('t','f') NOT NULL DEFAULT 'f',
  `reportinterval` mediumint NOT NULL DEFAULT '7',
  `reportlastdate` date NOT NULL DEFAULT '0000-00-00',
  `reportdeactivate` enum('t','f') NOT NULL DEFAULT 'f',
  `comments` text,
  `updated` datetime NOT NULL,
  `account_id` mediumint DEFAULT NULL,
  `advertiser_limitation` tinyint(1) NOT NULL DEFAULT '0',
  `type` tinyint NOT NULL DEFAULT '0',
  PRIMARY KEY (`clientid`),
  UNIQUE KEY `rv_clients_account_id` (`account_id`),
  KEY `rv_clients_agencyid_type` (`agencyid`,`type`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3;

CREATE TABLE IF NOT EXISTS `rv_data_summary_ad_hourly` (
  `data_summary_ad_hourly_id` bigint NOT NULL AUTO_INCREMENT,
  `date_time` datetime NOT NULL,
  `ad_id` int unsigned NOT NULL,
  `creative_id` int unsigned NOT NULL,
  `zone_id` int unsigned NOT NULL,
  `requests` int unsigned NOT NULL DEFAULT '0',
  `impressions` int unsigned NOT NULL DEFAULT '0',
  `clicks` int unsigned NOT NULL DEFAULT '0',
  `conversions` int unsigned NOT NULL DEFAULT '0',
  `total_basket_value` decimal(10,4) DEFAULT NULL,
  `total_num_items` int DEFAULT NULL,
  `total_revenue` decimal(10,4) DEFAULT NULL,
  `total_cost` decimal(10,4) DEFAULT NULL,
  `total_techcost` decimal(10,4) DEFAULT NULL,
  `updated` datetime NOT NULL,
  PRIMARY KEY (`data_summary_ad_hourly_id`),
  KEY `rv_data_summary_ad_hourly_date_time` (`date_time`),
  KEY `rv_data_summary_ad_hourly_ad_id_date_time` (`ad_id`,`date_time`),
  KEY `rv_data_summary_ad_hourly_zone_id_date_time` (`zone_id`,`date_time`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3;

CREATE TABLE IF NOT EXISTS `rv_log_maintenance_priority` (
  `log_maintenance_priority_id` int NOT NULL AUTO_INCREMENT,
  `start_run` datetime NOT NULL,
  `end_run` datetime NOT NULL,
  `operation_interval` int NOT NULL,
  `duration` int NOT NULL,
  `run_type` tinyint unsigned NOT NULL,
  `updated_to` datetime DEFAULT NULL,
  PRIMARY KEY (`log_maintenance_priority_id`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3;

CREATE TABLE IF NOT EXISTS `rv_log_maintenance_statistics` (
  `log_maintenance_statistics_id` int NOT NULL AUTO_INCREMENT,
  `start_run` datetime NOT NULL,
  `end_run` datetime NOT NULL,
  `duration` int NOT NULL,
  `adserver_run_type` int DEFAULT NULL,
  `search_run_type` int DEFAULT NULL,
  `tracker_run_type` int DEFAULT NULL,
  `updated_to` datetime DEFAULT NULL,
  PRIMARY KEY (`log_maintenance_statistics_id`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3;

CREATE TABLE IF NOT EXISTS `rv_placement_zone_assoc` (
  `placement_zone_assoc_id` mediumint NOT NULL AUTO_INCREMENT,
  `zone_id` mediumint DEFAULT NULL,
  `placement_id` mediumint DEFAULT NULL,
  PRIMARY KEY (`placement_zone_assoc_id`),
  KEY `rv_placement_zone_assoc_zone_id` (`zone_id`),
  KEY `rv_placement_zone_assoc_placement_id` (`placement_id`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3;

CREATE TABLE IF NOT EXISTS `rv_users` (
  `user_id` mediumint NOT NULL AUTO_INCREMENT,
  `contact_name` varchar(255) NOT NULL DEFAULT '',
  `email_address` varchar(64) NOT NULL DEFAULT '',
  `username` varchar(64) NOT NULL DEFAULT '',
  `password` varchar(64) NOT NULL DEFAULT '',
  `language` varchar(5) DEFAULT NULL,
  `default_account_id` mediumint DEFAULT NULL,
  `comments` text,
  `active` tinyint(1) NOT NULL DEFAULT '1',
  `sso_user_id` int DEFAULT NULL,
  `date_created` datetime DEFAULT NULL,
  `date_last_login` datetime DEFAULT NULL,
  `email_updated` datetime DEFAULT NULL,
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `rv_users_username` (`username`),
  UNIQUE KEY `rv_users_sso_user_id` (`sso_user_id`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3;

CREATE TABLE IF NOT EXISTS `rv_zones` (
  `zoneid` mediumint NOT NULL AUTO_INCREMENT,
  `affiliateid` mediumint DEFAULT NULL,
  `zonename` varchar(245) NOT NULL DEFAULT '',
  `description` varchar(255) NOT NULL DEFAULT '',
  `delivery` smallint NOT NULL DEFAULT '0',
  `zonetype` smallint NOT NULL DEFAULT '0',
  `category` text NOT NULL,
  `width` smallint NOT NULL DEFAULT '0',
  `height` smallint NOT NULL DEFAULT '0',
  `ad_selection` text NOT NULL,
  `chain` text NOT NULL,
  `prepend` text NOT NULL,
  `append` text NOT NULL,
  `appendtype` tinyint NOT NULL DEFAULT '0',
  `forceappend` enum('t','f') DEFAULT 'f',
  `inventory_forecast_type` smallint NOT NULL DEFAULT '0',
  `comments` text,
  `cost` decimal(10,4) DEFAULT NULL,
  `cost_type` smallint DEFAULT NULL,
  `cost_variable_id` varchar(255) DEFAULT NULL,
  `technology_cost` decimal(10,4) DEFAULT NULL,
  `technology_cost_type` smallint DEFAULT NULL,
  `updated` datetime NOT NULL,
  `block` int NOT NULL DEFAULT '0',
  `capping` int NOT NULL DEFAULT '0',
  `session_capping` int NOT NULL DEFAULT '0',
  `what` text NOT NULL,
  `rate` decimal(19,2) DEFAULT NULL,
  `pricing` varchar(50) NOT NULL DEFAULT 'CPM',
  `oac_category_id` int DEFAULT NULL,
  `ext_adselection` varchar(255) DEFAULT NULL,
  `show_capped_no_cookie` tinyint NOT NULL DEFAULT '0',
  PRIMARY KEY (`zoneid`),
  KEY `rv_zones_zonenameid` (`zonename`,`zoneid`),
  KEY `rv_zones_affiliateid` (`affiliateid`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8mb3;
