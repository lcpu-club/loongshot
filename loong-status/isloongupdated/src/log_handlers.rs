use actix_web::{get, web, HttpResponse};
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};

const LOG_ROOT: &str = "/home/arch/loong-status/build_logs";
const DEFAULT_PAGE_SIZE: usize = 1000;
const MAX_PAGE_SIZE: usize = 5000;
/// Keep pathological single lines (e.g. minified output) from reaching the browser.
const MAX_LINE_LEN: usize = 8192;

#[derive(Deserialize)]
pub struct LogRequest {
    pub base: String,
    pub log_name: String,
    /// 1-based page number. Missing or 0 means "last page".
    pub page: Option<usize>,
    pub page_size: Option<usize>,
}

#[derive(Serialize)]
pub struct LogPage {
    pub page: usize,
    pub page_size: usize,
    pub total_lines: usize,
    pub total_pages: usize,
    /// 1-based line number of the first line in `lines`.
    pub start_line: usize,
    pub lines: Vec<String>,
}

/// Reject anything that could escape the log directory.
fn log_path(base: &str, log_name: &str) -> Option<PathBuf> {
    let is_plain_name = |name: &str| {
        !name.is_empty()
            && !name.starts_with('.')
            && !name.contains('/')
            && !name.contains('\\')
            && !name.contains('\0')
    };

    if !is_plain_name(base) || !is_plain_name(log_name) {
        return None;
    }

    Some(Path::new(LOG_ROOT).join(format!("{}/{}.log", base, log_name)))
}

fn truncate_line(line: &mut String) {
    if line.len() <= MAX_LINE_LEN {
        return;
    }
    let cut = (0..=MAX_LINE_LEN)
        .rev()
        .find(|&i| line.is_char_boundary(i))
        .unwrap_or(0);
    line.truncate(cut);
    line.push_str(" …[line truncated]");
}

/// Read one page of a log file in a single streaming pass.
///
/// `requested_page == 0` selects the last page. The last `page_size` lines are
/// always buffered, so an out-of-range page falls back to the last page.
fn read_page(path: &Path, requested_page: usize, page_size: usize) -> std::io::Result<LogPage> {
    let mut reader = BufReader::with_capacity(64 * 1024, File::open(path)?);

    let wanted = requested_page.max(1);
    let first = (wanted - 1) * page_size;
    let last = first + page_size;

    let mut total_lines = 0usize;
    let mut lines: Vec<String> = Vec::new();
    let mut tail: VecDeque<String> = VecDeque::with_capacity(page_size);
    let mut buf: Vec<u8> = Vec::new();

    loop {
        buf.clear();
        if reader.read_until(b'\n', &mut buf)? == 0 {
            break;
        }

        let mut line = String::from_utf8_lossy(&buf).into_owned();
        while line.ends_with('\n') || line.ends_with('\r') {
            line.pop();
        }
        truncate_line(&mut line);

        if total_lines >= first && total_lines < last {
            lines.push(line.clone());
        }
        if tail.len() == page_size {
            tail.pop_front();
        }
        tail.push_back(line);

        total_lines += 1;
    }

    let total_pages = if total_lines == 0 {
        1
    } else {
        total_lines.div_ceil(page_size)
    };
    let page = if requested_page == 0 {
        total_pages
    } else {
        requested_page.min(total_pages)
    };
    let lines = if page == wanted {
        lines
    } else {
        // The tail window may start before the requested page begins.
        let skip = ((page - 1) * page_size).saturating_sub(total_lines - tail.len());
        tail.into_iter().skip(skip).collect()
    };
    let start_line = if lines.is_empty() {
        0
    } else {
        (page - 1) * page_size + 1
    };

    Ok(LogPage {
        page,
        page_size,
        total_lines,
        total_pages,
        start_line,
        lines,
    })
}

#[get("/api/logs")]
pub async fn get_log(info: web::Query<LogRequest>) -> HttpResponse {
    let path = match log_path(&info.base, &info.log_name) {
        Some(path) => path,
        None => return HttpResponse::BadRequest().body("Invalid log path."),
    };
    let page = info.page.unwrap_or(0);
    let page_size = info
        .page_size
        .unwrap_or(DEFAULT_PAGE_SIZE)
        .clamp(1, MAX_PAGE_SIZE);
    let log_path = path.clone();

    match web::block(move || read_page(&path, page, page_size)).await {
        Ok(Ok(log_page)) => HttpResponse::Ok().json(log_page),
        Ok(Err(e)) => {
            eprintln!("Failed to read log file: {}. Error: {}", log_path.display(), e);
            HttpResponse::NotFound().body("Log file not found.")
        }
        Err(e) => {
            eprintln!("Log read task failed: {}. Error: {}", log_path.display(), e);
            HttpResponse::InternalServerError().body("Failed to read log file.")
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn write_log(lines: &[String]) -> tempfile::NamedTempFile {
        let mut file = tempfile::NamedTempFile::new().unwrap();
        for line in lines {
            writeln!(file, "{}", line).unwrap();
        }
        file
    }

    #[test]
    fn last_page_by_default() {
        let lines: Vec<String> = (1..=2500).map(|i| format!("line {}", i)).collect();
        let file = write_log(&lines);
        let page = read_page(file.path(), 0, 1000).unwrap();
        assert_eq!(page.page, 3);
        assert_eq!(page.page_size, 1000);
        assert_eq!(page.total_lines, 2500);
        assert_eq!(page.total_pages, 3);
        assert_eq!(page.start_line, 2001);
        assert_eq!(page.lines.len(), 500);
        assert_eq!(page.lines[0], "line 2001");
        assert_eq!(page.lines[499], "line 2500");
    }

    #[test]
    fn explicit_and_out_of_range_pages() {
        let lines: Vec<String> = (1..=2500).map(|i| format!("line {}", i)).collect();
        let file = write_log(&lines);
        let page = read_page(file.path(), 2, 1000).unwrap();
        assert_eq!(page.start_line, 1001);
        assert_eq!(page.lines[0], "line 1001");
        assert_eq!(page.lines[999], "line 2000");

        let clamped = read_page(file.path(), 99, 1000).unwrap();
        assert_eq!(clamped.page, 3);
        assert_eq!(clamped.start_line, 2001);
        assert_eq!(clamped.lines.len(), 500);
    }

    #[test]
    fn empty_file_and_no_trailing_newline() {
        let file = write_log(&[]);
        let page = read_page(file.path(), 0, 1000).unwrap();
        assert_eq!(page.total_lines, 0);
        assert_eq!(page.total_pages, 1);
        assert_eq!(page.start_line, 0);
        assert!(page.lines.is_empty());

        let mut file = tempfile::NamedTempFile::new().unwrap();
        write!(file, "a\nb").unwrap();
        let page = read_page(file.path(), 0, 1000).unwrap();
        assert_eq!(page.total_lines, 2);
        assert_eq!(page.lines, vec!["a".to_string(), "b".to_string()]);
    }

    #[test]
    fn rejects_path_escape() {
        assert!(log_path("../../etc", "passwd").is_none());
        assert!(log_path("base", "../secret").is_none());
        assert!(log_path("base", "/etc/passwd").is_none());
        assert!(log_path("", "all").is_none());
        assert!(log_path("pkgbase", "all").is_some());
    }
}
