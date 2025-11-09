import os
import json
import datetime
import uuid
import locale
from flask import Flask, render_template, request, redirect, url_for
from google.cloud import storage

# Set locale to French for date formatting
try:
    locale.setlocale(locale.LC_TIME, "fr_FR.UTF-8")
except locale.Error:
    locale.setlocale(locale.LC_TIME, "French")


app = Flask(__name__)

# --- Configuration ---
BUCKET_NAME = "travel-feed"
DB_FILE = "db.json"
# ---

# Initialize Google Cloud Storage client
# This will automatically use your local authentication
# or the service account on Cloud Run.
storage_client = storage.Client()
bucket = storage_client.bucket(BUCKET_NAME)


def get_posts():
    """Reads and returns all posts from the JSON database."""
    if not os.path.exists(DB_FILE):
        return []
    with open(DB_FILE, "r") as f:
        posts_data = json.load(f)
        # Convert datetime strings back to datetime objects for sorting
        for post in posts_data:
            if "datetime" in post:
                post["datetime"] = datetime.datetime.fromisoformat(post["datetime"])
            elif "date" in post:
                # Handle old format for backward compatibility
                post["datetime"] = datetime.datetime.strptime(post["date"], "%Y-%m-%d")
    # Sort posts in anti-chronological order (newest first)
    return sorted(posts_data, key=lambda x: x["datetime"], reverse=True)


def save_posts(posts):
    """Saves the list of posts to the JSON database."""
    with open(DB_FILE, "w") as f:
        # Convert date objects to strings for JSON serialization
        json.dump(posts, f, indent=4, default=str)


@app.route("/")
def index():
    posts = get_posts()
    return render_template("index.html", posts=posts)


@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "POST":
        media_urls = []
        files = request.files.getlist("media")

        for file in files:
            if file.filename:
                # Generate a unique filename
                filename = f"{uuid.uuid4()}{os.path.splitext(file.filename)[1]}"
                blob = bucket.blob(filename)

                # Upload the file to GCS
                blob.upload_from_file(file.stream, content_type=file.content_type)

                # The bucket needs to be publicly readable.
                # The make_public() call is not needed and will fail
                # on buckets with uniform access control.
                media_urls.append(blob.public_url)

        # Combine date and time into a datetime object
        date_str = request.form.get("date")
        time_str = request.form.get("time")
        post_datetime = datetime.datetime.strptime(
            f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
        )

        new_post = {
            "id": str(uuid.uuid4()),
            "city": request.form.get("city"),
            "datetime": post_datetime.isoformat(),
            "title": request.form.get("title"),
            "text": request.form.get("text"),
            "media": media_urls,
        }

        posts = get_posts()
        posts.append(new_post)
        save_posts(posts)

        return redirect(url_for("index"))

    return render_template("add.html")


@app.route("/edit")
def edit_list():
    posts = get_posts()
    return render_template("edit_list.html", posts=posts)


@app.route("/edit-post/<post_id>", methods=["GET", "POST"])
def edit_post(post_id):
    posts = get_posts()
    post = next((p for p in posts if p["id"] == post_id), None)

    if not post:
        return redirect(url_for("index"))

    if request.method == "POST":
        # This part handles the form submission from the edit_post.html page
        # It's different from the deletion which will be handled in a separate route
        media_urls = list(post.get("media", []))
        files = request.files.getlist("media")

        for file in files:
            if file.filename:
                filename = f"{uuid.uuid4()}{os.path.splitext(file.filename)[1]}"
                blob = bucket.blob(filename)
                blob.upload_from_file(file.stream, content_type=file.content_type)
                media_urls.append(blob.public_url)

        date_str = request.form.get("date")
        time_str = request.form.get("time")
        post_datetime = datetime.datetime.strptime(
            f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
        )

        post["city"] = request.form.get("city")
        post["datetime"] = post_datetime.isoformat()
        post["title"] = request.form.get("title")
        post["text"] = request.form.get("text")
        post["media"] = media_urls

        save_posts(posts)
        return redirect(url_for("edit_list"))

    return render_template("edit_post.html", post=post)


@app.route("/delete-post/<post_id>", methods=["POST"])
def delete_post(post_id):
    posts = get_posts()
    posts = [p for p in posts if p["id"] != post_id]
    save_posts(posts)
    return redirect(url_for("edit_list"))


if __name__ == "__main__":
    app.run(debug=True)
