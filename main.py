import os
import psycopg2
from os import environ
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename


app = Flask(__name__)
app.secret_key = environ.get("APP_SECRET")

DB_HOST = environ.get('DB_HOST')
DB_NAME = environ.get('DB_NAME')
DB_USER = environ.get('DB_USER')
DB_PASS = environ.get('DB_PASS')

path = environ.get('PathToDirectory')
app.config['path'] = path


def get_db_connection():
    return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)


@app.route("/")
def index():
    if "username" not in session:
        return redirect(url_for("login"))

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT "ID" FROM "users" WHERE "name"=%s', (session["username"],))
            id_user = cursor.fetchone()[0]

            cursor.execute('SELECT "ID", "filename" FROM "files" WHERE "ID_user"=%s', (id_user,))
            files = cursor.fetchall()

    return render_template("index.html", files=files)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT 1 FROM "users" WHERE "name"=%s', (username,))
                if cursor.fetchone():
                    return render_template('register.html', message="Пользователь уже существует")

                hashed_password = generate_password_hash(password)
                cursor.execute(
                    'INSERT INTO "users" ("name", "password") VALUES (%s, %s)',
                    (username, hashed_password)
                )
                conn.commit()
                flash("Вы успешно зарегистрировались!", "success")
                return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT "password" FROM "users" WHERE "name"=%s', (username,))
                row = cursor.fetchone()
                if row and check_password_hash(row[0], password):
                    session['username'] = username
                    return redirect(url_for('index'))
                else:
                    return render_template('login.html', message="Неверный логин или пароль")

    return render_template('login.html')


@app.route("/upload", methods=["POST"])
def upload_file():
    if "username" not in session:
        return redirect(url_for("login"))

    if "files" not in request.files:
        return "Нет файлов"

    uploaded_files = request.files.getlist("files")
    saved_files = []

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT "ID" FROM "users" WHERE "name"=%s', (session["username"],))
            id_user = cursor.fetchone()[0]

            for file in uploaded_files:
                if file.filename == "":
                    continue
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['path'], filename)

                file.save(filepath)
                cursor.execute(
                    'INSERT INTO "files" ("ID_user", "filename") VALUES (%s, %s)',
                    (id_user, filename)
                )
                saved_files.append(filename)

            conn.commit()

    return {"saved": saved_files}

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config['path'], filename)

@app.route("/getting", methods=["GET"])
def getting_files():
    if "username" not in session:
        return redirect(url_for("login"))

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT "ID" FROM "users" WHERE "name"=%s', (session["username"],))
            id_user = cursor.fetchone()[0]

            cursor.execute('SELECT "ID", "filename" FROM "files" WHERE "ID_user"=%s', (id_user,))
            files = cursor.fetchall()

    return render_template("files.html", files=files)

@app.route("/delete/<filename>", methods=["DELETE"])
def delete_file(filename):
    if "username" not in session:
        return "Unauthorized", 401

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT "ID" FROM "users" WHERE "name"=%s', (session["username"],))
            id_user = cursor.fetchone()[0]

            cursor.execute('DELETE FROM "files" WHERE "ID_user"=%s AND "filename"=%s',
                           (id_user, filename))
            conn.commit()

    filepath = os.path.join(app.config['path'], filename)
    if os.path.exists(filepath):
        os.remove(filepath)

    return "Deleted", 200

@app.route("/download/<filename>", methods=["GET"])
def download_file(filename):
    if "username" not in session:
        return "Unauthorized", 401

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT "ID" FROM "users" WHERE "name"=%s', (session["username"],))
            id_user = cursor.fetchone()[0]

            cursor.execute('SELECT 1 FROM "files" WHERE "ID_user"=%s AND "filename"=%s',
                           (id_user, filename))
            if not cursor.fetchone():
                return "File not found", 404

    filepath = os.path.join(app.config['path'], filename)
    if not os.path.exists(filepath):
        return "File not found on disk", 404

    return send_from_directory(app.config['path'], filename, as_attachment=True)


if __name__ == '__main__':
    app.run(debug=True, port=5001)