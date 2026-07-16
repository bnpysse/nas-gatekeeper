use http_body_util::Empty;
use hyper::body::Bytes;
use hyper::{Request, Method};
use hyper::client::conn::http1;
use tokio::net::UnixStream;
use crate::tokio_io::TokioIo;

pub async fn handshake_socket(socket_path: &str) -> Result<(), String> {
    let stream = UnixStream::connect(socket_path).await
        .map_err(|e| format!("Failed to connect to Podman socket at {}: {}", socket_path, e))?;
    
    let io = TokioIo(stream);
    
    let (mut sender, conn) = http1::Builder::new()
        .handshake(io)
        .await
        .map_err(|e| format!("Hyper handshake failed: {}", e))?;

    tokio::spawn(async move {
        if let Err(err) = conn.await {
            eprintln!("Podman connection failed: {:?}", err);
        }
    });

    let req = Request::builder()
        .method(Method::GET)
        .uri("http://localhost/libpod/info")
        .header("Host", "localhost")
        .body(Empty::<Bytes>::new())
        .map_err(|e| format!("Failed to build request: {}", e))?;

    let res = sender.send_request(req).await
        .map_err(|e| format!("Failed to send request: {}", e))?;

    if res.status().is_success() {
        Ok(())
    } else {
        Err(format!("Podman API returned status: {}", res.status()))
    }
}
