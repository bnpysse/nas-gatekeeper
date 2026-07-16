use nas_gatekeeper::config::Config;
use nas_gatekeeper::ddns::{DdnsClient, CloudflareClient, fetch_public_ip, check_and_update_ip};
use nas_gatekeeper::podman;
use std::time::Duration;
use tokio::time;
use tokio::signal;

#[tokio::main]
async fn main() {
    let config_path = "/etc/nas-gatekeeper/config.toml";
    let config = match Config::load(config_path) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("Configuration error: {}", e);
            std::process::exit(1);
        }
    };

    let socket_path = "/run/podman/podman.sock";
    if let Err(e) = podman::handshake_socket(socket_path).await {
        eprintln!("Podman socket handshake failed: {}. Please ensure the Podman service is running and you have proper permissions.", e);
    } else {
        println!("Successfully connected to Podman socket at {}", socket_path);
    }

    let mut godaddy_client = None;
    if let Some(gd) = config.godaddy {
        println!("Initializing GoDaddy DDNS client for domain: {}", gd.domain);
        godaddy_client = Some((
            DdnsClient::new(gd.api_key, gd.api_secret, gd.domain),
            String::new(),
        ));
    }

    let mut cloudflare_client = None;
    if let Some(cf) = config.cloudflare {
        println!("Initializing Cloudflare DDNS client for domain: {} (record: {})", cf.domain, cf.record_name);
        cloudflare_client = Some((
            CloudflareClient::new(cf.api_token, cf.domain, cf.record_name),
            String::new(),
        ));
    }

    println!("Starting DDNS loop...");
    let http_client = reqwest::Client::new();
    let mut interval = time::interval(Duration::from_secs(config.ddns.check_interval_secs));
    let mut ctrl_c = std::pin::pin!(signal::ctrl_c());
    
    loop {
        tokio::select! {
            _ = interval.tick() => {
                match fetch_public_ip(&http_client).await {
                    Ok(ip) => {
                        if let Some((ref client, ref mut last_ip)) = godaddy_client {
                            let _ = check_and_update_ip(client, &ip, last_ip).await;
                        }
                        if let Some((ref client, ref mut last_ip)) = cloudflare_client {
                            let _ = check_and_update_ip(client, &ip, last_ip).await;
                        }
                    }
                    Err(e) => {
                        eprintln!("Failed to fetch public IP: {}", e);
                    }
                }
            }
            res = &mut ctrl_c => {
                if let Err(e) = res {
                    eprintln!("Failed to listen for Ctrl+C: {}", e);
                }
                println!("Graceful shutdown initiated...");
                break;
            }
        }
    }
}
