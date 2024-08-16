from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3

app = Flask(__name__)

def get_db_connection():
    conn = sqlite3.connect('packages.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/status')
def index():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT rowid,* FROM packages')
    packages = cursor.fetchall()
    conn.close()
    return render_template('index.html', packages=packages)

@app.route('/status/logs/<name>')
def show_logs(name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM logs WHERE name = ?", (name,))
    logs = cursor.fetchall()
    conn.close()
    return render_template('logs.html', logs=logs, name=name)

@app.route('/op/show/<name>')
def show(name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM packages where name=?',(name,))
    packages = cursor.fetchall()
    conn.close()
    if packages:
        data = {
                'name' : packages[0]['name'],
                'loong_ver' : packages[0]['loong_ver'],
                'x86_ver' : packages[0]['x86_ver'],
                'repo' : packages[0]['repo'],
                'build_status' : packages[0]['build_status']
        }
        return jsonify(data)
    else:
        return jsonify({'error': 'no package found.'}),404

@app.route('/op/add', methods=('POST',))
def add():
    name = request.form['name']
    loong_ver = request.form['loong_ver']
    x86_ver = request.form['x86_ver']
    repo = request.form['repo']
    build_status = request.form['build_status']

    conn = get_db_connection()
    cursor = conn.cursor()
    result = 'OK'
    try:
        cursor.execute('INSERT INTO packages (name, loong_ver, x86_ver, repo, build_status) VALUES (?, ?, ?, ?, ?)',
                   (name, loong_ver, x86_ver, repo, build_status))
    except:
        result = 'Error'
    conn.commit()
    conn.close()
    return jsonify({'result': result})

@app.route('/op/edit/<name>', methods=('POST',))
def edit(name):
    conn = get_db_connection()
    cursor = conn.cursor()
    loong_ver = request.form['loong_ver']
    x86_ver = request.form['x86_ver']
    repo = request.form['repo']
    build_status = request.form['build_status']
    result = 'OK'
    try:
        cursor.execute('UPDATE packages SET loong_ver = ?, x86_ver = ?, repo = ?, build_status = ? WHERE name = ?',
                       (loong_ver, x86_ver, repo, build_status, name))
        cursor.execute('INSERT INTO logs(name,operation,result) VALUES (?,?,?)', (name, 'build', build_status))
    except:
        result = 'Error'
    conn.commit()
    conn.close()
    return jsonify({'result': result})

@app.route('/op/delete/<name>', methods=('POST',))
def delete(name):
    conn = get_db_connection()
    cursor = conn.cursor()
    result = 'OK'
    try:
        cursor.execute('DELETE FROM packages WHERE name = ?', (name,))
    except:
        result = 'Error'
    conn.commit()
    conn.close()
    return jsonify({'result': result})

@app.route('/op/update/<name>', methods=('POST',))
def update(name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM packages WHERE name = ?', (name,))
    package = cursor.fetchone()
    result = 'Not found'
    if package:
        result = 'OK'
        build_status = request.form['build_status']
        try:
            cursor.execute('UPDATE packages SET build_status = ? WHERE name = ?',
                           (build_status, name))
            cursor.execute('INSERT INTO logs(name,operation,result) VALUES (?,?,?)', (name, 'build', build_status))
        except:
            result = 'Error'
        conn.commit()
        conn.close()
    return jsonify({'result': result})

@app.route('/op/upx86/<name>', methods=('POST',))
def upx86(name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM packages WHERE name = ?', (name,))
    package = cursor.fetchone()
    result = 'Not found'
    if package:
        result = 'OK'
        ver = request.form['ver']
        try:
            cursor.execute('UPDATE packages SET x86_ver = ? WHERE name = ?', (ver, name))
        except:
            result = 'Error'
        conn.commit()
        conn.close()
    return jsonify({'result': result})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

