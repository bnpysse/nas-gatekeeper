use serde::Deserialize;
use std::fs;
use std::path::Path;

#[derive(Debug, Deserialize, Clone)]
pub struct Config {
    pub godaddy: Option<GodaddyConfig>,
    pub cloudflare: Option<CloudflareConfig>,
    pub ddns: DdnsConfig,
}

#[derive(Debug, Deserialize, Clone)]
pub struct GodaddyConfig {
    pub api_key: String,
    pub api_secret: String,
    pub domain: String,
}

#[derive(Debug, Deserialize, Clone)]
pub struct CloudflareConfig {
    pub api_token: String,
    pub domain: String,
    pub record_name: String,
}

#[derive(Debug, Deserialize, Clone)]
pub struct DdnsConfig {
    pub check_interval_secs: u64,
}

impl Config {
    pub fn load<P: AsRef<Path>>(path: P) -> Result<Self, String> {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if let Ok(metadata) = fs::metadata(&path) {
                let mode = metadata.permissions().mode();
                if mode & 0o0077 != 0 {
                    eprintln!(
                        "WARNING: Config file {:?} is readable by other users (permissions: {:o}). \
                        It is highly recommended to run `chmod 600 {:?}` to protect your API keys/tokens.",
                        path.as_ref(),
                        mode & 0o777,
                        path.as_ref()
                    );
                }
            }
        }

        let content = fs::read_to_string(&path)
            .map_err(|e| format!("Failed to read config file {}: {}", path.as_ref().display(), e))?;
        
        let config: Config = toml::from_str(&content)
            .map_err(|e| format!("Failed to parse TOML config: {}", e))?;
            
        if config.godaddy.is_none() && config.cloudflare.is_none() {
            return Err("At least one DDNS provider (godaddy or cloudflare) must be configured".into());
        }

        if let Some(ref gd) = config.godaddy {
            if gd.api_key.is_empty() {
                return Err("Missing or empty 'api_key' in GoDaddy config".into());
            }
            if gd.api_secret.is_empty() {
                return Err("Missing or empty 'api_secret' in GoDaddy config".into());
            }
            if gd.domain.is_empty() {
                return Err("Missing or empty 'domain' in GoDaddy config".into());
            }
        }

        if let Some(ref cf) = config.cloudflare {
            if cf.api_token.is_empty() {
                return Err("Missing or empty 'api_token' in Cloudflare config".into());
            }
            if cf.domain.is_empty() {
                return Err("Missing or empty 'domain' in Cloudflare config".into());
            }
            if cf.record_name.is_empty() {
                return Err("Missing or empty 'record_name' in Cloudflare config".into());
            }
        }
        
        Ok(config)
    }
}
