use actix_web::{get, web, HttpResponse, Responder};
use serde::Deserialize;
use std::fs::read_to_string;
use std::path::Path;

#[derive(Deserialize)]
pub struct LogRequest {
    pub base: String,
    pub log_name: String,
}

#[get("/api/logs")]
pub async fn get_log(info: web::Query<LogRequest>) -> impl Responder {
    // Path of build logs
    let file_path = format!("/home/arch/loong-status/build_logs/{}/{}.log", info.base, info.log_name);
    let path = Path::new(&file_path);

    match read_to_string(path) {
        Ok(content) => HttpResponse::Ok()
            .content_type("text/plain")
            .body(content),
        Err(e) => {
            eprintln!("Failed to read log file: {}. Error: {}", file_path, e);
            HttpResponse::NotFound().body("Log file not found.")
        }
    }
}
