use actix_web::{get, web, App, HttpResponse, HttpServer, Responder};
use dotenv::dotenv;
use serde::{Serialize, Deserialize};
use sqlx::{postgres::PgPoolOptions, FromRow, Row};
use chrono::NaiveDateTime;
use std::fs::read_to_string;
use std::path::Path;

#[derive(Serialize, Debug, FromRow)]
struct Package {
    total_count: i64,
    name: String,
    base: String,
    repo: String,
    flags: Option<i32>,
    x86_version: Option<String>,
    x86_testing_version: Option<String>,
    x86_staging_version: Option<String>,
    loong_version: Option<String>,
    loong_testing_version: Option<String>,
    loong_staging_version: Option<String>,
}

#[derive(Serialize)]
struct LastUpdate {
    last_update: String,
}

#[derive(Serialize, Deserialize)]
struct QueryParams {
    page: Option<u32>,
    per_page: Option<u32>,
    name: Option<String>,
    error_type: Option<u32>,
    repo: Option<String>,
}

#[derive(Serialize, Debug, FromRow)]
struct CountResponse {
    core_match: i64,
    extra_match: i64,
    core_mismatch: i64,
    extra_mismatch: i64,
    core_total: i64,
    extra_total: i64,
}

#[derive(Deserialize)]
struct TaskParams {
    taskid: Option<i32>,
}

#[derive(Serialize, Debug, FromRow)]
struct Task {
    pkgbase: String,
    repo: i32,
    build_result: Option<String>,
    build_time: Option<String>,
}

#[derive(Deserialize)]
struct LogRequest {
    base: String,
    log_name: String
}

#[get("/api/tasks/result")]
async fn get_tasks(pool: web::Data<sqlx::Pool<sqlx::Postgres>>,
    query: web::Query<TaskParams>) -> impl Responder {

    let taskid = query.taskid.unwrap_or(0);
    let last_taskid: i32 = sqlx::query("SELECT max(taskid) from tasks").fetch_one(pool.get_ref()).await.unwrap().get(0);
    let realid = if taskid <= 0 { last_taskid + taskid } else { taskid };

    let query = "SELECT t.pkgbase,t.repo,l.build_time,t.info FROM tasks t LEFT JOIN logs l ON t.logid = l.id WHERE t.taskid = $1 ORDER by t.taskno";
    let rows = sqlx::query(query)
        .bind(realid)
        .fetch_all(pool.get_ref())
        .await;

    match rows {
        Ok(tasks) => {
            let tasks_with_converted_time: Vec<Task> = tasks.into_iter().map(|row| {
                let build_time: Option<NaiveDateTime> = row.try_get("build_time").ok();
                // Convert NaiveDateTime to formatted String, or None if NULL
                let build_time_str = build_time.map(|dt| dt.format("%Y-%m-%d %H:%M:%S").to_string());

                Task {
                    pkgbase: row.get("pkgbase"),
                    repo: row.get("repo"),
                    build_time: build_time_str, // Store as String
                    build_result: row.get("info"),
                }
            }).collect();

            HttpResponse::Ok().json(tasks_with_converted_time)
        },
        Err(_) => HttpResponse::InternalServerError().body("Database query failed"),
    }
}

#[get("/api/packages/status")]
async fn get_packages(pool: web::Data<sqlx::Pool<sqlx::Postgres>>) -> impl Responder {
    let packages: Vec<Package> = sqlx::query_as(
        "SELECT name, base, repo, flags, x86_version, x86_testing_version, x86_staging_version, loong_version, loong_testing_version, loong_staging_version FROM packages ORDER by repo, name"
    )
    .fetch_all(pool.get_ref())
    .await
    .unwrap();

    HttpResponse::Ok().json(packages)
}

#[get("/api/packages/stat")]
async fn get_stat(pool: web::Data<sqlx::Pool<sqlx::Postgres>>) -> impl Responder {
    let counts = sqlx::query_as::<_, CountResponse>(
        r#"
        SELECT
            COUNT(*) FILTER (WHERE repo = 'core' AND x86_version = regexp_replace(loong_version, '(-\w+)\.\w+$', '\1')) AS core_match,
            COUNT(*) FILTER (WHERE repo = 'extra' AND x86_version = regexp_replace(loong_version, '(-\w+)\.\w+$', '\1')) AS extra_match,
            COUNT(*) FILTER (WHERE repo = 'core' AND x86_version != regexp_replace(loong_version, '(-\w+)\.\w+$', '\1')) AS core_mismatch,
            COUNT(*) FILTER (WHERE repo = 'extra' AND x86_version != regexp_replace(loong_version, '(-\w+)\.\w+$', '\1')) AS extra_mismatch,
            COUNT(*) FILTER (WHERE repo='core' AND NOT x86_version is NULL) as core_total,
            COUNT(*) FILTER (WHERE repo='extra' AND NOT x86_version is NULL) as extra_total
        FROM packages
        "#
    )
    .fetch_one(pool.get_ref())
    .await.unwrap();

    HttpResponse::Ok().json( counts )
}

#[get("/api/packages/data")]
async fn get_data(
    pool: web::Data<sqlx::Pool<sqlx::Postgres>>,
    query: web::Query<QueryParams>,
) -> impl Responder {
    let page = query.page.unwrap_or(1);
    let per_page = query.per_page.unwrap_or(100);
    let offset = (page - 1) * per_page;

    let mut query_builder = sqlx::QueryBuilder::new(
        "SELECT COUNT(*) OVER() AS total_count, name, base, repo, flags, x86_version,
        x86_testing_version, x86_staging_version, loong_version, loong_testing_version,
        loong_staging_version FROM packages WHERE TRUE");

    // Construct search conditions
    if let Some(name) = &query.name {
        query_builder.push(" AND name ILIKE ");
        query_builder.push_bind(format!("%{}%", name));
    }

    if let Some(error_type) = &query.error_type {
        if *error_type == 1 {
            query_builder.push(" AND flags & (1 << 15) != 0");
        }
        if *error_type > 1 {
            query_builder.push(" AND flags >> 16 = ");
            query_builder.push_bind(*error_type as i64 - 1);
        }
    }

    if let Some(repo) = &query.repo {
        query_builder.push(" AND repo = ");
        query_builder.push_bind(repo);
    }

    query_builder
    .push(" ORDER BY name, base, repo LIMIT ")
    .push_bind(per_page as i64)
    .push(" OFFSET ")
    .push_bind(offset as i64);

    let packages: Vec<Package> = query_builder.build_query_as()
        .fetch_all(pool.get_ref())
        .await.unwrap();

    HttpResponse::Ok().json(packages)
}

#[get("/api/lastupdate")]
async fn get_last_update(pool: web::Data<sqlx::Pool<sqlx::Postgres>>) -> impl Responder {
    let last_update: String = sqlx::query("SELECT last_update FROM last_update LIMIT 1").fetch_one(pool.get_ref()).await.unwrap().get(0);

    HttpResponse::Ok().json(LastUpdate { last_update })
}

#[get("/api/logs")]
async fn get_log(info: web::Query<LogRequest>) -> impl Responder {
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

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    dotenv().ok();

    let database_url = std::env::var("DATABASE_URL").expect("DATABASE_URL must be set");
    let pool = PgPoolOptions::new()
        .max_connections(5)
        .connect(&database_url)
        .await
        .unwrap();

    HttpServer::new(move || {
        App::new()
            .app_data(web::Data::new(pool.clone())) 
            .service(get_packages)
            .service(get_data)
            .service(get_last_update)
            .service(get_stat)
            .service(get_tasks)
            .service(get_log)
    })
    .workers(2)
    .bind(("127.0.0.1", 8080))?
    .run()
    .await
}
