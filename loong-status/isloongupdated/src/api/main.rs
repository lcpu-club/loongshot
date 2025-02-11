use actix_web::{get, web, App, HttpResponse, HttpServer, Responder};
use dotenv::dotenv;
use serde::{Serialize, Deserialize};
use sqlx::{postgres::PgPoolOptions, FromRow, Row};

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

#[get("/api/packages/data")]
async fn get_data(
    pool: web::Data<sqlx::Pool<sqlx::Postgres>>,
    query: web::Query<QueryParams>,
) -> impl Responder {
    let page = query.page.unwrap_or(1);
    let per_page = query.per_page.unwrap_or(100);
    let offset = (page - 1) * per_page;

    let search_query = query.search.as_deref().unwrap_or("");

    let packages: Vec<Package> = sqlx::query_as(
        "SELECT name, base, repo, flags, x86_version, x86_testing_version, x86_staging_version, loong_version, loong_testing_version, loong_staging_version FROM packages WHERE name ILIKE $1 ORDER BY repo, name LIMIT $2 OFFSET $3")
    .bind(format!("%{}%", search_query))
    .bind(per_page as i64)
    .bind(offset as i64)
    .fetch_all(pool.get_ref())
    .await
    .unwrap();

    let total: i64 = sqlx::query("SELECT COUNT(*) FROM packages WHERE name ILIKE $1")
        .bind(format!("%{}%", search_query))
        .fetch_one(pool.get_ref())
        .await
        .unwrap()
        .try_get::<i64, _>(0)
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
    })
    .bind(("127.0.0.1", 8080))?
    .run()
    .await
}
