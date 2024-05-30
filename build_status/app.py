from flask import Flask, render_template, request, redirect, url_for
import sqlite3

app = Flask(__name__)

def get_db_connection():
    conn = sqlite3.connect('packages.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT rowid,* FROM packages')
    packages = cursor.fetchall()
    conn.close()
    return render_template('index.html', packages=packages)

@app.route('/add', methods=('GET', 'POST'))
def add():
    if request.method == 'POST':
        name = request.form['name']
        version = request.form['version']
        release = request.form['release']
        repo = request.form['repo']
        build_status = request.form['build_status']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO packages (name, version, release, repo, build_status) VALUES (?, ?, ?, ?, ?)',
                       (name, version, release, repo, build_status))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))

    return render_template('add.html')

@app.route('/edit/<int:id>', methods=('GET', 'POST'))
def edit(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM packages WHERE rowid = ?', (id,))
    package = cursor.fetchone()

    if request.method == 'POST':
        name = request.form['name']
        version = request.form['version']
        release = request.form['release']
        repo = request.form['repo']
        build_status = request.form['build_status']

        cursor.execute('UPDATE packages SET name = ?, version = ?, release = ?, repo = ?, build_status = ? WHERE rowid = ?',
                       (name, version, release, repo, build_status, id))
        conn.commit()
        conn.close()
        return redirect(url_for('index'))

    conn.close()
    return render_template('edit.html', package=package)

@app.route('/delete/<int:id>', methods=('POST',))
def delete(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM packages WHERE rowid = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/update', methods=('POST',))
def update():
    name = request.form['name']
    print(name)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM packages WHERE name = ?', (name,))
    package = cursor.fetchone()

    if package:
        build_status = request.form['build_status']
        cursor.execute('UPDATE packages SET build_status = ? WHERE name = ?',
                       (build_status, name))
        conn.commit()
        conn.close()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

