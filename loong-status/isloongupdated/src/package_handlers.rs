use actix_web::{get, web, HttpResponse, Responder};
use serde::Serialize;
use sqlx::{FromRow, Row};

#[derive(Serialize, Debug, FromRow)]
pub struct Package {
    pub total_count: i64,
    pub name: String,
    pub base: String,
    pub repo: String,
    pub flags: Option<i32>,
    pub x86_version: Option<String>,
    pub x86_testing_version: Option<String>,
    pub x86_staging_version: Option<String>,
    pub loong_version: Option<String>,
    pub loong_testing_version: Option<String>,
    pub loong_staging_version: Option<String>,
}

#[derive(Serialize)]
pub struct LastUpdate {
    pub last_update: String,
}

#[derive(serde::Deserialize)]
pub struct QueryParams {
    pub page: Option<u32>,
    pub per_page: Option<u32>,
    pub name: Option<String>,
    pub error_type: Option<u32>,
    pub repo: Option<String>,
}

#[derive(Serialize, Debug, FromRow)]
pub struct CountResponse {
    pub core_match: i64,
    pub extra_match: i64,
    pub core_mismatch: i64,
    pub extra_mismatch: i64,
    pub core_total: i64,
    pub extra_total: i64,
}

#[get("/api/packages/data")]
pub async fn get_data(
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

#[get("/api/packages/stat")]
pub async fn get_stat(pool: web::Data<sqlx::Pool<sqlx::Postgres>>) -> impl Responder {
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

    HttpResponse::Ok().json(counts)
}

#[get("/api/lastupdate")]
pub async fn get_last_update(pool: web::Data<sqlx::Pool<sqlx::Postgres>>) -> impl Responder {
    let last_update: String = sqlx::query("SELECT last_update FROM last_update LIMIT 1")
        .fetch_one(pool.get_ref())
        .await.unwrap()
        .get(0);

    HttpResponse::Ok().json(LastUpdate { last_update })
}
