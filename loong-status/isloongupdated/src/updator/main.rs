use dotenv;
use sqlx::postgres::PgPoolOptions;
use sqlx::Row;
use std::env;
use std::fs::File;
use std::path::Path;
use std::io::{BufRead, BufReader, Write};

#[derive(Debug, Clone)]
struct Package {
    name: String,
    base: String,
//    repo: String,
    version: String,
}

// Helper function to extract a file using tar
fn extract_tar_file(tar_file: &Path, extract_dir: &Path) {
    let output = std::process::Command::new("tar")
        .arg("xf")
        .arg(tar_file)
        .arg("-C")
        .arg(extract_dir)
        .output()
        .unwrap();

    if !output.status.success() {
        println!("{:?}", output);
        panic!("Failed to extract tar file");
    }
}

async fn download_and_parse_db(url: &str, arch: &str, repo: &str) -> Vec<Package> {
    let tmpdir = tempfile::tempdir().unwrap();
    let extract_dir = tmpdir.path().join("db");
    // create extract dir
    std::fs::create_dir(&extract_dir).unwrap();

    if url.starts_with("file:///") {
        // Local file handling
        let db_path = if arch == "x86_64" {
            format!("{}/{}.db", &url[7..], repo)  // Strip "file:///"
        } else if arch == "loong64" {
            format!("{}/{}/os/{}/{}.db", &url[7..], repo, arch, repo)
        } else {
            panic!("Unsupported architecture: {}", arch);
        };

        let src_path = Path::new(&db_path);
        if !src_path.exists() {
            panic!("Local file does not exist: {}", db_path);
        }
        extract_tar_file(src_path, &extract_dir);
    } else {
        let db_url = format!("{url}/{repo}/os/{arch}/{repo}.db");
        let tmpfile = tmpdir.path().join("db.tar.gz");
        let resp = reqwest::get(&db_url).await.unwrap();

        // collect all data in memory
        let data = resp.bytes().await.unwrap();

        let mut file = File::create(&tmpfile).unwrap();
        file.write_all(&data).unwrap();
        extract_tar_file(&tmpfile, &extract_dir);
    }

    let mut packages = Vec::new();

    // walk in db directory
    for entry in std::fs::read_dir(&extract_dir).unwrap() {
        let entry = entry.unwrap();
        let path = entry.path();
        let file = File::open(path.join("desc")).unwrap();
        let reader = BufReader::new(file);

        let mut name = String::new();
        let mut base = String::new();
        let mut version = String::new();
        let mut current_field = String::new();

        for line in reader.lines() {
            let line = line.unwrap();
            if line.starts_with('%') && line.ends_with('%') {
                current_field = line;
            } else if !line.is_empty() {
                match current_field.as_str() {
                    "%NAME%" => name = line,
                    "%BASE%" => base = line,
                    "%VERSION%" => version = line,
                    _ => {}
                }
            }
        }

        packages.push(Package {
            name,
            base,
            //repo: repo.to_string(),
            version,
        });
    }

    // Cleanup
    std::fs::remove_dir_all(&tmpdir).unwrap();

    return packages;
}

#[tokio::main]
async fn main() -> Result<(), sqlx::Error> {
    dotenv::dotenv().ok();

    let db_url = env::var("DATABASE_URL").expect("DATABASE_URL must be set");
    let pool = create_db_pool(&db_url).await?;

    create_tables(&pool).await?;

    let x86_url = env::var("X86_URL").unwrap_or_else(|_| "https://mirrors.pku.edu.cn/archlinux".to_string());
    let loong_url = env::var("LOONG_URL").unwrap_or_else(|_| "https://mirrors.pku.edu.cn/loongarch-lcpu/archlinux".to_string());

    let x86_repos = vec!["core", "extra"];
    let loong_repos = vec!["core", "extra", "core-testing", "extra-testing", "core-staging", "extra-staging"];

    for repo in &x86_repos {
        handle_repo_update(&pool, &x86_url, "x86_64", repo, "x86_version").await?;
    }

    for repo in loong_repos {
        let column = match repo {
            "core" | "extra" => "loong_version",
            "core-testing" | "extra-testing" => "loong_testing_version",
            "core-staging" | "extra-staging" => "loong_staging_version",
            _ => panic!("Unknown repo"),
        };
        handle_repo_update(&pool, &loong_url, "loong64", repo, column).await?;
    }

    sqlx::query(
        "DELETE FROM packages
        WHERE x86_version IS NULL
        AND loong_version IS NULL
        AND loong_testing_version IS NULL
        AND loong_staging_version IS NULL"
    ).execute(&pool).await?;

    update_last_update_time(&pool).await?;

    Ok(())
}

/// Creates a PostgreSQL connection pool.
async fn create_db_pool(db_url: &str) -> Result<sqlx::PgPool, sqlx::Error> {
    PgPoolOptions::new()
        .max_connections(5)
        .connect(db_url)
        .await
}

/// Creates necessary database tables if they don't already exist.
async fn create_tables(pool: &sqlx::PgPool) -> Result<(), sqlx::Error> {
    sqlx::query(
        "CREATE TABLE IF NOT EXISTS packages (
            name TEXT PRIMARY KEY,
            base TEXT,
            repo TEXT,
            x86_version TEXT,
            loong_version TEXT,
            loong_testing_version TEXT,
            loong_staging_version TEXT
        )"
    ).execute(pool).await?;

    sqlx::query(
        "CREATE TABLE IF NOT EXISTS last_update (
            last_update TEXT PRIMARY KEY
        )"
    ).execute(pool).await?;

    Ok(())
}

/// Handles updating package data for a given repository.
async fn handle_repo_update(
    pool: &sqlx::PgPool, url: &str, arch: &str, repo: &str, version_column: &str
) -> Result<(), sqlx::Error> {
    let packages = download_and_parse_db(url, arch, repo).await;
    let real_repo = match repo {
        "core-testing" | "core-staging" => "core",
        "extra-testing" | "extra-staging" => "extra",
        _ => repo,
    };

    flag_unused_packages(pool, version_column, real_repo, &packages).await?;
    insert_or_update_packages(pool, version_column, real_repo, &packages).await?;

    Ok(())
}

/// Updates existing packages in the database.
async fn flag_unused_packages(
    pool: &sqlx::PgPool, version_column: &str, real_repo: &str, packages: &[Package]
) -> Result<(), sqlx::Error> {
    let origin_packages = sqlx::query(&format!(
        "SELECT name FROM packages WHERE repo = $1 AND {} IS NOT NULL", version_column
    ))
    .bind(real_repo)
    .fetch_all(pool)
    .await?;

    let mut packages_set = std::collections::HashSet::new();
    for package in origin_packages.iter() {
        packages_set.insert(package.get::<String, _>("name"));
    }

    for package in packages.iter() {
        packages_set.remove(&package.name);
    }

    for package in packages_set.iter() {
        println!("Set {} from {} to NULL", package, version_column);
        sqlx::query(&format!(
            "UPDATE packages SET {} = NULL WHERE name = $1", version_column
        ))
        .bind(package)
        .execute(pool)
        .await?;
    }

    Ok(())
}

/// Inserts or updates packages in the database.
async fn insert_or_update_packages(
    pool: &sqlx::PgPool, version_column: &str, real_repo: &str, packages: &[Package]
) -> Result<(), sqlx::Error> {
    for package in packages {
        let exists = sqlx::query("SELECT COUNT(*) FROM packages WHERE name = $1")
            .bind(&package.name)
            .fetch_one(pool)
            .await?
            .get::<i64, _>(0) > 0;

        if exists {
            sqlx::query(&format!(
                "UPDATE packages SET {} = $1 WHERE name = $2", version_column
            ))
            .bind(&package.version)
            .bind(&package.name)
            .execute(pool)
            .await?;
        } else {
            sqlx::query(&format!(
                "INSERT INTO packages (name, base, repo, {}) VALUES ($1, $2, $3, $4)", version_column
            ))
            .bind(&package.name)
            .bind(&package.base)
            .bind(real_repo)
            .bind(&package.version)
            .execute(pool)
            .await?;
        }
    }

    Ok(())
}

/// Updates the last update time in the database.
async fn update_last_update_time(pool: &sqlx::PgPool) -> Result<(), sqlx::Error> {
    let last_update = sqlx::query("SELECT COUNT(*) FROM last_update")
        .fetch_one(pool)
        .await?
        .get::<i64, _>(0);

    if last_update == 0 {
        sqlx::query("INSERT INTO last_update (last_update) VALUES ($1)")
            .bind(chrono::Utc::now().to_string())
            .execute(pool)
            .await?;
    } else {
        sqlx::query("UPDATE last_update SET last_update = $1")
            .bind(chrono::Utc::now().to_string())
            .execute(pool)
            .await?;
    }

    Ok(())
}
