use actix_web::{get, web, HttpResponse, Responder};
use chrono::{Local, Utc, NaiveDateTime, TimeZone};
use serde::{Deserialize, Serialize};
use sqlx::{FromRow, Row};

#[derive(Deserialize)]
pub struct TaskParams {
    pub taskid: Option<i32>,
}

#[derive(Serialize, Debug, FromRow)]
pub struct Task {
    pub taskno: i32,
    pub pkgbase: String,
    pub repo: i32,
    pub build_result: Option<String>,
    pub build_time: Option<String>,
}

#[derive(Serialize)]
pub struct TaskResponse {
    pub taskid: i32,
    pub tasks: Vec<Task>,
}

#[get("/api/tasks/result")]
pub async fn get_tasks(
    pool: web::Data<sqlx::Pool<sqlx::Postgres>>,
    query: web::Query<TaskParams>,
) -> impl Responder {
    let input_id = query.taskid.unwrap_or(0);

    let max_taskid_result = sqlx::query("SELECT max(taskid) from tasks")
        .fetch_one(pool.get_ref())
        .await;

    let last_taskid: i32 = match max_taskid_result {
        Ok(row) => row.get::<Option<i32>, _>(0).unwrap_or(0),
        Err(_) => return HttpResponse::InternalServerError().body("Failed to get max taskid"),
    };

    // Logic: if 0 or negative, offset from max. Else use specific ID.
    let realid = if input_id <= 0 {
        last_taskid + input_id
    } else {
        if input_id > last_taskid {
            last_taskid
        } else {
            input_id
        }
    };

    // Fetch the tasks
    let query_str = "SELECT t.taskno, t.pkgbase, t.repo, l.build_time, t.info FROM tasks t LEFT JOIN logs l ON t.logid = l.id WHERE t.taskid = $1 ORDER by t.taskno";
    let rows = sqlx::query(query_str)
        .bind(realid)
        .fetch_all(pool.get_ref())
        .await;

    match rows {
        Ok(tasks) => {
            let tasks_converted: Vec<Task> = tasks.into_iter().map(|row| {
                let build_time: Option<NaiveDateTime> = row.try_get("build_time").ok();
                let build_time_str = build_time.and_then(|dt| {
                    Local.from_local_datetime(&dt)
                        .earliest()
                        .map(|local_dt| local_dt.with_timezone(&Utc).to_rfc3339())
                });

                Task {
                    taskno: row.get("taskno"),
                    pkgbase: row.get("pkgbase"),
                    repo: row.get("repo"),
                    build_time: build_time_str,
                    build_result: row.get("info"),
                }
            }).collect();

            // Return both the ID and the list
            HttpResponse::Ok().json(TaskResponse {
                taskid: realid,
                tasks: tasks_converted,
            })
        },
        Err(_) => HttpResponse::InternalServerError().body("Database query failed"),
    }
}
