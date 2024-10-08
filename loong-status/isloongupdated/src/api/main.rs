use actix_web::{get, web, App, HttpResponse, HttpServer, Responder};
use dotenv::dotenv;
use serde::Serialize;
use sqlx::{postgres::PgPoolOptions, FromRow, Row};

#[derive(Serialize, Debug, FromRow)]
struct Package {
    name: String,
    base: String,
    repo: String,
    x86_version: Option<String>,
    loong_version: Option<String>,
    loong_testing_version: Option<String>,
    loong_staging_version: Option<String>,
}

#[derive(Serialize)]
struct LastUpdate {
    last_update: String,
}

#[get("/api/packages/status")]
async fn get_packages(pool: web::Data<sqlx::Pool<sqlx::Postgres>>) -> impl Responder {
    let packages: Vec<Package> = sqlx::query_as(
        "SELECT name, base, repo, x86_version, loong_version, loong_testing_version, loong_staging_version FROM packages ORDER by repo, name"
    )
    .fetch_all(pool.get_ref())
    .await
    .unwrap();

    HttpResponse::Ok().json(packages)
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
            .service(get_last_update)
    })
    .bind(("127.0.0.1", 8080))?
    .run()
    .await
}
