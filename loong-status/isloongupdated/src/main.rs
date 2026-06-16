use actix_web::{web, App, HttpServer};

mod log_handlers;
mod package_handlers;
mod task_handlers;

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    dotenv::dotenv().ok();

    let database_url = std::env::var("DATABASE_URL").expect("DATABASE_URL must be set");
    let pool = sqlx::postgres::PgPoolOptions::new()
        .max_connections(5)
        .connect(&database_url)
        .await
        .unwrap();

    HttpServer::new(move || {
        App::new()
            .app_data(web::Data::new(pool.clone()))
            .service(package_handlers::get_data)
            .service(package_handlers::get_last_update)
            .service(package_handlers::get_stat)
            .service(task_handlers::get_tasks)
            .service(task_handlers::get_tasks_by_build_time)
            .service(log_handlers::get_log)
    })
    .workers(2)
    .bind(("127.0.0.1", 8080))?
    .run()
    .await
}
