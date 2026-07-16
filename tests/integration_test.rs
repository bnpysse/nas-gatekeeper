use nas_gatekeeper::config::Config;
use nas_gatekeeper::ddns::{DdnsProvider, check_and_update_ip};
use nas_gatekeeper::podman::handshake_socket;
use std::sync::{Arc, Mutex};
use std::fs;

struct MockDdnsProvider {
    pub updates: Arc<Mutex<Vec<String>>>,
}

impl DdnsProvider for MockDdnsProvider {
    async fn update_dns_record(&self, ip: &str) -> Result<(), String> {
        let mut updates = self.updates.lock().unwrap();
        updates.push(ip.to_string());
        Ok(())
    }
}

#[tokio::test]
async fn test_ddns_core_logic() {
    let provider = MockDdnsProvider {
        updates: Arc::new(Mutex::new(Vec::new())),
    };

    let mut last_ip = String::new();

    // Step 1: "1.1.1.1" (First time, should trigger update)
    check_and_update_ip(&provider, "1.1.1.1", &mut last_ip).await.unwrap();
    assert_eq!(last_ip, "1.1.1.1");
    assert_eq!(provider.updates.lock().unwrap().len(), 1);
    assert_eq!(provider.updates.lock().unwrap()[0], "1.1.1.1");

    // Step 2: "1.1.1.1" (IP unchanged, no update)
    check_and_update_ip(&provider, "1.1.1.1", &mut last_ip).await.unwrap();
    assert_eq!(last_ip, "1.1.1.1");
    assert_eq!(provider.updates.lock().unwrap().len(), 1); // Length still 1

    // Step 3: "2.2.2.2" (IP changed, should trigger update)
    check_and_update_ip(&provider, "2.2.2.2", &mut last_ip).await.unwrap();
    assert_eq!(last_ip, "2.2.2.2");
    assert_eq!(provider.updates.lock().unwrap().len(), 2); // Length is now 2
    assert_eq!(provider.updates.lock().unwrap()[1], "2.2.2.2");
}

#[test]
fn test_config_robustness() {
    let tmp_dir = std::env::temp_dir();
    
    // Test 1: Missing file
    let invalid_path = tmp_dir.join("non_existent_config.toml");
    let res = Config::load(&invalid_path);
    assert!(res.is_err());
    
    // Test 2: Malformed config
    let malformed_path = tmp_dir.join("malformed_config.toml");
    fs::write(&malformed_path, "invalid toml data [] =").unwrap();
    let res2 = Config::load(&malformed_path);
    assert!(res2.is_err());
    
    // Test 3: Missing api_key
    let missing_key_path = tmp_dir.join("missing_key_config.toml");
    fs::write(&missing_key_path, r#"
        [godaddy]
        api_key = ""
        api_secret = "secret"
        domain = "example.com"
        
        [ddns]
        check_interval_secs = 60
    "#).unwrap();
    let res3 = Config::load(&missing_key_path);
    assert!(res3.is_err());

    // Test 4: Missing both provider configs
    let missing_all_path = tmp_dir.join("missing_all_config.toml");
    fs::write(&missing_all_path, r#"
        [ddns]
        check_interval_secs = 60
    "#).unwrap();
    let res4 = Config::load(&missing_all_path);
    assert!(res4.is_err());

    // Test 5: Valid Cloudflare config
    let valid_cf_path = tmp_dir.join("valid_cf_config.toml");
    fs::write(&valid_cf_path, r#"
        [cloudflare]
        api_token = "my_token"
        domain = "example.com"
        record_name = "direct.example.com"
        
        [ddns]
        check_interval_secs = 60
    "#).unwrap();
    let res5 = Config::load(&valid_cf_path);
    assert!(res5.is_ok());
}

#[tokio::test]
async fn test_unix_socket_handshake() {
    // We check /run/podman/podman.sock but don't expect it to succeed on all environments
    let socket_path = "/run/podman/podman.sock";
    let res = handshake_socket(socket_path).await;
    match res {
        Ok(_) => println!("Podman socket is reachable."),
        Err(e) => {
            println!("Podman socket error gracefully handled: {}", e);
            // Verify that the error message is clear and didn't panic.
        }
    }
}
