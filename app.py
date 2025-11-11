import os
import json
import datetime
import uuid
from flask import Flask, render_template, request, redirect, url_for
from google.cloud import storage

app = Flask(__name__)

# Cloud Storage configuration
BUCKET_NAME = "travel-feed"
DB_FILE = "db.json"

storage_client = storage.Client()
bucket = storage_client.bucket(BUCKET_NAME)

# French month names
MONTHS_FR = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]


def format_datetime_fr(dt):
    day = dt.day
    month = MONTHS_FR[dt.month - 1].capitalize()
    year = dt.year
    hour = dt.hour
    minute = dt.minute
    return f"Le {day} {month} {year} à {hour}h{minute:02d}"


def get_posts():
    """Reads and returns all posts from the JSON database in GCS."""
    blob = bucket.blob(DB_FILE)
    if not blob.exists():
        return []
    posts_data = json.loads(blob.download_as_text())

    # Convert datetime strings back to datetime objects for sorting
    for post in posts_data:
        post["datetime"] = datetime.datetime.fromisoformat(post["datetime"])
        post["display_datetime"] = format_datetime_fr(post["datetime"])

        # Normalize media format for backward compatibility
        if "media" in post:
            normalized_media = []
            for item in post["media"]:
                if isinstance(item, str):
                    normalized_media.append({"url": item, "description": ""})
                else:
                    normalized_media.append(item)
            post["media"] = normalized_media

    return sorted(posts_data, key=lambda x: x["datetime"], reverse=True)


def save_posts(posts):
    """Saves the list of posts to the JSON database in GCS."""
    blob = bucket.blob(DB_FILE)
    data = json.dumps(posts, indent=4, default=str)
    blob.upload_from_string(data, content_type="application/json")

    # Set metadata to disable caching
    blob.cache_control = "no-store"
    blob.patch()


@app.route("/")
def index():
    posts = get_posts()
    return render_template("index.html", posts=posts)


@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "POST":
        media_items = []
        medias = request.files.getlist("media")
        media_descriptions = request.form.getlist("media_description")

        for i, media in enumerate(medias):
            if media.filename:
                # Generate a unique filename
                filename = f"{uuid.uuid4()}{os.path.splitext(media.filename)[1]}"
                blob = bucket.blob(filename)

                # Upload the file to GCS
                blob.upload_from_file(media.stream, content_type=media.content_type)

                media_item = {
                    "url": blob.public_url,
                    "description": media_descriptions[i]
                    if i < len(media_descriptions)
                    else "",
                }
                media_items.append(media_item)

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
            "text": request.form.get("text"),
            "media": media_items,
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
        # Keep existing media
        existing_media = post.get("media", [])
        # Normalize old format to new format if needed
        media_items = []
        for item in existing_media:
            if isinstance(item, str):
                media_items.append({"url": item, "description": ""})
            else:
                media_items.append(item)

        # Add new media
        files = request.files.getlist("media")
        media_descriptions = request.form.getlist("media_description")

        for i, file in enumerate(files):
            if file.filename:
                filename = f"{uuid.uuid4()}{os.path.splitext(file.filename)[1]}"
                blob = bucket.blob(filename)
                blob.upload_from_file(file.stream, content_type=file.content_type)

                media_item = {
                    "url": blob.public_url,
                    "description": media_descriptions[i]
                    if i < len(media_descriptions)
                    else "",
                }
                media_items.append(media_item)

        date_str = request.form.get("date")
        time_str = request.form.get("time")
        post_datetime = datetime.datetime.strptime(
            f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
        )

        post["city"] = request.form.get("city")
        post["datetime"] = post_datetime.isoformat()
        post["text"] = request.form.get("text")
        post["media"] = media_items

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
