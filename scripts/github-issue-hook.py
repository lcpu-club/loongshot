import argparse
import dbinit
from github import Github

def main():
    parser = argparse.ArgumentParser(description='Auto issue creation for build errors')
    parser.add_argument('--db', nargs=2, metavar=('DATABASE', 'TABLE'), required=True,
                       help='Database path')
    parser.add_argument('-t', '--token',  required=True,
                       help='Github token')
    parser.add_argument('-r', '--repo', required=True,
                       help='Github repo')
    args = parser.parse_args()

    try:
        # Connect to database
        conn = dbinit.get_conn(args.db[0])
        cursor = conn.cursor()
        print(f"Connected to database: {args.db[0]}")
        query = f"SELECT name, base, repo, status, x86_version, loong_version FROM {args.db[1]} WHERE status != 'Pending' AND status != 'Success' AND status != 'Building'"
        cursor.execute(query)
        records = cursor.fetchall()

        # Connect to GitHub repo
        g = Github(args.token)
        github_repo = g.get_repo(args.repo)

        # Create issues for each record
        for record in records:
            name, base, repo, status, x86_version, loong_version = record
            
            body = f"""
## Details  
{base}/{name} in {repo}
- X86 version：{x86_version}
- Current Loong version：{loong_version}

## Error Type  
```error
{status}
```  

See more details in the [build log](https://loongarchlinux.lcpu.dev/log?base={base}&name={name}&version={x86_version}).
"""
            
            issue = github_repo.create_issue(
                title=f"[Bot] {base}/{name} {loong_version} -> {x86_version} failed to build",
                body=body.strip(),
                labels=["build-error", "automated"]
            )

    except Exception as e:
        print(f"Failed to create issue: {str(e)}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    main()