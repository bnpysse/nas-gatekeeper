use reqwest::Client;
use serde_json::json;

#[allow(async_fn_in_trait)]
pub trait DdnsProvider {
    async fn update_dns_record(&self, ip: &str) -> Result<(), String>;
}

pub async fn fetch_public_ip(client: &Client) -> Result<String, String> {
    let resp = client.get("https://api64.ipify.org")
        .send()
        .await
        .map_err(|e| format!("Failed to fetch IP: {}", e))?;
        
    let ip = resp.text().await.map_err(|e| format!("Failed to read IP response: {}", e))?;
    Ok(ip.trim().to_string())
}

pub struct DdnsClient {
    client: Client,
    godaddy_key: String,
    godaddy_secret: String,
    domain: String,
}

impl DdnsClient {
    pub fn new(godaddy_key: String, godaddy_secret: String, domain: String) -> Self {
        Self {
            client: Client::new(),
            godaddy_key,
            godaddy_secret,
            domain,
        }
    }
}

impl DdnsProvider for DdnsClient {

    async fn update_dns_record(&self, ip: &str) -> Result<(), String> {
        let url = format!("https://api.godaddy.com/v1/domains/{}/records/A/%2A", self.domain);
        
        let payload = json!([
            {
                "data": ip,
                "ttl": 600
            }
        ]);

        let resp = self.client.put(&url)
            .header("Authorization", format!("sso-key {}:{}", self.godaddy_key, self.godaddy_secret))
            .json(&payload)
            .send()
            .await
            .map_err(|e| format!("GoDaddy API request failed: {}", e))?;

        if resp.status().is_success() {
            Ok(())
        } else {
            let error_text = resp.text().await.unwrap_or_default();
            Err(format!("GoDaddy API returned error: {}", error_text))
        }
    }
}

pub struct CloudflareClient {
    client: Client,
    api_token: String,
    domain: String,
    record_name: String,
}

impl CloudflareClient {
    pub fn new(api_token: String, domain: String, record_name: String) -> Self {
        Self {
            client: Client::new(),
            api_token,
            domain,
            record_name,
        }
    }

    async fn get_zone_id(&self) -> Result<String, String> {
        let url = format!("https://api.cloudflare.com/client/v4/zones?name={}", self.domain);
        let resp = self.client.get(&url)
            .header("Authorization", format!("Bearer {}", self.api_token))
            .send()
            .await
            .map_err(|e| format!("Cloudflare list zones request failed: {}", e))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let error_text = resp.text().await.unwrap_or_default();
            return Err(format!("Cloudflare returned status {} on list zones: {}", status, error_text));
        }

        let json_body: serde_json::Value = resp.json()
            .await
            .map_err(|e| format!("Failed to parse Cloudflare zone list JSON: {}", e))?;

        let zones = json_body["result"].as_array()
            .ok_or_else(|| "Cloudflare result is not an array".to_string())?;

        if zones.is_empty() {
            return Err(format!("No zone found for domain: {}", self.domain));
        }

        let zone_id = zones[0]["id"].as_str()
            .ok_or_else(|| "Zone ID is not a string".to_string())?;

        Ok(zone_id.to_string())
    }

    async fn get_record_id(&self, zone_id: &str) -> Result<Option<String>, String> {
        let url = format!(
            "https://api.cloudflare.com/client/v4/zones/{}/dns_records?name={}&type=A",
            zone_id, self.record_name
        );
        let resp = self.client.get(&url)
            .header("Authorization", format!("Bearer {}", self.api_token))
            .send()
            .await
            .map_err(|e| format!("Cloudflare list DNS records request failed: {}", e))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let error_text = resp.text().await.unwrap_or_default();
            return Err(format!("Cloudflare returned status {} on list records: {}", status, error_text));
        }

        let json_body: serde_json::Value = resp.json()
            .await
            .map_err(|e| format!("Failed to parse Cloudflare DNS records list JSON: {}", e))?;

        let records = json_body["result"].as_array()
            .ok_or_else(|| "Cloudflare records result is not an array".to_string())?;

        if records.is_empty() {
            Ok(None)
        } else {
            let record_id = records[0]["id"].as_str()
                .ok_or_else(|| "Record ID is not a string".to_string())?;
            Ok(Some(record_id.to_string()))
        }
    }
}

impl DdnsProvider for CloudflareClient {

    async fn update_dns_record(&self, ip: &str) -> Result<(), String> {
        let zone_id = self.get_zone_id().await?;
        let record_id_opt = self.get_record_id(&zone_id).await?;

        let payload = json!({
            "type": "A",
            "name": self.record_name,
            "content": ip,
            "ttl": 60,
            "proxied": false
        });

        let (url, method) = match record_id_opt {
            Some(ref record_id) => (
                format!("https://api.cloudflare.com/client/v4/zones/{}/dns_records/{}", zone_id, record_id),
                reqwest::Method::PUT
            ),
            None => (
                format!("https://api.cloudflare.com/client/v4/zones/{}/dns_records", zone_id),
                reqwest::Method::POST
            )
        };

        let resp = self.client.request(method, &url)
            .header("Authorization", format!("Bearer {}", self.api_token))
            .json(&payload)
            .send()
            .await
            .map_err(|e| format!("Cloudflare update DNS record request failed: {}", e))?;

        if resp.status().is_success() {
            Ok(())
        } else {
            let error_text = resp.text().await.unwrap_or_default();
            Err(format!("Cloudflare API returned error: {}", error_text))
        }
    }
}

pub async fn check_and_update_ip<P: DdnsProvider>(provider: &P, ip: &str, last_ip: &mut String) -> Result<(), String> {
    if ip != *last_ip {
        println!("IP changed from {} to {}", last_ip, ip);
        match provider.update_dns_record(ip).await {
            Ok(_) => {
                println!("DNS record updated successfully.");
                *last_ip = ip.to_string();
                Ok(())
            }
            Err(e) => {
                eprintln!("Failed to update DNS: {}", e);
                Err(e)
            }
        }
    } else {
        println!("IP has not changed: {}", ip);
        Ok(())
    }
}
