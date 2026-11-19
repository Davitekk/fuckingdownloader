use super::*;
use std::io::{Read, Write};

#[test]
fn downloads_a_local_fixture_with_yt_dlp() {
    if std::env::var_os("FDL_TEST_YTDLP").is_none() {
        return;
    }
    let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
    let addr = listener.local_addr().unwrap();
    let media = std::env::var_os("FDL_TEST_YTDLP").unwrap();
    let bytes = std::fs::read(media).unwrap();
    std::thread::spawn(move || {
        for stream in listener.incoming().flatten() {
            let mut stream = stream;
            let mut request = [0; 8192];
            let size = stream.read(&mut request).unwrap();
            write!(stream, "HTTP/1.1 200 OK\r\nContent-Type: video/mp4\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", bytes.len()).unwrap();
            if !request[..size].starts_with(b"HEAD ") {
                let _ = stream.write_all(&bytes);
            }
        }
    });
    let root = tempfile::tempdir().unwrap();
    let request = Request {
        url: parse_link(&format!("http://{addr}/sample.mp4")).unwrap(),
        folder: root.path().to_owned(),
        cookies: None,
        mode: Mode::Video,
        format: "mp4".into(),
        height: "Best".into(),
        bitrate: "Best".into(),
        playlist: false,
        range: String::new(),
        subtitles: false,
        sponsorblock: false,
        preview: false,
        login_test: false,
        forced: None,
    };
    let (tx, rx) = std::sync::mpsc::channel();
    let result = request.execute(&tx, &AtomicBool::new(false));
    if let Err(error) = result {
        let log: Vec<_> = rx
            .try_iter()
            .filter_map(|event| match event {
                Event::Line(line) => Some(line),
                _ => None,
            })
            .collect();
        panic!("{error}\n{}", log.join("\n"));
    }
    let job = std::fs::read_dir(root.path())
        .unwrap()
        .next()
        .unwrap()
        .unwrap();
    assert!(
        std::fs::read_dir(job.path())
            .unwrap()
            .flatten()
            .any(
                |file| file.path().extension().is_some_and(|ext| ext == "mp4")
                    && file.metadata().unwrap().len() > 0
            )
    );
}

#[test]
fn validates_url_scheme_and_domain_boundaries() {
    assert!(parse_link("file:///C:/media.mp4").is_err());
    assert!(parse_link("https://user:pass@tiktok.com/video").is_err());
    assert!(belongs("vm.tiktok.com", "tiktok.com"));
    assert!(!belongs("not-tiktok.com", "tiktok.com"));
    assert!(!belongs("tiktok.com.example.org", "tiktok.com"));
}
