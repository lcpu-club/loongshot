use actix_web::{get, web, HttpResponse, Responder};
use chrono::{Local, Utc, NaiveDateTime, TimeZone};
use serde::{Deserialize, Serialize};
use sqlx::{FromRow, Row};

#[derive(Deserialize)]
pub struct TaskParams {
    pub taskid: Option<i32>,
}

#[derive(Deserialize)]
pub struct BuildTimeParams {
    pub build_time: String,
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

#[derive(Serialize)]
pub struct TaskidSummary {
    pub taskid: i32,
    pub pkgbase: String,
    pub count: i64,
}

/// Resolve the input taskid to a real taskid using the offset-from-max logic.
async fn resolve_taskid(
    pool: &sqlx::Pool<sqlx::Postgres>,
    input_id: i32,
) -> i32 {
    let max_taskid_result = sqlx::query("SELECT max(taskid) from tasks")
        .fetch_one(pool)
        .await;

    let last_taskid: i32 = match max_taskid_result {
        Ok(row) => row.get::<Option<i32>, _>(0).unwrap_or(0),
        Err(_) => 0,
    };

    // Logic: if 0 or negative, offset from max. Else use specific ID.
    if input_id <= 0 {
        last_taskid + input_id
    } else if input_id > last_taskid {
        last_taskid
    } else {
        input_id
    }
}

/// Fetch all tasks for a given taskid and return a JSON HttpResponse.
async fn fetch_tasks_by_taskid(
    pool: &sqlx::Pool<sqlx::Postgres>,
    taskid: i32,
) -> HttpResponse {
    let query_str = "SELECT t.taskno, t.pkgbase, t.repo, l.build_time, t.info FROM tasks t LEFT JOIN logs l ON t.logid = l.id WHERE t.taskid = $1 ORDER by t.taskno";
    let rows = sqlx::query(query_str)
        .bind(taskid)
        .fetch_all(pool)
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

            HttpResponse::Ok().json(TaskResponse {
                taskid,
                tasks: tasks_converted,
            })
        },
        Err(_) => HttpResponse::InternalServerError().body("Database query failed"),
    }
}

#[get("/api/tasks/result")]
pub async fn get_tasks(
    pool: web::Data<sqlx::Pool<sqlx::Postgres>>,
    query: web::Query<TaskParams>,
) -> impl Responder {
    let input_id = query.taskid.unwrap_or(0);
    let realid = resolve_taskid(pool.get_ref(), input_id).await;
    fetch_tasks_by_taskid(pool.get_ref(), realid).await
}

#[get("/api/tasks/by_build_time")]
pub async fn get_tasks_by_build_time(
    pool: web::Data<sqlx::Pool<sqlx::Postgres>>,
    query: web::Query<BuildTimeParams>,
) -> impl Responder {
    let build_time = &query.build_time;

    // Build date range: $1 00:00:00 to $1 23:59:59
    let date_start = format!("{} 00:00:00", build_time);
    let date_end = format!("{} 23:59:59", build_time);

    // Convert date strings to NaiveDateTime for proper timestamp binding
    use chrono::NaiveDateTime;
    let date_start_dt = match NaiveDateTime::parse_from_str(&date_start, "%Y-%m-%d %H:%M:%S") {
        Ok(dt) => dt,
        Err(_) => return HttpResponse::BadRequest().body("Invalid date format"),
    };
    let date_end_dt = match NaiveDateTime::parse_from_str(&date_end, "%Y-%m-%d %H:%M:%S") {
        Ok(dt) => dt,
        Err(_) => return HttpResponse::BadRequest().body("Invalid date format"),
    };

    // Step 1: Find all distinct taskids that have records within this date
    let count_query = "SELECT COUNT(DISTINCT t.taskid) FROM tasks t LEFT JOIN logs l ON t.logid = l.id WHERE l.build_time >= $1 AND l.build_time <= $2";
    let count_row = sqlx::query(count_query)
        .bind(&date_start_dt)
        .bind(&date_end_dt)
        .fetch_one(pool.get_ref())
        .await;

    let distinct_count: i64 = match count_row {
        Ok(row) => row.get(0),
        Err(e) => return HttpResponse::InternalServerError().body(format!("Failed to query build_time: {}", e)),
    };

    if distinct_count == 0 {
        return HttpResponse::Ok().json(Vec::<TaskResponse>::new());
    }

    if distinct_count == 1 {
        // Single taskid: return the same format as get_tasks
        let taskid_row = sqlx::query("SELECT DISTINCT t.taskid FROM tasks t LEFT JOIN logs l ON t.logid = l.id WHERE l.build_time >= $1 AND l.build_time <= $2")
            .bind(&date_start_dt)
            .bind(&date_end_dt)
            .fetch_one(pool.get_ref())
            .await;

        let taskid: i32 = match taskid_row {
            Ok(row) => row.get(0),
            Err(e) => return HttpResponse::InternalServerError().body(format!("Failed to get taskid: {}", e)),
        };

        return fetch_tasks_by_taskid(pool.get_ref(), taskid).await;
    }

    // Multiple taskids: return summary array {taskid, pkgbase (min taskno), count}
    // Use a simpler approach: find min taskno per taskid, then join to get pkgbase
    let summary_query = r#"
        WITH task_summary AS (
            SELECT
                t.taskid,
                MIN(t.taskno) as min_taskno,
                COUNT(*) as count
            FROM tasks t
            LEFT JOIN logs l ON t.logid = l.id
            WHERE l.build_time >= $1 AND l.build_time <= $2
            GROUP BY t.taskid
        )
        SELECT
            ts.taskid,
            t.pkgbase,
            ts.count
        FROM task_summary ts
        JOIN tasks t ON t.taskid = ts.taskid AND t.taskno = ts.min_taskno
        ORDER BY ts.taskid
    "#;

    let rows = sqlx::query(summary_query)
        .bind(&date_start_dt)
        .bind(&date_end_dt)
        .fetch_all(pool.get_ref())
        .await;

    match rows {
        Ok(summaries) => {
            let result: Vec<TaskidSummary> = summaries.into_iter().map(|row| {
                TaskidSummary {
                    taskid: row.get("taskid"),
                    pkgbase: row.get("pkgbase"),
                    count: row.get("count"),
                }
            }).collect();

            HttpResponse::Ok().json(result)
        },
        Err(e) => HttpResponse::InternalServerError().body(format!("Database query failed: {}", e)),
    }
}
