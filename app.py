import psycopg2

from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = '00000'
# dbname, user, password can be different
connect = psycopg2.connect("dbname=movie user=postgres password=0423")
cur = connect.cursor()


@app.route('/')
def login():
    return render_template("login.html")


def sort_movies(sort_method):
    if sort_method == "latest":
        cur.execute("SELECT * FROM movies ORDER BY rel_date desc;")
    elif sort_method == "genre":
        cur.execute("SELECT * FROM movies ORDER BY genre;")
    elif sort_method == "ratings":
        cur.execute(
            "SELECT movies.*, AVG(reviews.ratings) AS avg_ratings\n"
            "FROM movies\n"
            "LEFT JOIN reviews ON movies.id = reviews.mid\n"
            "GROUP BY movies.id\n"
            "ORDER BY avg_ratings;")
    else:
        cur.execute("SELECT * FROM movies ORDER BY rel_date desc;")


def sort_reviews(sort_method):
    if sort_method == "latest":
        cur.execute("SELECT mid, uid, ratings, review, TO_CHAR(rev_time, 'YYYY-MM-DD HH24:MI')\n"
                    "FROM reviews ORDER BY rev_time desc;")
    elif sort_method == "title":
        cur.execute("SELECT mid, uid, ratings, review, TO_CHAR(rev_time, 'YYYY-MM-DD HH24:MI')\n"
                    "FROM reviews, movies\n"
                    "WHERE movies.id=reviews.mid\n"
                    "ORDER BY title;")
    elif sort_method == "followers":
        cur.execute("SELECT mid, uid, ratings, review, TO_CHAR(rev_time, 'YYYY-MM-DD HH24:MI'), COUNT(distinct ties.opid) as followers_cnt\n"
                    "FROM reviews\n"
                    "LEFT JOIN ties ON reviews.uid=ties.id AND ties.tie='follow'\n"
                    "GROUP BY (reviews.uid, reviews.mid)\n"
                    "ORDER BY followers_cnt DESC;")
    else:
        cur.execute("SELECT mid, uid, ratings, review, TO_CHAR(rev_time, 'YYYY-MM-DD HH24:MI')\n"
                    "FROM reviews ORDER BY rev_time desc;")


def query_table(sort_m_m, sort_r_m):
    # movies section
    sort_movies(sort_m_m)
    movies = cur.fetchall()
    avg_ratings = {}
    for movie in movies:
        mid = movie[0]
        cur.execute("SELECT avg(ratings) FROM reviews WHERE reviews.mid='{}';".format(mid))
        avg_rat = cur.fetchall()[0][0]
        avg_ratings[mid] = round(avg_rat, 1) if avg_rat is not None else None

    # reviews section
    sort_reviews(sort_r_m)
    reviews = cur.fetchall()
    movie_titles = {}
    for review in reviews:
        mid = review[0]
        cur.execute("SELECT title FROM movies WHERE movies.id='{}';".format(mid))
        movie_title = cur.fetchall()[0][0]
        movie_titles[mid] = movie_title

    return movies, avg_ratings, reviews, movie_titles


def tie(tie_action, id, user_id):
    if tie_action == 'follow':
        # follow
        cur.execute("INSERT INTO ties (id, opid, tie)\n"
                    "VALUES ('{}', '{}', 'follow')\n"
                    "ON CONFLICT (id, opid) DO UPDATE\n"
                    "SET tie = EXCLUDED.tie;".format(id, user_id))
        connect.commit()
    elif tie_action == 'unfollow':
        # unfollow (if follow, delete follow)
        cur.execute("DELETE FROM ties WHERE id = '{}' AND opid = '{}' AND tie = 'follow';".format(id, user_id))
        connect.commit()
    elif tie_action == 'mute':
        # mute
        cur.execute("INSERT INTO ties (id, opid, tie)\n"
                    "VALUES ('{}', '{}', 'mute')\n"
                    "ON CONFLICT (id, opid) DO UPDATE\n"
                    "SET tie = EXCLUDED.tie;".format(id, user_id))
        connect.commit()
    elif tie_action == 'unmute':
        # unmute (if mute, delete mute)
        cur.execute("DELETE FROM ties WHERE id = '{}' AND opid = '{}' AND tie = 'mute';".format(id, user_id))
        connect.commit()


@app.route('/main', methods=['get', 'post'])
def main():
    user_id = session.get('user_id')
    sort_m_m = request.args["sort_m_m"]
    sort_r_m = request.args["sort_r_m"]

    movies, avg_ratings, reviews, movie_titles = query_table(sort_m_m, sort_r_m)

    return render_template("main.html", user_id=user_id,
                           movies=movies, avg_ratings=avg_ratings,
                           reviews=reviews, movie_titles=movie_titles)


@app.route('/movie_info/<string:mid>', methods=['get', 'post'])
def movie_info(mid):
    user_id = session.get('user_id')

    # movie details
    cur.execute("SELECT * FROM movies WHERE movies.id = '{}';".format(mid))
    movie_details = cur.fetchall()

    # reviews
    cur.execute("SELECT mid, uid, ratings, review, TO_CHAR(rev_time, 'YYYY-MM-DD HH24:MI')\n"
                "FROM reviews r\n"
                "WHERE r.mid='{}' AND NOT EXISTS(SELECT * FROM ties t\n"
                "WHERE t.opid='{}' AND t.id=r.uid AND t.tie='mute');".format(mid, user_id))
    movie_reviews = cur.fetchall()

    # avg rating
    cur.execute("SELECT avg(ratings) FROM reviews WHERE reviews.mid='{}';".format(mid))
    avg_rat_result = cur.fetchone()
    avg_rat = round(avg_rat_result[0], 1) if avg_rat_result[0] is not None else None

    # review submit
    if request.method == 'POST':
        rating = request.form.get('rating')
        review = request.form.get('review')
        cur.execute("INSERT INTO reviews\n"
                    "VALUES ('{}', '{}', {}, '{}', NOW())\n"
                    "ON CONFLICT (mid, uid) DO UPDATE\n"
                    "SET ratings = EXCLUDED.ratings,\n"
                    "review = EXCLUDED.review,\n"
                    "rev_time = EXCLUDED.rev_time;".format(mid, user_id, rating, review))
        connect.commit()
        return redirect(url_for('movie_info', mid=mid))

    return render_template("movie_info.html", mid=mid, user_id=user_id,
                           movie_details=movie_details, movie_reviews=movie_reviews,
                           avg_rat=avg_rat)


@app.route('/user_info/<string:id>', methods=['get', 'post'])
def user_info(id):
    user_id = session.get('user_id')

    # page:
    #   user_info(my_info=False, admin=False),
    #   my_info(my_info=True, admin=False),
    #   admin_info(my_info=False, admin=True),
    #   admin_my_info(my_info=True, admin=True)

    my_info = False
    admin = False

    # this page is my user info
    if id == user_id:
        my_info = True

    # this page is admin info
    cur.execute("SELECT role FROM users WHERE id='{}';".format(id))
    role = cur.fetchone()[0]
    if role == 'admin':
        admin = True

    # user's reviews
    cur.execute("SELECT mid, uid, ratings, review, TO_CHAR(rev_time, 'YYYY-MM-DD HH24:MI')\n"
                "FROM reviews WHERE reviews.uid = '{}';".format(id))
    user_reviews = cur.fetchall()

    # movie titles
    movie_titles = {}
    for review in user_reviews:
        mid = review[0]
        cur.execute("SELECT title FROM movies WHERE movies.id='{}';".format(mid))
        movie_title = cur.fetchall()[0][0]
        movie_titles[mid] = movie_title

    # followers
    cur.execute("SELECT opid FROM ties WHERE id='{}' AND tie='follow';".format(id))
    followers = [follower[0] for follower in cur.fetchall()]

    # tie status
    cur.execute("SELECT tie FROM ties WHERE id='{}' AND opid='{}';".format(id, user_id))
    tie_status = cur.fetchone()
    tie_status = tie_status[0] if tie_status is not None else None

    if not my_info:
        # user_info or admin_info
        # tie action
        if request.method == 'POST':
            tie_action = request.form.get("tie")
            tie(tie_action, id, user_id)
            return redirect(url_for('user_info', id=id, user_id=user_id))
        return render_template("user_info.html", id=id, user_id=user_id, admin=admin, tie_status=tie_status,
                           user_reviews=user_reviews, movie_titles=movie_titles, followers=followers)

    else:
        # followed
        cur.execute("SELECT * FROM ties WHERE opid='{}' AND tie='follow';".format(user_id))
        followings = [following[0] for following in cur.fetchall()]

        # muted
        cur.execute("SELECT * FROM ties WHERE opid='{}' AND tie='mute';".format(user_id))
        mutings = [muting[0] for muting in cur.fetchall()]

        if request.method == 'POST':
            # delete
            review_mid = request.form.get("review_mid")
            cur.execute("DELETE FROM reviews WHERE mid='{}' AND uid='{}';".format(review_mid, user_id))
            connect.commit()

            if not admin:
                # my_info
                # unfollow
                tie_action = request.form.get("tie")
                tie_id = request.form.get("tie_id")
                if tie_action == 'unfollow':
                    # unfollow (if follow, delete follow)
                    cur.execute(
                        "DELETE FROM ties WHERE id = '{}' AND opid = '{}' AND tie = 'follow';".format(tie_id, user_id))
                    connect.commit()
                elif tie_action == 'unmute':
                    # unmute (if mute, delete mute)
                    cur.execute(
                        "DELETE FROM ties WHERE id = '{}' AND opid = '{}' AND tie = 'mute';".format(tie_id, user_id))
                    connect.commit()
            else:
                # admin_my_info
                # add movie
                if request.method == 'POST':
                    title = request.form.get("title")
                    director = request.form.get("director")
                    genre = request.form.get("genre")
                    rel_date = request.form.get("rel_date")

                    # id for new movie
                    cur.execute("SELECT COUNT(id) FROM movies;")
                    movie_id = cur.fetchone()[0] + 1
                    cur.execute("INSERT INTO movies\n"
                                "VALUES ('{}', '{}', '{}', '{}', '{}');".format(movie_id, title, director, genre,
                                                                                rel_date))
                    connect.commit()

            return redirect(url_for('user_info', id=id, user_id=user_id))

        return render_template("my_info.html", id=id, user_id=user_id, admin=admin,
                                   user_reviews=user_reviews, movie_titles=movie_titles, followers=followers,
                                   followings=followings, mutings=mutings)


@app.route('/return', methods=['post'])
def re_turn():
    return redirect(url_for('main', sort_m_m="latest", sort_r_m="latest"))


@app.route('/sort', methods=['get', 'post'])
def sort():
    sort_m_m = str(request.form.get("sort_movies", "latest"))
    sort_r_m = str(request.form.get("sort_reviews", "latest"))
    return redirect(url_for('main', sort_m_m=sort_m_m, sort_r_m=sort_r_m))


@app.route('/logout', methods=['post'])
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/register', methods=['get', 'post'])
def register():
    id = request.form["id"]
    password = request.form["password"]
    send = request.form["send"]

    # Check if id and password are at least 1 character long
    if len(id) < 1 or len(password) < 1:
        error_message = "ID와 PW는 최소 1글자 이상이어야 합니다."
        return render_template("login.html", error_message=error_message)

    if send == "sign up":
        # Check if the user is trying to register as admin
        if id == "admin" and password == "0000":
            error_message = "admin으로 회원가입할 수 없습니다."
            return render_template("login.html", error_message=error_message)

        # Check if the user already exists
        cur.execute("SELECT * FROM users WHERE id = %s;", (id,))
        existing_user = cur.fetchone()
        if existing_user:
            error_message = "이미 가입되어 있는 id입니다."
            return render_template("login.html", error_message=error_message)

        # Register the new user
        cur.execute("INSERT INTO users VALUES (%s, %s);", (id, password))
        connect.commit()
        return render_template("login.html")

    elif send == "sign in":
        # Check if the user exists and the password is correct
        cur.execute("SELECT * FROM users WHERE id = %s AND password = %s;", (id, password))
        user = cur.fetchone()
        if user:
            session['user_id'] = id
            return redirect(url_for('main', sort_m_m="latest", sort_r_m="latest"))
        else:
            error_message = "가입되어 있지 않은 회원입니다. 가입부터 해주세요."
            return render_template("login.html", error_message=error_message)


if __name__ == '__main__':
    app.run()
