import os
import json
import datetime
import uuid
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import Flask, render_template, request, redirect, url_for, jsonify
from google.cloud import storage

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB limit

# Cloud Storage configuration
BUCKET_NAME = "travel-feed"
DB_FILE = "db.json"
SUBSCRIBERS_FILE = "subscribers.json"

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
    blob.cache_control = "no-store"
    data = json.dumps(posts, indent=4, default=str)
    blob.upload_from_string(data, content_type="application/json")


def get_subscribers():
    """Reads and returns all subscribers from the JSON database in GCS."""
    blob = bucket.blob(SUBSCRIBERS_FILE)
    if not blob.exists():
        return []
    return json.loads(blob.download_as_text())


def save_subscribers(subscribers):
    """Saves the list of subscribers to the JSON database in GCS."""
    blob = bucket.blob(SUBSCRIBERS_FILE)
    blob.cache_control = "no-store"
    data = json.dumps(subscribers, indent=4)
    blob.upload_from_string(data, content_type="application/json")


def send_email(subject, html_body, to_email):
    """Sends an email using Gmail SMTP."""
    from_email = os.environ.get("EMAIL")
    from_password = os.environ.get("EMAIL_PASSWORD")

    if not from_email or not from_password:
        print("Email credentials not configured")
        return

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Carnet de voyage <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    msg.attach(MIMEText(html_body, "html"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(from_email, from_password)
        text = msg.as_string()
        server.sendmail(from_email, to_email, text)
        server.quit()
    except Exception as e:
        print(f"Error sending email: {e}")


def create_post_email(post, recipient_email):
    """Creates a beautiful HTML email for a new post."""
    with open("templates/email_new_post.html", "r", encoding="utf-8") as f:
        html_template = f.read()

    html = html_template.replace("{{ city }}", post["city"])
    html = html.replace("{{ display_datetime }}", post["display_datetime"])
    html = html.replace("{{ email }}", recipient_email)

    return html


@app.route("/")
def index():
    posts = get_posts()
    unsubscribe_success = request.args.get("unsubscribe_success")
    return render_template(
        "index.html", posts=posts, unsubscribe_success=unsubscribe_success
    )


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

        # Send email notification to all subscribers
        subscribers = get_subscribers()
        if subscribers:
            new_post["display_datetime"] = format_datetime_fr(post_datetime)
            subject = new_post["city"]

            for subscriber in subscribers:
                try:
                    email_html = create_post_email(new_post, subscriber)
                    send_email(subject, email_html, subscriber)
                except Exception as e:
                    print(f"Failed to send email to {subscriber}: {e}")

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
        # Update descriptions of existing media
        existing_media_urls = request.form.getlist("existing_media_url")
        existing_media_descs = request.form.getlist("existing_media_description")
        description_map = dict(zip(existing_media_urls, existing_media_descs))

        for media_item in post.get("media", []):
            if media_item["url"] in description_map:
                media_item["description"] = description_map[media_item["url"]]

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
                post["media"].append(media_item)

        date_str = request.form.get("date")
        time_str = request.form.get("time")
        post_datetime = datetime.datetime.strptime(
            f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
        )

        post["city"] = request.form.get("city")
        post["datetime"] = post_datetime.isoformat()
        post["text"] = request.form.get("text")

        save_posts(posts)
        return redirect(url_for("edit_list"))

    return render_template("edit_post.html", post=post)


@app.route("/delete-post/<post_id>", methods=["POST"])
def delete_post(post_id):
    posts = get_posts()
    posts = [p for p in posts if p["id"] != post_id]
    save_posts(posts)
    return redirect(url_for("edit_list"))


@app.route("/subscribe", methods=["POST"])
def subscribe():
    email = request.form.get("email", "").strip().lower()

    if not email:
        return jsonify({"success": False, "message": "Email requis"}), 400

    # Basic email validation
    if "@" not in email or "." not in email.split("@")[1]:
        return jsonify({"success": False, "message": "Email invalide"}), 400

    subscribers = get_subscribers()

    if email in subscribers:
        return jsonify({"success": False, "message": "Vous êtes déjà abonné"}), 400

    subscribers.append(email)
    save_subscribers(subscribers)

    return jsonify({"success": True, "message": "Inscription réussie !"})


@app.route("/unsubscribe")
def unsubscribe():
    email = request.args.get("email", "").strip().lower()

    if not email:
        return redirect(url_for("index"))

    subscribers = get_subscribers()

    if email in subscribers:
        subscribers.remove(email)
        save_subscribers(subscribers)
        return redirect(url_for("index", unsubscribe_success="true"))

    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
