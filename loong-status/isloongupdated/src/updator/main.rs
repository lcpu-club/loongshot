use dotenv;
use sqlx::postgres::PgPoolOptions;
use sqlx::Row;
use std::env;
use std::fs::File;
use std::io::{BufRead, BufReader, Write};

#[derive(Debug, Clone)]
struct Package {
    name: String,
    base: String,
    repo: String,
    version: String,
}

async fn download_and_parse_db(url: &str, arch: &str, repo: &str) -> Vec<Package> {
    let tmpdir = tempfile::tempdir().unwrap();
    let tmpfile = tmpdir.path().join("db.tar.gz");
    let extract_dir = tmpdir.path().join("db");
    // create extract dir
    std::fs::create_dir(&extract_dir).unwrap();

    let db_url = format!("{url}/{repo}/os/{arch}/{repo}.db");
    let resp = reqwest::get(&db_url).await.unwrap();

    // collect all data in memory
    let data = resp.bytes().await.unwrap();

    let mut file = File::create(&tmpfile).unwrap();
    file.write_all(&data).unwrap();

    // Extract the db file, call tar xf $tmpfile
    let output = std::process::Command::new("tar")
        .arg("xf")
        .arg(&tmpfile)
        .arg("-C")
        .arg(&extract_dir)
        .output()
        .unwrap();

    if !output.status.success() {
        println!("{:?}", output);
        panic!("Failed to extract db file");
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
            repo: repo.to_string(),
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
    let pool = PgPoolOptions::new()
        .max_connections(5)
        .connect(&db_url)
        .await?;

    // Create the packages table if it doesn't exist
    sqlx::query(
        "CREATE TABLE IF NOT EXISTS packages (
            name TEXT PRIMARY KEY,
            base TEXT,
            repo TEXT,
            x86_version TEXT,
            loong_version TEXT,
            loong_testing_version TEXT,
            loong_staging_version TEXT
        )",
    )
    .execute(&pool)
    .await?;

    // Create a table to record last update time
    sqlx::query(
        "CREATE TABLE IF NOT EXISTS last_update (
            last_update TEXT PRIMARY KEY
        )",
    )
    .execute(&pool)
    .await?;

    let x86_url =
        env::var("X86_URL").unwrap_or_else(|_| "https://mirrors.pku.edu.cn/archlinux".to_string());
    let loong_url = env::var("LOONG_URL")
        .unwrap_or_else(|_| "https://mirrors.pku.edu.cn/loongarch-lcpu/archlinux".to_string());

    let x86_repos = vec!["core", "extra"];
    let loong_repos = vec![
        "core",
        "extra",
        "core-testing",
        "extra-testing",
        "core-staging",
        "extra-staging",
    ];

    for repo in &x86_repos {
        let packages = download_and_parse_db(&x86_url, "x86_64", repo).await;
        // for all packages in packages table, if not it in the packages we just downloaded, set it to null
        let origin_packages =
            sqlx::query("SELECT name FROM packages WHERE repo = $1 AND x86_version IS NOT NULL")
                .bind(repo)
                .fetch_all(&pool)
                .await?;
        // use hashset to speed up
        let mut packages_set = std::collections::HashSet::new();
        for package in origin_packages.iter() {
            packages_set.insert(package.get::<String, _>("name"));
        }
        for package in packages.iter() {
            if packages_set.contains(&package.name) {
                packages_set.remove(&package.name);
            }
        }
        for package in packages_set.iter() {
            println!("Set {} from x86_version to NULL", package);
            sqlx::query(
                "UPDATE packages 
                SET x86_version = NULL
                WHERE name = $1",
            )
            .bind(package)
            .execute(&pool)
            .await?;
        }

        for package in packages {
            sqlx::query(
                "UPDATE packages 
                SET x86_version = $1
                WHERE name = $2",
            )
            .bind(&package.version)
            .bind(&package.name)
            .execute(&pool)
            .await?;

            if sqlx::query("SELECT COUNT(*) FROM packages WHERE name = $1")
                .bind(&package.name)
                .fetch_one(&pool)
                .await?
                .get::<i64, _>(0)
                == 0
            {
                sqlx::query(
                    "INSERT INTO packages (name, base, repo, x86_version)
                    VALUES ($1, $2, $3, $4)",
                )
                .bind(&package.name)
                .bind(&package.base)
                .bind(&package.repo)
                .bind(&package.version)
                .execute(&pool)
                .await?;
            }
        }
    }

    for repo in loong_repos {
        let packages = download_and_parse_db(&loong_url, "loong64", repo).await;
        let column = match repo {
            "core" => "loong_version",
            "extra" => "loong_version",
            "core-testing" => "loong_testing_version",
            "extra-testing" => "loong_testing_version",
            "core-staging" => "loong_staging_version",
            "extra-staging" => "loong_staging_version",
            _ => panic!("Unknown repo"),
        };

        let real_repo = match repo {
            "core-testing" => "core",
            "extra-testing" => "extra",
            "core-staging" => "core",
            "extra-staging" => "extra",
            _ => repo,
        };
        // get all packages in the packages table which is repo `real_repo` and status column is not null
        let origin_packages = sqlx::query(&format!(
            "SELECT name FROM packages WHERE repo = $1 AND {} IS NOT NULL",
            column
        ))
        .bind(real_repo)
        .fetch_all(&pool)
        .await?;
        // use hashset to speed up
        let mut packages_set = std::collections::HashSet::new();
        for package in origin_packages.iter() {
            packages_set.insert(package.get::<String, _>("name"));
        }
        for package in packages.iter() {
            if packages_set.contains(&package.name) {
                packages_set.remove(&package.name);
            }
        }
        for package in packages_set.iter() {
            println!("Set {} from {} to NULL", package, column);
            sqlx::query(&format!(
                "UPDATE packages 
                SET {} = NULL
                WHERE name = $1",
                column
            ))
            .bind(package)
            .execute(&pool)
            .await?;
        }

        for package in packages {
            if sqlx::query("SELECT COUNT(*) FROM packages WHERE name = $1")
                .bind(&package.name)
                .fetch_one(&pool)
                .await?
                .get::<i64, _>(0)
                == 0
            {
                sqlx::query(&format!(
                    "INSERT INTO packages (name, base, repo, {})
                    VALUES ($1, $2, $3, $4)",
                    column
                ))
                .bind(&package.name)
                .bind(&package.base)
                .bind(real_repo)
                .bind(&package.version)
                .execute(&pool)
                .await?;
            } else {
                sqlx::query(&format!(
                    "UPDATE packages
                    SET {} = $1
                    WHERE name = $2",
                    column
                ))
                .bind(&package.version)
                .bind(&package.name)
                .execute(&pool)
                .await?;
            }
        }
    }
    // Update last update time, if it doesn't exist, insert it
    let last_update = sqlx::query("SELECT COUNT(*) FROM last_update")
        .fetch_one(&pool)
        .await?
        .get::<i64, _>(0);
    if last_update == 0 {
        sqlx::query("INSERT INTO last_update (last_update) VALUES ($1)")
            .bind(chrono::Utc::now().to_string())
            .execute(&pool)
            .await?;
    } else {
        sqlx::query("UPDATE last_update SET last_update = $1")
            .bind(chrono::Utc::now().to_string())
            .execute(&pool)
            .await?;
    }

    Ok(())
}
