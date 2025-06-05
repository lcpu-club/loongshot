use actix_web::{get, web, App, HttpResponse, HttpServer, Responder};
use dotenv::dotenv;
use serde::{Serialize, Deserialize};
use sqlx::{postgres::PgPoolOptions, FromRow, Row};
use chrono::NaiveDateTime;

#[derive(Serialize, Debug, FromRow)]
struct Package {
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

#[derive(Serialize)]
struct PagerResponse {
    data: Vec<Package>,
    total: i64,
}


#[derive(Serialize, Deserialize)]
struct QueryParams {
    page: Option<u32>,
    per_page: Option<u32>,
    search: Option<String>,
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

    let search_query = query.search.as_deref().unwrap_or("");
    let select_query = "SELECT name, base, repo, flags, x86_version, x86_testing_version, x86_staging_version, loong_version, loong_testing_version, loong_staging_version FROM packages";

    let (where_clause, order_clause, bind_values) = if search_query.starts_with(":code") {
        (
            "WHERE flags >> 16 = $1",
            "ORDER BY repo, name LIMIT $2 OFFSET $3",
            1,
        )
    } else if search_query.starts_with(":fail") {
        (
            "WHERE flags & (1 << 15) != 0",
            "ORDER BY repo, name LIMIT $1 OFFSET $2",
            2,
        )
    }else {
        (
            "WHERE name ILIKE $1",
            "ORDER BY repo, name LIMIT $2 OFFSET $3",
            3,
        )
    };

    let query = format!("{} {} {}", select_query, where_clause, order_clause);
    let mut sql_query = sqlx::query_as(&query);
    match bind_values {
        1 => sql_query = sql_query.bind(search_query[5..].parse().unwrap_or(0) as i64),
        3 => sql_query = sql_query.bind(format!("%{}%", search_query)),
        _ => (),
    }
    sql_query = sql_query.bind(per_page as i64).bind(offset as i64);

    let packages: Vec<Package> = sql_query
    .fetch_all(pool.get_ref())
    .await
    .unwrap();

    let query_total = format!("{} {}", "SELECT COUNT(*) FROM packages", where_clause);
    let mut total_query = sqlx::query_scalar::<_, i64>(&query_total);
    match bind_values {
        1 => total_query = total_query.bind(search_query[5..].parse().unwrap_or(0) as i64),
        3 => total_query = total_query.bind(format!("%{}%", search_query)),
        _ => (),
    }
    let total: i64 = total_query
        .fetch_one(pool.get_ref())
        .await
        .unwrap();

    HttpResponse::Ok().json(PagerResponse { data: packages, total})
}

#[get("/api/lastupdate")]
async fn get_last_update(pool: web::Data<sqlx::Pool<sqlx::Postgres>>) -> impl Responder {
    let last_update: String = sqlx::query("SELECT last_update FROM last_update LIMIT 1").fetch_one(pool.get_ref()).await.unwrap().get(0);

    HttpResponse::Ok().json(LastUpdate { last_update })
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
    })
    .workers(2)
    .bind(("127.0.0.1", 8080))?
    .run()
    .await
}
